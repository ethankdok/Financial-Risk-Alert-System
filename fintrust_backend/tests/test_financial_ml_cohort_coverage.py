"""Strict local planner smoke tests; use temporary files, never real production data."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.cohort_coverage import assess, save


class CohortCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "source.sqlite3"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE companies(ticker TEXT PRIMARY KEY, market TEXT, industry_code TEXT,
                    listing_status TEXT, listed_at TEXT, subindustry TEXT);
                CREATE TABLE financial_filings(ticker TEXT, fiscal_year INTEGER);
                CREATE TABLE normalized_financial_facts(ticker TEXT, period TEXT, value REAL);
                INSERT INTO companies VALUES('2330','TWSE','24','listed','1994-09-05','foundry');
                INSERT INTO companies VALUES('2454','TWSE','24','listed','2001-07-23','design');
                INSERT INTO companies VALUES('3711','TWSE','24','listed','2018-04-30','packaging');
                INSERT INTO companies VALUES('1785','TWSE','24','listed','2000-01-01','holdout');
                INSERT INTO companies VALUES('1234','TWSE','20','listed','1998-01-01','not semiconductor');
                INSERT INTO companies VALUES('3333','TPEX','24','listed','1998-01-01','not TWSE');
                INSERT INTO financial_filings VALUES('2330',2013);
                INSERT INTO normalized_financial_facts VALUES('2330','2013FY',9999);
                INSERT INTO normalized_financial_facts VALUES('2330','2024FY',9999);
                INSERT INTO normalized_financial_facts VALUES('2454','2013Q1',9999);
            """)

    def test_companies_by_year_and_holdout(self):
        rows, report = assess(self.path, self.path, start_year=2013, end_year=2015)
        self.assertEqual(report['status'], 'local_gap_plan_created')
        self.assertEqual(report['company_master_rows'], 6)
        self.assertEqual(report['candidate_companies'], 2)
        self.assertEqual(report['company_years'], 6)
        self.assertEqual(report['excluded_post_listing_company_years'], 3)
        self.assertFalse(any(r['ticker'] in {'1785', '3711'} for r in rows))
        self.assertEqual(next(r for r in rows if r['ticker'] == '2330' and r['fiscal_year'] == 2013)['coverage_status'], 'recorded_but_unverified')
        self.assertEqual(next(r for r in rows if r['ticker'] == '2454' and r['fiscal_year'] == 2013)['annual_fact_rows'], 0)
        self.assertNotIn('9999', str(rows))

    def test_no_master_table_does_not_substitute_seed_companies(self):
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TABLE companies')
        rows, report = assess(self.path, self.path)
        self.assertFalse(rows)
        self.assertEqual(report['status'], 'blocked_no_local_semiconductor_master')

    def test_missing_database_never_created(self):
        missing = Path(self.temp.name) / 'does_not_exist.sqlite3'
        rows, report = assess(missing, missing)
        self.assertEqual(report['status'], 'blocked_master_database_absent')
        self.assertFalse(missing.exists())

    def test_report_write_does_not_change_sources(self):
        before = self.path.read_bytes()
        rows, report = assess(self.path, self.path, start_year=2013, end_year=2013)
        out = save(rows, report, Path(self.temp.name) / 'output')
        self.assertTrue(all(p.exists() for p in out))
        self.assertEqual(before, self.path.read_bytes())

    def test_invalid_year_range(self):
        with self.assertRaises(ValueError):
            assess(self.path, self.path, start_year=2015, end_year=2013)


if __name__ == '__main__':
    unittest.main()