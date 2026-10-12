"""Integrity Workbench Phase 1, REAL tier: genuine local MOPS facts and archived conference PDFs (read-only).

The pipeline database is copied to a temporary file first (the existing SQLite repository commits its schema
script on open), so the approved file cannot change; its SHA-256 is asserted before and after. Skips when the
local data are not present (e.g. a fresh checkout).
"""

from __future__ import annotations

import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PIPELINE_DB = BACKEND / "data" / "financial_pipeline.sqlite3"
ARCHIVE = BACKEND / "data" / "official-ir-pdfs-live-test"
LITERATURE_DB = BACKEND / "data" / "literature_models" / "literature_inputs.sqlite3"
HAS_REAL = PIPELINE_DB.is_file() and (ARCHIVE / "2454" / "2025" / "manifest.json").is_file()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(HAS_REAL, "local pipeline database / conference archive not present")
class RealIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from app.services.analysis_repository import SqliteAnalysisRepository
        from app.services.claim_evidence_adapter import ClaimEvidenceAdapter
        from app.services.claim_verification_service import ClaimVerificationService
        from app.services.integrity.contracts import AssessmentRequest
        from app.services.integrity.service import IntegrityWorkbench
        from app.services.jsd_bridge_service import JsdBridgeService
        from app.services.jsd_calibration import build_jsd_calibration_repository
        from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
        from app.services.pipeline_evidence_repository import PipelineEvidenceRepository

        cls.originals = {p: sha(p) for p in (PIPELINE_DB, LITERATURE_DB) if p.is_file()}
        cls.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        copy = Path(cls.tmp.name) / "pipeline_copy.sqlite3"
        shutil.copyfile(PIPELINE_DB, copy)
        repo = SqliteAnalysisRepository(str(copy))
        archive = FileConferencePdfArchiveRepository(ARCHIVE)
        claims = ClaimVerificationService(ClaimEvidenceAdapter(fact_repository=PipelineEvidenceRepository(repo),
                                                               conference_repository=archive, event_repository=repo), llm=None)
        cls.workbench = IntegrityWorkbench(repo, jsd_bridge=JsdBridgeService(archive, build_jsd_calibration_repository()),
                                           conference_repository=archive, claim_service=claims,
                                           literature_database=str(LITERATURE_DB))
        cls.results = {t: cls.workbench.assess(AssessmentRequest(ticker=t)) for t in ("2454", "2330")}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def finding(self, ticker: str, check_id: str) -> dict:
        return next(f for f in self.results[ticker]["financial_findings"] if f["check_id"] == check_id)

    def test_2454_f1_real_divergence_is_a_document_request_not_a_fraud_label(self) -> None:
        f1 = self.finding("2454", "F1_REVENUE_RECEIVABLES_ALIGNMENT")
        self.assertEqual((f1["status"], f1["period"], f1["review_queue"]), ("descriptive_divergence", "2025FY", "requires_verification"))
        self.assertEqual((f1["computed"]["sales_growth"], f1["computed"]["ar_growth"], f1["computed"]["gap_percentage_points"]),
                         ("0.123222", "0.412138", "28.89"))
        self.assertEqual(f1["inputs"]["receivables_t"]["value_twd"], "62056117000")
        self.assertEqual(f1["inputs"]["receivables_t"]["scope"], "consolidated")
        self.assertEqual(self.results["2454"]["investigation_priority"]["queue"], "requires_verification")
        self.assertIsNone(self.results["2454"]["investigation_priority"]["fraud_probability"])

    def test_2330_f1_within_heuristic_and_f2_both_companies(self) -> None:
        f1 = self.finding("2330", "F1_REVENUE_RECEIVABLES_ALIGNMENT")
        self.assertEqual((f1["status"], f1["period"], f1["computed"]["gap_percentage_points"]), ("within_screening_heuristic", "2024FY", "0.57"))
        for ticker, period, gap in (("2330", "2024FY", "-653745309000"), ("2454", "2025FY", "-56675297000")):
            f2 = self.finding(ticker, "F2_NET_INCOME_CFO_ALIGNMENT")
            self.assertEqual((f2["status"], f2["period"], f2["computed"]["net_income_minus_cfo_twd"]), ("descriptive_gap", period, gap))
            self.assertIsNone(f2["review_queue"])

    def test_issuer_claims_are_supported_from_verified_sources_but_not_independent(self) -> None:
        for ticker, count in (("2454", 2), ("2330", 2)):
            checks = self.results[ticker]["claim_checks"]
            self.assertEqual(len(checks), count)
            for check in checks:
                self.assertTrue(check["source_verification"]["verified"], check["source_verification"])
                self.assertEqual(check["verdict"], "supported")
                self.assertEqual(check["precision_check"]["result"], "within_printed_precision")
                self.assertFalse(check["corroboration"]["independent_corroboration"])

    def test_literature_models_not_computable_and_jsd_uncalibrated(self) -> None:
        for ticker in ("2454", "2330"):
            result = self.results[ticker]
            self.assertTrue(all(m["raw_score"] is None and m["status"] == "not_computable" for m in result["paper_models"]))
            shift = result["data_shift"]
            self.assertEqual((shift["status"], shift["calibration_status"], shift["drift_level"]), ("comparable", "uncalibrated", None))
            self.assertTrue(all(shift["compatibility_checks"].values()))
            self.assertEqual(result["source_coverage"]["independent_third_party_sources"], 0)
            self.assertFalse(result["point_in_time_supported"])

    def test_originals_are_byte_identical(self) -> None:
        self.assertEqual(self.originals, {p: sha(p) for p in self.originals})


if __name__ == "__main__":
    unittest.main()
