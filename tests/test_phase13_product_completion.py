from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from flask import Blueprint
from werkzeug.security import generate_password_hash

from flask_data_repository import FirestoreFlaskDataRepository, SqliteFlaskDataRepository
from member_services import MemberAuthService, NotificationService


class FakeFinTrustClient:
    def health(self):
        return {"module": "test", "datastore_backend": "sqlite"}

    def companies(self):
        return {"companies": [{"ticker": "2454", "name": "聯發科", "subindustry": "IC 設計"}]}

    def latest_analysis(self, ticker):
        return {"ticker": ticker, "company_name": "聯發科", "overall_severity": "high", "summary": "test snapshot", "rule_cards": []}

    def metrics(self, ticker, *, latest_only=True, limit=1000):
        return {"ticker": ticker, "count": 1, "metrics": [{"run_id": "run-1", "period": "2026Q2", "metric_code": "revenue", "label": "Revenue", "value": 100, "unit": "元", "formula": "source"}]}

    def analysis_runs(self, ticker):
        return [{"run_id": "run-1", "ticker": ticker, "trigger": "manual", "status": "completed", "started_at": "2026-09-14T00:00:00Z", "completed_at": "2026-09-14T00:01:00Z", "overall_severity": "high"}]

    def conferences(self, ticker):
        return [
            {"event_id": "conf-1", "ticker": ticker, "company_name": "聯發科", "title": "Earnings call Q2", "status": "available", "conference_date": "2026-07-31", "source_name": "company_official_ir", "source_url": "https://example.test/ir", "document_url": "https://example.test/transcript.pdf", "document_text_preview": "Revenue growth and inventory recovery.", "retrieved_at": "2026-09-14T00:00:00Z", "extracted_topics": ["revenue_orders"]},
            {"event_id": "conf-2", "ticker": ticker, "company_name": "聯發科", "title": "Earnings call Q1", "status": "available", "conference_date": "2026-04-30", "source_name": "company_official_ir", "source_url": "https://example.test/ir-q1", "document_url": "https://example.test/q1.pdf", "retrieved_at": "2026-09-13T00:00:00Z"},
        ]

    def material_events(self, ticker):
        return [
            {"event_id": "mat-1", "ticker": ticker, "company_name": "聯發科", "title": "公告本公司董事會決議資本支出案", "status": "available", "event_date": "2026-09-01", "event_time": "17:30:00", "source_name": "twse_openapi", "source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L", "raw_text": "官方重大訊息內容", "retrieved_at": "2026-09-15T00:00:00Z", "related_metrics": ["capex_intensity"]},
            {"event_id": "mat-2", "ticker": ticker, "company_name": "聯發科", "title": "公告本公司營收資訊", "status": "available", "event_date": "2026-08-15", "source_name": "mops", "source_url": "https://mops.example/list", "detail_url": "https://mops.example/detail", "raw_text": "官方重大訊息內容", "retrieved_at": "2026-09-12T00:00:00Z"},
            {"event_id": "blocked", "ticker": ticker, "company_name": "聯發科", "title": "MOPS diagnostic placeholder", "status": "blocked_by_source", "event_date": None, "source_name": "mops", "source_url": "https://mops.example/blocked"},
        ]

    def official_evidence_card(self, ticker, extract_documents=False):
        return {"ticker": ticker, "company_name": "聯發科", "overall_severity": "high", "investor_conferences": self.conferences(ticker), "material_events": self.material_events(ticker), "run_id": "run-1", "narrative_shift": {"baseline_period": "2026Q1", "current_period": "2026Q2", "metrics": {"topic_distribution_jsd": 0.2, "tfidf_cosine_similarity": 0.7}}}

    def facts(self, ticker, *, limit=1000, run_id=None, period=None, statement_type=None, search=None):
        return {"ticker": ticker, "count": 1, "facts": [{"ticker": ticker, "period": "2026Q2", "metric_code": "revenue", "statement_type": "income_statement", "value": 100, "unit": "元", "source_url": "https://example.test"}]}

    def rule_results(self, ticker, *, limit=1000, run_id=None, triggered=None):
        return {"ticker": ticker, "count": 1, "rule_results": [{"run_id": "run-1", "rule_id": "r1", "name": "High risk", "triggered": True, "explanation": "Triggered", "evidence_metrics": ["revenue"]}]}

    def latest_text_intelligence(self, ticker):
        return {
            "run_id": "run-1",
            "ticker": ticker,
            "text_evidence": [{"sentence_text": "Revenue outlook changed.", "topics": ["financial_outlook"], "source_url": "https://example.test"}],
            "narrative_shift": {
                "baseline_period": "2026Q1",
                "current_period": "2026Q2",
                "metrics": {"topic_distribution_jsd": 0.2, "tfidf_cosine_similarity": 0.7},
                "emerging_terms": ["AI"],
                "disappearing_terms": ["inventory"],
            },
        }


class FakeSnapshot:
    exists = True
    id = "firebase_uid_123"

    def to_dict(self):
        return {"uid": "firebase_uid_123", "email": "member@example.com"}


class Phase13ProductCompletionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_env = {key: os.environ.get(key) for key in ("ALLOW_DEMO_SEED_DATA", "FLASK_DATABASE_PATH", "APP_ENV", "SECRET_KEY", "FINTRUST_API_BASE_URL", "MEMBER_ALLOW_LOCAL_PASSWORD_AUTH", "NOTIFICATION_JOB_TOKEN")}
        os.environ["ALLOW_DEMO_SEED_DATA"] = "false"
        os.environ["FLASK_DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "app-import.db")
        os.environ["APP_ENV"] = "development"
        os.environ["MEMBER_ALLOW_LOCAL_PASSWORD_AUTH"] = "true"
        os.environ.pop("SECRET_KEY", None)

        fake_data_shift = types.ModuleType("data_shift")
        fake_data_shift.data_shift_bp = Blueprint("data_shift_phase13_test", __name__)
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
        self.repo_dir = tempfile.TemporaryDirectory()
        self.repo = SqliteFlaskDataRepository(Path(self.repo_dir.name) / "phase13.sqlite3")
        self.repo.initialize()
        self.repo.create_admin({
            "username": "admin001",
            "password_hash": generate_password_hash("demo1234"),
            "display_name": "Admin",
            "role": "系統管理員",
            "is_active": 1,
            "created_at": "2026-09-14 00:00:00",
        })
        self.app_module.repository = self.repo
        self.app_module.member_auth = MemberAuthService(self.repo, app_env="development")
        self.app_module.FinTrustClient = FakeFinTrustClient
        self.client = self.app_module.app.test_client()

    def tearDown(self) -> None:
        self.repo_dir.cleanup()

    def test_member_e2e_profile_watchlist_preferences_and_logout(self) -> None:
        response = self.client.post("/api/member/auth/register", json={"email": "member@example.com", "password": "strongpass", "display_name": "Member"})
        self.assertEqual(response.status_code, 201)
        uid = response.json["member"]["uid"]
        self.assertEqual(self.repo.get_member(uid)["email"], "member@example.com")

        profile = self.client.put("/api/member/profile", json={"display_name": "New Member", "email": "member@example.com"})
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json["member"]["display_name"], "New Member")

        watch = self.client.post("/api/member/watchlist", json={"ticker": "2454", "company_name": "聯發科", "alert_enabled": True})
        self.assertEqual(watch.status_code, 201)
        self.assertEqual(self.client.get("/api/member/watchlist").json["items"][0]["ticker"], "2454")

        prefs = self.client.put("/api/member/notification-preferences", json={"email_enabled": True, "important_alerts": True, "material_event_alerts": False, "conference_alerts": True, "narrative_shift_alerts": True, "digest_frequency": "weekly"})
        self.assertEqual(prefs.status_code, 200)
        self.assertEqual(prefs.json["preferences"]["digest_frequency"], "weekly")

        evidence = self.client.get("/api/member/companies/2454/evidence")
        self.assertEqual(evidence.status_code, 200)

        self.assertEqual(self.client.post("/api/member/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/member/me").status_code, 401)

    def test_notification_decision_dedupe_and_new_evidence_identity(self) -> None:
        member = self.app_module.member_auth.register_local(email="notify@example.com", password="strongpass", display_name="Notify")
        self.repo.upsert_watchlist_item(member["uid"], {"ticker": "2454", "company_name": "聯發科", "alert_enabled": 1, "created_at": "t0", "updated_at": "t0"})
        evidence_state = {"run_id": "run-1"}

        service = NotificationService(
            self.repo,
            evidence_provider=lambda ticker: {"ticker": ticker, "company_name": "聯發科", "overall_severity": "high", "run_id": evidence_state["run_id"]},
        )
        first = service.process_member(member["uid"])
        second = service.process_member(member["uid"])
        evidence_state["run_id"] = "run-2"
        third = service.process_member(member["uid"])

        self.assertEqual(first[0]["status"], "sent")
        self.assertEqual(second[0]["status"], "suppressed_duplicate")
        self.assertEqual(third[0]["status"], "sent")
        history = self.repo.list_notification_history(member["uid"])
        self.assertEqual(len(history), 3)

    def test_event_level_notification_dedupe_and_digest_preferences(self) -> None:
        member = self.app_module.member_auth.register_local(email="events@example.com", password="strongpass", display_name="Events")
        self.repo.upsert_watchlist_item(member["uid"], {"ticker": "2454", "company_name": "聯發科", "alert_enabled": 1, "created_at": "t0", "updated_at": "t0"})
        self.repo.save_notification_preferences(member["uid"], {
            "email_enabled": 1,
            "important_alerts": 1,
            "material_event_alerts": 1,
            "conference_alerts": 0,
            "narrative_shift_alerts": 1,
            "digest_frequency": "weekly",
            "updated_at": "t0",
        })
        service = NotificationService(
            self.repo,
            evidence_provider=lambda ticker: {
                "ticker": ticker,
                "company_name": "聯發科",
                "notification_items": [
                    {"notification_type": "material_event", "evidence_identity": "mat-1", "title": "重大訊息一", "event_date": "2026-09-01", "source_name": "twse_openapi", "official_url": "https://example.test/mat-1"},
                    {"notification_type": "material_event", "evidence_identity": "mat-2", "title": "重大訊息二", "event_date": "2026-09-02", "source_name": "twse_openapi", "official_url": "https://example.test/mat-2"},
                    {"notification_type": "investor_conference", "evidence_identity": "conf-1", "title": "法說會"},
                    {"notification_type": "narrative_shift", "evidence_identity": "2026Q1->2026Q2", "baseline_period": "2026Q1", "current_period": "2026Q2", "metric_summary": "JSD=0.2"},
                ],
            },
        )

        daily = service.process_member(member["uid"], digest_frequency="daily")
        weekly = service.process_member(member["uid"], digest_frequency="weekly")
        duplicate_weekly = service.process_member(member["uid"], digest_frequency="weekly")

        self.assertEqual(daily, [])
        self.assertEqual([item["notification_type"] for item in weekly], ["material_event", "material_event", "narrative_shift"])
        self.assertTrue(all(item["status"] == "sent" for item in weekly))
        self.assertTrue(all(item["status"] == "suppressed_duplicate" for item in duplicate_weekly))

        self.repo.save_notification_preferences(member["uid"], {"digest_frequency": "off", "updated_at": "t1"})
        off = service.process_member(member["uid"])
        self.assertEqual(off, [])

    def test_official_browser_api_filters_multiple_real_records(self) -> None:
        response = self.client.get("/api/official-evidence/browser?ticker=2454&type=material_event&source=twse&limit=10")
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data["summary"]["material_event_count"], 2)
        self.assertEqual(len(data["records"]), 1)
        self.assertEqual(data["records"][0]["title"], "公告本公司董事會決議資本支出案")
        self.assertEqual(data["records"][0]["official_url"], "https://openapi.twse.com.tw/v1/opendata/t187ap04_L")
        self.assertEqual(data["summary"]["latest_official_event_date"], "2026-09-01")
        self.assertEqual(data["summary"]["system_last_synchronized_at"], "2026-09-15T00:00:00Z")
        self.assertEqual(data["summary"]["subindustry"], "IC 設計")
        self.assertEqual(data["text_intelligence"]["run_id"], "run-1")
        self.assertEqual(data["narrative_shift"]["baseline_period"], "2026Q1")
        self.assertNotIn("blocked_by_source", {item["status"] for item in data["records"]})

    def test_financial_evidence_page_is_owned_real_data_browser(self) -> None:
        html = Path("financial-evidence.html").read_text(encoding="utf-8")

        self.assertIn("/api/official-evidence/browser", html)
        self.assertIn("官方資料日期", html)
        self.assertIn("系統同步時間", html)
        self.assertIn("與上一期比較 / Narrative Shift", html)
        self.assertIn("Relevant-text JSD", html)
        self.assertIn("TF-IDF Cosine", html)
        self.assertIn("target=\"_blank\"", html)
        self.assertNotIn("公告本公司董事會決議資本支出案", html)
        self.assertNotIn("MOPS diagnostic placeholder", html)

    def test_records_page_uses_real_member_history_or_empty_state(self) -> None:
        response = self.client.get("/api/member/analysis-history")
        self.assertEqual(response.status_code, 401)

        member = self.app_module.member_auth.register_local(email="history@example.com", password="strongpass", display_name="History")
        with self.client.session_transaction() as session:
            session["member_uid"] = member["uid"]
        response = self.client.get("/api/member/analysis-history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [])
        self.assertIn("不提供假分析紀錄", response.json["message"])

    def test_admin_text_intelligence_lab_marks_weak_supervision(self) -> None:
        with self.client.session_transaction() as session:
            session["admin_id"] = 1

        response = self.client.get("/api/admin/text-intelligence-lab/summary")
        self.assertEqual(response.status_code, 200)
        self.assertIn("WEAK SUPERVISION", response.json["weak_supervision_notice"])
        self.assertIn("Human GT", response.json["weak_supervision_notice"])
        self.assertEqual(response.json["persistence_design"]["training_safety"], "No model training runs synchronously inside Flask/FastAPI browser requests.")

    def test_admin_financial_evidence_surface_contains_narrative_shift_metrics(self) -> None:
        html = Path("admin-financial-evidence.html").read_text(encoding="utf-8")

        self.assertIn("與上一期比較 / Narrative Shift", html)
        self.assertIn("Relevant-text JSD", html)
        self.assertIn("Topic JSD", html)
        self.assertIn("TF-IDF Cosine", html)
        self.assertIn("official source", html)

    def test_admin_evidence_console_api_and_refresh_auth_boundary(self) -> None:
        unauth = self.client.post("/api/financial/admin/companies/2454/unified-refresh", json={"include_gemini": False})
        self.assertEqual(unauth.status_code, 401)

        with self.client.session_transaction() as session:
            session["admin_id"] = 1

        status = self.client.get("/api/admin/system/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json["flask_datastore_backend"], "sqlite")

        overview = self.client.get("/api/admin/financial/companies/2454/overview")
        self.assertIn(overview.status_code, {200, 207})
        data = overview.json["data"]
        self.assertEqual(data["facts"]["count"], 1)
        self.assertEqual(data["rule_results"]["count"], 1)
        self.assertEqual(len(data["text_intelligence"]["text_evidence"]), 1)

    def test_scheduler_endpoint_requires_token_when_configured(self) -> None:
        os.environ["NOTIFICATION_JOB_TOKEN"] = "test-token"
        try:
            self.assertEqual(self.client.post("/api/system/notifications/process").status_code, 401)
            ok = self.client.post("/api/system/notifications/process", headers={"X-Notification-Job-Token": "test-token"})
            self.assertEqual(ok.status_code, 200)
        finally:
            os.environ.pop("NOTIFICATION_JOB_TOKEN", None)

    def test_firestore_member_identity_shape_keeps_string_ids_and_disables_passwords(self) -> None:
        payload = FirestoreFlaskDataRepository._doc_payload(FakeSnapshot())
        self.assertEqual(payload["id"], "firebase_uid_123")

        repo = object.__new__(FirestoreFlaskDataRepository)
        with self.assertRaises(RuntimeError):
            repo.set_member_password_hash("firebase_uid_123", "hash")

        os.environ["MEMBER_ALLOW_LOCAL_PASSWORD_AUTH"] = "true"
        try:
            self.assertFalse(MemberAuthService(self.repo, app_env="production").local_password_enabled())
        finally:
            os.environ["MEMBER_ALLOW_LOCAL_PASSWORD_AUTH"] = "true"


if __name__ == "__main__":
    unittest.main()
