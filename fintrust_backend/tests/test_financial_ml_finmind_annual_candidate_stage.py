"""Synthetic checks for candidate-only annual family semantics."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.finmind_annual_candidate_stage import stage
from research.financial_ml.finmind_bulk_stage import DATASETS, URL


class AnnualCandidateStageTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.raw = self.base / "raw"
        self.candidates = self.base / "sample.csv"
        with self.candidates.open("w", encoding="utf-8", newline="") as fp:
            wr = csv.DictWriter(fp, fieldnames=["ticker", "normal_label_status"])
            wr.writeheader()
            wr.writerows([
                {"ticker": "2330", "normal_label_status": "UNREVIEWED"},
                {"ticker": "2452", "normal_label_status": "UNREVIEWED"}
            ])
        for ticker in ("2330", "2452"):
            folder = self.raw / ticker
            folder.mkdir(parents=True)
            for i, dataset in enumerate(DATASETS):
                lines = []
                if ticker == "2330":
                    if i == 0:
                        lines = [{"stock_id": ticker, "date": f"2014-{m:02d}-{d:02d}",
                                  "type": "Revenue", "value": value}
                                 for (m, d), value in zip(
                                     ((3, 31), (6, 30), (9, 30), (12, 31)),
                                     (10, 20, 30, 40))]
                        lines += [{"stock_id":ticker, "date":"2014-12-31",
                                   "type":"CostOfGoodsSold", "value":0}]
                    elif i == 1:
                        lines = [{"stock_id":ticker, "date":"2014-12-31",
                                  "type":"TotalAssets","value":100}]
                    else:
                        lines = [{"stock_id":ticker, "date":"2014-12-31",
                                  "type":"CashFlowsFromOperatingActivities","value":70}]
                (folder/(dataset+".json")).write_text(json.dumps({
                    "source":URL,"ticker":ticker,"dataset":dataset,
                    "period":["2013-01-01","2025-12-31"],
                    "records":lines,
                }),encoding="utf-8")

    def read_csv(self):
        with (self.base/"out"/"finmind_annual_candidate_lines.csv").open(
            encoding="utf-8", newline="") as file:
            return list(csv.DictReader(file))

    def test_income_sum_cashflow_q4_balance_instant(self):
        result = stage(self.candidates,self.raw,self.base/"out",start_year=2014,end_year=2014)
        self.assertFalse(result["training_dataset_ready"])
        data = [x for x in self.read_csv() if x["ticker"]=="2330"]
        sales = next(x for x in data if x["candidate_mops_metric"]=="revenue")
        self.assertEqual(sales["candidate_annual_value"],"100")
        self.assertEqual(sales["source_quarters_found"],"4")
        self.assertEqual(sales["training_admitted"],"false")
        cfo = next(x for x in data if x["candidate_mops_metric"]=="operating_cash_flow")
        self.assertEqual(cfo["candidate_annual_value"],"70")
        self.assertEqual(cfo["method_candidate"],"Q4_CUMULATIVE_CANDIDATE")
        assets = next(x for x in data if x["candidate_mops_metric"]=="total_assets")
        self.assertEqual(assets["candidate_annual_value"],"100")
        self.assertEqual(assets["method_candidate"],"DEC31_INSTANT_CANDIDATE")

    def test_missing_three_quarters_is_not_zero(self):
        stage(self.candidates,self.raw,self.base/"out",start_year=2014,end_year=2014)
        line=next(x for x in self.read_csv() if x["ticker"]=="2330" and
                  x["candidate_mops_metric"]=="cost_of_goods_sold")
        self.assertEqual(line["status"],"missing_income_quarter")
        self.assertEqual(line["candidate_annual_value"],"")

    def test_empty_source_distinct_from_missing_metric(self):
        stage(self.candidates,self.raw,self.base/"out",start_year=2014,end_year=2014)
        rows=[x for x in self.read_csv() if x["ticker"]=="2452"]
        self.assertTrue(rows)
        self.assertEqual({x["status"] for x in rows},{"empty_provider_response"})
        self.assertTrue(all(x["candidate_annual_value"]=="" for x in rows))

    def test_reserved_case_rejected(self):
        text = self.candidates.read_text(encoding="utf-8").replace("2452","1785")
        self.candidates.write_text(text,encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"reserved"):
            stage(self.candidates,self.raw,self.base/"out",start_year=2014,end_year=2014)

    def test_conflicting_provider_duplicate_is_rejected(self):
        path=self.raw/"2330"/(DATASETS[0]+".json")
        doc=json.loads(path.read_text(encoding="utf-8"))
        doc["records"].append({"stock_id":"2330","date":"2014-03-31",
                               "type":"Revenue","value":999})
        path.write_text(json.dumps(doc),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"duplicate_period"):
            stage(self.candidates,self.raw,self.base/"out",start_year=2014,end_year=2014)


if __name__ == "__main__":
    unittest.main()
