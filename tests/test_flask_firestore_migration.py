from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from scripts.migrate_flask_sqlite_to_firestore import (
    fingerprint_rows,
    load_sqlite_bundle,
    verify_bundle,
)


class FlaskFirestoreMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db = Path(self.tempdir.name) / "legacy.db"
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE admins(id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, display_name TEXT, role TEXT, is_active INTEGER, created_at TEXT);
                CREATE TABLE keywords(id INTEGER PRIMARY KEY, phrase TEXT, category TEXT, risk TEXT, source TEXT, reason TEXT, status TEXT, approved_by INTEGER, approved_at TEXT, updated_by INTEGER, updated_at TEXT);
                CREATE TABLE risk_features(id INTEGER PRIMARY KEY, name TEXT, dimension TEXT, weight INTEGER, keywords_json TEXT, definition TEXT, explain TEXT, status TEXT, updated_by INTEGER, updated_at TEXT);
                CREATE TABLE audit_logs(id INTEGER PRIMARY KEY, admin_id INTEGER, action TEXT, target TEXT, summary TEXT, before_json TEXT, after_json TEXT, created_at TEXT);
                CREATE TABLE analysis_records(id INTEGER PRIMARY KEY, query_text TEXT, risk_score INTEGER, raw_score INTEGER, risk_level TEXT, matched_keywords_json TEXT, matched_features_json TEXT, created_at TEXT);
                INSERT INTO admins VALUES(4,'admin004','HASH','Una','系統管理員',1,'2026-09-01 10:00:00');
                INSERT INTO keywords VALUES(9,'保證獲利','保證報酬','高','人工匯入','reason','active',4,'t1',4,'t2');
                INSERT INTO risk_features VALUES(12,'保證報酬','金融高風險主張',3,'["保證獲利","穩賺不賠"]','definition','explain','active',4,'t3');
                INSERT INTO audit_logs VALUES(15,4,'修改','關鍵字','summary','{"x":1}','{"x":2}','t4');
                INSERT INTO analysis_records VALUES(20,'text',67,6,'高風險','[{"id":9}]','[{"id":12}]','t5');
                """
            )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_native_firestore_shapes_and_counters(self) -> None:
        bundle = load_sqlite_bundle(self.db)
        self.assertEqual(bundle.counts, {"admins": 1, "keywords": 1, "risk_features": 1, "audit_logs": 1, "analysis_records": 1})
        self.assertEqual(bundle.counters["admins"], 4)
        self.assertEqual(bundle.counters["analysis_records"], 20)
        self.assertEqual(bundle.collections["risk_features"][0]["keywords"], ["保證獲利", "穩賺不賠"])
        self.assertEqual(bundle.collections["audit_logs"][0]["before"], {"x": 1})
        self.assertEqual(bundle.collections["analysis_records"][0]["max_score"], 0)
        self.assertEqual(bundle.collections["analysis_records"][0]["matched_features"], [{"id": 12}])
        self.assertNotIn("keywords_json", bundle.collections["risk_features"][0])

    def test_load_sqlite_bundle_preserves_existing_max_score(self) -> None:
        modern_db = Path(self.tempdir.name) / "modern.db"
        with closing(sqlite3.connect(modern_db)) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE admins(id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, display_name TEXT, role TEXT, is_active INTEGER, created_at TEXT);
                CREATE TABLE keywords(id INTEGER PRIMARY KEY, phrase TEXT, category TEXT, risk TEXT, source TEXT, reason TEXT, status TEXT, approved_by INTEGER, approved_at TEXT, updated_by INTEGER, updated_at TEXT);
                CREATE TABLE risk_features(id INTEGER PRIMARY KEY, name TEXT, dimension TEXT, weight INTEGER, keywords_json TEXT, definition TEXT, explain TEXT, status TEXT, updated_by INTEGER, updated_at TEXT);
                CREATE TABLE audit_logs(id INTEGER PRIMARY KEY, admin_id INTEGER, action TEXT, target TEXT, summary TEXT, before_json TEXT, after_json TEXT, created_at TEXT);
                CREATE TABLE analysis_records(id INTEGER PRIMARY KEY, query_text TEXT, risk_score INTEGER, raw_score INTEGER, max_score INTEGER, risk_level TEXT, matched_keywords_json TEXT, matched_features_json TEXT, created_at TEXT);
                INSERT INTO admins VALUES(4,'admin004','HASH','Una','系統管理員',1,'2026-09-01 10:00:00');
                INSERT INTO analysis_records VALUES(20,'text',50,7,14,'中風險','[]','[{"id":12}]','t5');
                """
            )

        bundle = load_sqlite_bundle(modern_db)

        self.assertEqual(bundle.collections["analysis_records"][0]["raw_score"], 7)
        self.assertEqual(bundle.collections["analysis_records"][0]["max_score"], 14)
        self.assertEqual(bundle.collections["analysis_records"][0]["matched_features"], [{"id": 12}])

    def test_fingerprint_is_order_independent(self) -> None:
        rows = [{"id": 2, "x": [1, 2]}, {"id": 1, "x": [3]}]
        self.assertEqual(fingerprint_rows(rows), fingerprint_rows(list(reversed(rows))))

    def test_verification_detects_mutation(self) -> None:
        source = load_sqlite_bundle(self.db)
        destination = load_sqlite_bundle(self.db)
        self.assertTrue(verify_bundle(source, destination)["ok"])
        destination.collections["keywords"][0]["risk"] = "低"
        self.assertFalse(verify_bundle(source, destination)["ok"])


if __name__ == "__main__":
    unittest.main()
