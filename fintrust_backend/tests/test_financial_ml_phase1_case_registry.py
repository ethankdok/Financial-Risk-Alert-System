"""Hermetic tests for Phase 1 source-reviewed Taiwan event-year catalogue."""
from __future__ import annotations
import copy
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.phase1_case_registry import extract, validate


class Phase1CaseRegistryTests(unittest.TestCase):
    def setUp(self):
        self.seed_path = Path(__file__).resolve().parents[1] / "research" / "financial_ml" / "phase1_case_sources_seed.json"
        self.seed = json.loads(self.seed_path.read_text(encoding="utf-8"))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_all_cases_are_taiwan_and_1785_is_holdout(self):
        cases = validate(self.seed)
        self.assertEqual(len(cases), 3)
        self.assertEqual({c["ticker"] for c in cases}, {"3027", "8299", "6452"})
        self.assertEqual(self.seed["reserved_final_holdout"]["ticker"], "1785")

    def test_export_has_no_unverified_positives_or_negatives(self):
        result = extract(self.seed_path, self.root)
        self.assertEqual(result["candidate_cases"], 3)
        self.assertEqual(result["candidate_company_years"], 7)
        self.assertEqual(result["training_rows_admitted"], 0)
        self.assertEqual(result["approved_positive_labels"], 0)
        self.assertEqual(result["approved_negative_labels"], 0)
        with (self.root / "taiwan_case_year_candidates.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 7)
        self.assertEqual({r["supervised_label"] for r in rows}, {"UNKNOWN"})
        self.assertEqual({r["admitted_into_model_training"] for r in rows}, {"false"})
        self.assertEqual({r["original_filing_pit_verified"] for r in rows}, {"false"})
        self.assertNotIn("1785", {r["ticker"] for r in rows})
        self.assertEqual({int(r["fiscal_year"]) for r in rows if r["ticker"] == "3027"}, {2015, 2016})

    def test_8299_supreme_civil_remand_is_not_treated_as_final(self):
        entry = next(c for c in self.seed["candidates"] if c["ticker"] == "8299")
        self.assertEqual(
            entry["legal_status"],
            "SUPREME_CIVIL_REMAND_WITH_SEPARATE_FINAL_CRIMINAL_CASE_REFERENCED")
        self.assertEqual(entry["legal_evidence_document_date"], "2025-11-19")
        self.assertTrue(any(
            x["source_id"] == "judicial_8299_supreme_remand_20251119"
            for x in entry["sources"]))
        self.assertFalse(entry["first_public_disclosure_primary_archived"])
        self.assertFalse(entry["review"]["label_method_owner_approved"])

    def test_asof_known_time_is_not_auto_certified_as_earliest(self):
        extract(self.seed_path, self.root)
        with (self.root / "taiwan_case_year_candidates.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        refs = [r for r in rows if r["ticker"] == "3027"]
        self.assertTrue(all(r["candidate_first_public_notice_at"].startswith("2017-06-08") for r in refs))
        self.assertTrue(all(r["first_public_disclosure_primary_archived"] == "false" for r in refs))
        self.assertTrue(all("first_notice_archived" in r["review_missing"] for r in refs))

    def test_invented_holdout_issuer_or_false_negative_forbidden(self):
        altered = copy.deepcopy(self.seed)
        altered["candidates"][0]["ticker"] = "1785"
        with self.assertRaisesRegex(ValueError, "holdout"):
            validate(altered)
        altered = copy.deepcopy(self.seed)
        altered["reserved_final_holdout"]["in_any_training_or_hyperparameter_selection"] = True
        with self.assertRaisesRegex(ValueError, "1785_holdout"):
            validate(altered)

    def test_unapproved_manual_review_and_unarchived_source_not_accepted(self):
        altered = copy.deepcopy(self.seed)
        altered["candidates"][0]["review"]["label_method_owner_approved"] = True
        with self.assertRaisesRegex(ValueError, "cannot_be_preapproved"):
            validate(altered)
        altered = copy.deepcopy(self.seed)
        altered["candidates"][0]["sources"][0]["archive_sha256"] = "not_a_sha"
        with self.assertRaisesRegex(ValueError, "archive_sha256"):
            validate(altered)

    def test_duplicate_company_year_and_only_media_not_allowed(self):
        altered = copy.deepcopy(self.seed)
        altered["candidates"][0]["affected_fiscal_years"].append(2015)
        with self.assertRaisesRegex(ValueError, "duplicate_affected_year"):
            validate(altered)
        altered = copy.deepcopy(self.seed)
        altered["candidates"][1]["sources"] = [
            altered["candidates"][1]["sources"][1]]
        with self.assertRaisesRegex(ValueError, "only_secondary"):
            validate(altered)

    def test_external_pretraining_does_not_skip_taiwan_domain_review(self):
        altered = copy.deepcopy(self.seed)
        altered["transfer_policy"]["auto_admit_synthetic_labels"] = True
        with self.assertRaisesRegex(ValueError, "unsafe_external"):
            validate(altered)
        altered = copy.deepcopy(self.seed)
        altered["transfer_policy"]["auto_admit_foreign_examples"] = True
        with self.assertRaisesRegex(ValueError, "unsafe_external"):
            validate(altered)

    def test_bad_disclosure_time_rejected_and_evidence_domain_allowlisted(self):
        altered = copy.deepcopy(self.seed)
        altered["candidates"][0]["initial_disclosure_candidate_at"] = "2017-06-08T23:58:00"
        with self.assertRaisesRegex(ValueError, "timezone_aware"):
            validate(altered)
        altered = copy.deepcopy(self.seed)
        altered["candidates"][0]["sources"][0]["url"] = "https://example.com/unreviewed.html"
        with self.assertRaisesRegex(ValueError, "unreviewed_or_non_https"):
            validate(altered)


if __name__ == "__main__":
    unittest.main()
