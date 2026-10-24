"""Round2 tests run against the real checked-in, source-linked issuer-year records."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from research.financial_ml.round1_event_registry import build as round1_build
from research.financial_ml.round2_binary_labels import (
    HOME, INPUT, build, make_labels, _read_csv,
)


class Round2BinaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def _case(self):
        report = build(self.root / "out")
        rows = _read_csv(self.root / "out" / "round2_binary_research_labels.csv")
        followups = _read_csv(self.root / "out" / "round2_targeted_followup_queue.csv")
        return report, rows, followups

    def _raw_inputs(self):
        round1_build(self.root / "sources")
        return (json.loads(INPUT.read_text(encoding="utf-8")),
                _read_csv(self.root / "sources" / "round1_event_registry.csv"),
                _read_csv(self.root / "sources" / "round1_event_period_links.csv"))

    def test_real_numeric_classes_and_no_duplicate_pairs(self):
        report, rows, followups = self._case()
        self.assertEqual((report["rows_numeric_y"], report["y_1"], report["y_0"]),
                         (16, 8, 8))
        self.assertEqual(len({(r["ticker"], r["fiscal_year"]) for r in rows}), 16)
        self.assertEqual(set(r["y"] for r in rows), {"0", "1"})
        self.assertTrue(all(r["strict_24m_y"] == "" for r in rows))
        self.assertTrue(all(r["original_xbrl_first_filing_verified"] == "false"
                            for r in rows))
        self.assertFalse(report["has_numeric_financial_x"])
        self.assertGreaterEqual(len(followups), 1)

    def test_real_positives_issuer_and_annual_amount_notice(self):
        _, rows, _ = self._case()
        expected = {
            ("2305", "2015"), ("3432", "2022"), ("6918", "2023"),
            ("6485", "2023"), ("6485", "2024"),
            ("7547", "2021"), ("7547", "2022"), ("7547", "2023"),
        }
        self.assertEqual({(r["ticker"], r["fiscal_year"]) for r in rows
                          if r["y"] == "1"}, expected)
        self.assertTrue(all(r["annual_event_id"] and r["notice_date"]
                            for r in rows if r["y"] == "1"))
        # Restatement is not equivalent to fraud.
        self.assertTrue(all(r["certified_fraud_label"] == "" for r in rows))

    def test_silver_negative_controls_are_period_specific(self):
        report, rows, _ = self._case()
        neg = [r for r in rows if r["y"] == "0"]
        self.assertEqual({r["ticker"] for r in neg},
                         {"2330", "2454", "2317", "6488"})
        self.assertEqual({r["fiscal_year"] for r in neg}, {"2022", "2023"})
        self.assertTrue(all(r["evidence_grade"].startswith("SILVER_THIRD_PARTY")
                            and r["negative_window_complete"] == "false"
                            for r in neg))
        self.assertTrue(report["only_silver_labels"])
        self.assertEqual(report["gold_labels"], 0)

    def test_1785_heldout_and_no_mass_negative_assumption(self):
        report, rows, _ = self._case()
        self.assertFalse(any(r["ticker"] == "1785" for r in rows))
        self.assertEqual(report["unassigned_mass_negative_rows"], 0)
        self.assertTrue(report["reserved_holdout_1785"])

    def test_invalid_positive_evidence_is_rejected(self):
        evidence, events, periods = self._raw_inputs()
        altered = deepcopy(evidence)
        altered["positives"][0]["source_url"] = "https://example.org/fake"
        with self.assertRaisesRegex(ValueError, "not_linked"):
            make_labels(altered, events, periods)
        altered = deepcopy(evidence)
        altered["positives"][0]["fiscal_year"] = 2024
        with self.assertRaisesRegex(ValueError, "not_supported"):
            make_labels(altered, events, periods)
        altered = deepcopy(evidence)
        altered["positives"][0]["ticker"] = "1785"
        with self.assertRaisesRegex(ValueError, "1785_contamination"):
            make_labels(altered, events, periods)

    def test_invalid_negative_evidence_or_leakage_is_rejected(self):
        evidence, events, periods = self._raw_inputs()
        altered = deepcopy(evidence)
        altered["negatives"][0]["negative_window_complete"] = True
        with self.assertRaisesRegex(ValueError, "snapshot_is_not_eligible"):
            make_labels(altered, events, periods)
        altered = deepcopy(evidence)
        altered["negatives"][0]["ticker"] = "6485"
        with self.assertRaisesRegex(ValueError, "duplicate_or_conflicting_y"):
            make_labels(altered, events, periods)
        altered = deepcopy(evidence)
        altered["negatives"][0]["source_url"] = "https://fake.example/stock/2330/filings"
        # The host must be a recognized declared issuer-source; not merely a path match.
        with self.assertRaisesRegex(ValueError, "negative_source_identity"):
            make_labels(altered, events, periods)

    def test_immutable_idempotence_and_hash(self):
        report, _, _ = self._case()
        self.assertEqual(build(self.root / "out"), report)
        label_path = self.root / "out" / "round2_binary_research_labels.csv"
        label_path.write_text("tamper", encoding="utf-8")
        with self.assertRaisesRegex(FileExistsError, "round2_immutable_output_conflict"):
            build(self.root / "out")
        # Fresh output report is parseable and commits exact CSV source SHA.
        report2 = build(self.root / "fresh")
        self.assertEqual(report2["source_evidence_sha256"],
                         __import__("hashlib").sha256(INPUT.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
