from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol


class DuplicateRecordError(ValueError):
    """Raised when a unique field already exists."""


class FlaskDataRepository(Protocol):
    backend_name: str

    def initialize(self) -> None: ...
    def get_admin(self, admin_id: int, *, active_only: bool = False) -> dict[str, Any] | None: ...
    def get_admin_by_username(self, username: str, *, active_only: bool = False) -> dict[str, Any] | None: ...
    def list_admins(self) -> list[dict[str, Any]]: ...
    def create_admin(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_admin(self, admin_id: int, fields: dict[str, Any]) -> dict[str, Any] | None: ...
    def set_admin_password(self, admin_id: int, password_hash: str) -> bool: ...
    def count_active_system_admins(self) -> int: ...

    def list_keywords(self, *, active_only: bool = False) -> list[dict[str, Any]]: ...
    def get_keyword(self, keyword_id: int) -> dict[str, Any] | None: ...
    def create_keyword(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_keyword(self, keyword_id: int, fields: dict[str, Any]) -> dict[str, Any] | None: ...
    def delete_keyword(self, keyword_id: int) -> dict[str, Any] | None: ...

    def list_risk_features(self, *, active_only: bool = False) -> list[dict[str, Any]]: ...
    def get_risk_feature(self, feature_id: int) -> dict[str, Any] | None: ...
    def create_risk_feature(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_risk_feature(self, feature_id: int, fields: dict[str, Any]) -> dict[str, Any] | None: ...
    def delete_risk_feature(self, feature_id: int) -> dict[str, Any] | None: ...

    def append_audit(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def list_audit_logs(self, limit: int = 500) -> list[dict[str, Any]]: ...
    def clear_audit_logs(self) -> None: ...
    def create_analysis_record(self, payload: dict[str, Any]) -> int: ...

    def create_member(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def get_member(self, uid: str) -> dict[str, Any] | None: ...
    def get_member_by_email(self, email: str) -> dict[str, Any] | None: ...
    def list_members(self, limit: int = 500) -> list[dict[str, Any]]: ...
    def update_member(self, uid: str, fields: dict[str, Any]) -> dict[str, Any] | None: ...
    def set_member_password_hash(self, uid: str, password_hash: str) -> None: ...
    def get_member_password_hash(self, uid: str) -> str | None: ...
    def list_watchlist(self, member_uid: str) -> list[dict[str, Any]]: ...
    def upsert_watchlist_item(self, member_uid: str, payload: dict[str, Any]) -> dict[str, Any]: ...
    def update_watchlist_item(self, member_uid: str, ticker: str, fields: dict[str, Any]) -> dict[str, Any] | None: ...
    def delete_watchlist_item(self, member_uid: str, ticker: str) -> dict[str, Any] | None: ...
    def get_notification_preferences(self, member_uid: str) -> dict[str, Any]: ...
    def save_notification_preferences(self, member_uid: str, preferences: dict[str, Any]) -> dict[str, Any]: ...
    def append_notification_history(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    def list_notification_history(self, member_uid: str | None = None, limit: int = 100) -> list[dict[str, Any]]: ...
    def find_notification_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None: ...


class SqliteFlaskDataRepository:
    """Compatibility backend for local development and migration verification."""

    backend_name = "sqlite"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS admins (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  display_name TEXT NOT NULL,
                  role TEXT NOT NULL,
                  is_active INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS keywords (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  phrase TEXT UNIQUE NOT NULL,
                  category TEXT NOT NULL,
                  risk TEXT NOT NULL,
                  source TEXT NOT NULL,
                  reason TEXT,
                  status TEXT NOT NULL DEFAULT 'active',
                  approved_by INTEGER,
                  approved_at TEXT NOT NULL,
                  updated_by INTEGER,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(approved_by) REFERENCES admins(id),
                  FOREIGN KEY(updated_by) REFERENCES admins(id)
                );
                CREATE TABLE IF NOT EXISTS risk_features (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE NOT NULL,
                  dimension TEXT NOT NULL,
                  weight INTEGER NOT NULL,
                  keywords_json TEXT NOT NULL DEFAULT '[]',
                  definition TEXT NOT NULL,
                  explain TEXT,
                  status TEXT NOT NULL DEFAULT 'active',
                  updated_by INTEGER,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(updated_by) REFERENCES admins(id)
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  admin_id INTEGER,
                  action TEXT NOT NULL,
                  target TEXT NOT NULL,
                  summary TEXT NOT NULL,
                  before_json TEXT,
                  after_json TEXT,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(admin_id) REFERENCES admins(id)
                );
                CREATE TABLE IF NOT EXISTS analysis_records (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  query_text TEXT NOT NULL,
                  risk_score INTEGER NOT NULL,
                  raw_score INTEGER NOT NULL DEFAULT 0,
                  max_score INTEGER NOT NULL DEFAULT 0,
                  risk_level TEXT NOT NULL,
                  matched_keywords_json TEXT NOT NULL DEFAULT '[]',
                  matched_features_json TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS members (
                  uid TEXT PRIMARY KEY,
                  email TEXT UNIQUE NOT NULL,
                  display_name TEXT NOT NULL,
                  account_status TEXT NOT NULL DEFAULT 'active',
                  auth_provider TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  schema_version INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS member_credentials (
                  member_uid TEXT PRIMARY KEY,
                  password_hash TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(member_uid) REFERENCES members(uid) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS member_watchlist (
                  member_uid TEXT NOT NULL,
                  ticker TEXT NOT NULL,
                  company_name TEXT,
                  alert_enabled INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  PRIMARY KEY(member_uid, ticker),
                  FOREIGN KEY(member_uid) REFERENCES members(uid) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS notification_preferences (
                  member_uid TEXT PRIMARY KEY,
                  email_enabled INTEGER NOT NULL DEFAULT 1,
                  digest_frequency TEXT NOT NULL DEFAULT 'daily',
                  important_alerts INTEGER NOT NULL DEFAULT 1,
                  material_event_alerts INTEGER NOT NULL DEFAULT 1,
                  conference_alerts INTEGER NOT NULL DEFAULT 1,
                  narrative_shift_alerts INTEGER NOT NULL DEFAULT 1,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(member_uid) REFERENCES members(uid) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS notification_history (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  member_uid TEXT NOT NULL,
                  ticker TEXT NOT NULL,
                  notification_type TEXT NOT NULL,
                  dedupe_key TEXT UNIQUE NOT NULL,
                  subject TEXT NOT NULL,
                  body TEXT NOT NULL,
                  status TEXT NOT NULL,
                  provider_status TEXT,
                  safe_error_detail TEXT,
                  created_at TEXT NOT NULL,
                  sent_at TEXT,
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  FOREIGN KEY(member_uid) REFERENCES members(uid) ON DELETE CASCADE
                );
                """
            )
            self._ensure_analysis_records_max_score(connection)

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }

    def _ensure_analysis_records_max_score(self, connection: sqlite3.Connection) -> None:
        columns = self._columns(connection, "analysis_records")
        if "max_score" not in columns:
            connection.execute(
                "ALTER TABLE analysis_records "
                "ADD COLUMN max_score INTEGER NOT NULL DEFAULT 0"
            )

    def get_admin(self, admin_id: int, *, active_only: bool = False) -> dict[str, Any] | None:
        query = "SELECT * FROM admins WHERE id=?"
        params: list[Any] = [admin_id]
        if active_only:
            query += " AND is_active=1"
        with self._connect() as connection:
            return self._row(connection.execute(query, params).fetchone())

    def get_admin_by_username(self, username: str, *, active_only: bool = False) -> dict[str, Any] | None:
        query = "SELECT * FROM admins WHERE username=?"
        params: list[Any] = [username]
        if active_only:
            query += " AND is_active=1"
        with self._connect() as connection:
            return self._row(connection.execute(query, params).fetchone())

    def list_admins(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id,username,display_name,role,is_active,created_at,password_hash "
                "FROM admins ORDER BY is_active DESC, id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_admin(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO admins(username,password_hash,display_name,role,is_active,created_at) "
                    "VALUES(?,?,?,?,?,?)",
                    (
                        payload["username"], payload["password_hash"], payload["display_name"],
                        payload["role"], int(payload.get("is_active", 1)), payload["created_at"],
                    ),
                )
                admin_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError("admin username already exists") from exc
        return {**payload, "id": admin_id}

    def update_admin(self, admin_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_admin(admin_id)
        if not old:
            return None
        after = {**old, **fields, "id": admin_id}
        with self._connect() as connection:
            connection.execute(
                "UPDATE admins SET display_name=?, role=?, is_active=? WHERE id=?",
                (after["display_name"], after["role"], int(after["is_active"]), admin_id),
            )
        return after

    def set_admin_password(self, admin_id: int, password_hash: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("UPDATE admins SET password_hash=? WHERE id=?", (password_hash, admin_id))
            return cursor.rowcount > 0

    def count_active_system_admins(self) -> int:
        with self._connect() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM admins WHERE role='系統管理員' AND is_active=1"
            ).fetchone()[0])

    def list_keywords(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = (
            "SELECT k.*, a.display_name AS updated_by_name "
            "FROM keywords k LEFT JOIN admins a ON a.id=k.updated_by"
        )
        if active_only:
            query += " WHERE k.status='active'"
        query += " ORDER BY k.id DESC"
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        return [dict(row) for row in rows]

    def get_keyword(self, keyword_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._row(connection.execute("SELECT * FROM keywords WHERE id=?", (keyword_id,)).fetchone())

    def create_keyword(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO keywords(phrase,category,risk,source,reason,status,approved_by,approved_at,updated_by,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    tuple(payload[key] for key in (
                        "phrase", "category", "risk", "source", "reason", "status",
                        "approved_by", "approved_at", "updated_by", "updated_at",
                    )),
                )
                keyword_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError("keyword phrase already exists") from exc
        return {**payload, "id": keyword_id}

    def update_keyword(self, keyword_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_keyword(keyword_id)
        if not old:
            return None
        after = {**old, **fields, "id": keyword_id}
        try:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE keywords SET phrase=?,category=?,risk=?,source=?,reason=?,status=?,updated_by=?,updated_at=? WHERE id=?",
                    (
                        after["phrase"], after["category"], after["risk"], after["source"], after["reason"],
                        after["status"], after["updated_by"], after["updated_at"], keyword_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError("keyword phrase already exists") from exc
        return after

    def delete_keyword(self, keyword_id: int) -> dict[str, Any] | None:
        old = self.get_keyword(keyword_id)
        if not old:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM keywords WHERE id=?", (keyword_id,))
        return old

    def list_risk_features(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM risk_features"
        if active_only:
            query += " WHERE status='active'"
        query += " ORDER BY id DESC"
        with self._connect() as connection:
            rows = connection.execute(query).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["keywords"] = json.loads(item.pop("keywords_json") or "[]")
            result.append(item)
        return result

    def get_risk_feature(self, feature_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM risk_features WHERE id=?", (feature_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["keywords"] = json.loads(item.pop("keywords_json") or "[]")
        return item

    def create_risk_feature(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT INTO risk_features(name,dimension,weight,keywords_json,definition,explain,status,updated_by,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        payload["name"], payload["dimension"], int(payload["weight"]),
                        json.dumps(payload.get("keywords", []), ensure_ascii=False), payload["definition"],
                        payload.get("explain", ""), payload["status"], payload["updated_by"], payload["updated_at"],
                    ),
                )
                feature_id = int(cursor.lastrowid)
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError("risk feature name already exists") from exc
        return {**payload, "id": feature_id}

    def update_risk_feature(self, feature_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_risk_feature(feature_id)
        if not old:
            return None
        after = {**old, **fields, "id": feature_id}
        try:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE risk_features SET name=?,dimension=?,weight=?,keywords_json=?,definition=?,explain=?,status=?,updated_by=?,updated_at=? WHERE id=?",
                    (
                        after["name"], after["dimension"], int(after["weight"]),
                        json.dumps(after.get("keywords", []), ensure_ascii=False), after["definition"],
                        after.get("explain", ""), after["status"], after["updated_by"], after["updated_at"], feature_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError("risk feature name already exists") from exc
        return after

    def delete_risk_feature(self, feature_id: int) -> dict[str, Any] | None:
        old = self.get_risk_feature(feature_id)
        if not old:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM risk_features WHERE id=?", (feature_id,))
        return old

    def append_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO audit_logs(admin_id,action,target,summary,before_json,after_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    payload.get("admin_id"), payload["action"], payload["target"], payload["summary"],
                    json.dumps(payload.get("before"), ensure_ascii=False) if payload.get("before") is not None else None,
                    json.dumps(payload.get("after"), ensure_ascii=False) if payload.get("after") is not None else None,
                    payload["created_at"],
                ),
            )
            audit_id = int(cursor.lastrowid)
        return {**payload, "id": audit_id}

    def list_audit_logs(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT l.*, a.username AS admin_id_text, a.display_name AS admin_name, a.role "
                "FROM audit_logs l LEFT JOIN admins a ON a.id=l.admin_id ORDER BY l.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["before"] = json.loads(item.pop("before_json")) if item.get("before_json") else None
            item["after"] = json.loads(item.pop("after_json")) if item.get("after_json") else None
            result.append(item)
        return result

    def clear_audit_logs(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM audit_logs")

    def create_analysis_record(self, payload: dict[str, Any]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO analysis_records(query_text,risk_score,raw_score,max_score,risk_level,matched_keywords_json,matched_features_json,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (
                    payload["query_text"], payload["risk_score"], payload["raw_score"], payload.get("max_score", 0),
                    payload["risk_level"],
                    json.dumps(payload.get("matched_keywords", []), ensure_ascii=False),
                    json.dumps(payload.get("matched_features", []), ensure_ascii=False), payload["created_at"],
                ),
            )
            return int(cursor.lastrowid)

    def create_member(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO members(uid,email,display_name,account_status,auth_provider,created_at,updated_at,schema_version)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        payload["uid"], payload["email"], payload["display_name"],
                        payload.get("account_status", "active"), payload.get("auth_provider", "local_password"),
                        payload["created_at"], payload["updated_at"], int(payload.get("schema_version", 1)),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError("member email or uid already exists") from exc
        return dict(payload)

    def get_member(self, uid: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._row(connection.execute("SELECT * FROM members WHERE uid=?", (uid,)).fetchone())

    def get_member_by_email(self, email: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._row(connection.execute("SELECT * FROM members WHERE lower(email)=lower(?)", (email,)).fetchone())

    def list_members(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM members ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def update_member(self, uid: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_member(uid)
        if not old:
            return None
        after = {**old, **fields, "uid": uid}
        try:
            with self._connect() as connection:
                connection.execute(
                    "UPDATE members SET display_name=?, email=?, account_status=?, updated_at=? WHERE uid=?",
                    (after["display_name"], after["email"], after["account_status"], after["updated_at"], uid),
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateRecordError("member email already exists") from exc
        return after

    def set_member_password_hash(self, uid: str, password_hash: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO member_credentials(member_uid,password_hash,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(member_uid) DO UPDATE SET password_hash=excluded.password_hash, updated_at=excluded.updated_at""",
                (uid, password_hash),
            )

    def get_member_password_hash(self, uid: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT password_hash FROM member_credentials WHERE member_uid=?", (uid,)).fetchone()
        return str(row["password_hash"]) if row else None

    def list_watchlist(self, member_uid: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM member_watchlist WHERE member_uid=? ORDER BY ticker",
                (member_uid,),
            ).fetchall()
        return [{**dict(row), "alert_enabled": int(row["alert_enabled"])} for row in rows]

    def upsert_watchlist_item(self, member_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = {**payload, "member_uid": member_uid}
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO member_watchlist(member_uid,ticker,company_name,alert_enabled,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(member_uid,ticker) DO UPDATE SET
                    company_name=excluded.company_name,
                    alert_enabled=excluded.alert_enabled,
                    updated_at=excluded.updated_at""",
                (
                    member_uid, item["ticker"], item.get("company_name"),
                    int(item.get("alert_enabled", 1)), item["created_at"], item["updated_at"],
                ),
            )
        return {**item, "alert_enabled": int(item.get("alert_enabled", 1))}

    def update_watchlist_item(self, member_uid: str, ticker: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = next((item for item in self.list_watchlist(member_uid) if item["ticker"] == ticker), None)
        if not old:
            return None
        after = {**old, **fields, "member_uid": member_uid, "ticker": ticker}
        with self._connect() as connection:
            connection.execute(
                "UPDATE member_watchlist SET company_name=?, alert_enabled=?, updated_at=? WHERE member_uid=? AND ticker=?",
                (after.get("company_name"), int(after.get("alert_enabled", 1)), after["updated_at"], member_uid, ticker),
            )
        return {**after, "alert_enabled": int(after.get("alert_enabled", 1))}

    def delete_watchlist_item(self, member_uid: str, ticker: str) -> dict[str, Any] | None:
        old = next((item for item in self.list_watchlist(member_uid) if item["ticker"] == ticker), None)
        if not old:
            return None
        with self._connect() as connection:
            connection.execute("DELETE FROM member_watchlist WHERE member_uid=? AND ticker=?", (member_uid, ticker))
        return old

    @staticmethod
    def _default_notification_preferences(member_uid: str, updated_at: str | None = None) -> dict[str, Any]:
        return {
            "member_uid": member_uid,
            "email_enabled": 1,
            "digest_frequency": "daily",
            "important_alerts": 1,
            "material_event_alerts": 1,
            "conference_alerts": 1,
            "narrative_shift_alerts": 1,
            "updated_at": updated_at or "",
        }

    def get_notification_preferences(self, member_uid: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM notification_preferences WHERE member_uid=?", (member_uid,)).fetchone()
        return dict(row) if row else self._default_notification_preferences(member_uid)

    def save_notification_preferences(self, member_uid: str, preferences: dict[str, Any]) -> dict[str, Any]:
        item = {**self._default_notification_preferences(member_uid), **preferences, "member_uid": member_uid}
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO notification_preferences
                (member_uid,email_enabled,digest_frequency,important_alerts,material_event_alerts,conference_alerts,narrative_shift_alerts,updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(member_uid) DO UPDATE SET
                    email_enabled=excluded.email_enabled,
                    digest_frequency=excluded.digest_frequency,
                    important_alerts=excluded.important_alerts,
                    material_event_alerts=excluded.material_event_alerts,
                    conference_alerts=excluded.conference_alerts,
                    narrative_shift_alerts=excluded.narrative_shift_alerts,
                    updated_at=excluded.updated_at""",
                (
                    member_uid, int(item["email_enabled"]), item["digest_frequency"], int(item["important_alerts"]),
                    int(item["material_event_alerts"]), int(item["conference_alerts"]),
                    int(item["narrative_shift_alerts"]), item["updated_at"],
                ),
            )
        return {**item, **{key: int(item[key]) for key in ("email_enabled", "important_alerts", "material_event_alerts", "conference_alerts", "narrative_shift_alerts")}}

    def append_notification_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO notification_history
                (member_uid,ticker,notification_type,dedupe_key,subject,body,status,provider_status,safe_error_detail,created_at,sent_at,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    payload["member_uid"], payload["ticker"], payload["notification_type"], payload["dedupe_key"],
                    payload["subject"], payload["body"], payload["status"], payload.get("provider_status"),
                    payload.get("safe_error_detail"), payload["created_at"], payload.get("sent_at"),
                    json.dumps(payload.get("metadata", {}), ensure_ascii=False),
                ),
            )
            history_id = int(cursor.lastrowid)
        return {**payload, "id": history_id}

    def list_notification_history(self, member_uid: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        query = "SELECT * FROM notification_history"
        params: list[Any] = []
        if member_uid:
            query += " WHERE member_uid=?"
            params.append(member_uid)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            output.append(item)
        return output

    def find_notification_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM notification_history WHERE dedupe_key=?", (dedupe_key,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        return item


class FirestoreFlaskDataRepository:
    """Firestore backend used by the Flask admin and text-risk application."""

    backend_name = "firestore"

    def __init__(self, project_id: str | None = None) -> None:
        from google.cloud import firestore

        self.firestore = firestore
        self.client = firestore.Client(project=project_id or None)

    def initialize(self) -> None:
        # Firestore is schemaless; collection creation happens on first write.
        return None

    @staticmethod
    def _doc_payload(snapshot: Any) -> dict[str, Any] | None:
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        raw_id = data.get("id", snapshot.id)
        try:
            data["id"] = int(raw_id)
        except (TypeError, ValueError):
            data["id"] = str(raw_id)
        return data

    def _collection_rows(self, name: str) -> list[dict[str, Any]]:
        rows = []
        for snapshot in self.client.collection(name).stream():
            item = self._doc_payload(snapshot)
            if item is not None:
                rows.append(item)
        return rows

    def _find_one(self, collection: str, field: str, value: Any) -> dict[str, Any] | None:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection(collection).where(filter=FieldFilter(field, "==", value)).limit(1)
        for snapshot in query.stream():
            return self._doc_payload(snapshot)
        return None

    def _next_id(self, collection: str) -> int:
        existing_ids = [int(row["id"]) for row in self._collection_rows(collection) if row.get("id") is not None]
        floor = max(existing_ids, default=0)
        counter_ref = self.client.collection("_meta").document("counters")
        transaction = self.client.transaction()
        firestore = self.firestore

        @firestore.transactional
        def increment(txn: Any) -> int:
            snapshot = counter_ref.get(transaction=txn)
            values = snapshot.to_dict() or {}
            current = max(int(values.get(collection, 0) or 0), floor)
            next_value = current + 1
            txn.set(counter_ref, {collection: next_value}, merge=True)
            return next_value

        return int(increment(transaction))

    def _create_unique(self, collection: str, unique_field: str, payload: dict[str, Any]) -> dict[str, Any]:
        if self._find_one(collection, unique_field, payload[unique_field]) is not None:
            raise DuplicateRecordError(f"{collection}.{unique_field} already exists")
        record_id = self._next_id(collection)
        item = {**payload, "id": record_id}
        self.client.collection(collection).document(str(record_id)).set(item)
        return item

    def get_admin(self, admin_id: int, *, active_only: bool = False) -> dict[str, Any] | None:
        item = self._doc_payload(self.client.collection("admins").document(str(admin_id)).get())
        if item and active_only and int(item.get("is_active", 0)) != 1:
            return None
        return item

    def get_admin_by_username(self, username: str, *, active_only: bool = False) -> dict[str, Any] | None:
        item = self._find_one("admins", "username", username)
        if item and active_only and int(item.get("is_active", 0)) != 1:
            return None
        return item

    def list_admins(self) -> list[dict[str, Any]]:
        rows = self._collection_rows("admins")
        rows.sort(key=lambda row: (-int(row.get("is_active", 0)), int(row.get("id", 0))))
        return rows

    def create_admin(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._create_unique("admins", "username", payload)

    def update_admin(self, admin_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_admin(admin_id)
        if not old:
            return None
        after = {**old, **fields, "id": admin_id}
        self.client.collection("admins").document(str(admin_id)).set(after)
        return after

    def set_admin_password(self, admin_id: int, password_hash: str) -> bool:
        ref = self.client.collection("admins").document(str(admin_id))
        if not ref.get().exists:
            return False
        ref.update({"password_hash": password_hash})
        return True

    def count_active_system_admins(self) -> int:
        return sum(
            1 for row in self._collection_rows("admins")
            if row.get("role") == "系統管理員" and int(row.get("is_active", 0)) == 1
        )

    def list_keywords(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        rows = self._collection_rows("keywords")
        if active_only:
            rows = [row for row in rows if row.get("status") == "active"]
        admin_names = {int(row["id"]): row.get("display_name") for row in self._collection_rows("admins")}
        for row in rows:
            updated_by = row.get("updated_by")
            row["updated_by_name"] = admin_names.get(int(updated_by)) if updated_by is not None else None
        rows.sort(key=lambda row: int(row.get("id", 0)), reverse=True)
        return rows

    def get_keyword(self, keyword_id: int) -> dict[str, Any] | None:
        return self._doc_payload(self.client.collection("keywords").document(str(keyword_id)).get())

    def create_keyword(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._create_unique("keywords", "phrase", payload)

    def update_keyword(self, keyword_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_keyword(keyword_id)
        if not old:
            return None
        phrase_owner = self._find_one("keywords", "phrase", fields.get("phrase", old.get("phrase")))
        if phrase_owner and int(phrase_owner["id"]) != keyword_id:
            raise DuplicateRecordError("keyword phrase already exists")
        after = {**old, **fields, "id": keyword_id}
        self.client.collection("keywords").document(str(keyword_id)).set(after)
        return after

    def delete_keyword(self, keyword_id: int) -> dict[str, Any] | None:
        old = self.get_keyword(keyword_id)
        if not old:
            return None
        self.client.collection("keywords").document(str(keyword_id)).delete()
        return old

    def list_risk_features(self, *, active_only: bool = False) -> list[dict[str, Any]]:
        rows = self._collection_rows("risk_features")
        if active_only:
            rows = [row for row in rows if row.get("status") == "active"]
        for row in rows:
            row["keywords"] = list(row.get("keywords") or [])
        rows.sort(key=lambda row: int(row.get("id", 0)), reverse=True)
        return rows

    def get_risk_feature(self, feature_id: int) -> dict[str, Any] | None:
        item = self._doc_payload(self.client.collection("risk_features").document(str(feature_id)).get())
        if item is not None:
            item["keywords"] = list(item.get("keywords") or [])
        return item

    def create_risk_feature(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._create_unique("risk_features", "name", {**payload, "keywords": list(payload.get("keywords") or [])})

    def update_risk_feature(self, feature_id: int, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_risk_feature(feature_id)
        if not old:
            return None
        name_owner = self._find_one("risk_features", "name", fields.get("name", old.get("name")))
        if name_owner and int(name_owner["id"]) != feature_id:
            raise DuplicateRecordError("risk feature name already exists")
        after = {**old, **fields, "id": feature_id, "keywords": list(fields.get("keywords", old.get("keywords", [])) or [])}
        self.client.collection("risk_features").document(str(feature_id)).set(after)
        return after

    def delete_risk_feature(self, feature_id: int) -> dict[str, Any] | None:
        old = self.get_risk_feature(feature_id)
        if not old:
            return None
        self.client.collection("risk_features").document(str(feature_id)).delete()
        return old

    def append_audit(self, payload: dict[str, Any]) -> dict[str, Any]:
        audit_id = self._next_id("audit_logs")
        item = {**payload, "id": audit_id}
        self.client.collection("audit_logs").document(str(audit_id)).set(item)
        return item

    def list_audit_logs(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._collection_rows("audit_logs")
        admins = {int(row["id"]): row for row in self._collection_rows("admins")}
        for row in rows:
            admin_id = row.get("admin_id")
            admin = admins.get(int(admin_id)) if admin_id is not None else None
            row["admin_id_text"] = admin.get("username") if admin else None
            row["admin_name"] = admin.get("display_name") if admin else None
            row["role"] = admin.get("role") if admin else None
        rows.sort(key=lambda row: int(row.get("id", 0)), reverse=True)
        return rows[:limit]

    def clear_audit_logs(self) -> None:
        batch = self.client.batch()
        count = 0
        for snapshot in self.client.collection("audit_logs").stream():
            batch.delete(snapshot.reference)
            count += 1
            if count % 400 == 0:
                batch.commit()
                batch = self.client.batch()
        if count % 400:
            batch.commit()

    def create_analysis_record(self, payload: dict[str, Any]) -> int:
        record_id = self._next_id("analysis_records")
        self.client.collection("analysis_records").document(str(record_id)).set({**payload, "id": record_id})
        return record_id

    def create_member(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.get_member(payload["uid"]) or self.get_member_by_email(payload["email"]):
            raise DuplicateRecordError("member email or uid already exists")
        self.client.collection("members").document(str(payload["uid"])).set(dict(payload), merge=True)
        return dict(payload)

    def get_member(self, uid: str) -> dict[str, Any] | None:
        snapshot = self.client.collection("members").document(str(uid)).get()
        return snapshot.to_dict() if snapshot.exists else None

    def get_member_by_email(self, email: str) -> dict[str, Any] | None:
        return self._find_one("members", "email", email)

    def list_members(self, limit: int = 500) -> list[dict[str, Any]]:
        rows = self._collection_rows("members")
        rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
        return rows[:limit]

    def update_member(self, uid: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        old = self.get_member(uid)
        if not old:
            return None
        email_owner = self.get_member_by_email(str(fields.get("email", old.get("email"))))
        if email_owner and str(email_owner.get("uid")) != str(uid):
            raise DuplicateRecordError("member email already exists")
        after = {**old, **fields, "uid": uid}
        self.client.collection("members").document(str(uid)).set(after, merge=True)
        return after

    def set_member_password_hash(self, uid: str, password_hash: str) -> None:
        raise RuntimeError("Firestore member password storage is disabled; use managed member authentication.")

    def get_member_password_hash(self, uid: str) -> str | None:
        raise RuntimeError("Firestore member password storage is disabled; use managed member authentication.")

    def list_watchlist(self, member_uid: str) -> list[dict[str, Any]]:
        rows = self._collection_rows(f"members/{member_uid}/watchlist")
        rows.sort(key=lambda row: str(row.get("ticker") or ""))
        return rows

    def upsert_watchlist_item(self, member_uid: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = {**payload, "member_uid": member_uid}
        self.client.collection("members").document(member_uid).collection("watchlist").document(str(item["ticker"])).set(item, merge=True)
        return item

    def update_watchlist_item(self, member_uid: str, ticker: str, fields: dict[str, Any]) -> dict[str, Any] | None:
        old_ref = self.client.collection("members").document(member_uid).collection("watchlist").document(ticker)
        snapshot = old_ref.get()
        if not snapshot.exists:
            return None
        after = {**(snapshot.to_dict() or {}), **fields, "member_uid": member_uid, "ticker": ticker}
        old_ref.set(after, merge=True)
        return after

    def delete_watchlist_item(self, member_uid: str, ticker: str) -> dict[str, Any] | None:
        ref = self.client.collection("members").document(member_uid).collection("watchlist").document(ticker)
        snapshot = ref.get()
        if not snapshot.exists:
            return None
        old = snapshot.to_dict() or {}
        ref.delete()
        return old

    @staticmethod
    def _default_notification_preferences(member_uid: str, updated_at: str | None = None) -> dict[str, Any]:
        return SqliteFlaskDataRepository._default_notification_preferences(member_uid, updated_at)

    def get_notification_preferences(self, member_uid: str) -> dict[str, Any]:
        snapshot = self.client.collection("members").document(member_uid).collection("settings").document("notification_preferences").get()
        return snapshot.to_dict() if snapshot.exists else self._default_notification_preferences(member_uid)

    def save_notification_preferences(self, member_uid: str, preferences: dict[str, Any]) -> dict[str, Any]:
        item = {**self._default_notification_preferences(member_uid), **preferences, "member_uid": member_uid}
        self.client.collection("members").document(member_uid).collection("settings").document("notification_preferences").set(item, merge=True)
        return item

    def append_notification_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        history_id = self._next_id("notification_history")
        item = {**payload, "id": history_id}
        self.client.collection("notification_history").document(str(history_id)).set(item, merge=True)
        self.client.collection("members").document(payload["member_uid"]).collection("notification_history").document(str(history_id)).set(item, merge=True)
        return item

    def list_notification_history(self, member_uid: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if member_uid:
            rows = self._collection_rows(f"members/{member_uid}/notification_history")
        else:
            rows = self._collection_rows("notification_history")
        rows.sort(key=lambda row: (str(row.get("created_at") or ""), int(row.get("id", 0))), reverse=True)
        return rows[:limit]

    def find_notification_by_dedupe_key(self, dedupe_key: str) -> dict[str, Any] | None:
        return self._find_one("notification_history", "dedupe_key", dedupe_key)


def build_flask_data_repository(base_dir: str | Path) -> FlaskDataRepository:
    backend = os.getenv("FLASK_DATASTORE_BACKEND", "sqlite").strip().lower()
    if backend == "firestore":
        return FirestoreFlaskDataRepository(os.getenv("GOOGLE_CLOUD_PROJECT") or None)
    if backend != "sqlite":
        raise ValueError(f"Unsupported FLASK_DATASTORE_BACKEND: {backend}")
    db_path = os.getenv("FLASK_DATABASE_PATH") or str(Path(base_dir) / "financial_risk.db")
    return SqliteFlaskDataRepository(db_path)
