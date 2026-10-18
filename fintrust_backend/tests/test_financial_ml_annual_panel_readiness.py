"""Synthetic regression for provisional temporal panel readiness."""
from __future__ import annotations
import csv
import hashlib
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.annual_panel_readiness import METRICS, prepare


class AnnualPanelReadinessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.path = self.root/"candidate.csv"
        self.fields = ("ticker", "fiscal_year", "source_family", "candidate_mops_metric",
                       "status", "candidate_annual_value", "source_sha256",
                       "training_admitted", "publication_asof_verified",
                       "label_status", "source_quarters_found")
        self.rows = []
        for ticker in ("2330", "2452"):
            for year in (2013, 2014, 2015, 2016, 2017):
                for index, metric in enumerate(METRICS):
                    family = ("income" if index < 5 else
                              "cashflow" if metric == "operating_cash_flow" else "balance")
                    present = (ticker == "2330" and not (year == 2014 and metric == "net_income"))
                    self.rows.append({
                        "ticker": ticker, "fiscal_year": year,
                        "source_family": family, "candidate_mops_metric": metric,
                        "status": "candidate_annual_value" if present else "empty_provider_response",
                        "candidate_annual_value": ("0" if metric == "gross_profit" else "42") if present else "",
                        "source_sha256": hashlib.sha256((ticker+family).encode()).hexdigest(),
                        "training_admitted": "false", "publication_asof_verified": "false",
                        "label_status": "UNREVIEWED", "source_quarters_found": "4" if present else "0"
                    })
        self.save()

    def save(self):
        with self.path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=self.fields)
            writer.writeheader()
            writer.writerows(self.rows)

    def test_window_counts_and_missing_not_zero(self):
        report = prepare(self.path, self.root/"out", window_lengths=(3,5))
        self.assertEqual(report["source_company_years"], 10)
        self.assertEqual(report["complete_12_metric_company_years"], 4)
        self.assertEqual(report["window_stats"]["3"]["candidate_complete_windows"], 1)
        self.assertEqual(report["window_stats"]["5"]["candidate_complete_windows"], 0)
        self.assertFalse(report["financial_model_admitted"])
        with (self.root/"out"/"company_year_candidate_panel.csv").open(
                encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        gap = next(row for row in rows if row["ticker"] == "2330" and row["fiscal_year"] == "2014")
        self.assertEqual(gap["net_income"], "")
        self.assertEqual(gap["gross_profit"], "0")
        self.assertEqual(gap["training_admitted"], "false")

    def test_duplicate_or_incomplete_company_year_rejected(self):
        self.rows.append(dict(self.rows[0]))
        self.save()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            prepare(self.path, self.root/"out")
        self.rows.pop()
        self.rows.pop(0)
        self.save()
        with self.assertRaisesRegex(ValueError, "incomplete_company_year"):
            prepare(self.path, self.root/"out")

    def test_reserved_case_and_fake_label_rejected(self):
        self.rows[0]["ticker"] = "1785"
        self.save()
        with self.assertRaisesRegex(ValueError, "reserved"):
            prepare(self.path, self.root/"out")
        self.rows[0]["ticker"] = "2330"
        self.rows[0]["label_status"] = "reviewed_normal"
        self.save()
        with self.assertRaisesRegex(ValueError, "unapproved_outcome"):
            prepare(self.path, self.root/"out")

    def test_no_fabricated_missing_values_or_nonfinite(self):
        self.rows[0]["status"] = "missing_income_quarter"
        self.save()
        with self.assertRaisesRegex(ValueError, "fabricated_value"):
            prepare(self.path, self.root/"out")
        self.rows[0]["status"] = "candidate_annual_value"
        self.rows[0]["candidate_annual_value"] = "NaN"
        self.save()
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            prepare(self.path, self.root/"out")

    def test_training_claim_and_hash_conflict_rejected(self):
        self.rows[0]["training_admitted"] = "true"
        self.save()
        with self.assertRaisesRegex(ValueError, "unauthorized_model_admission"):
            prepare(self.path, self.root/"out")
        self.rows[0]["training_admitted"] = "false"
        self.rows[0]["source_sha256"] = "a"*64
        self.save()
        with self.assertRaisesRegex(ValueError, "inconsistent_source_hash"):
            prepare(self.path, self.root/"out")


if __name__ == "__main__":
    unittest.main()
