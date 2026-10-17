import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.taxonomy_gap_plan import build, save


class TestTaxonomyGapPlan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.report = self.root / "2026.json"
        self.report.write_text(json.dumps({
            "generated_at": "2026-09-21T00:00:00Z", "scope": "all",
            "requested_companies": 3,
            "pass_count": 1, "partial_count": 1, "fail_count": 1,
            "companies": [
                {"ticker": "2330", "company": "A", "subindustry": "晶圓代工"},
                {"ticker": "2454", "company": "B", "subindustry": "IC 設計"},
                {"ticker": "1785", "company": "heldout", "subindustry": "材料"},
            ],
        }), encoding="utf-8")
        self.db = self.root / "financial.sqlite3"
        with sqlite3.connect(self.db) as c:
            c.execute("CREATE TABLE financial_filings (ticker TEXT, fiscal_year INTEGER)")
            c.execute("CREATE TABLE normalized_financial_facts (ticker TEXT, period TEXT)")
            c.execute("INSERT INTO financial_filings VALUES ('2330', 2014)")
            c.execute("INSERT INTO normalized_financial_facts VALUES ('2330', '2014FY')")
            c.execute("INSERT INTO normalized_financial_facts VALUES ('2454', '2015FY')")
            c.execute("INSERT INTO normalized_financial_facts VALUES ('2330', '2024FY')")

    def test_candidates_not_verified_or_labeled(self):
        rows, r = build(self.report, facts_db=self.db, start_year=2013, end_year=2015)
        self.assertEqual(r["candidate_companies"], 2)
        self.assertEqual(r["candidate_company_years"], 6)
        self.assertEqual(r["reviewed_normal_company_years"], 0)
        self.assertEqual(r["verified_historical_eligible_company_years"], 0)
        self.assertTrue(all(row["normal_label_status"] == "UNREVIEWED" for row in rows))
        self.assertTrue(all(row["historical_listing_status"] == "UNVERIFIED" for row in rows))
        self.assertFalse(any(row["ticker"] == "1785" for row in rows))
        self.assertEqual(r["reference_coverage_counts_2026_only"]["PASS"], 1)

    def test_local_facts_not_training_ready(self):
        rows, r = build(self.report, facts_db=self.db, start_year=2013, end_year=2015)
        got = {(x["ticker"],x["fiscal_year"]): x for x in rows}
        self.assertEqual(got[("2330",2014)]["local_data_status"], "local_records_unverified")
        self.assertEqual(got[("2454",2015)]["local_data_status"], "partial_local_records")
        self.assertEqual(got[("2454",2013)]["local_data_status"], "not_in_local_financial_db")
        self.assertEqual(r["local_data_counts"]["local_records_unverified"], 1)

    def test_missing_local_db_does_not_block(self):
        rows, r = build(self.report, facts_db=self.root / "missing.sqlite3")
        self.assertEqual(len(rows), 10)
        self.assertEqual(r["local_database_status"], "local_database_absent")
        self.assertFalse((self.root / "missing.sqlite3").exists())

    def test_duplicate_ticker_fails_closed(self):
        x = json.loads(self.report.read_text())
        x["companies"][1]["ticker"] = "2330"
        self.report.write_text(json.dumps(x), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate ticker"):
            build(self.report, facts_db=self.db)

    def test_count_mismatch_fails_closed(self):
        x = json.loads(self.report.read_text())
        x["requested_companies"] = 96
        self.report.write_text(json.dumps(x), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            build(self.report, facts_db=self.db)

    def test_csv_and_json_exports(self):
        rows, r = build(self.report, facts_db=self.db, start_year=2013, end_year=2014)
        a, b = save(rows, r, self.root / "out")
        with Path(a).open(encoding="utf-8-sig", newline="") as f:
            csvrows = list(csv.DictReader(f))
        self.assertEqual(len(csvrows), 4)
        self.assertTrue(Path(b).exists())


if __name__ == "__main__":
    unittest.main()