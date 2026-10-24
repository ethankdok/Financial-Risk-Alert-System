"""Hermetic cohort QA: no real licensed TEJ/FinLab rows committed."""
import csv
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.round2_label_cohorts import build

H=("ticker","calendar_year","observed_months","observed_month_count",
   "max_reported_restatement_count","last_observed_count")
FULL=";".join(f"{i:02d}" for i in range(1,13))

def fixture_csv(path,records):
    with path.open("w",encoding="utf-8-sig",newline="") as file:
        w=csv.DictWriter(file,fieldnames=H)
        w.writeheader()
        for ticker,yr,n,mo in records:
            w.writerow(dict(ticker=ticker, calendar_year=yr,observed_months=mo,
                observed_month_count=len(mo.split(";")),
                max_reported_restatement_count=n,last_observed_count=n))

class LabelCohortTests(unittest.TestCase):
    def test_explicit_proxy_not_official_and_temporal_features(self):
        with tempfile.TemporaryDirectory() as t:
            a=Path(t)/"input.csv";out=Path(t)/"out"
            fixture_csv(a,[
                ("2330",2014,5,FULL),("1101",2016,1,FULL),
                ("1101",2021,0,FULL),("1101",2023,0,FULL),
                ("1785",2016,0,FULL),("000102",2017,1,FULL),
                ("1201",2017,0,"01;02;03"),("1301",2018,0,FULL),
            ])
            result=build(a,out)
            self.assertEqual(result["included_company_years"],4)
            self.assertEqual(result["included_proxy_positive"],1)
            self.assertEqual(result["included_proxy_negative"],3)
            self.assertEqual(result["official_y_24m_confirmed_positive"],0)
            self.assertEqual(result["official_y_24m_confirmed_negative"],0)
            self.assertEqual(result["year_2014_reference_only"],
                             {"company_years":1,"positive_cues":1})
            self.assertEqual(result["split_counts"]["train"]["proxy_positive"],1)
            self.assertEqual(result["split_counts"]["validation"]["company_years"],1)
            self.assertEqual(result["split_counts"]["test"]["company_years"],1)
            self.assertEqual(result,build(a,out))
            with (out/"tej_calendar_proxy_cohort_private.csv").open(
                    encoding="utf-8-sig",newline="") as f:
                rows=list(csv.DictReader(f))
            self.assertTrue(all(x["y_official_annual_24m"]=="" for x in rows))
            self.assertTrue(all(x["training_features_ready"]=="false" for x in rows))
            train=next(x for x in rows if x["calendar_year"]=="2016")
            self.assertEqual(train["feature_asof_date"],"2015-12-31")
            self.assertEqual(train["max_safe_annual_financial_fy"],"2014")
            self.assertNotIn("1785",{x["ticker"] for x in rows})
            (out/"tej_calendar_proxy_cohort_private.csv").write_text(
                "corrupted", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError,"refuse_overwrite"):
                build(a,out)

    def test_duplicate_and_invalid_counts(self):
        with tempfile.TemporaryDirectory() as t:
            src=Path(t)/"i.csv";out=Path(t)/"out"
            fixture_csv(src,[("2330",2018,0,FULL),("2330",2018,0,FULL)])
            with self.assertRaisesRegex(ValueError,"duplicate_ticker_calendar_year"):
                build(src,out)
            fixture_csv(src,[("2330",2018,-1,FULL)])
            with self.assertRaisesRegex(ValueError,"restatement_count_not_unsigned"):
                build(src,out)

if __name__=="__main__":
    unittest.main()
