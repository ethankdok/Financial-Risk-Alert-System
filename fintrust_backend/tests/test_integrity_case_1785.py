"""Phase 1.1 Gate B: read-only 1785 retrospective case view (RETROSPECTIVE_CASE).

SYNTHETIC tier: a fake research service drives the contract, the negative paths (unsupported ticker, unavailable
data, archive tampering, excluded records, XSS) and the API → Flask → page chain. REAL tier: the accepted 1785
research archive — counts, run ids, withdrawn cells, strict pre-event status and evidence-verified events.
"""

from __future__ import annotations

import hashlib
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
from app.routers.integrity import get_integrity_workbench
from app.services.integrity import case_study as cs
from tests.integrity_fixtures import workbench as synthetic_workbench

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(REPO) not in sys.path:
    sys.path.append(str(REPO))  # appended: the FastAPI ``app`` package keeps precedence over the root Flask app.py

from flask import Flask  # noqa: E402

import integrity_routes  # noqa: E402
from fintrust_client import FinTrustClient  # noqa: E402

XSS = '<img src=x onerror="alert(1)">'
BASE = "http://fastapi.internal"
DATA = BACKEND / "data"
HISTORICAL_DB = DATA / "historical_audit" / "historical_audit.sqlite3"
LITERATURE_DB = DATA / "literature_models" / "literature_inputs.sqlite3"
RESULTS_DB = DATA / "historical_audit" / "research_results.sqlite3"
HAS_REAL = HISTORICAL_DB.is_file() and LITERATURE_DB.is_file()


def _row(model, year, status, score=None):
    obs = {"observation_id": f"lobs1_{year}", "line_key": "code:1140", "source_concept": XSS, "value": "1",
           "published_value": "1,708,039", "published_unit": "TWD_thousand", "raw_sha256": "a" * 64,
           "locator": "pdf_page=5;column=current;line=1140", "extraction_method": "pdf_text_account_code",
           "source_url": "https://doc.twse.com.tw/server-java/t57sb01?step=9&kind=A&co_id=1785&filename=x.pdf"}
    inputs = [{"metric": m, "relative_period": r, "fiscal_year": year, "status": "computed", "source_observations": [obs]}
              for m, r in (("cogs", "t"), ("inventory", "t"), ("inventory", "t-1"))]
    comps = ([{"variable": v, "status": "computed", "value": "0.1", "reasons": [], "inputs": inputs}
              for v in ("GMI", "TATA")] if model.startswith("beneish") else
             [{"variable": v, "status": "computed", "value": "-0.2", "reasons": [], "inputs": inputs}
              for v in ("ch_inv", "rsst_acc", "soft_assets")])
    if status != "computed":
        comps = []
    return {"model_id": model, "fiscal_year": year, "status": status, "score": score, "score_exact": score,
            "components": comps, "missing_inputs": [] if status == "computed" else [{"status": status, "metric": "x"}],
            "reasons": [] if status == "computed" else [status],
            "input_filing_versions": [{"filing_version_id": f"hfv1_{year}", "fiscal_year": year, "source_url": "javascript:x"}],
            "observation": {"filing_version_id": f"hfv1_{year}"}, "source_observation_ids": [f"lobs1_{year}"],
            "zero_evidence_used": ["f" * 64] if score == "0.892005" else []}


def _run(policy, *, computed_years=(2013,), score="1.0"):
    results = {m: [_row(m, y, "computed" if y in computed_years else "source_unavailable", score if y in computed_years else None)
                   for y in range(2011, 2026)] for m in cs.MODELS}
    return {"run_id": f"rrun1_{policy[:4]}", "input_digest": "b" * 64, "output_digest": "c" * 64,
            "method_version": "synthetic", "output": {"models": {"results": results, "counts": {}, "status": "computed",
                                                                 "usage_policy": "SYNTHETIC"}}}


class FakeResearch:
    """SYNTHETIC research service with the read interface the case view uses."""

    def __init__(self, *, available=True, fail=False, timeline_keys=None):
        self.available, self.fail = available, fail
        self.calls = []
        keys = timeline_keys if timeline_keys is not None else {
            "mops:20160819:171005:1": "E2_verified_notice_quote", "mops:20160331:184945:4": "E1_official_listing_metadata",
            "trading_suspension_from_20160517": "E2_verified_notice_quote",
            "tpex:證櫃監字第10502013431號": "E2_verified_official_document"}
        self.timeline_rows = [{"event_key": k, "evidence_tier": t, "title": XSS if "0819" in k else f"title {k}",
                               "publication_at": "2016-01-01", "available_from": "2016-01-01", "content_hash": "d" * 64,
                               "source_url": "javascript:alert(1)" if "0331" in k else "https://www.tpex.org.tw/x.htm"}
                              for k, t in keys.items()]

    def health(self):
        self.calls.append("health")
        return {"dataset_available": self.available, "literature_inputs_available": self.available,
                "research_layer_version": "synthetic", "approved_baseline_commit": "synthetic"}

    def build_run(self, kind, ticker, context, **kwargs):
        self.calls.append(("build_run", context.mode.value, kwargs.get("version_policy")))
        if self.fail:
            raise RuntimeError("synthetic failure")
        if context.mode.value == "STRICT_AS_OF":
            return {"run_id": "rrun1_strict", "output": {"models": {"status": "insufficient_point_in_time_evidence",
                                                                   "counts": {}, "strict_note": "none admitted"}}}
        return _run(kwargs["version_policy"])

    def timeline(self, ticker, context, **kwargs):
        self.calls.append("timeline")
        return {"events": self.timeline_rows}

    def case_overview(self, ticker):
        self.calls.append("case_overview")
        return {"company_name": "SYNTHETIC 光洋科", "case_id": "synthetic", "coverage": {"restatement_comparisons": 3}}


class CaseSyntheticTests(unittest.TestCase):
    def test_mode_banner_separation_and_persistence(self) -> None:
        out = cs.RetrospectiveCaseService(FakeResearch()).summary("1785", "original_only")
        self.assertEqual((out["status"], out["review_mode"], out["hindsight"], out["point_in_time_supported"], out["persist"]),
                         ("available", "RETROSPECTIVE_CASE", True, False, False))
        self.assertEqual(out["banner"], "事後研究／包含後續申報版本，不代表事件曝光前可用資訊")
        self.assertIn("CURRENT_REVIEW", out["separation"])
        self.assertEqual(out["method_approval"], "DRAFT_PENDING_METHOD_OWNER_REVIEW")
        self.assertFalse(out["dataset_identity"]["persisted"])
        self.assertFalse(out["baseline_check"]["matches"])  # synthetic data never claims the accepted baseline
        self.assertEqual(out["strict_pre_event"]["status"], "insufficient_point_in_time_evidence")

    def test_unsupported_ticker_and_policy_are_refused_without_substitution(self) -> None:
        service = cs.RetrospectiveCaseService(FakeResearch())
        for ticker in ("2454", "2330", "9999"):
            with self.assertRaises(cs.UnsupportedResearchCase):
                service.summary(ticker, "latest_available")
        with self.assertRaises(ValueError):
            service.summary("1785", "earliest_available")
        self.assertEqual(service.research.calls, [])  # nothing computed for a refused request

    def test_unavailable_dataset_or_failure_returns_typed_state_without_scores(self) -> None:
        for research, reason in ((FakeResearch(available=False), "historical_dataset_or_literature_inputs_unavailable"),
                                 (FakeResearch(fail=True), "research_computation_error:RuntimeError")):
            out = cs.RetrospectiveCaseService(research).summary("1785", "latest_available")
            self.assertEqual((out["status"], out["reason"], out["cells"], out["events"]), ("source_unavailable", reason, [], []))
            self.assertIn("不會改用其他公司", out["instructions"])

    def test_event_verification_tiers_and_tampered_archive(self) -> None:
        out = cs.RetrospectiveCaseService(FakeResearch()).summary("1785", "latest_available")
        events = {e["event_id"]: e for e in out["events"]}
        self.assertEqual(events["restated_period_fy2011_fy2015"]["verification_status"], "verified_official_document")
        self.assertEqual(events["press_conference_20160331"]["verification_status"], "official_listing_only")
        self.assertEqual(events["gold_transfer_2015q4"]["verification_status"], "needs_source_verification")
        self.assertEqual(events["gold_transfer_2015q4"]["event_class"], "physical_asset_incident")
        self.assertEqual(events["restatement_impact_20161229"]["event_class"], "restatement")
        self.assertEqual(events["trading_resumption_20170103"]["verification_status"], "needs_source_verification")
        self.assertIn("trading_resumption_20170103", events["trading_resumption_20170103"]["expected_records_missing_from_archive"])
        self.assertTrue(all(e["used_in_model_calculation"] is False for e in out["events"]))
        self.assertIsNone(events["press_conference_20160331"]["verifying_records"][0]["source_url"])  # javascript: withheld
        all_keys = [r["event_key"] for e in out["events"] for r in e["verifying_records"] + e["related_records"]]
        self.assertNotIn("tpex:證櫃監字第10502013431號", all_keys)  # another company's notice is never 1785 evidence

    def test_crosswalk_and_inventory_turnover_readiness(self) -> None:
        out = cs.RetrospectiveCaseService(FakeResearch()).summary("1785", "latest_available")
        rows = {r["feature"]: r for r in out["crosswalk"]}
        self.assertEqual(set(rows), {"GMI", "TATA", "ΔInventory", "RSST Accruals", "Soft Assets", "存貨週轉率", "CFO − NI"})
        self.assertEqual(rows["存貨週轉率"]["implementation"], "readiness_only")
        self.assertEqual(rows["CFO − NI"]["implementation"], "not_available_in_frozen_inputs")
        self.assertTrue(any("NI − CFO" in x for x in rows["CFO − NI"]["limitations"]))
        turnover = {t["fiscal_year"]: t for t in out["inventory_turnover_readiness"]}
        self.assertEqual(turnover[2013]["status"], "inputs_available_same_filing")
        self.assertIsNone(turnover[2013]["value"])
        self.assertEqual(turnover[2014]["status"], "not_ready")
        self.assertEqual([s["fiscal_year"] for s in out["series"]["ch_inv"] if s["value"] is not None], [2013])

    def test_no_fraud_probability_or_risk_score_fields(self) -> None:
        out = cs.RetrospectiveCaseService(FakeResearch()).summary("1785", "latest_available")
        text = json.dumps(out, ensure_ascii=False).lower()
        self.assertNotIn("fraud_probability", text)
        self.assertNotIn("risk_score", text)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def render(payload: dict) -> dict:
    result = subprocess.run(["node", str(REPO / "tests" / "integrity_case_page_harness.js")], input=json.dumps(payload),
                            capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
    return json.loads(result.stdout)


class CaseApiChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.research = FakeResearch()
        fastapi_app.dependency_overrides[get_research_service] = lambda: self.research
        # Every route reached here must be isolated: the default analysis repository commits its schema on open
        # and would rewrite the approved pipeline database (Phase 1.1 incident).
        synthetic = synthetic_workbench()
        fastapi_app.dependency_overrides[get_integrity_workbench] = lambda: synthetic
        self.api = TestClient(fastapi_app)
        self.seen = []

        def opener(request, timeout):
            path = request.full_url[len(BASE):]
            self.seen.append(path)
            response = self.api.request(request.get_method(), path, headers=dict(request.header_items()))
            if response.status_code >= 400:
                raise HTTPError(request.full_url, response.status_code, "error", {}, io.BytesIO(response.content))
            return _Response(response.content)

        flask_app = Flask(__name__)
        flask_app.register_blueprint(integrity_routes.create_integrity_blueprint(client=FinTrustClient(base_url=BASE, opener=opener)))
        self.web = flask_app.test_client()

    def tearDown(self) -> None:
        self.api.close()
        fastapi_app.dependency_overrides.clear()

    def test_api_contract_and_errors(self) -> None:
        ok = self.api.get("/api/v1/integrity/research-cases/1785/summary?version_policy=latest_available")
        self.assertEqual((ok.status_code, ok.json()["review_mode"]), (200, "RETROSPECTIVE_CASE"))
        self.assertEqual(self.api.get("/api/v1/integrity/research-cases/1785/summary").status_code, 422)
        self.assertEqual(self.api.get("/api/v1/integrity/research-cases/1785/summary?version_policy=strict").status_code, 422)
        other = self.api.get("/api/v1/integrity/research-cases/2454/summary?version_policy=latest_available")
        self.assertEqual((other.status_code, other.json()["detail"]["error_code"]), (404, "research_case_not_supported"))
        current = self.api.post("/api/v1/integrity/assessments/preview", json={"ticker": "1785"})
        self.assertEqual(current.status_code, 404)  # CURRENT_REVIEW never serves the research case
        paths = fastapi_app.openapi()["paths"]
        self.assertEqual(set(paths["/api/v1/integrity/research-cases/{ticker}/summary"]), {"get"})

    def test_flask_whitelist_and_pass_through(self) -> None:
        before = len(self.seen)
        for url in ("/api/integrity/research-cases/1785/summary", "/api/integrity/research-cases/1785/summary?version_policy=x",
                    "/api/integrity/research-cases/17X5/summary?version_policy=latest_available"):
            self.assertEqual(self.web.get(url).status_code, 400)
        self.assertEqual(len(self.seen), before)
        response = self.web.get("/api/integrity/research-cases/1785/summary?version_policy=original_only&persist=true&extra=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seen[-1], "/api/v1/integrity/research-cases/1785/summary?version_policy=original_only")
        missing = self.web.get("/api/integrity/research-cases/2454/summary?version_policy=latest_available")
        self.assertEqual((missing.status_code, missing.get_json()["detail"]["error_code"]), (404, "research_case_not_supported"))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_page_renders_escaped_case_with_official_links_only(self) -> None:
        summary = self.web.get("/api/integrity/research-cases/1785/summary?version_policy=latest_available").get_json()["data"]
        out = render({"summary": summary, "search": "?cell=dechow_2011_model1_v1:2013"})
        self.assertNotIn("img", out["tags"])
        self.assertNotIn("script", out["tags"])
        self.assertIn(XSS, out["timeline"])
        self.assertIn("事後研究／包含後續申報版本，不代表事件曝光前可用資訊", out["banner"])
        self.assertIn("待來源驗證（未進入計算）", out["timeline"])
        self.assertIn("實體資產事件（黃金不法轉出）", out["timeline"])
        self.assertIn("事件公開前（2016-05-13 截點）沒有任何可驗證的文獻模型分數", out["strict"])
        self.assertIn("FY2013", out["detail"])
        self.assertGreater(out["fills"], 0)
        for link in out["links"]:
            self.assertRegex(link, r"^https://(doc\.twse\.com\.tw|www\.tpex\.org\.tw|mopsov\.twse\.com\.tw)/")
        self.assertTrue(out["requests"][0]["url"].endswith("version_policy=latest_available"))

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_page_unavailable_and_error_states(self) -> None:
        unavailable = cs.RetrospectiveCaseService(FakeResearch(available=False)).summary("1785", "latest_available")
        out = render({"summary": unavailable})
        self.assertIn("研究資料不可用", out["identity"])
        self.assertIn("不顯示任何分數", out["grid"])
        error = render({"status": 503, "error_detail": {"message": "down"}})
        self.assertIn("研究資料暫時無法讀取", error["identity"])
        self.assertEqual(error["identityClass"], "state error")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(HAS_REAL, "approved historical audit archive / literature inputs not present")
class CaseRealTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from app.services.financial_research.service import ResearchConfig, ResearchService

        cls.before = {p: sha(p) for p in (HISTORICAL_DB, LITERATURE_DB, RESULTS_DB) if p.is_file()}
        service = cs.RetrospectiveCaseService(ResearchService(ResearchConfig.from_env()))
        cls.out = {p: service.summary("1785", p) for p in cs.VERSION_POLICIES}

    def test_accepted_baseline_reproduced_exactly(self) -> None:
        for policy, out in self.out.items():
            self.assertEqual(out["status"], "available")
            self.assertTrue(out["dataset_identity"]["matches_accepted_run"], policy)
            self.assertEqual(out["dataset_identity"]["run_id"], cs.ACCEPTED_RUNS[policy])
            self.assertTrue(out["baseline_check"]["matches"])
        self.assertEqual(self.out["latest_available"]["baseline_check"]["observed"],
                         {"computed": 26, "not_computable": 34, "cells": 60, "withdrawn_latest_available_dechow": [2015, 2023],
                          "original_only_dechow_fy2012": "0.892005"})

    def test_key_cells_and_zero_proof_dependency(self) -> None:
        cells = {(c["model_id"], c["fiscal_year"]): c for c in self.out["original_only"]["cells"]}
        fy2012 = cells[("dechow_2011_model1_v1", 2012)]
        self.assertEqual((fy2012["status"], fy2012["score"]), ("computed", "0.892005"))
        self.assertTrue(fy2012["zero_evidence_used"])
        latest = {(c["model_id"], c["fiscal_year"]): c for c in self.out["latest_available"]["cells"]}
        for year in (2015, 2023):
            cell = latest[("dechow_2011_model1_v1", year)]
            self.assertEqual(cell["status"], "not_computable")
            self.assertIn("cross_filing_overlap_mismatch", cell["missing_reasons"])
        for out in self.out.values():
            for cell in out["cells"]:
                for comp in cell["components"]:
                    for obs in comp["observations"]:
                        self.assertTrue(obs["source_url"] is None or obs["source_url"].startswith("https://"))

    def test_strict_pre_event_has_no_score(self) -> None:
        strict = self.out["latest_available"]["strict_pre_event"]
        self.assertEqual(strict["status"], "insufficient_point_in_time_evidence")
        self.assertTrue(all(v.get("computed", 0) == 0 for v in strict["counts"].values()))

    def test_events_verified_only_from_archive(self) -> None:
        events = {e["event_id"]: e["verification_status"] for e in self.out["latest_available"]["events"]}
        self.assertEqual(events, {
            "restated_period_fy2011_fy2015": "verified_official_document", "gold_transfer_2015q4": "needs_source_verification",
            "press_conference_20160331": "official_listing_only", "press_conference_20160506": "official_listing_only",
            "trading_method_change_20160510": "needs_source_verification",
            "misstatement_admission_20160513": "verified_official_document",
            "trading_suspension_20160517": "verified_official_document",
            "restatement_completed_20161205": "verified_official_document",
            "restatement_impact_20161229": "official_listing_only",
            "trading_resumption_20170103": "verified_official_document"})
        self.assertTrue(all(not e["expected_records_missing_from_archive"] for e in self.out["latest_available"]["events"]))

    def test_research_stores_untouched(self) -> None:
        self.assertEqual(self.before, {p: sha(p) for p in self.before})

    def test_payload_has_no_local_paths(self) -> None:
        text = json.dumps(self.out, ensure_ascii=False)
        for marker in ("C:\\\\", "/Users/", "historical_audit/raw", ".sqlite3"):
            self.assertNotIn(marker, text)


if __name__ == "__main__":
    unittest.main()
