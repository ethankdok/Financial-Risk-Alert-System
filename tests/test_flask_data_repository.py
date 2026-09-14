from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from flask_data_repository import (
    DuplicateRecordError,
    FirestoreFlaskDataRepository,
    SqliteFlaskDataRepository,
)


class SqliteFlaskDataRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.repo = SqliteFlaskDataRepository(Path(self.temp_dir.name) / "test.db")
        self.repo.initialize()
        self.admin = self.repo.create_admin({
            "username": "admin001",
            "password_hash": "hash",
            "display_name": "Ethan",
            "role": "系統管理員",
            "is_active": 1,
            "created_at": "2026-09-11 00:00:00",
        })

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_new_database_has_max_score_column(self) -> None:
        with closing(sqlite3.connect(self.repo.path)) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(analysis_records)")}

        self.assertIn("max_score", columns)

    def test_initialize_adds_max_score_to_legacy_database_without_data_loss(self) -> None:
        legacy_db = Path(self.temp_dir.name) / "legacy.db"
        with closing(sqlite3.connect(legacy_db)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE admins (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  display_name TEXT NOT NULL,
                  role TEXT NOT NULL,
                  is_active INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE keywords (
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
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE risk_features (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE NOT NULL,
                  dimension TEXT NOT NULL,
                  weight INTEGER NOT NULL,
                  keywords_json TEXT NOT NULL DEFAULT '[]',
                  definition TEXT NOT NULL,
                  explain TEXT,
                  status TEXT NOT NULL DEFAULT 'active',
                  updated_by INTEGER,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE audit_logs (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  admin_id INTEGER,
                  action TEXT NOT NULL,
                  target TEXT NOT NULL,
                  summary TEXT NOT NULL,
                  before_json TEXT,
                  after_json TEXT,
                  created_at TEXT NOT NULL
                );
                CREATE TABLE analysis_records (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  query_text TEXT NOT NULL,
                  risk_score INTEGER NOT NULL,
                  raw_score INTEGER NOT NULL DEFAULT 0,
                  risk_level TEXT NOT NULL,
                  matched_keywords_json TEXT NOT NULL DEFAULT '[]',
                  matched_features_json TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO analysis_records(
                  query_text,
                  risk_score,
                  raw_score,
                  risk_level,
                  matched_keywords_json,
                  matched_features_json,
                  created_at
                )
                VALUES('legacy text', 67, 6, '高風險', '[]', '[]', '2026-09-11 00:00:00');
                """
            )

        legacy_repo = SqliteFlaskDataRepository(legacy_db)
        legacy_repo.initialize()
        legacy_repo.initialize()

        with closing(sqlite3.connect(legacy_db)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(analysis_records)")
            }
            row = connection.execute(
                "SELECT query_text, risk_score, raw_score, max_score, risk_level FROM analysis_records"
            ).fetchone()

        self.assertIn("max_score", columns)
        self.assertEqual(row, ("legacy text", 67, 6, 0, "高風險"))

    def test_unique_admin_username(self) -> None:
        with self.assertRaises(DuplicateRecordError):
            self.repo.create_admin({
                "username": "admin001",
                "password_hash": "other",
                "display_name": "Duplicate",
                "role": "內容審核員",
                "is_active": 1,
                "created_at": "2026-09-11 00:00:00",
            })

    def test_keyword_and_feature_native_shapes(self) -> None:
        keyword = self.repo.create_keyword({
            "phrase": "保證獲利",
            "category": "保證報酬",
            "risk": "高",
            "source": "人工",
            "reason": "test",
            "status": "active",
            "approved_by": self.admin["id"],
            "approved_at": "2026-09-11 00:00:00",
            "updated_by": self.admin["id"],
            "updated_at": "2026-09-11 00:00:00",
        })
        rows = self.repo.list_keywords(active_only=True)
        self.assertEqual(rows[0]["id"], keyword["id"])
        self.assertEqual(rows[0]["updated_by_name"], "Ethan")

        feature = self.repo.create_risk_feature({
            "name": "保證報酬",
            "dimension": "金融高風險主張",
            "weight": 3,
            "keywords": ["保證獲利"],
            "definition": "definition",
            "explain": "explain",
            "status": "active",
            "updated_by": self.admin["id"],
            "updated_at": "2026-09-11 00:00:00",
        })
        loaded = self.repo.get_risk_feature(feature["id"])
        self.assertEqual(loaded["keywords"], ["保證獲利"])

    def test_audit_and_analysis_records(self) -> None:
        self.repo.append_audit({
            "admin_id": self.admin["id"],
            "action": "新增",
            "target": "關鍵字",
            "summary": "test",
            "before": None,
            "after": {"phrase": "保證獲利"},
            "created_at": "2026-09-11 00:00:00",
        })
        logs = self.repo.list_audit_logs()
        self.assertEqual(logs[0]["admin_name"], "Ethan")
        self.assertEqual(logs[0]["after"], {"phrase": "保證獲利"})

        record_id = self.repo.create_analysis_record({
            "query_text": "test",
            "risk_score": 10,
            "raw_score": 1,
            "max_score": 14,
            "risk_level": "低風險",
            "matched_keywords": [],
            "matched_features": [],
            "created_at": "2026-09-11 00:00:00",
        })
        self.assertEqual(record_id, 1)
        with closing(sqlite3.connect(self.repo.path)) as connection:
            row = connection.execute(
                "SELECT risk_score, raw_score, max_score FROM analysis_records WHERE id=?",
                (record_id,),
            ).fetchone()
        self.assertEqual(row, (10, 1, 14))

        default_record_id = self.repo.create_analysis_record({
            "query_text": "old caller",
            "risk_score": 0,
            "raw_score": 0,
            "risk_level": "低風險",
            "matched_keywords": [],
            "matched_features": [],
            "created_at": "2026-09-11 00:00:00",
        })
        with closing(sqlite3.connect(self.repo.path)) as connection:
            default_row = connection.execute(
                "SELECT max_score FROM analysis_records WHERE id=?",
                (default_record_id,),
            ).fetchone()
        self.assertEqual(default_row[0], 0)

    def test_firestore_analysis_record_preserves_max_score(self) -> None:
        class FakeDocument:
            def __init__(self, collection, document_id: str) -> None:
                self.collection = collection
                self.document_id = document_id

            def set(self, payload) -> None:
                self.collection.rows[self.document_id] = payload

        class FakeCollection:
            def __init__(self) -> None:
                self.rows = {}

            def document(self, document_id: str) -> FakeDocument:
                return FakeDocument(self, document_id)

        class FakeClient:
            def __init__(self) -> None:
                self.collections = {}

            def collection(self, name: str) -> FakeCollection:
                if name not in self.collections:
                    self.collections[name] = FakeCollection()
                return self.collections[name]

        repo = object.__new__(FirestoreFlaskDataRepository)
        repo.client = FakeClient()
        repo._next_id = lambda collection: 42

        record_id = repo.create_analysis_record({
            "query_text": "test",
            "risk_score": 50,
            "raw_score": 7,
            "max_score": 14,
            "risk_level": "中風險",
            "matched_keywords": [],
            "matched_features": [],
            "created_at": "2026-09-11 00:00:00",
        })

        saved = repo.client.collections["analysis_records"].rows["42"]
        self.assertEqual(record_id, 42)
        self.assertEqual(saved["max_score"], 14)
        self.assertEqual(saved["id"], 42)


if __name__ == "__main__":
    unittest.main()
