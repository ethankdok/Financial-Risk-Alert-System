"""Integrity Workbench Phase 1: Flask host integration, proxy whitelist and error pass-through (no network).

The full API → Flask → page chain is covered in ``fintrust_backend/tests/test_integrity_phase1_api.py``.
"""

from __future__ import annotations

import importlib
import io
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from flask import Flask

from fintrust_client import FinTrustClient
from integrity_routes import create_integrity_blueprint
from tests.test_claim_verification_proxy import FakeHttpResponse

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.example.test"


class IntegrityHostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        env = {"ALLOW_DEMO_SEED_DATA": "false", "APP_ENV": "development",
               "FLASK_DATABASE_PATH": str(Path(cls.temp.name) / "integrity-proxy.db")}
        with patch.dict(os.environ, env):
            sys.modules.pop("app", None)
            cls.app_module = importlib.import_module("app")

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop("app", None)
        cls.temp.cleanup()

    def test_routes_registered_alongside_existing_ones(self) -> None:
        rules = {rule.rule for rule in self.app_module.app.url_map.iter_rules()}
        for rule in ("/api/integrity/companies", "/api/integrity/companies/<ticker>/readiness",
                     "/api/integrity/assessments/preview", "/api/research/cases", "/api/financial/companies", "/health"):
            self.assertIn(rule, rules)
        self.assertFalse([r for r in rules if r.startswith("/api/integrity") and ("persist" in r or "admin" in r)])

    def test_page_served_and_single_low_interference_entry(self) -> None:
        client = self.app_module.app.test_client()
        page = client.get("/financial-integrity.html")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"financial-integrity.js", page.data)
        page.close()
        script = client.get("/financial-integrity.js")
        self.assertEqual(script.status_code, 200)
        self.assertNotIn(b"innerHTML", script.data)
        self.assertNotIn(b"fintrust_backend", script.data)
        script.close()
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertEqual(index.count('href="financial-integrity.html"'), 1)
        self.assertEqual(sum(p.read_text(encoding="utf-8").count("financial-integrity.html")
                             for p in ROOT.glob("*.html") if p.name not in ("index.html", "financial-integrity.html")), 0)
        dockerfile = (ROOT / "Dockerfile.flask").read_text(encoding="utf-8")
        self.assertIn("integrity_routes.py", dockerfile)  # app.py imports it at start-up
        self.assertIn("COPY *.html *.js *.css ./", dockerfile)

    def test_page_calls_only_same_origin_flask_routes(self) -> None:
        script = (ROOT / "financial-integrity.js").read_text(encoding="utf-8")
        urls = set(re.findall(r'"(/api/[^"]+)"', script))
        self.assertEqual(urls, {"/api/integrity/companies", "/api/integrity/assessments/preview"})
        self.assertNotRegex(script, r"https?://(?!doi\.org)[a-z]")
        self.assertNotIn("persist: true", script)


class IntegrityProxyTests(unittest.TestCase):
    def client(self, opener):
        app = Flask(__name__)
        app.register_blueprint(create_integrity_blueprint(
            client=FinTrustClient(base_url=BASE, ingestion_token="secret-token", opener=opener)))
        return app.test_client()

    def test_forwards_whitelisted_body_with_persist_false_and_no_token(self) -> None:
        seen = []

        def opener(request, timeout):
            seen.append((request.full_url, request.get_method(), json.loads(request.data),
                         {k.lower() for k, _ in request.header_items()}))
            return FakeHttpResponse({"ticker": "2454"})

        response = self.client(opener).post("/api/integrity/assessments/preview", json={
            "ticker": "2454", "sections": ["jsd", "jsd", "claims"], "review_mode": "CURRENT_REVIEW",
            "base_url": "http://evil.test", "token": "x"})
        self.assertEqual(response.status_code, 200)
        url, method, body, headers = seen[0]
        self.assertEqual((url, method), (f"{BASE}/api/v1/integrity/assessments/preview", "POST"))
        self.assertEqual(body, {"ticker": "2454", "review_mode": "CURRENT_REVIEW", "sections": ["jsd", "claims"],
                                "persist": False})
        self.assertNotIn("x-ingestion-token", headers)

    def test_invalid_input_is_rejected_before_the_backend(self) -> None:
        calls = []
        client = self.client(lambda request, timeout: calls.append(request))
        for body in ({"ticker": "AMT"}, {}, {"ticker": "2454", "persist": True}, {"ticker": "2454", "persist": "true"},
                     {"ticker": "2454", "sections": "jsd"}, {"ticker": "2454", "sections": []},
                     {"ticker": "2454", "review_mode": "as_of"}):
            with self.subTest(body=body):
                self.assertEqual(client.post("/api/integrity/assessments/preview", json=body).status_code, 400)
        self.assertEqual(client.post("/api/integrity/assessments/preview", data="not json").status_code, 400)
        self.assertEqual(client.get("/api/integrity/companies/24X4/readiness").status_code, 400)
        self.assertEqual(calls, [])

    def test_backend_errors_pass_through_without_leaking_secrets(self) -> None:
        for status in (403, 404, 409, 422, 503):
            with self.subTest(status=status):
                detail = {"detail": {"error_code": f"code_{status}", "message": "m"}}

                def opener(request, timeout, status=status, detail=detail):
                    raise HTTPError(request.full_url, status, "error", {}, io.BytesIO(json.dumps(detail).encode()))

                response = self.client(opener).get("/api/integrity/companies/2454/readiness")
                payload = response.get_json()
                self.assertEqual((response.status_code, payload["detail"]["error_code"]), (status, f"code_{status}"))
                self.assertNotIn("secret-token", response.get_data(as_text=True))
                self.assertNotIn(BASE, response.get_data(as_text=True))

    def test_unreachable_backend_is_502(self) -> None:
        from urllib.error import URLError

        def opener(request, timeout):
            raise URLError("connection refused")

        self.assertEqual(self.client(opener).get("/api/integrity/companies").status_code, 502)

    def test_client_methods_never_persist(self) -> None:
        seen = []
        client = FinTrustClient(base_url=BASE, opener=lambda r, t: seen.append(json.loads(r.data)) or FakeHttpResponse({}))
        client.integrity_preview({"ticker": "2454", "persist": True})
        self.assertEqual(seen, [{"ticker": "2454", "persist": False}])


if __name__ == "__main__":
    unittest.main()
