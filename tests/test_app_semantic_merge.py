from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from flask import Blueprint


class FakeRepository:
    backend_name = "fake"

    def __init__(self) -> None:
        self.admins = {
            1: {
                "id": 1,
                "username": "admin001",
                "password_hash": "hash",
                "display_name": "Ethan",
                "role": "系統管理員",
                "is_active": 1,
                "created_at": "2026-09-14 00:00:00",
            }
        }
        self.keywords = []
        self.risk_features = []
        self.audit_logs = []
        self.analysis_records = []

    def initialize(self) -> None:
        return None

    def get_admin(self, admin_id: int, *, active_only: bool = False):
        admin = self.admins.get(int(admin_id))
        if admin and active_only and int(admin.get("is_active", 0)) != 1:
            return None
        return dict(admin) if admin else None

    def get_admin_by_username(self, username: str, *, active_only: bool = False):
        for admin in self.admins.values():
            if admin["username"] == username:
                if active_only and int(admin.get("is_active", 0)) != 1:
                    return None
                return dict(admin)
        return None

    def list_admins(self):
        return [dict(admin) for admin in self.admins.values()]

    def create_admin(self, payload):
        admin_id = max(self.admins, default=0) + 1
        admin = {**payload, "id": admin_id}
        self.admins[admin_id] = admin
        return dict(admin)

    def update_admin(self, admin_id: int, fields):
        old = self.admins.get(int(admin_id))
        if not old:
            return None
        old.update(fields)
        return dict(old)

    def set_admin_password(self, admin_id: int, password_hash: str) -> bool:
        admin = self.admins.get(int(admin_id))
        if not admin:
            return False
        admin["password_hash"] = password_hash
        return True

    def count_active_system_admins(self) -> int:
        return sum(
            1
            for admin in self.admins.values()
            if admin.get("role") == "系統管理員" and int(admin.get("is_active", 0)) == 1
        )

    def list_keywords(self, *, active_only: bool = False):
        rows = [dict(keyword) for keyword in self.keywords]
        if active_only:
            rows = [row for row in rows if row.get("status") == "active"]
        return rows

    def get_keyword(self, keyword_id: int):
        return None

    def create_keyword(self, payload):
        keyword = {**payload, "id": len(self.keywords) + 1}
        self.keywords.append(keyword)
        return dict(keyword)

    def update_keyword(self, keyword_id: int, fields):
        return {**fields, "id": keyword_id}

    def delete_keyword(self, keyword_id: int):
        return None

    def list_risk_features(self, *, active_only: bool = False):
        rows = [dict(feature) for feature in self.risk_features]
        if active_only:
            rows = [row for row in rows if row.get("status") == "active"]
        return rows

    def get_risk_feature(self, feature_id: int):
        return None

    def create_risk_feature(self, payload):
        feature = {**payload, "id": len(self.risk_features) + 1}
        self.risk_features.append(feature)
        return dict(feature)

    def update_risk_feature(self, feature_id: int, fields):
        return {**fields, "id": feature_id}

    def delete_risk_feature(self, feature_id: int):
        return None

    def append_audit(self, payload):
        audit_id = len(self.audit_logs) + 1
        record = {**payload, "id": audit_id}
        self.audit_logs.append(record)
        return record

    def list_audit_logs(self, limit: int = 500):
        return list(reversed(self.audit_logs))[:limit]

    def clear_audit_logs(self) -> None:
        self.audit_logs.clear()

    def create_analysis_record(self, payload) -> int:
        record_id = len(self.analysis_records) + 1
        self.analysis_records.append({**payload, "id": record_id})
        return record_id


class AppSemanticMergeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_env = {
            key: os.environ.get(key)
            for key in ("ALLOW_DEMO_SEED_DATA", "FLASK_DATABASE_PATH", "APP_ENV", "SECRET_KEY")
        }
        os.environ["ALLOW_DEMO_SEED_DATA"] = "false"
        os.environ["FLASK_DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "app-import.db")
        os.environ["APP_ENV"] = "development"
        os.environ.pop("SECRET_KEY", None)

        fake_data_shift = types.ModuleType("data_shift")
        fake_data_shift.data_shift_bp = Blueprint("data_shift_test", __name__)
        cls.old_data_shift = sys.modules.get("data_shift")
        sys.modules["data_shift"] = fake_data_shift
        sys.modules.pop("app", None)
        cls.app_module = importlib.import_module("app")
        cls.app_module.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop("app", None)
        if cls.old_data_shift is None:
            sys.modules.pop("data_shift", None)
        else:
            sys.modules["data_shift"] = cls.old_data_shift
        for key, value in cls.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cls.temp_dir.cleanup()

    def setUp(self) -> None:
        self.repo = FakeRepository()
        self.app_module.repository = self.repo
        self.client = self.app_module.app.test_client()

    def login_as(self, admin_id: int = 1) -> None:
        with self.client.session_transaction() as session:
            session["admin_id"] = admin_id

    def test_health_returns_datastore_backend(self) -> None:
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["datastore_backend"], "fake")

    def test_analyze_uses_dynamic_max_score_and_saves_record(self) -> None:
        self.repo.keywords = [
            {
                "id": 1,
                "phrase": "保證獲利",
                "category": "保證報酬",
                "risk": "高",
                "source": "test",
                "reason": "keyword",
                "status": "active",
            }
        ]
        self.repo.risk_features = [
            {
                "id": 10,
                "name": "保證報酬／低風險高報酬",
                "dimension": "金融高風險主張",
                "weight": 3,
                "keywords": ["保證獲利", "穩賺不賠"],
                "definition": "definition",
                "explain": "explain",
                "status": "active",
            },
            {
                "id": 11,
                "name": "群組／私訊／外部導流",
                "dimension": "行動誘導",
                "weight": 2,
                "keywords": ["加入 VIP"],
                "definition": "definition",
                "explain": "explain",
                "status": "active",
            },
            {
                "id": 12,
                "name": "社會認同／從眾訴求",
                "dimension": "社會影響",
                "weight": 5,
                "keywords": ["大家都買了"],
                "definition": "definition",
                "explain": "explain",
                "status": "active",
            },
        ]

        response = self.client.post(
            "/api/analyze",
            json={"text": "保證獲利、穩賺不賠，請加入 VIP。"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json
        self.assertEqual(payload["raw_score"], 5)
        self.assertEqual(payload["max_score"], 10)
        self.assertEqual(payload["score"], 50)
        self.assertEqual(payload["risk_level"], "中風險")
        self.assertEqual(payload["summary"]["active_feature_count"], 3)
        self.assertEqual(payload["normalization"]["formula"], "100 * raw_score / max_score")
        self.assertEqual(payload["threshold"]["status"], "prototype")
        self.assertEqual(self.repo.analysis_records[0]["max_score"], 10)
        self.assertEqual(self.repo.analysis_records[0]["raw_score"], 5)
        self.assertEqual(len(payload["matched_features"][0]["matched_keywords"]), 2)

    def test_analyze_zero_active_features_is_safe(self) -> None:
        response = self.client.post("/api/analyze", json={"text": "任何文字"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["raw_score"], 0)
        self.assertEqual(response.json["max_score"], 0)
        self.assertEqual(response.json["score"], 0)
        self.assertEqual(response.json["summary"]["active_feature_count"], 0)
        self.assertEqual(self.repo.analysis_records[0]["max_score"], 0)

    def test_keyword_only_match_does_not_add_feature_weight(self) -> None:
        self.repo.keywords = [
            {
                "id": 1,
                "phrase": "保證獲利",
                "category": "保證報酬",
                "risk": "高",
                "source": "test",
                "reason": "keyword",
                "status": "active",
            }
        ]
        self.repo.risk_features = [
            {
                "id": 10,
                "name": "未驗證權威訴求",
                "dimension": "可信感強化",
                "weight": 4,
                "keywords": ["老師推薦"],
                "definition": "definition",
                "explain": "explain",
                "status": "active",
            }
        ]

        response = self.client.post("/api/analyze", json={"text": "保證獲利"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["summary"]["keyword_count"], 1)
        self.assertEqual(response.json["summary"]["feature_count"], 0)
        self.assertEqual(response.json["raw_score"], 0)
        self.assertEqual(response.json["max_score"], 4)
        self.assertEqual(response.json["score"], 0)

    def test_demo_seed_uses_latest_v4_risk_features(self) -> None:
        os.environ["ALLOW_DEMO_SEED_DATA"] = "true"
        self.repo.keywords = []
        self.repo.risk_features = []

        try:
            self.app_module.ensure_seed_data()
        finally:
            os.environ["ALLOW_DEMO_SEED_DATA"] = "false"

        self.assertEqual(
            [feature["name"] for feature in self.repo.risk_features],
            [
                "保證報酬／低風險高報酬",
                "內線／未公開消息訴求",
                "來源不可驗證",
                "急迫性／時間壓力",
                "稀缺性訴求",
                "群組／私訊／外部導流",
                "未驗證權威訴求",
                "社會認同／從眾訴求",
            ],
        )

    def test_last_system_admin_protection_remains(self) -> None:
        self.login_as(1)

        response = self.client.put(
            "/api/admins/1",
            json={"role": "內容審核員", "is_active": 1},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("系統至少必須保留一位啟用中的系統管理員", response.json["error"])

    def test_self_disable_protection_remains(self) -> None:
        self.login_as(1)

        response = self.client.put(
            "/api/admins/1",
            json={"role": "系統管理員", "is_active": 0},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("不能停用目前正在登入的自己", response.json["error"])


if __name__ == "__main__":
    unittest.main()
