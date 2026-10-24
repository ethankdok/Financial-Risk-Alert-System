"""Hermetic schema tests (synthetic fixtures are never counted as actual labels)."""
import csv
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

from research.financial_ml.round2_bulk_outcome_adapter import REQUIRED, build, validate_row

BASE = {
    "ticker": "2303", "fiscal_year": "2020",
    "annual_core_restatement_event": "1",
    "event_notice_date": "2022-03-31",
    "first_annual_filed_at": "2021-03-15",
    "followup_end_at": "", "full_24m_event_coverage": "false",
    "source_url": "https://example.org/notice/2303",
    "source_archive_sha256": "a" * 64,
    "statement_scope": "consolidated_annual",
    "reviewer_status": "SOURCE_REPORTED_REVIEWABLE",
}


class BulkAdapterTests(unittest.TestCase):
    def test_positive_requires_24_month_window(self):
        x = validate_row(BASE)
        self.assertEqual(x["y"], "1")
        self.assertEqual(x["label_observation_end_at"], "2023-03-15")
        r = dict(BASE, event_notice_date="2023-04-01")
        with self.assertRaisesRegex(ValueError, "outside_24m"):
            validate_row(r)

    def test_negative_cannot_infer_absence_without_followup(self):
        neg = dict(BASE, ticker="2454", annual_core_restatement_event="0",
                   event_notice_date="", full_24m_event_coverage="true",
                   followup_end_at="2023-03-15")
        self.assertEqual(validate_row(neg)["y"], "0")
        neg["followup_end_at"] = "2022-12-31"
        with self.assertRaisesRegex(ValueError, "censored"):
            validate_row(neg)
        neg["followup_end_at"] = "2023-03-15"
        neg["full_24m_event_coverage"] = "false"
        with self.assertRaisesRegex(ValueError, "missing_complete"):
            validate_row(neg)

    def test_reservation_and_period_scope(self):
        with self.assertRaisesRegex(ValueError, "reserved_case"):
            validate_row(dict(BASE, ticker="1785"))
        with self.assertRaisesRegex(ValueError, "not_comparable"):
            validate_row(dict(BASE, statement_scope="quarter"))
        with self.assertRaisesRegex(ValueError, "insufficient"):
            validate_row(dict(BASE, source_archive_sha256=""))

    def test_bulk_duplicate_and_immutable_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "source.csv"
            with file.open("w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=REQUIRED)
                w.writeheader()
                w.writerow(BASE)
            out = Path(tmp) / "result"
            a = build(file, out)
            self.assertEqual((a["total_rows"], a["counts"]["1"]), (1, 1))
            self.assertEqual(build(file, out), a)
            with file.open("a", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=REQUIRED)
                w.writerow(BASE)
            with self.assertRaisesRegex(ValueError, "duplicate"):
                build(file, Path(tmp) / "dup")


if __name__ == "__main__":
    unittest.main()
