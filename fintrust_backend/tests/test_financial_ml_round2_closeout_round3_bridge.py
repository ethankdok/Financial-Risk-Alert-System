"""Synthetic end-to-end Round2 closeout and Round3 release-gate tests."""
from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path

from research.financial_ml import round2_closeout_round3_bridge as bridge
from research.financial_ml import round2_evidence_review as first
from test_financial_ml_round2_evidence_review import (
    Round2EvidenceReviewTests, read_csv, write_csv,
)


def add_row_fields(path, fn):
    rows = read_csv(path)
    new = [fn(dict(r), i) for i, r in enumerate(rows)]
    write_csv(path, new)


class Round2CloseoutTests(unittest.TestCase):
    def setUp(self):
        fixture = Round2EvidenceReviewTests(
            "test_offline_review_packet_all_sample_grains_no_fake_labels")
        fixture.setUp()
        self.addCleanup(fixture.tmp.cleanup)
        self.fixture = fixture
        self.data = fixture.data
        self.review = fixture.output
        self.out = self.data / "round2_closeout"
        self.prepare_round1_extra_tables()
        seed = json.loads(Path(first.__file__).with_name(
            "phase1_case_sources_seed.json").read_text(encoding="utf-8"))
        linked = {source["source_id"]: (case["case_id"], source["url"])
                  for case in seed["candidates"] for source in case["sources"]}
        add_row_fields(fixture.official_path, lambda r, i: {
            **r, "case_id": linked[r["source_id"]][0],
            "source_url": linked[r["source_id"]][1]
        })
        fixture.run_gate()
        self.report_path = self.review / "round2_evidence_review_report.json"

    def rewrite_review_hashes(self, indices):
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        names = {
            0: self.fixture.baseline_path,
            1: Path(first.__file__).with_name("phase1_case_sources_seed.json"),
            2: self.fixture.paper_path, 3: self.fixture.original_path,
            4: self.fixture.quarters_path, 5: self.fixture.sparse_path,
            6: self.fixture.official_path, 7: self.fixture.vintage_path,
            8: self.fixture.phase8_path,
        }
        for k in indices:
            report["input_sha256"][str(k)] = bridge.digest(names[k])
        self.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def prepare_round1_extra_tables(self):
        frozen = self.data / "final_round1_integrated_ml_dataset"
        annual = []
        paper = []
        for n in range(120):
            ticker = str(2201+n)
            for year in range(2013, 2026):
                complete = len(annual) < 535
                annual.append({
                    "ticker": ticker, "fiscal_year": str(year),
                    "complete_candidate_vector": str(complete).lower(),
                    "source_sha256": "a"*64,
                    "label_status": "UNKNOWN", "training_admitted": "false",
                })
                paper.append({
                    "ticker": ticker, "fiscal_year": str(year),
                    "evidence_tier": "FINMIND_PROVISIONAL",
                    "complete_candidate_vector": "false",
                    "label_status": "UNKNOWN", "training_admitted": "false",
                })
        for k in range(64):
            paper.append({
                "ticker": str(2401 + k//8), "fiscal_year": str(2013 + k%8),
                "evidence_tier": "MOPS_OFFICIAL_RETROSPECTIVE",
                "complete_candidate_vector": str(k<11).lower(),
                "label_status": "UNKNOWN", "training_admitted": "false",
            })
        self.annual_path = frozen / "annual_12_amount_candidate_index.csv"
        self.annual_paper_path = frozen / "annual_original_15_paper_candidate_index.csv"
        write_csv(self.annual_path, annual)
        write_csv(self.annual_paper_path, paper)
        add_row_fields(self.fixture.sparse_path, lambda r, i: {
            **r, "sample_key": f"COMP:{r['ticker']}:{r['reporting_period']}",
            "issuer_split": "fit", "time_split": "fit",
            "joint_strict_split": "fit",
            "observed_selected_feature_count": "16" if i < 72 else "15",
            "selected_feature_count": "24",
            **{f"qf_{n:02d}": "0" for n in range(1,25)}
        })
        dict_rows = [{
            "feature_id": f"qf_{n:02d}", "concept_key": f"ifrs-full|Synthetic{n}",
            "period_grain": "instant", "fit_issuer_quarters": "40",
            "fit_distinct_issuers": "5", "supervised_training_admitted": "false"
        } for n in range(1,25)]
        self.dict_path = frozen / "quarterly_fit_selected_feature_dictionary.csv"
        write_csv(self.dict_path, dict_rows)
        report = json.loads(self.fixture.baseline_path.read_text(encoding="utf-8"))
        report.update({
            "annual_12_amount_full_12_company_years": 535,
            "quarter_fit_only_selected_exact_concept_grain_features": 24,
            "quarter_sparse_observed_selected_feature_cells": 2232,
        })
        self.fixture.baseline_path.write_text(json.dumps(report), encoding="utf-8")

    def run_bridge(self):
        return bridge.build(self.data, self.review, self.out)

    def test_complete_offline_integrity_and_strictly_blocked_round3(self):
        closeout, release = self.run_bridge()
        self.assertTrue(closeout["round2_engineering_gates_passed"])
        self.assertFalse(closeout["round2_research_label_acceptance_passed"])
        self.assertEqual(closeout["round2_source_sha256_verified"], 9)
        self.assertEqual(closeout["reviewer_template_rows"], 163)
        self.assertEqual(closeout["official_legal_sources_hashed_against_archived_bytes"], 0)
        self.assertEqual(release["quarter_fit_only_features"], 24)
        self.assertEqual(release["quarter_observed_feature_cells"], 2232)
        self.assertFalse(release["supervised_fraud_train_allowed"])
        self.assertFalse(release["literature_baseline_fraud_auc_allowed"])
        self.assertTrue(release["unlabeled_anomaly_diagnostics_allowed"])
        manifest = read_csv(self.out / "round3_research_source_manifest.csv")
        self.assertEqual(len(manifest), 3)
        self.assertTrue(all(x["fraud_supervised_use"] == "BLOCKED" for x in manifest))

    def test_official_document_receipt_and_raw_sha_are_actually_read(self):
        import_seed = json.loads(Path(first.__file__).with_name(
            "phase1_case_sources_seed.json").read_text(encoding="utf-8"))
        case = import_seed["candidates"][0]
        source = case["sources"][0]
        raw = b"Real bytes in a synthetic official-document fixture" * 10
        sha = hashlib.sha256(raw).hexdigest()
        archive = self.data / "phase7_official_case_asof_recovery" / (
            "official_case_bytes/" + case["case_id"] + "/" + source["source_id"] + ".html")
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(raw)
        archive.with_suffix(".json").write_text(json.dumps({
            "sha256": sha, "url": source["url"]
        }), encoding="utf-8")
        add_row_fields(self.fixture.official_path, lambda r, i: ({
            **r, "file_sha256": sha,
            "document_identity_status":
                "CONTENT_IDENTITY_SUPPORTED_PROVENANCE_REVIEW_OPEN"
        } if r["source_id"] == source["source_id"] else r))
        self.rewrite_review_hashes([6])
        closeout, release = self.run_bridge()
        self.assertEqual(closeout["official_legal_sources_hashed_against_archived_bytes"], 1)
        self.assertEqual(closeout["official_legal_source_retrieval_provenance_independently_verified"], 0)
        self.assertFalse(release["supervised_fraud_train_allowed"])

    def test_tampered_original_legal_document_is_rejected(self):
        self.test_official_document_receipt_and_raw_sha_are_actually_read()
        # The closeout already exists now; test raw archive verifier independently.
        p = list((self.data / "phase7_official_case_asof_recovery").rglob("*.html"))[0]
        p.write_bytes(b"modified")
        with self.assertRaisesRegex(ValueError, "archived_bytes_changed"):
            bridge.audit_official_legal_files(self.data,
                first.validate(json.loads(Path(first.__file__).with_name(
                    "phase1_case_sources_seed.json").read_text(encoding="utf-8"))))

    def test_user_returned_round2_report_can_be_pinned(self):
        expected = bridge.digest(self.report_path)
        result, release = bridge.build(self.data, self.review, self.out,
                                       expected_report_sha256=expected)
        self.assertTrue(result["round2_engineering_gates_passed"])
        self.assertFalse(release["supervised_fraud_train_allowed"])

    def test_wrong_user_returned_report_sha_fails_before_outputs(self):
        with self.assertRaisesRegex(ValueError, "accepted_report_sha_mismatch"):
            bridge.build(self.data, self.review, self.out,
                         expected_report_sha256="0"*64)
        self.assertFalse(self.out.exists())

    def test_round2_input_integrity_drift_fails_before_transfer(self):
        self.fixture.paper_path.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "prior_accepted_input_changed:2"):
            self.run_bridge()

    def test_no_auto_supervised_training_from_manually_entered_positive(self):
        add_row_fields(self.review / "round2_independent_review_template.csv",
            lambda r,i: {**r, "decision_status":
                         "APPROVED" if i==0 else r["decision_status"]})
        with self.assertRaisesRegex(ValueError, "template_approval_not_verified"):
            self.run_bridge()

    def test_heldout_1785_is_not_a_comparison(self):
        add_row_fields(self.review / "round2_unreviewed_comparison_quarters.csv",
            lambda r,i: {**r, "ticker": "1785"} if i==0 else r)
        with self.assertRaisesRegex(ValueError, "holdout_or_bad_issuer_in_review"):
            self.run_bridge()

    def test_reproducible_closeout_cannot_overwrite_completed_audit(self):
        self.run_bridge()
        original = (self.out / "round2_closure_and_round3_preflight.json").read_bytes()
        with self.assertRaisesRegex(FileExistsError, "preserve_review_history"):
            self.run_bridge()
        self.assertEqual(original,
            (self.out / "round2_closure_and_round3_preflight.json").read_bytes())

    def test_missing_critical_quarter_feature_is_rejected(self):
        rows = read_csv(self.dict_path)
        rows[0]["feature_id"] = "qf_99"
        write_csv(self.dict_path, rows)
        with self.assertRaisesRegex(ValueError, "feature_dictionary_not_fit_only_or_not_in_matrix"):
            self.run_bridge()

    def test_unsupported_manual_positive_outcome_in_case_review(self):
        add_row_fields(self.review / "round2_case_year_review.csv",
                       lambda r,i: {**r, "independent_period_outcome":
                                    "1" if i==0 else r["independent_period_outcome"]})
        with self.assertRaisesRegex(ValueError, "source_outcome_forged"):
            self.run_bridge()

    def test_round1_disagrees_with_quarter_observation_count(self):
        report = json.loads(self.fixture.baseline_path.read_text(encoding="utf-8"))
        report["quarter_sparse_observed_selected_feature_cells"] = 3434
        self.fixture.baseline_path.write_text(json.dumps(report), encoding="utf-8")
        self.rewrite_review_hashes([0])
        with self.assertRaisesRegex(ValueError, "report_numeric_consistency_conflict"):
            self.run_bridge()


if __name__ == "__main__":
    unittest.main()
