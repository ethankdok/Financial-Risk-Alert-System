"""Round 1: validate real archived leads and the offline event index."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from research.financial_ml.round1_event_registry import (
    build, load_sources, prepare_events, record, secure_url,
)


class Round1EventRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _load(self):
        report = build(self.root / "round1")
        with (self.root / "round1" / "round1_event_registry.csv").open(
                encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        with (self.root / "round1" / "round1_event_period_links.csv").open(
                encoding="utf-8", newline="") as f:
            links = list(csv.DictReader(f))
        return report, rows, links

    def test_real_source_counts_and_unique_event_keys(self):
        report, rows, links = self._load()
        self.assertEqual(report["input_record_count"], 22)
        self.assertEqual(report["unique_notices"], 20)
        self.assertEqual(report["unique_issuers"], 19)
        self.assertEqual(len({r["event_id"] for r in rows}), len(rows))
        self.assertEqual(len(links), report["event_year_or_quarter_links"])
        self.assertEqual(report["positive_training_labels_issued"], 0)
        self.assertEqual(report["negative_training_labels_issued"], 0)
        self.assertFalse(report["official_full_market_census_completed"])

    def test_consolidates_duplicate_same_notice_but_not_fiscal_years(self):
        _, rows, links = self._load()
        for ticker, years in [("3662", "2014;2015"), ("2384", "2014;2015")]:
            found = [r for r in rows if r["ticker"] == ticker]
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0]["annual_years"], years)
            self.assertEqual({r["fiscal_year"] for r in links
                              if r["ticker"] == ticker}, set(years.split(";")))

    def test_official_1785_reserved_from_training(self):
        _, rows, links = self._load()
        case = next(r for r in rows if r["ticker"] == "1785")
        self.assertEqual(case["evidence_tier"], "TPEX_PRIMARY_WEB")
        self.assertEqual(case["annual_years"], "2011;2012;2013;2014;2015")
        self.assertEqual(case["reserved_holdout"], "true")
        self.assertEqual(case["training_label"], "")
        self.assertEqual(case["training_admitted"], "false")
        self.assertTrue(all(r["reserved_holdout"] == "true" for r in links
                            if r["ticker"] == "1785"))

    def test_confirmed_correction_vs_allegation_vs_quarter(self):
        _, rows, links = self._load()
        point = next(r for r in rows if r["ticker"] == "6485")
        self.assertEqual(point["annual_years"], "2023;2024")
        self.assertEqual(point["event_family"], "ANNUAL_CORE_CORRECTION")
        self.assertEqual(point["annual_target_candidate"], "true")
        apex = next(r for r in rows if r["ticker"] == "5210")
        self.assertEqual(apex["event_family"], "INVESTIGATION_ALLEGATION")
        self.assertEqual(apex["annual_target_candidate"], "false")
        self.assertEqual(apex["training_label"], "")
        self.assertFalse(any(r["annual_target_candidate"] == "true" for r in links
                             if r["ticker"] in ("5210", "8487")))
        self.assertIn("2022Q3", {r["period"] for r in links
                                if r["ticker"] == "8487"})

    def test_no_mutations_and_idempotent_run(self):
        report, _, _ = self._load()
        self.assertEqual(build(self.root / "round1"), report)
        file = self.root / "round1" / "round1_event_registry.csv"
        file.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "round1_refuses_overwrite"):
            build(self.root / "round1")

    def test_bad_source_or_identifier_is_rejected(self):
        raw, _ = load_sources()
        changed = deepcopy(raw)
        changed["round10"]["events"][0]["event_class"] = "UNEXPECTED"
        with self.assertRaises(KeyError):
            prepare_events(changed)
        with self.assertRaisesRegex(ValueError, "invalid_https"):
            secure_url("http://mops.twse.com.tw/")
        with self.assertRaisesRegex(ValueError, "invalid_ticker"):
            record("12345", "foo", "2025-01-01", "NON_TARGET_NOTICE",
                   "test", [2023], [], "https://example.com/",
                   source_id="test", note="foo")

    def test_report_matches_output_sha256(self):
        import hashlib
        report, _, _ = self._load()
        stored = json.loads((self.root / "round1" /
                             "round1_event_registry_report.json").read_text(
                                 encoding="utf-8"))
        self.assertEqual(stored, report)
        for name, expected in report["output_sha256"].items():
            self.assertEqual(hashlib.sha256(
                (self.root / "round1" / name).read_bytes()).hexdigest(), expected)


if __name__ == "__main__":
    unittest.main()
