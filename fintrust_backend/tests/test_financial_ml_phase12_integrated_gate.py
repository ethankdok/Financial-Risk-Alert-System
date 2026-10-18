"""Integrated Phase 1/Phase 2 source integrity and research gates (network-free)."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import phase12_integrated_gate as gate
from research.financial_ml.finmind_bulk_stage import DATASETS, URL
from research.financial_ml.finmind_cross_industry_pilot import FIELDS


class Phase12IntegratedGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.raw=self.root/"raw"
        self.cohort=self.root/"cohort.csv"
        self.cohort.parent.mkdir(parents=True,exist_ok=True)
        self.rows=[]
        for num in range(24):
            ticker=str(2200+num)
            self.rows.append(dict(ticker=ticker,company_name="Example",
                industry_category="半導體業" if num%2 else "電子零組件業",
                market="twse", source_snapshot_date="2026-10-18",
                historical_eligibility="UNVERIFIED",normal_label_status="UNREVIEWED"))
        self.save_cohort()

    def save_cohort(self):
        with self.cohort.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS)
            w.writeheader();w.writerows(self.rows)

    def raw_file(self,ticker,ds,rows,source=URL):
        path=self.raw/ticker/(ds+".json")
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({
            "source":source,"ticker":ticker,"dataset":ds,
            "period":["2013-01-01","2025-12-31"],
            "period_semantics":"QUARTERLY_UNVERIFIED_ANNUAL_AGGREGATION",
            "original_filing_vintage":"UNKNOWN","records":rows
        }),encoding="utf-8")
        return path

    def test_missing_archive_never_counts_as_provider_empty(self):
        report=gate.raw_audit(self.cohort,self.raw,self.root/"qa")
        self.assertEqual(report["missing_archives"],72)
        self.assertEqual(report["provider_empty_responses"],0)
        self.assertEqual(report["safe_companies"],24)
        self.assertFalse(report["original_filing_publication_asof_verified"])

    def test_provider_empty_valid_distinct_from_null_values(self):
        self.raw_file("2200",DATASETS[0],[])
        row=gate.inspect_archive(self.raw/"2200"/(DATASETS[0]+".json"),"2200",DATASETS[0])
        self.assertEqual(row["status"],"provider_empty_response")
        self.raw_file("2200",DATASETS[0],[
            {"stock_id":"2200","date":"2018-12-31","type":"Revenue","value":None}])
        row=gate.inspect_archive(self.raw/"2200"/(DATASETS[0]+".json"),"2200",DATASETS[0])
        self.assertEqual(row["status"],"quarantined")

    def test_conflicting_type_date_quarantines_only_bad_issuer(self):
        self.raw_file("2200",DATASETS[0],[
            {"stock_id":"2200","date":"2018-12-31","type":"Revenue","value":100},
            {"stock_id":"2200","date":"2018-12-31","type":"Revenue","value":200}])
        report=gate.raw_audit(self.cohort,self.raw,self.root/"qa")
        self.assertEqual(report["quarantined_issuers"],["2200"])
        self.assertEqual(report["safe_companies"],23)
        with (self.root/"qa"/"phase2_safe_cohort.csv").open(
                encoding="utf-8",newline="") as f:
            ids=[r["ticker"] for r in csv.DictReader(f)]
        self.assertNotIn("2200",ids)
        self.assertIn("2201",ids)

    def test_wrong_dataset_and_ticker_are_quarantined(self):
        self.raw_file("2200",DATASETS[0],[],source="https://fake.invalid/api")
        item=gate.inspect_archive(self.raw/"2200"/(DATASETS[0]+".json"),"2200",DATASETS[0])
        self.assertEqual(item["status"],"quarantined")
        self.assertIn("identity",item["reason"])

    def test_finmind_percentage_not_used_as_amount(self):
        self.raw_file("2200",DATASETS[0],[
            {"stock_id":"2200","date":"2018-12-31","type":"OperatingIncome_per","value":"4.3"},
            {"stock_id":"2200","date":"2018-12-31","type":"Revenue","value":"0"}])
        item=gate.inspect_archive(self.raw/"2200"/(DATASETS[0]+".json"),"2200",DATASETS[0])
        self.assertEqual(item["status"],"nonempty_provisional_archive")
        self.assertEqual(item["amount_rows"],1)
        self.assertEqual(item["percentage_rows"],1)
        self.assertEqual(item["periods_observed"],1)

    def test_reserved_1785_and_fake_normal_never_admitted(self):
        self.rows[0]["ticker"]="1785"
        self.save_cohort()
        with self.assertRaises(ValueError):
            gate.raw_audit(self.cohort,self.raw,self.root/"qa")
        self.rows[0]["ticker"]="2200"
        self.rows[0]["normal_label_status"]="reviewed_normal"
        self.save_cohort()
        with self.assertRaises(ValueError):
            gate.raw_audit(self.cohort,self.raw,self.root/"qa")

    def test_no_api_by_default_from_phase1_plus_phase2(self):
        # Only 24 candidates are used in this fixture; all files missing.
        root=self.root/"data"
        folder=root/"finmind_scaled_120"
        folder.mkdir(parents=True)
        (folder/"finmind_scaled_cohort.csv").write_bytes(self.cohort.read_bytes())
        result=gate.run(root,self.root/"integrated",execute_download=False)
        self.assertFalse(result["download_opt_in"])
        self.assertEqual(result["phase1_approved_positive_labels"],0)
        self.assertEqual(result["phase2_raw"]["missing_archives"],72)
        self.assertFalse(result["phase2_complete_for_trusted_15_features"])
        self.assertTrue(result["reserved_1785_final_holdout"])
        self.assertTrue((self.root/"integrated"/"phase12_gate_report.json").is_file())

    def test_download_argument_bounds_and_no_auto_approval(self):
        with self.assertRaisesRegex(ValueError,"unbounded"):
            gate.run(self.root,self.root/"out",max_rounds=11)
        self.assertFalse(gate.inspect_archive(
            self.root/"unknown.json","2200",DATASETS[0])["source_sha256"])


if __name__=="__main__":
    unittest.main()
