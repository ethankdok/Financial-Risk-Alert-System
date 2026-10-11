"""API → Flask proxy → page renderer chain (in-process, no network, no production side effects).

The Flask research blueprint forwards through ``FinTrustClient`` whose opener dispatches to the FastAPI app via
``TestClient``. Payloads are checked for FastAPI/Flask parity and rendered with the real ``historical-research.js``
render functions under Node. FIXTURE tier always runs; the REAL tier runs on the approved local archive.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.routers.historical_research import get_research_service
from app.services.financial_research.service import ReadOnlyHistoricalAuditRepository, ResearchService
from tests.test_financial_research_real import HAS_REAL, service as real_service
from tests.test_historical_evidence import EvidenceTestCase

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))  # appended: the FastAPI ``app`` package keeps precedence over the root Flask app.py

from flask import Flask  # noqa: E402

import research_routes  # noqa: E402
from fintrust_client import FinTrustClient  # noqa: E402

BASE = "http://fastapi.internal"
VIEWS = {
    "overview": ("/cases/1785", {}),
    "bridge": ("/cases/1785/restatement-bridge", {"analysis_mode": "RETROSPECTIVE_FORENSIC", "scope": "consolidated"}),
    "timeline": ("/cases/1785/timeline", {"analysis_mode": "STRICT_AS_OF", "cutoff_at": "2016-05-13T00:00:00+08:00", "limit": "50"}),
    "discrepancy": ("/cases/1785/source-discrepancies", {"analysis_mode": "CURRENT_EVIDENCE_RECONCILIATION"}),
    "text": ("/cases/1785/text-readiness", {"analysis_mode": "RETROSPECTIVE_FORENSIC"}),
}
STRICT_BODY = {"ticker": "1785", "analysis_mode": "STRICT_AS_OF", "cutoff_at": "2016-05-13T00:00:00+08:00",
               "version_policy": "latest_available", "start_year": 2011, "end_year": 2016}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def fastapi_opener(client: TestClient, seen: list):
    def opener(request, timeout):
        path = request.full_url[len(BASE):]
        seen.append((request.get_method(), path, request.data))
        response = client.request(request.get_method(), path, content=request.data,
                                  headers={k: v for k, v in request.header_items()})
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, "error", {}, io.BytesIO(response.content))
        return _Response(response.content)
    return opener


def render(payloads: dict) -> dict:
    result = subprocess.run(["node", str(BACKEND / "tests" / "research_ui_harness.js")], input=json.dumps(payloads),
                            capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    return json.loads(result.stdout)


class ChainMixin:
    service: ResearchService

    def start_chain(self) -> None:
        fastapi_app.dependency_overrides[get_research_service] = lambda: self.service
        self.api = TestClient(fastapi_app)
        self.seen: list = []
        flask_app = Flask(__name__)
        flask_app.register_blueprint(research_routes.create_research_blueprint(
            client=FinTrustClient(base_url=BASE, opener=fastapi_opener(self.api, self.seen))))
        self.web = flask_app.test_client()

    def stop_chain(self) -> None:
        self.api.close()
        fastapi_app.dependency_overrides.clear()

    def collect(self) -> dict:
        payloads = {}
        for view, (path, params) in VIEWS.items():
            proxied = self.web.get(f"/api/research{path}", query_string=params)
            direct = self.api.get(f"/api/v1/research{path}", params=params)
            self.assertEqual((proxied.status_code, direct.status_code), (200, 200), view)
            self.assertEqual(proxied.get_json(), {"success": True, "data": direct.json()}, view)  # proxy parity
            payloads[view] = direct.json()
        computed = self.web.post("/api/research/financial-signals/compute", json={**STRICT_BODY, "persist": True})
        self.assertEqual(computed.status_code, 200)
        self.assertFalse(computed.get_json()["data"]["persisted"])  # the browser path can never persist
        self.assertFalse(json.loads(self.seen[-1][2])["persist"])
        payloads["signals"] = computed.get_json()["data"]
        return payloads

    def check_errors_pass_through(self) -> None:
        cases = [(self.web.get("/api/research/cases/2330"), 404),
                 (self.web.get("/api/research/cases/1785/timeline", query_string={"analysis_mode": "STRICT_AS_OF"}), 422),
                 (self.web.get("/api/research/cases/1785/source-discrepancies",
                               query_string={"analysis_mode": "RETROSPECTIVE_FORENSIC"}), 409),
                 (self.web.get("/api/research/cases/1785/../../etc"), 404), (self.web.get("/api/research/cases/x1/timeline"), 400),
                 (self.web.get("/api/research/cases/1785/admin"), 400), (self.web.get("/api/research/runs/bad"), 400)]
        for response, status in cases:
            self.assertEqual(response.status_code, status, response.get_data(as_text=True)[:200])
        detail = self.web.get("/api/research/cases/1785/timeline", query_string={"analysis_mode": "STRICT_AS_OF"}).get_json()
        self.assertEqual(detail["detail"]["error_code"], "cutoff_at_required")
        injected = self.web.get("/api/research/cases/1785/timeline",
                                query_string={"analysis_mode": "RETROSPECTIVE_FORENSIC", "persist": "true", "path": "/etc"})
        self.assertEqual(injected.status_code, 200)
        self.assertNotIn("persist", self.seen[-1][1])  # non-whitelisted parameters are dropped

    def check_rendered(self, html: dict) -> None:
        for view, text in html.items():
            self.assertNotIn("風險低", text, view)
            self.assertNotIn("低風險", text, view)
            self.assertNotIn("<script", text.lower(), view)
            for anchor in __import__("re").findall(r"<a [^>]+>", text):
                self.assertIn('rel="noopener noreferrer"', anchor)
                self.assertRegex(anchor, r'href="https?://(mopsov\.twse\.com\.tw|mops\.twse\.com\.tw|doc\.twse\.com\.tw|www\.tpex\.org\.tw)')
        self.assertIn("依 2016 年 11 月公告回溯重述", html["bridge"])
        self.assertIn("目前缺乏可核驗的事件前財務輸入", html["signals"])
        self.assertIn("NOT_APPLICABLE", html["text"])
        self.assertIn("RETROSPECTIVE_FORENSIC", html["bridge"])
        self.assertIn("STRICT_AS_OF", html["timeline"])


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page renderer")
class FixtureChainTests(ChainMixin, EvidenceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_all()
        self.service = ResearchService(repository=ReadOnlyHistoricalAuditRepository(self.repository.database_path),
                                       conference_repository=None, pdf_provider=None)
        self.start_chain()

    def tearDown(self) -> None:
        self.stop_chain()
        super().tearDown()

    def test_chain_parity_rendering_and_error_pass_through(self) -> None:
        payloads = self.collect()
        html = render(payloads)
        self.check_rendered(html)
        self.check_errors_pass_through()

    def test_untrusted_text_is_escaped(self) -> None:
        payload = self.collect()["timeline"]
        payload["events"] = [{**payload["events"][0], "title": '<img src=x onerror="alert(1)"><script>x</script>',
                              "source_url": "javascript:alert(1)"}] if payload["events"] else []
        payload["total"] = len(payload["events"])
        html = render({"timeline": payload})["timeline"]
        self.assertNotIn("<img", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("javascript:", html)


@unittest.skipUnless(shutil.which("node") and HAS_REAL, "node and the approved local archive are required")
class RealChainTests(ChainMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.service = real_service()
        self.start_chain()

    def tearDown(self) -> None:
        self.stop_chain()

    def test_real_chain_renders_the_case_evidence(self) -> None:
        payloads = self.collect()
        signals = payloads["signals"]["result"]
        payloads["detail"] = next(f for f in signals["features"] if f["feature_id"] == "gross_margin")
        html = render(payloads)
        self.check_rendered(html)
        self.assertIn("1,721 千元", html["discrepancy"])
        self.assertIn("34,436,171 千元", html["discrepancy"])
        self.assertIn("34,434,450 千元", html["discrepancy"])
        self.assertIn("19,423,635 千元", html["discrepancy"])
        self.assertIn("19,421,914 千元", html["discrepancy"])
        self.assertIn("fc7151400c1cd776852e9f309f7840eb794881f6e1ab27970cf2c2996b613b01", html["discrepancy"])
        self.assertIn("第 8 頁", html["discrepancy"])
        self.assertIn("不轉入風險分數", html["discrepancy"])
        self.assertIn("967,367 千元", html["bridge"])  # FY2013 consolidated ΔCOGS
        self.assertIn("-2.8252%", html["bridge"])  # FY2013 consolidated gross-margin change
        for value in ("44", "38", "1190／1139"):
            self.assertIn(f"<strong>{value}</strong>", html["text"])
        self.assertIn("<strong>0</strong>", html["text"])
        self.assertIn("E1_official_listing_metadata", html["timeline"])
        self.assertIn("no_verified_observation_before_cutoff", html["detail"])
        self.check_errors_pass_through()


if __name__ == "__main__":
    unittest.main()
