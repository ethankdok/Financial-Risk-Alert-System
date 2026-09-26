from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Blueprint
from werkzeug.security import generate_password_hash

from fintrust_client import FinTrustClient
from flask_data_repository import SqliteFlaskDataRepository
from member_services import EmailMessage, SmtpEmailProvider, create_email_provider


class FakeFinTrustClient:
    def health(self):
        return {"module": "test", "datastore_backend": "sqlite"}


class FakeSmtpClient:
    sent_messages = []
    logged_in = False
    tls_started = False

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self, context=None):
        self.__class__.tls_started = True

    def login(self, username, password):
        self.__class__.logged_in = True

    def send_message(self, message):
        self.__class__.sent_messages.append(message)


class FakeHttpResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b'{"status":"ok"}'


class Phase15FlaskReleaseReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_env = {
            key: os.environ.get(key)
            for key in (
                "ALLOW_DEMO_SEED_DATA",
                "FLASK_DATABASE_PATH",
                "APP_ENV",
                "SECRET_KEY",
                "EMAIL_PROVIDER",
                "SMTP_HOST",
                "SMTP_PORT",
                "SMTP_USERNAME",
                "SMTP_PASSWORD",
                "EMAIL_FROM",
                "SMTP_USE_TLS",
                "MEMBER_ALLOW_LOCAL_PASSWORD_AUTH",
            )
        }
        os.environ["ALLOW_DEMO_SEED_DATA"] = "false"
        os.environ["FLASK_DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "phase15-import.db")
        os.environ["APP_ENV"] = "development"
        os.environ["MEMBER_ALLOW_LOCAL_PASSWORD_AUTH"] = "true"
        os.environ.pop("SECRET_KEY", None)

        fake_data_shift = types.ModuleType("data_shift")
        fake_data_shift.data_shift_bp = Blueprint("data_shift_phase15_test", __name__)
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
        self.repo = SqliteFlaskDataRepository(Path(self.repo_dir.name) / "phase15.sqlite3")
        self.repo.initialize()
        self.repo.create_admin({
            "username": "admin001",
            "password_hash": generate_password_hash("demo1234"),
            "display_name": "Admin",
            "role": "系統管理員",
            "is_active": 1,
            "created_at": "2026-09-15 00:00:00",
        })
        self.app_module.repository = self.repo
        self.app_module.FinTrustClient = FakeFinTrustClient
        self.client = self.app_module.app.test_client()

    def tearDown(self) -> None:
        self.repo_dir.cleanup()

    def test_smtp_provider_sends_without_exposing_secret_in_health(self) -> None:
        provider = SmtpEmailProvider(
            host="smtp.example.test",
            port=587,
            username="user",
            password="secret-password",
            from_email="alerts@example.test",
            use_tls=True,
            use_ssl=False,
        )
        FakeSmtpClient.sent_messages = []
        FakeSmtpClient.logged_in = False
        FakeSmtpClient.tls_started = False

        with patch("member_services.smtplib.SMTP", FakeSmtpClient):
            result = provider.send(EmailMessage(
                to_email="member@example.test",
                subject="Release smoke",
                body="Hello",
                notification_type="release_smoke",
            ))

        self.assertEqual(result["status"], "sent")
        self.assertTrue(FakeSmtpClient.tls_started)
        self.assertTrue(FakeSmtpClient.logged_in)
        self.assertEqual(FakeSmtpClient.sent_messages[0]["To"], "member@example.test")
        self.assertNotIn("secret-password", str(provider.health()))

    def test_email_provider_factory_defaults_to_console_and_supports_smtp(self) -> None:
        os.environ["EMAIL_PROVIDER"] = "console"
        self.assertEqual(create_email_provider().name, "console")

        os.environ["EMAIL_PROVIDER"] = "smtp"
        os.environ["SMTP_HOST"] = "smtp.example.test"
        os.environ["SMTP_PORT"] = "587"
        os.environ["EMAIL_FROM"] = "alerts@example.test"
        self.assertEqual(create_email_provider().name, "smtp")

    def test_admin_system_status_reports_notification_provider_health(self) -> None:
        with self.client.session_transaction() as session:
            session["admin_id"] = 1
        os.environ["EMAIL_PROVIDER"] = "smtp"
        os.environ["SMTP_HOST"] = "smtp.example.test"
        os.environ["SMTP_PORT"] = "587"
        os.environ["EMAIL_FROM"] = "alerts@example.test"

        response = self.client.get("/api/admin/system/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["notification_provider"]["provider"], "smtp")
        self.assertTrue(response.json["notification_provider"]["configured"])

    def test_flask_dockerfile_packages_member_services_module(self) -> None:
        dockerfile = Path(__file__).resolve().parents[1] / "Dockerfile.flask"
        content = dockerfile.read_text(encoding="utf-8")

        self.assertIn("member_services.py", content)

    def test_extensionless_html_routes_are_served_for_browser_links(self) -> None:
        response = self.client.get("/result")

        self.assertEqual(response.status_code, 200)
        self.assertIn("金融資訊分析結果", response.get_data(as_text=True))

    def test_fintrust_client_health_uses_service_health_endpoint(self) -> None:
        seen = {}

        def opener(request, timeout):
            seen["url"] = request.full_url
            return FakeHttpResponse()

        result = FinTrustClient(base_url="https://api.example.test", opener=opener).health()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(seen["url"], "https://api.example.test/health")


if __name__ == "__main__":
    unittest.main()
