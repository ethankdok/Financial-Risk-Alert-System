"""Integrity Workbench Phase 1: FastAPI contract, errors, and the API → FinTrustClient → Flask → page chain.

SYNTHETIC fixtures only; the workbench dependency is overridden, so nothing touches real data or the network.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.routers.integrity import get_integrity_workbench
from tests.integrity_fixtures import (
    BASE_DATA,
    FakeBridge,
    FakeClaimService,
    FakeRepository,
    annual_rows,
    archive_for,
    registry_file,
    shift_result,
    statement,
    workbench,
)

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))  # appended: the FastAPI ``app`` package keeps precedence over the root Flask app.py

from flask import Flask  # noqa: E402

import integrity_routes  # noqa: E402
from fintrust_client import FinTrustClient  # noqa: E402

BASE = "http://fastapi.internal"
XSS = '<img src=x onerror="alert(1)">'
TOP_LEVEL = {"contract_version", "ticker", "company", "review_mode", "generated_at", "data_latest_available_at",
             "method_approval", "point_in_time_supported", "hindsight", "source_coverage", "financial_overview",
             "paper_models", "financial_findings", "claim_checks", "data_shift", "evidence_records",
             "investigation_priority", "next_checks", "missing_data", "method_versions", "dependency_digests", "persist"}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def Event():
    """SYNTHETIC material event with hostile strings (real model used by OfficialEvidenceService)."""
    from app.official_event_models import MaterialEventRecord

    return MaterialEventRecord(ticker="2303", company_name="SYNTHETIC", subindustry="synthetic", title=XSS,
                               event_date="2025-03-01", source_url="javascript:alert(1)", status="available")


class ApiTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.entry = statement(excerpt=f"Net Sales 1,000 {XSS}")
        registry = registry_file(Path(self.tmp.name), [self.entry])
        self.repo = FakeRepository(annual_rows("2303", BASE_DATA) + annual_rows(
            "2303", {"revenue": {2022: 1000000000.0}}))
        self.wb = workbench(repository=self.repo, bridge=FakeBridge(shift_result()), archive=archive_for(self.entry),
                            claim_service=FakeClaimService("supported", period="2024FY"), registry=registry)
        fastapi_app.dependency_overrides[get_integrity_workbench] = lambda: self.wb
        self.api = TestClient(fastapi_app)

    def tearDown(self) -> None:
        self.api.close()
        fastapi_app.dependency_overrides.clear()
        self.tmp.cleanup()


class ContractTests(ApiTestCase):
    def test_preview_contract_typed_and_decimal_strings(self) -> None:
        response = self.api.post("/api/v1/integrity/assessments/preview", json={"ticker": "2303"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(TOP_LEVEL <= set(body), TOP_LEVEL - set(body))
        self.assertEqual((body["review_mode"], body["persist"], body["point_in_time_supported"]), ("CURRENT_REVIEW", False, False))
        f1 = body["financial_findings"][0]
        self.assertEqual((f1["status"], f1["computed"]["gap"]), ("descriptive_divergence", "0.4"))
        for record in body["evidence_records"]:
            self.assertTrue(record["value"] is None or isinstance(record["value"], str))
        self.assertEqual(body["data_shift"]["metrics"], {"jsd": "0.123456", "cosine_similarity": "0.876543"})
        self.assertEqual(len(body["dependency_digests"]["input_digest"]), 64)

    def test_sections_subset(self) -> None:
        body = self.api.post("/api/v1/integrity/assessments/preview",
                             json={"ticker": "2303", "sections": ["financial_checks"]}).json()
        self.assertEqual((body["paper_models"], body["claim_checks"], body["data_shift"]), ([], [], None))

    def test_companies_and_readiness(self) -> None:
        companies = self.api.get("/api/v1/integrity/companies").json()
        self.assertEqual({c["ticker"] for c in companies["companies"]}, {"2303", "2330", "2454", "3711"})
        self.assertTrue(next(c for c in companies["companies"] if c["ticker"] == "2303")["persisted_snapshot"] is False)
        readiness = self.api.get("/api/v1/integrity/companies/2303/readiness").json()
        self.assertEqual(readiness["modules"]["F1_revenue_receivables"]["status"], "descriptive_divergence")
        self.assertEqual(readiness["review_modes"]["STRICT_AS_OF"], "not_supported_publication_times_unknown")

    def test_error_statuses(self) -> None:
        post = lambda body: self.api.post("/api/v1/integrity/assessments/preview", json=body)  # noqa: E731
        self.assertEqual(post({"ticker": "2303", "persist": True}).status_code, 422)
        self.assertEqual(post({"ticker": "2303", "backend_url": "http://evil"}).status_code, 422)
        self.assertEqual(post({"ticker": "2303", "sections": ["fraud_score"]}).status_code, 422)
        self.assertEqual(post({"ticker": "23O3"}).status_code, 422)
        strict = post({"ticker": "2303", "review_mode": "STRICT_AS_OF"})
        self.assertEqual((strict.status_code, strict.json()["detail"]["error_code"]), (409, "review_mode_not_supported"))
        unknown = post({"ticker": "1785"})
        self.assertEqual((unknown.status_code, unknown.json()["detail"]["error_code"]), (404, "ticker_not_supported"))
        self.assertEqual(self.api.get("/api/v1/integrity/companies/9999/readiness").status_code, 404)
        self.repo.fail = True
        outage = post({"ticker": "2303"})
        self.assertEqual((outage.status_code, outage.json()["detail"]["error_code"]), (503, "integrity_data_unavailable"))
        self.assertEqual(self.api.get("/api/v1/integrity/companies").status_code, 503)

    def test_no_write_route_and_only_read_calls(self) -> None:
        paths = fastapi_app.openapi()["paths"]
        routes = {(path, tuple(sorted(m.upper() for m in ops))) for path, ops in paths.items()
                  if path.startswith("/api/v1/integrity")}
        self.assertEqual(routes, {("/api/v1/integrity/companies", ("GET",)),
                                  ("/api/v1/integrity/companies/{ticker}/readiness", ("GET",)),
                                  ("/api/v1/integrity/assessments/preview", ("POST",))})
        self.api.post("/api/v1/integrity/assessments/preview", json={"ticker": "2303"})
        self.assertTrue(set(self.repo.calls) <= {"list_facts", "get_latest_snapshot", "list_investor_conferences",
                                                 "list_material_events", "get_official_event_sync_status"}, self.repo.calls)


def fastapi_opener(client: TestClient, seen: list):
    def opener(request, timeout):
        path = request.full_url[len(BASE):]
        seen.append((request.get_method(), path, request.data, dict(request.header_items())))
        response = client.request(request.get_method(), path, content=request.data,
                                  headers={k: v for k, v in request.header_items()})
        if response.status_code >= 400:
            raise HTTPError(request.full_url, response.status_code, "error", {}, io.BytesIO(response.content))
        return _Response(response.content)
    return opener


class ChainTests(ApiTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.repo.events = [Event()]
        self.seen: list = []
        flask_app = Flask(__name__)
        flask_app.register_blueprint(integrity_routes.create_integrity_blueprint(
            client=FinTrustClient(base_url=BASE, ingestion_token="secret-token", opener=fastapi_opener(self.api, self.seen))))
        self.web = flask_app.test_client()

    def test_flask_parity_whitelist_and_no_token(self) -> None:
        direct = self.api.post("/api/v1/integrity/assessments/preview", json={"ticker": "2303"}).json()
        proxied = self.web.post("/api/integrity/assessments/preview",
                                json={"ticker": "2303", "base_url": "http://evil", "persist": False, "extra": 1}).get_json()
        self.assertTrue(proxied["success"])
        for key in ("financial_findings", "paper_models", "claim_checks", "data_shift", "investigation_priority", "next_checks"):
            self.assertEqual(proxied["data"][key], direct[key])
        method, path, body, headers = self.seen[-1]
        self.assertEqual((method, path, json.loads(body)), ("POST", "/api/v1/integrity/assessments/preview",
                                                            {"ticker": "2303", "persist": False}))
        self.assertNotIn("X-ingestion-token", headers)

    def test_flask_validation_and_error_propagation(self) -> None:
        before = len(self.seen)
        self.assertEqual(self.web.post("/api/integrity/assessments/preview", json={"ticker": "2303", "persist": True}).status_code, 400)
        self.assertEqual(self.web.post("/api/integrity/assessments/preview", json={"ticker": "x"}).status_code, 400)
        self.assertEqual(self.web.post("/api/integrity/assessments/preview", json={"ticker": "2303", "sections": ["x"]}).status_code, 400)
        self.assertEqual(self.web.post("/api/integrity/assessments/preview", json={"ticker": "2303", "review_mode": "AS_OF"}).status_code, 400)
        self.assertIn(self.web.get("/api/integrity/companies/../readiness").status_code, (400, 404))
        self.assertEqual(len(self.seen), before)
        for body, status, code in (({"ticker": "1785"}, 404, "ticker_not_supported"),
                                   ({"ticker": "2303", "review_mode": "STRICT_AS_OF"}, 409, "review_mode_not_supported")):
            response = self.web.post("/api/integrity/assessments/preview", json=body)
            self.assertEqual((response.status_code, response.get_json()["detail"]["error_code"]), (status, code))
        self.repo.fail = True
        self.assertEqual(self.web.post("/api/integrity/assessments/preview", json={"ticker": "2303"}).status_code, 503)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_page_renders_escaped_text_and_official_links_only(self) -> None:
        companies = self.web.get("/api/integrity/companies").get_json()["data"]
        preview = self.web.post("/api/integrity/assessments/preview", json={"ticker": "2303"}).get_json()["data"]
        out = render({"companies": companies, "preview": preview, "ticker": "2303"})
        self.assertNotIn("img", out["tags"])
        self.assertNotIn("script", out["tags"])
        self.assertIn(XSS, out["cross"])  # shown literally as text
        self.assertIn(XSS, out["overview"])
        for link in out["links"]:
            self.assertRegex(link, r"^https://(mopsov\.twse\.com\.tw|doi\.org)/")
        self.assertIn("需要補件確認", out["summary"])
        self.assertIn("同一發行人自報", out["cross"])
        self.assertIn("未校準", out["cross"])
        self.assertIn("無（不可計算）", out["models"])
        self.assertIn("不估計停供或供應鏈中斷機率", out["b2b"])
        not_computable = [b for b in out["badges"] if "不可計算" in b["text"]]
        self.assertTrue(not_computable and all(" ok" not in b["className"] for b in not_computable))
        self.assertEqual(out["requests"][1]["body"], {"ticker": "2303", "review_mode": "CURRENT_REVIEW",
                                                      "sections": ["financial_checks", "literature", "jsd", "claims"]})

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_page_error_and_empty_states(self) -> None:
        companies = self.web.get("/api/integrity/companies").get_json()["data"]
        error = render({"companies": companies, "preview_status": 503, "ticker": "2303",
                        "error_detail": {"error_code": "integrity_data_unavailable", "message": "fact repository unavailable"}})
        self.assertIn("資料來源暫時無法讀取", error["summary"])
        self.assertEqual(error["summaryClass"], "state error")
        empty_repo = FakeRepository([])
        empty = workbench(repository=empty_repo).assess.__self__
        fastapi_app.dependency_overrides[get_integrity_workbench] = lambda: empty
        preview = self.web.post("/api/integrity/assessments/preview", json={"ticker": "3711"}).get_json()["data"]
        out = render({"companies": companies, "preview": preview, "ticker": "3711"})
        self.assertIn("尚無已歸檔的年度財報事實", out["overview"])
        self.assertIn("資料不足", out["summary"])


def render(payload: dict) -> dict:
    result = subprocess.run(["node", str(REPO / "tests" / "integrity_page_harness.js")], input=json.dumps(payload),
                            capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    return json.loads(result.stdout)


if __name__ == "__main__":
    unittest.main()
