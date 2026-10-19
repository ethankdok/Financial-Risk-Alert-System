"""Round2 research review gate: synthetic fixtures only, NEVER real labels."""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import round2_evidence_review as m
from research.financial_ml.phase1_case_registry import validate


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=tuple(rows[0]))
        w.writeheader()
        w.writerows(rows)


def read_csv(path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class Round2EvidenceReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name) / "financial_ml"
        self.output = self.data / "round2_case_outcome_review"
        seed = json.loads(Path(m.__file__).with_name(
            "phase1_case_sources_seed.json").read_text(encoding="utf-8"))
        self.cases = validate(seed)
        self.expected = {(c["ticker"], str(y)) for c in self.cases
                         for y in c["affected_fiscal_years"]}
        sources = {(c["ticker"], str(y)) for c in self.cases
                   for target in c["affected_fiscal_years"]
                   for y in range(target - 2, target + 1)}
        paper = []
        originals = []
        vintages = []
        for ticker, year in sorted(sources):
            n = 15 if (ticker, year) == ("3027", "2015") else 7
            sha = hashlib.sha256(f"case-source:{ticker}:{year}".encode()).hexdigest()
            paper.append({
                "ticker": ticker, "fiscal_year": year,
                "source_sha256": sha, "official_xbrl_status": "validated",
                "components_computed": n, "components_required": 15,
                "outcome_label": "UNKNOWN",
                "approved_positive_label": "false",
                "approved_negative_label": "false",
                "original_filing_vintage_verified": "false",
                "historical_filing_publication_at_verified": "false",
                "original_notice_publication_at_verified": "false",
                "admitted_for_supervised_learning": "false",
            })
            originals.append({
                "ticker": ticker, "fiscal_year": year,
                "source_sha256": sha, "label_status": "UNKNOWN",
                "training_admitted": "false",
            })
            vintages.append({
                "ticker": ticker, "fiscal_year": year,
                "local_original_candidate_status": "NO_USER_SUPPLIED_ORIGINAL_VERSION",
                "local_source_sha256": "",
                "publication_time_independently_verified": "false",
                "original_version_independently_verified": "false",
                "supervised_label": "UNKNOWN", "training_admitted": "false",
            })
        self.paper_path = self.data / "phase10_case_official_paper_audit" / "phase10_case_official_paper_features.csv"
        self.original_path = self.data / "final_round1_integrated_ml_dataset" / "case_official_15_paper_candidate_separate.csv"
        self.vintage_path = self.data / "phase8_case_original_filing_recovery" / "original_case_filing_source_intake.csv"
        write_csv(self.paper_path, paper)
        write_csv(self.original_path, originals)
        write_csv(self.vintage_path, vintages)
        self.vintages = vintages

        primary = []
        for case in self.cases:
            for source in case["sources"]:
                if source["kind"] == "SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE":
                    continue
                primary.append({
                    "ticker": case["ticker"], "source_id": source["source_id"],
                    "document_identity_status": "NO_ARCHIVED_OFFICIAL_BYTES",
                    "file_sha256": "", "first_market_disclosure_time_verified": "false",
                    "outcome_label_approved": "false",
                })
        self.official_path = self.data / "phase7_official_case_asof_recovery" / "phase7_official_source_review.csv"
        write_csv(self.official_path, primary)
        comparison = []
        sparse = []
        for issuer in range(2001, 2013):
            ticker = str(issuer)
            for period in m.CASE_QUARTERS:
                sha = hashlib.sha256(f"comparison:{ticker}:{period}".encode()).hexdigest()
                item = {
                    "ticker": ticker, "reporting_period": period,
                    "data_role": "UNLABELED_MULTIISSUER_COMPARISON",
                    "source_status": "OFFICIAL_QUARTER_SAME_GRAIN_CANDIDATE_VINTAGE_UNKNOWN",
                    "source_sha256": sha, "label_status": "UNKNOWN",
                    "training_admitted": "false",
                }
                comparison.append(item)
                sparse.append({k:v for k,v in item.items() if k!="data_role"})
        for period in m.CASE_QUARTERS:
            comparison.append({
                "ticker": "6452", "reporting_period": period,
                "data_role": "ALLEGED_EVENT_PERIOD_NOT_CONFIRMED_POSITIVE",
                "source_status": "QUARTER_CONTEXT_VALIDATED_VINTAGE_UNKNOWN",
                "source_sha256": "b"*64, "label_status": "UNKNOWN",
                "training_admitted": "false",
            })
        self.quarters_path = self.data / "final_round1_integrated_ml_dataset" / "quarterly_issuer_period_source_index.csv"
        self.sparse_path = self.data / "final_round1_integrated_ml_dataset" / "quarterly_sparse_feature_matrix.csv"
        write_csv(self.quarters_path, comparison)
        write_csv(self.sparse_path, sparse)
        self.phase8_path = self.data / "phase8_case_original_filing_recovery" / "phase8_integrated_report.json"
        self.phase8_path.write_text(json.dumps({
            "holdout_1785_never_used": True, "positive_labels_admitted": 0,
            "negative_labels_admitted": 0, "supervised_model_training_admitted": False
        }), encoding="utf-8")
        self.baseline_path = self.data / "final_round1_integrated_ml_dataset" / "round1_dataset_readiness_report.json"
        self.baseline_path.write_text(json.dumps({
            "status": "FINALIZATION_ROUND1_REAL_TAIWAN_DATA_INTEGRATED_RESEARCH_TIERS_QA",
            "last_event_holdout_1785_excluded": True,
            "approved_positive_labels": 0, "approved_negative_labels": 0,
            "fraud_supervised_training_rows_admitted": 0,
            "original_first_filing_versions_verified": 0,
            "first_publication_times_verified": 0,
            "input_sha256": {"phase10_case_official_paper_features.csv:5": m.digest(self.paper_path)},
        }), encoding="utf-8")

    def run_gate(self):
        return m.build(self.data, self.output)

    def test_offline_review_packet_all_sample_grains_no_fake_labels(self):
        report = self.run_gate()
        self.assertEqual(report["candidate_case_company_years"], 7)
        self.assertEqual(report["separate_alleged_case_quarters"], 12)
        self.assertEqual(report["unreviewed_comparison_issuer_quarters"], 144)
        self.assertEqual(report["review_template_rows"], 163)
        self.assertEqual(report["reviewed_fraud_positives"], 0)
        self.assertEqual(report["reviewed_healthy_negatives"], 0)
        self.assertEqual(report["supervised_fraud_training_admitted"], 0)
        self.assertEqual(len(read_csv(self.output / "round2_case_year_review.csv")), 7)
        self.assertEqual(len(read_csv(self.output / "round2_case_quarter_review.csv")), 12)
        self.assertTrue(all(r["independent_period_outcome"] == "UNKNOWN"
                            for r in read_csv(self.output / "round2_unreviewed_comparison_quarters.csv")))
        self.assertNotIn("1785", {
            r["ticker"] for r in read_csv(self.output / "round2_independent_review_template.csv")})

    def test_allegations_do_not_become_automatic_positive(self):
        self.run_gate()
        rows = read_csv(self.output / "round2_case_quarter_review.csv")
        self.assertTrue(all(r["independent_period_outcome"] == "UNKNOWN"
                            and "PERIOD_SPECIFIC_LEGAL_FINDING" in r["review_blockers"]
                            for r in rows))

    def test_original_source_digest_tampered_after_round1_fails_closed(self):
        paper = read_csv(self.paper_path)
        paper[0]["components_computed"] = "15"
        write_csv(self.paper_path, paper)
        with self.assertRaisesRegex(ValueError, "prior_round1_case_source_changed"):
            self.run_gate()

    def test_source_value_disagreement_fails_even_if_hash_refreshed(self):
        originals = read_csv(self.original_path)
        originals[0]["source_sha256"] = "0"*64
        write_csv(self.original_path, originals)
        with self.assertRaisesRegex(ValueError, "paper_original_evidence_disagreement"):
            self.run_gate()

    def test_forged_supervised_case_approval_fails(self):
        originals = read_csv(self.original_path)
        originals[0]["training_admitted"] = "true"
        write_csv(self.original_path, originals)
        with self.assertRaisesRegex(ValueError, "source_approval_forged"):
            self.run_gate()

    def test_forged_supervised_quarterly_normal_fails(self):
        quarter = read_csv(self.quarters_path)
        quarter[0]["label_status"] = "0"
        write_csv(self.quarters_path, quarter)
        with self.assertRaisesRegex(ValueError, "source_outcome_forged"):
            self.run_gate()

    def test_holdout_in_quarter_sources_is_rejected(self):
        quarter = read_csv(self.quarters_path)
        quarter[0]["ticker"] = "1785"
        write_csv(self.quarters_path, quarter)
        with self.assertRaisesRegex(ValueError, "duplicate_or_holdout_quarter"):
            self.run_gate()

    def test_sparse_quarter_sha_mismatch_fails(self):
        sparse = read_csv(self.sparse_path)
        sparse[0]["source_sha256"] = "c"*64
        write_csv(self.sparse_path, sparse)
        with self.assertRaisesRegex(ValueError, "quarter_sparse_source_disagreement"):
            self.run_gate()

    def test_vintage_archive_submitted_does_not_automatically_verify(self):
        vintages = read_csv(self.vintage_path)
        vintages[0]["local_original_candidate_status"] = "MANUAL_SOURCE_BYTES_ARCHIVED_NEEDS_PUBLISHER_REVIEW"
        vintages[0]["local_source_sha256"] = "d"*64
        write_csv(self.vintage_path, vintages)
        report = self.run_gate()
        self.assertEqual(report["original_filing_vintages_certified"], 0)
        self.assertEqual(report["supervised_fraud_training_admitted"], 0)

    def test_missing_prior_phase8_result_has_explicit_error(self):
        self.phase8_path.unlink()
        with self.assertRaisesRegex(ValueError, "phase8_integrated_report_missing"):
            self.run_gate()

    def test_legal_document_cannot_approve_unreviewed_label(self):
        official = read_csv(self.official_path)
        official[0]["outcome_label_approved"] = "true"
        write_csv(self.official_path, official)
        with self.assertRaisesRegex(ValueError, "source_approval_forged"):
            self.run_gate()

    def test_duplicate_review_sources_fail_closed(self):
        quarter = read_csv(self.quarters_path)
        quarter.append(dict(quarter[0]))
        write_csv(self.quarters_path, quarter)
        with self.assertRaisesRegex(ValueError, "duplicate_or_holdout_quarter"):
            self.run_gate()


if __name__ == "__main__":
    unittest.main()
