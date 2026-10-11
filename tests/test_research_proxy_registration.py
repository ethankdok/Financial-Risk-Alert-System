"""Phase 4: the shared Flask app registers the research proxy, serves the research page, and ships it in its image.

Research proxy behaviour (parity, error pass-through, no persistence from the browser) is covered end to end in
``fintrust_backend/tests/test_research_ui_chain.py``; here only the Flask host integration is checked.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from fintrust_client import FinTrustClient
from research_routes import create_research_blueprint

ROOT = Path(__file__).resolve().parents[1]


class _Response:
    def __init__(self, payload) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


class ResearchProxyRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        env = {"ALLOW_DEMO_SEED_DATA": "false", "APP_ENV": "development",
               "FLASK_DATABASE_PATH": str(Path(cls.temp.name) / "research-proxy.db")}
        with patch.dict(os.environ, env):
            sys.modules.pop("app", None)
            cls.app_module = importlib.import_module("app")

    @classmethod
    def tearDownClass(cls) -> None:
        sys.modules.pop("app", None)
        cls.temp.cleanup()

    def test_routes_registered_without_changing_existing_ones(self) -> None:
        rules = {rule.rule for rule in self.app_module.app.url_map.iter_rules()}
        for rule in ("/api/research/cases", "/api/research/cases/<ticker>", "/api/research/cases/<ticker>/<view>",
                     "/api/research/financial-signals/compute", "/api/research/runs/<run_id>",
                     "/api/research/literature/models", "/api/research/cases/<ticker>/literature/coverage",
                     "/api/research/literature/<action>",
                     "/api/financial/companies", "/api/financial/data-shift/analyze", "/health"):
            self.assertIn(rule, rules)
        self.assertFalse([r for r in rules if r.startswith("/api/research") and "admin" in r])

    def test_research_page_is_served_and_shipped(self) -> None:
        client = self.app_module.app.test_client()
        page = client.get("/historical-research.html")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"historical-research.js", page.data)
        page.close()
        script = client.get("/historical-research.js")
        self.assertEqual(script.status_code, 200)
        script.close()
        dockerfile = (ROOT / "Dockerfile.flask").read_text(encoding="utf-8")
        self.assertIn("research_routes.py", dockerfile)
        self.assertIn("COPY *.html *.js *.css ./", dockerfile)

    def test_catch_all_serves_web_assets_only(self) -> None:
        client = self.app_module.app.test_client()
        for path in ("/financial_risk.db", "/app.py", "/requirements.txt", "/.env", "/static/../app.py",
                     "/fintrust_backend/data/historical_audit/historical_audit.sqlite3",
                     "/fintrust_backend/app/main.py", "/docs/development/PHASE3_5_DESIGN_LOCK.md", "/phase9-web-before.json"):
            response = client.get(path)
            self.assertEqual(response.status_code, 404, path)
            response.close()
        for path in ("/", "/index.html", "/analysis", "/style.css", "/static/script.js", "/historical-research.js"):
            response = client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()

    def test_encoded_traversal_backups_and_streams_are_refused(self) -> None:
        client = self.app_module.app.test_client()
        for path in ("/%2e%2e/app.py", "/static/%2e%2e/app.py", "/static/..%2fapp.py", "/%252e%252e/app.py",
                     "/static%5c..%5capp.py", "/static/%5c..%5capp.py", "/app.py%00.html", "/style.css::$DATA",
                     "/index.html~", "/static/./script.js", "//etc/passwd", "/financial_risk.db%2ehtml",
                     "/templates/../app.py", "/static/script_backup.js"):
            response = client.get(path)
            self.assertIn(response.status_code, (400, 404), path)
            self.assertNotIn(b"import ", response.data, path)
            response.close()
        servable = self.app_module._servable
        for name in ("static/script_backup.js", "static/script_before_summary.js", "index.html.bak", "app.html.orig",
                     "x.tmp.js", "a:b.html", "%2e%2e.html", "static\\..\\app.py", "a\x00.html"):
            self.assertFalse(servable(name), name)
        for name in ("index.html", "historical-research.js", "static/script.js", "templates/index.html", "style.css"):
            self.assertTrue(servable(name), name)

    def test_every_root_web_asset_is_a_tracked_site_file(self) -> None:
        import subprocess

        tracked = set(subprocess.run(["git", "ls-files", "*.html", "*.js", "*.css"], cwd=ROOT, capture_output=True,
                                     text=True, check=True).stdout.split())
        on_disk = {p.name for p in ROOT.iterdir() if p.is_file() and p.suffix in {".html", ".js", ".css"}}
        self.assertFalse(on_disk - tracked, "untracked root web files would be publicly served")
        client = self.app_module.app.test_client()
        for name in sorted(on_disk):
            response = client.get(f"/{name}")
            self.assertEqual(response.status_code, 200, name)
            response.close()

    def test_unconfigured_backend_returns_a_structured_error(self) -> None:
        app = Flask(__name__)
        app.register_blueprint(create_research_blueprint(client=FinTrustClient(
            base_url="https://api.example.test", opener=lambda request, timeout: _Response({"count": 0, "cases": []}))))
        response = app.test_client().get("/api/research/cases")
        self.assertEqual(response.get_json(), {"success": True, "data": {"count": 0, "cases": []}})
        with patch.dict(os.environ, {"FINTRUST_API_BASE_URL": ""}):
            unconfigured = Flask(__name__)
            unconfigured.register_blueprint(create_research_blueprint())
            failed = unconfigured.test_client().get("/api/research/cases")
        self.assertEqual(failed.status_code, 502)
        self.assertFalse(failed.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
