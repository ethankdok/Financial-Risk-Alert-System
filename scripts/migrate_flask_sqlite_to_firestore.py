from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

COLLECTIONS = ("admins", "keywords", "risk_features", "audit_logs", "analysis_records")
BATCH_WRITE_LIMIT = 400


@dataclass(frozen=True)
class MigrationBundle:
    collections: dict[str, list[dict[str, Any]]]

    @property
    def counters(self) -> dict[str, int]:
        return {
            name: max((int(row["id"]) for row in rows), default=0)
            for name, rows in self.collections.items()
        }

    @property
    def counts(self) -> dict[str, int]:
        return {name: len(rows) for name, rows in self.collections.items()}


def _json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _rows(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query).fetchall()]


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def load_sqlite_bundle(database_path: Path) -> MigrationBundle:
    if not database_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {database_path}")

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        missing = [name for name in COLLECTIONS if name not in tables]
        if missing:
            raise RuntimeError(f"SQLite database is missing expected tables: {', '.join(missing)}")

        admins = _rows(connection, "SELECT * FROM admins ORDER BY id")
        keywords = _rows(connection, "SELECT * FROM keywords ORDER BY id")

        features = []
        for row in _rows(connection, "SELECT * FROM risk_features ORDER BY id"):
            row["keywords"] = _json(row.pop("keywords_json", None), [])
            features.append(row)

        audit_logs = []
        for row in _rows(connection, "SELECT * FROM audit_logs ORDER BY id"):
            row["before"] = _json(row.pop("before_json", None), None)
            row["after"] = _json(row.pop("after_json", None), None)
            audit_logs.append(row)

        analysis_columns = _columns(connection, "analysis_records")
        analysis_records = []
        for row in _rows(connection, "SELECT * FROM analysis_records ORDER BY id"):
            if "max_score" not in analysis_columns:
                row["max_score"] = 0
            row["matched_keywords"] = _json(row.pop("matched_keywords_json", None), [])
            row["matched_features"] = _json(row.pop("matched_features_json", None), [])
            analysis_records.append(row)

        return MigrationBundle(
            collections={
                "admins": admins,
                "keywords": keywords,
                "risk_features": features,
                "audit_logs": audit_logs,
                "analysis_records": analysis_records,
            }
        )
    finally:
        connection.close()


def canonicalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [canonicalize(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def fingerprint_rows(rows: Iterable[dict[str, Any]]) -> str:
    ordered = sorted((canonicalize(row) for row in rows), key=lambda row: int(row["id"]))
    payload = json.dumps(ordered, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def bundle_report(bundle: MigrationBundle) -> dict[str, Any]:
    return {
        "counts": bundle.counts,
        "counters": bundle.counters,
        "fingerprints": {
            name: fingerprint_rows(rows)
            for name, rows in bundle.collections.items()
        },
    }


def _firestore_client(project_id: str | None):
    from google.cloud import firestore

    return firestore.Client(project=project_id or None)


def read_firestore_bundle(client: Any) -> MigrationBundle:
    collections: dict[str, list[dict[str, Any]]] = {}
    for name in COLLECTIONS:
        rows: list[dict[str, Any]] = []
        for snapshot in client.collection(name).stream():
            row = snapshot.to_dict() or {}
            row["id"] = int(row.get("id") or snapshot.id)
            rows.append(row)
        rows.sort(key=lambda row: int(row["id"]))
        collections[name] = rows
    return MigrationBundle(collections=collections)


def destination_counts(client: Any) -> dict[str, int]:
    return {
        name: sum(1 for _ in client.collection(name).stream())
        for name in COLLECTIONS
    }


def _chunks(items: list[tuple[Any, dict[str, Any]]], size: int = BATCH_WRITE_LIMIT):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def write_bundle(client: Any, bundle: MigrationBundle, *, allow_existing: bool = False) -> None:
    existing = destination_counts(client)
    nonempty = {name: count for name, count in existing.items() if count}
    if nonempty and not allow_existing:
        details = ", ".join(f"{name}={count}" for name, count in nonempty.items())
        raise RuntimeError(
            "Destination Firestore collections are not empty. "
            f"Refusing to overwrite without --allow-existing: {details}"
        )

    writes: list[tuple[Any, dict[str, Any]]] = []
    for name, rows in bundle.collections.items():
        for row in rows:
            writes.append((client.collection(name).document(str(row["id"])), row))

    for chunk in _chunks(writes):
        batch = client.batch()
        for ref, payload in chunk:
            batch.set(ref, payload)
        batch.commit()

    counter_ref = client.collection("_meta").document("counters")
    existing_counter_snapshot = counter_ref.get()
    existing_counters = existing_counter_snapshot.to_dict() or {} if existing_counter_snapshot.exists else {}
    safe_counters = {
        name: max(int(existing_counters.get(name, 0) or 0), value)
        for name, value in bundle.counters.items()
    }
    counter_ref.set(safe_counters, merge=True)


def verify_bundle(source: MigrationBundle, destination: MigrationBundle) -> dict[str, Any]:
    report: dict[str, Any] = {"ok": True, "collections": {}}
    for name in COLLECTIONS:
        source_rows = source.collections[name]
        destination_rows = destination.collections[name]
        source_fingerprint = fingerprint_rows(source_rows)
        destination_fingerprint = fingerprint_rows(destination_rows)
        item = {
            "source_count": len(source_rows),
            "destination_count": len(destination_rows),
            "source_fingerprint": source_fingerprint,
            "destination_fingerprint": destination_fingerprint,
            "match": len(source_rows) == len(destination_rows)
            and source_fingerprint == destination_fingerprint,
        }
        report["collections"][name] = item
        report["ok"] = report["ok"] and item["match"]
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-time Flask SQLite -> Firestore migration with exact count/fingerprint verification."
    )
    parser.add_argument("--database", default="financial_risk.db", help="Source SQLite database path")
    parser.add_argument("--project", default=None, help="Google Cloud project ID (ADC is used for auth)")
    parser.add_argument("--execute", action="store_true", help="Actually write to Firestore; default is dry-run")
    parser.add_argument(
        "--allow-existing",
        action="store_true",
        help="Allow writes when target collections already contain documents",
    )
    parser.add_argument("--report", default=None, help="Optional JSON report output path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = load_sqlite_bundle(Path(args.database))
    report: dict[str, Any] = {"mode": "execute" if args.execute else "dry-run", "source": bundle_report(source)}

    if not args.execute:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.report:
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    client = _firestore_client(args.project)
    write_bundle(client, source, allow_existing=args.allow_existing)
    destination = read_firestore_bundle(client)
    verification = verify_bundle(source, destination)
    report["verification"] = verification
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if verification["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
