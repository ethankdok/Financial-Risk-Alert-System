from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from flask_data_repository import DuplicateRecordError, SqliteFlaskDataRepository


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
            "risk_level": "低風險",
            "matched_keywords": [],
            "matched_features": [],
            "created_at": "2026-09-11 00:00:00",
        })
        self.assertEqual(record_id, 1)


if __name__ == "__main__":
    unittest.main()
