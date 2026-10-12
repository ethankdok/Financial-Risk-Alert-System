"""Integrity Workbench Phase 1: adapters and composer (claims, JSD, literature readiness, evidence families). SYNTHETIC."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from app.services.integrity import composer as cp
from app.services.integrity.adapters import ClaimsAdapter, JsdAdapter, LiteratureAdapter, verify_shift_compatibility
from app.services.integrity.contracts import AssessmentRequest
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
LITERATURE_DB = BACKEND / "data" / "literature_models" / "literature_inputs.sqlite3"
RESULTS_DB = BACKEND / "data" / "historical_audit" / "research_results.sqlite3"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ClaimsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.entry = statement()
        self.registry = registry_file(Path(self.tmp.name), [self.entry])
        rows = annual_rows("2303", {"revenue": {2024: 1000000000.0}})
        self.index = workbench(rows).facts.collect("2303")["index"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def check(self, service, archive=None):
        adapter = ClaimsAdapter(archive or archive_for(self.entry), service, self.registry)
        return adapter.assess("2303", self.index)["checks"][0]

    def test_supported_is_same_issuer_not_independent(self) -> None:
        result = self.check(FakeClaimService("supported"))
        self.assertEqual(result["verdict"], "supported")
        self.assertTrue(result["source_verification"]["verified"])
        self.assertFalse(result["corroboration"]["independent_corroboration"])
        self.assertEqual(result["corroboration"]["type"], "same_issuer_self_reported")
        self.assertEqual(result["precision_check"]["result"], "within_printed_precision")
        self.assertIsNone(result["evidence"][0]["source_reference"])  # javascript: link withheld

    def test_conflicting_and_insufficient_pass_through(self) -> None:
        self.assertEqual(self.check(FakeClaimService("conflicting", reason="value_mismatch"))["verdict"], "conflicting")
        insufficient = self.check(FakeClaimService("insufficient_evidence", reason="no_official_evidence"))
        self.assertEqual((insufficient["verdict"], insufficient["reason_code"]), ("insufficient_evidence", "no_official_evidence"))

    def test_period_or_value_parse_mismatch_is_inconclusive(self) -> None:
        period = self.check(FakeClaimService("supported", period="2023FY"))
        self.assertEqual((period["verdict"], period["reason_code"]), ("inconclusive", "claim_parse_mismatch:period"))
        value = self.check(FakeClaimService("supported", value_text="1"))  # the comma-split parser defect pattern
        self.assertEqual(value["reason_code"], "claim_parse_mismatch:value")

    def test_verifier_tolerance_is_not_enough_without_printed_precision(self) -> None:
        index = workbench(annual_rows("2303", {"revenue": {2024: 1015000000.0}})).facts.collect("2303")["index"]
        adapter = ClaimsAdapter(archive_for(self.entry), FakeClaimService("supported"), self.registry)
        result = adapter.assess("2303", index)["checks"][0]
        self.assertEqual((result["verdict"], result["reason_code"]),
                         ("inconclusive", "verifier_supported_but_outside_printed_precision"))

    def test_tampered_source_or_changed_document_is_never_verified(self) -> None:
        service = FakeClaimService("supported")
        cases = {"excerpt_found": archive_for(self.entry, page_text="(In NT$ millions)\nNet Sales 9,999 900"),
                 "sha256_matches_pin": archive_for(self.entry, sha="e" * 64),
                 "context_found": archive_for(self.entry, page_text="Net Sales 1,000 900 11.1%")}
        for failed, archive in cases.items():
            with self.subTest(failed=failed):
                result = self.check(service, archive)
                self.assertEqual(result["verdict"], "insufficient_evidence")
                self.assertIn(failed, result["reason_code"])
        missing = ClaimsAdapter(archive_for(statement(document="other.pdf")), service, self.registry)
        self.assertEqual(missing.assess("2303", self.index)["checks"][0]["reason_code"], "document_not_in_archive")
        self.assertEqual(service.received, [])  # the verifier is never asked about an unverified statement

    def test_no_archive_no_verifier_no_statement(self) -> None:
        self.assertEqual(ClaimsAdapter(None, FakeClaimService(), self.registry).assess("2303", {})["checks"][0]["reason_code"],
                         "official_conference_archive_not_configured")
        self.assertEqual(ClaimsAdapter(archive_for(self.entry), None, self.registry).assess("2303", {})["checks"][0]["reason_code"],
                         "claim_verifier_not_available")
        empty = ClaimsAdapter(archive_for(self.entry), FakeClaimService(), self.registry).assess("2454", {})
        self.assertEqual((empty["status"], empty["reason"]), ("unavailable", "no_registered_issuer_statement_for_ticker"))

    def test_real_registry_quotes_are_verbatim_and_pinned(self) -> None:
        from app.services.integrity.adapters import load_registry

        for entry in load_registry()["statements"]:
            self.assertEqual(len(entry["document_sha256"]), 64)
            self.assertNotIn(",", entry["normalized_claim"])
            self.assertTrue(entry["excerpt"].strip())


class RealVerifierClaimTests(unittest.TestCase):
    """The existing ClaimVerificationService over SYNTHETIC facts: forecast, period mismatch and the unit fix."""

    def service(self, rows):
        from app.services.claim_evidence_adapter import ClaimEvidenceAdapter
        from app.services.claim_verification_service import ClaimVerificationService
        from app.services.pipeline_evidence_repository import PipelineEvidenceRepository

        repo = FakeRepository(rows)
        return ClaimVerificationService(ClaimEvidenceAdapter(fact_repository=PipelineEvidenceRepository(repo),
                                                             conference_repository=None, event_repository=repo), llm=None)

    def verify(self, rows, text):
        from app.claim_verification_models import ClaimVerifyRequest

        return self.service(rows).verify(ClaimVerifyRequest(company_code="2330", claim=text)).verdict

    def test_twd_unit_facts_are_comparable_after_the_scale_fix(self) -> None:
        rows = annual_rows("2330", {"revenue": {2024: 2894307699000.0}})
        self.assertEqual(self.verify(rows, "台積電2024年營收28943.1億元"), "supported")
        self.assertEqual(self.verify(rows, "台積電2024年營收35000億元"), "conflicting")

    def test_period_mismatch_and_forecast_are_not_supported(self) -> None:
        rows = annual_rows("2330", {"revenue": {2024: 2894307699000.0}})
        self.assertEqual(self.verify(rows, "台積電2023年營收28943.1億元"), "insufficient_evidence")
        self.assertNotEqual(self.verify(rows, "台積電預計2026年營收將達40000億元"), "supported")


class JsdTests(unittest.TestCase):
    def assess(self, result=None, **kwargs):
        return JsdAdapter(FakeBridge(result if result is not None else shift_result(), **kwargs)).assess("2303")

    def test_uncalibrated_returns_raw_metrics_without_level(self) -> None:
        out = self.assess()
        self.assertEqual((out["status"], out["calibration_status"], out["drift_level"]), ("comparable", "uncalibrated", None))
        self.assertEqual(out["metrics"], {"jsd": "0.123456", "cosine_similarity": "0.876543"})
        self.assertIsNone(out["source_documents"][1]["source_url"])  # non-official host withheld

    def test_incompatible_pairs_never_report_metrics_or_levels(self) -> None:
        base = shift_result()
        other_type = shift_result(source_documents=[base["source_documents"][0],
                                                    {**base["source_documents"][1], "document_type": "financial_results_release"}])
        other_lang = shift_result(source_documents=[base["source_documents"][0], {**base["source_documents"][1], "language": "zh-Hant"}])
        cases = {"same_document_type": other_type, "same_language": other_lang,
                 "adjacent_quarters": shift_result(period_2="2025Q4",
                                                   source_documents=[base["source_documents"][0],
                                                                     {**base["source_documents"][1], "period": "2025Q4"}]),
                 "same_ticker": shift_result(ticker="2330")}
        for failed, result in cases.items():
            with self.subTest(failed=failed):
                result["calibration"] = {"status": "calibrated", "scope": {"ticker": "2303", "document_type": "earnings_presentation",
                                                                          "language": "en"}}
                result["drift_result"] = "雙指標顯著文字漂移（需人工確認）"
                out = self.assess(result)
                self.assertEqual(out["status"], "not_comparable")
                self.assertIn(failed, out["reason"])
                self.assertIsNone(out["metrics"])
                self.assertIsNone(out["drift_level"])

    def test_calibration_profile_mismatch_drops_the_level(self) -> None:
        result = shift_result(calibration={"status": "calibrated", "scope": {"ticker": "2303", "document_type": "full_earnings_transcript",
                                                                            "language": "en"}},
                              drift_result="雙指標顯著文字漂移（需人工確認）")
        out = self.assess(result)
        self.assertEqual((out["calibration_status"], out["drift_level"]), ("uncalibrated", None))
        matching = shift_result(calibration={"status": "calibrated", "scope": {"ticker": "2303", "document_type": "earnings_presentation",
                                                                              "language": "en"}},
                                drift_result="雙指標顯著文字漂移（需人工確認）")
        self.assertEqual(self.assess(matching)["drift_level"], "雙指標顯著文字漂移（需人工確認）")

    def test_unavailable_paths(self) -> None:
        self.assertEqual(JsdAdapter(None).assess("2303")["reason"], "official_conference_archive_not_configured")
        self.assertEqual(self.assess(configured=False)["status"], "unavailable")
        self.assertEqual(self.assess(error=True)["reason"], "jsd_bridge_error:RuntimeError")
        insufficient = self.assess({"analysis_status": "insufficient_data", "reason_code": "periods_not_adjacent",
                                    "available_documents": [], "limitations": []})
        self.assertEqual((insufficient["status"], insufficient["reason"], insufficient["metrics"]),
                         ("unavailable", "periods_not_adjacent", None))
        quality = self.assess(shift_result(analysis_status="quality_insufficient", metrics=None))
        self.assertEqual((quality["status"], quality["metrics"]), ("quality_insufficient", None))
        self.assertTrue(all(verify_shift_compatibility("2303", shift_result()).values()))


class LiteratureTests(unittest.TestCase):
    def test_missing_inputs_give_null_score_from_the_unchanged_engines(self) -> None:
        index = workbench().facts.collect("2303")["index"]
        out = LiteratureAdapter(None).assess("2303", 2025, index)
        self.assertEqual(out["reason"], "literature_input_store_not_available")
        for model in out["models"]:
            self.assertEqual((model["status"], model["raw_score"], model["availability"]), ("not_computable", None, "not_computable"))
            self.assertEqual(model["approval_status"], "DRAFT_PENDING_METHOD_OWNER_REVIEW")
            self.assertFalse(any(a["admitted_as_model_input"] for a in model["pipeline_fact_availability"]))
        beneish = out["models"][0]
        receivables = next(a for a in beneish["pipeline_fact_availability"] if a["model_input"] == "receivables")
        self.assertTrue(receivables["pipeline_fact_t"])  # available in the pipeline, still not admitted

    @unittest.skipUnless(LITERATURE_DB.is_file(), "local literature input store not present")
    def test_1785_retrospective_scores_are_never_substituted_and_stores_are_untouched(self) -> None:
        before = (sha(LITERATURE_DB), sha(RESULTS_DB) if RESULTS_DB.is_file() else None)
        adapter = LiteratureAdapter(str(LITERATURE_DB))
        production = adapter.assess("2330", 2024, {})
        self.assertEqual(production["frozen_observation_count"], 0)
        self.assertEqual(production["reason"], "no_frozen_literature_inputs_for_ticker")
        research_case = adapter.assess("1785", 2012, {})
        self.assertGreater(research_case["frozen_observation_count"], 0)
        self.assertTrue(research_case["reason"].startswith("frozen_inputs_exist_only_as_historical_research_case"))
        for model in production["models"] + research_case["models"]:
            self.assertIsNone(model["raw_score"])
        self.assertEqual(before, (sha(LITERATURE_DB), sha(RESULTS_DB) if RESULTS_DB.is_file() else None))


class ComposerTests(unittest.TestCase):
    def test_same_evidence_family_counts_once_across_finding_and_model_component(self) -> None:
        f1 = {"finding_id": "F1:2025FY", "check_id": "F1_REVENUE_RECEIVABLES_ALIGNMENT", "status": "descriptive_divergence",
              "review_queue": "requires_verification", "evidence_families": ["revenue", "receivables"],
              "evidence_ids": ["fact:a", "fact:b"], "not_independent_of": ["beneish_1999_full8_v1:DSRI"]}
        claim = {"finding_id": "F3:x", "check_id": "F3_ISSUER_CLAIM_VERIFICATION", "status": "conflicting",
                 "review_queue": "requires_verification", "evidence_families": ["revenue", "issuer_presentation"],
                 "evidence_ids": ["claim:x"], "not_independent_of": []}
        records = {"fact:a": {"independence": "regulator_published_issuer_data"},
                   "claim:x": {"independence": "issuer_self_reported"}}
        models = [{"model_id": "beneish_1999_full8_v1", "status": "computed"}]
        priority = cp.investigation_priority([f1, claim], records, models)
        self.assertEqual(priority["queue"], "requires_verification")
        self.assertEqual(priority["distinct_evidence_families"], ["issuer_presentation", "receivables", "revenue"])
        self.assertEqual(priority["distinct_evidence_family_count"], 3)
        self.assertEqual(priority["evidence_family_citations"]["receivables"], ["F1:2025FY", "beneish_1999_full8_v1:DSRI"])
        self.assertEqual(priority["independent_third_party_corroboration_count"], 0)
        self.assertIsNone(priority["fraud_probability"])

    def test_queue_rule_levels(self) -> None:
        computed = {"finding_id": "F2:1", "check_id": "F2_NET_INCOME_CFO_ALIGNMENT", "status": "descriptive_gap",
                    "review_queue": None, "evidence_families": [], "evidence_ids": [], "not_independent_of": []}
        self.assertEqual(cp.investigation_priority([computed], {}, [])["queue"], "no_item_triggered")
        self.assertEqual(cp.investigation_priority([{**computed, "review_queue": "monitor"}], {}, [])["queue"], "monitor")
        self.assertEqual(cp.investigation_priority([{**computed, "status": "unavailable"}], {}, [])["queue"],
                         "insufficient_evidence")


class WorkbenchAssembleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.entry = statement()
        self.registry = registry_file(Path(self.tmp.name), [self.entry])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_preview_is_read_only_and_never_marks_independence(self) -> None:
        repo = FakeRepository(annual_rows("2303", BASE_DATA))
        wb = workbench(repository=repo, bridge=FakeBridge(shift_result()), archive=archive_for(self.entry),
                       claim_service=FakeClaimService("supported", value_text="1000", period="2024FY"),
                       registry=self.registry)
        repo.rows += annual_rows("2303", {"revenue": {2024: 1000000000.0}}, retrieved_at="2026-01-01T00:00:00+00:00")
        repo.rows = [r for r in repo.rows if not (r["metric_code"] == "revenue" and r["period"] == "2024FY"
                                                  and r["value"] == 1000.0)]
        out = wb.assess(AssessmentRequest(ticker="2303"))
        self.assertTrue(set(repo.calls) <= {"list_facts", "get_latest_snapshot", "list_investor_conferences",
                                            "list_material_events", "get_official_event_sync_status"}, repo.calls)
        self.assertFalse(out["persist"])
        self.assertFalse(out["point_in_time_supported"])
        self.assertEqual(out["method_approval"], "DRAFT_PENDING_METHOD_OWNER_REVIEW")
        self.assertNotIn("independent_third_party", {r["independence"] for r in out["evidence_records"]})
        claim_record = next(r for r in out["evidence_records"] if r["evidence_id"].startswith("claim:"))
        self.assertEqual((claim_record["independence"], claim_record["source_sha256"]), ("issuer_self_reported", "d" * 64))
        self.assertEqual(out["source_coverage"]["independent_third_party_sources"], 0)
        self.assertTrue(any(n["check_id"] == "B2B_NO_NETWORK_INFERENCE" for n in out["next_checks"]))
        self.assertTrue(all(n["is_risk_conclusion"] is False for n in out["next_checks"]))

        def keys(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    yield k
                    yield from keys(v)
            elif isinstance(value, list):
                for v in value:
                    yield from keys(v)
        self.assertFalse({k for k in keys(out) if "probab" in k.lower() or k.lower() in ("fraud", "risk_score")} - {"fraud_probability"})
        self.assertIsNone(out["investigation_priority"]["fraud_probability"])


if __name__ == "__main__":
    unittest.main()
