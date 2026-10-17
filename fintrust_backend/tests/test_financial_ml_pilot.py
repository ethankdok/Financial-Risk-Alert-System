import csv
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.pilot import build, save


FIELDS = ["ticker", "fiscal_year", "period", "metric_code", "value", "unit", "statement_scope",
          "filing_version_id", "filing_version_type", "quality_status", "validation_status",
          "point_in_time_eligible", "effective_available_at", "source_kind", "accounting_framework"]


def fact(year, metric, value, **kwargs):
    r = {"ticker": "1785", "fiscal_year": str(year), "period": f"{year}FY",
         "metric_code": metric, "value": str(value), "unit": "TWD", "statement_scope": "consolidated",
         "filing_version_id": f"v{year}", "filing_version_type": "restated", "quality_status": "accepted",
         "validation_status": "validated", "point_in_time_eligible": "false",
         "effective_available_at": "2017-01-01T00:00:00+08:00", "source_kind": "mops_xbrl_instance",
         "accounting_framework": "TIFRS"}
    r.update(kwargs)
    return r


class TestPilot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "source.csv"

    def dump(self, rows):
        with self.file.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)

    def test_retrospective_ratios_lag_and_missing_without_fake_labels(self):
        rows = [fact(2014, "revenue", 100), fact(2014, "inventory", 10),
                fact(2014, "total_assets", 80), fact(2015, "revenue", 125),
                fact(2015, "inventory", 15), fact(2015, "total_assets", 120),
                fact(2015, "gross_profit", 25), fact(2015, "cost_of_goods_sold", 100),
                fact(2015, "operating_cash_flow", 8), fact(2015, "net_income", 20)]
        self.dump(rows)
        records, report = build([self.file], mode="retrospective")
        self.assertEqual(len(records), 2)
        self.assertAlmostEqual(records[1]["gross_margin"], 0.2)
        self.assertAlmostEqual(records[1]["inventory_turnover"], 8.0)
        self.assertAlmostEqual(records[1]["revenue_yoy"], 0.25)
        self.assertAlmostEqual(records[1]["earnings_cashflow_gap_proxy"], 0.12)
        self.assertIsNone(records[0]["inventory_turnover"])
        self.assertEqual(report["labeled_rows"], 0)
        self.assertIn("Retrospective", report["strict_warning"])
        self.assertTrue(save(records, report, Path(self.tmp.name) / "out").exists())

    def test_strict_prevents_restated_or_late_versions(self):
        self.dump([fact(2015, "revenue", 100)])
        cutoffs = Path(self.tmp.name) / "cutoffs.csv"
        cutoffs.write_text("ticker,fiscal_year,cutoff_at\n1785,2015,2016-03-31T00:00:00+08:00\n")
        records, report = build([self.file], mode="strict", cutoffs_path=cutoffs)
        self.assertFalse(records)
        self.assertEqual(report["rejection_counts"]["not_original"], 1)
        self.dump([fact(2015, "revenue", 100, filing_version_type="original",
                        point_in_time_eligible="true", effective_available_at="2016-04-01T00:00:00+08:00")])
        records, report = build([self.file], mode="strict", cutoffs_path=cutoffs)
        self.assertEqual(report["rejection_counts"]["published_after_cutoff"], 1)

    def test_ambiguous_versions_are_withheld(self):
        self.dump([fact(2015, "revenue", 100), fact(2015, "revenue", 110, filing_version_id="different")])
        records, report = build([self.file], mode="retrospective")
        self.assertFalse(records)
        self.assertEqual(len(report["ambiguous_company_years"]), 1)

    def test_conflicting_duplicate_field_is_withheld(self):
        self.dump([fact(2015, "revenue", 100), fact(2015, "revenue", 200)])
        records, report = build([self.file], mode="retrospective")
        self.assertFalse(records)
        self.assertEqual(len(report["ambiguous_company_years"]), 1)

    def test_label_ledger_is_not_guessed(self):
        self.dump([fact(2015, "revenue", 100)])
        labels = Path(self.tmp.name) / "labels.csv"
        labels.write_text("ticker,fiscal_year,label,label_source,outcome_known_at\n1785,2015,1,official_notice,2016-05-13T00:00:00+08:00\n")
        records, report = build([self.file], mode="retrospective", labels_path=labels)
        self.assertEqual(records[0]["label"], "1")
        self.assertEqual(report["positive_labels"], 1)


if __name__ == "__main__":
    unittest.main()