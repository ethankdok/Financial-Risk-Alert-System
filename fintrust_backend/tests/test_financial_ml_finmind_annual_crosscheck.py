"""Hermetic period-comparison checks; no FinMind internet requests."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.finmind_annual_crosscheck import compare, value_of, DATASETS


class FinMindAnnualCrosscheckTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / "finmind"
        self.manifest = self.base / "mops.json"

    def setup_sources(self, *, revenue=(10,20,30,40), total_assets=500, mops_revenue=100):
        ticker = "2330"
        for family, dataset in DATASETS.items():
            path = self.root / ticker / f"{dataset}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            if family == "income":
                items = [
                    {"stock_id":ticker,"date":f"2014-{m:02d}-{d:02d}",
                     "type":"Revenue","value":v}
                    for (m,d),v in zip(((3,31),(6,30),(9,30),(12,31)),revenue)
                ]
            elif family == "balance":
                items = [{"stock_id":ticker,"date":"2014-12-31",
                          "type":"TotalAssets","value":total_assets},
                         {"stock_id":ticker,"date":"2014-12-31",
                          "type":"TotalAssets_per","value":100}]
            else:
                items = []
            path.write_text(json.dumps({"ticker":ticker,"dataset":dataset,
                                        "records":items}), encoding="utf-8")
        self.manifest.write_text(json.dumps({"outcomes":{"2330:2014":{
            "ticker":ticker,"fiscal_year":2014,"status":"validated",
            "statement_scope":"consolidated","accounting_framework":"TIFRS",
            "content_hash":"a"*64,
            "facts":[{"metric_code":"revenue","value":str(mops_revenue),"unit":"TWD"},
                     {"metric_code":"total_assets","value":str(total_assets),"unit":"TWD"}]
        }}}), encoding="utf-8")

    def result_rows(self):
        with (self.base/"out"/"finmind_mops_annual_crosscheck.csv").open(
                encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    def test_four_quarters_are_compared_without_claiming_approval(self):
        self.setup_sources()
        report = compare(self.root, self.manifest, self.base/"out",
                         start_year=2014, end_year=2014)
        self.assertFalse(report["annual_dataset_built"])
        self.assertFalse(report["candidate_mapping_is_approved"])
        rows = self.result_rows()
        revenue = next(r for r in rows if r["mops_metric"]=="revenue")
        self.assertEqual(revenue["finmind_q4_value"],"40")
        self.assertEqual(revenue["finmind_four_quarter_sum"],"100")
        self.assertEqual(revenue["candidate_preference"],"FOUR_QUARTER_SUM_CANDIDATE")
        assets = next(r for r in rows if r["mops_metric"]=="total_assets")
        self.assertEqual(assets["candidate_preference"],"Q4_INSTANT_CANDIDATE")
        self.assertEqual(assets["finmind_four_quarter_sum"],"")

    def test_when_q4_equals_official_annual_q4_is_candidate(self):
        self.setup_sources(revenue=(10,20,30,40),mops_revenue=40)
        compare(self.root,self.manifest,self.base/"out",start_year=2014,end_year=2014)
        revenue = next(r for r in self.result_rows() if r["mops_metric"]=="revenue")
        self.assertEqual(revenue["candidate_preference"],"Q4_ONLY_CANDIDATE")

    def test_missing_quarter_never_imputed_or_summed(self):
        self.setup_sources(revenue=(10,20,30))
        compare(self.root,self.manifest,self.base/"out",start_year=2014,end_year=2014)
        revenue = next(r for r in self.result_rows() if r["mops_metric"]=="revenue")
        self.assertEqual(revenue["finmind_four_quarter_sum"],"")
        self.assertEqual(revenue["finmind_quarters_found"],"3")
        self.assertEqual(revenue["candidate_preference"],"NO_MATCH")

    def test_empty_provider_no_fake_annual_data(self):
        self.setup_sources()
        for path in (self.root/"2330").glob("*.json"):
            document=json.loads(path.read_text())
            document["records"]=[]
            path.write_text(json.dumps(document))
        compare(self.root,self.manifest,self.base/"out",start_year=2014,end_year=2014)
        self.assertTrue(all(r["candidate_preference"]=="NO_MATCH" for r in self.result_rows()))

    def test_reserved_case_fails_before_reading_files(self):
        with self.assertRaisesRegex(ValueError,"reserved_case"):
            compare(self.root,self.manifest,self.base/"out",tickers=("1785",))

    def test_conflicting_duplicate_period_fails_closed(self):
        self.setup_sources()
        path=self.root/"2330"/(DATASETS["income"]+".json")
        document=json.loads(path.read_text())
        document["records"].append({"stock_id":"2330","date":"2014-03-31",
                                    "type":"Revenue","value":999})
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(ValueError,"conflicting_type_period"):
            compare(self.root,self.manifest,self.base/"out",start_year=2014,end_year=2014)

    def test_nonnumeric_and_boolean_are_not_accepted(self):
        for value in (True, None, "not-a-number", "NaN"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    value_of(value)


if __name__=="__main__":
    unittest.main()
