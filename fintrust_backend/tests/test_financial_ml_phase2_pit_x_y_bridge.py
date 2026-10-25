"""Phase 2 integration tests using fictitious source artifacts only."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml.phase2_pit_x_y_bridge import build,BENEISH

HASH0="a"*64
HASH1="b"*64
URL="https://mops.twse.com.tw/mops/web/index"


def write_csv(path,headers,rows):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        wr=csv.DictWriter(f,fieldnames=headers);wr.writeheader();wr.writerows(rows)


def manifest_item(year):
    return {
        "ticker":"1203","fiscal_year":year,
        "status":"validated","statement_scope":"consolidated",
        "accounting_framework":"TIFRS","filing_version_type":"original",
        "filing_version_id":f"1203-FY{year}-ORIGINAL",
        "content_hash":HASH1 if year==2014 else HASH0,
        "source_kind":"mops_xbrl_zip","point_in_time_eligible":True,
        "original_version_verified":True,"first_publication_verified":True,
        "original_first_public_at":f"{year+1}-03-20",
        "original_publication_evidence_url":URL,
    }


class Phase2BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.base=Path(self.tmp.name)
        self.proxy=self.base/"proxy.csv"
        self.manifest=self.base/"manifest.json"
        self.lit=self.base/"lit.csv"
        self.facts=self.base/"facts.csv"
        self.out=self.base/"out"
        write_csv(self.proxy,["ticker","calendar_year","case_key","split",
            "y_tej_calendar_proxy","y_official_annual_24m",
            "feature_asof_date","max_safe_annual_financial_fy"],[
            dict(ticker="1203",calendar_year="2016",case_key="1203-CY2016",
                 split="train",y_tej_calendar_proxy="1",y_official_annual_24m="",
                 feature_asof_date="2015-12-31",max_safe_annual_financial_fy="2014")
        ])
        self.arr={f"1203:{yr}":manifest_item(yr) for yr in (2013,2014)}
        self.manifest.write_text(json.dumps({"outcomes":self.arr}),encoding="utf-8")
        lr={"ticker":"1203","fiscal_year":"2014",
            "filing_version_id":"1203-FY2014-ORIGINAL",
            "filing_version_type":"original","accounting_framework":"TIFRS",
            "statement_scope":"consolidated","raw_sha256":HASH1,
            "analysis_mode":"retrospective",
            **{k:"1.0" for k in BENEISH}}
        write_csv(self.lit,list(lr),[lr])
        facts=[]
        metrics={
            "net_income":10,"total_assets":100,"current_assets":50,
            "current_liabilities":25,"total_liabilities":40,
            "operating_cash_flow":8,"accounts_receivable":12,
            "inventory":20,"revenue":120,
        }
        for yr in (2013,2014):
            for key,value in metrics.items():
                facts.append(dict(ticker="1203",fiscal_year=yr,metric_code=key,
                    value=value if yr==2014 else value-1,unit="TWD",
                    filing_version_id=f"1203-FY{yr}-ORIGINAL",
                    raw_sha256=HASH1 if yr==2014 else HASH0))
        write_csv(self.facts,list(facts[0]),facts)

    def tearDown(self):self.tmp.cleanup()

    def test_label_only_reports_missing_not_zero(self):
        report=build(self.proxy,self.out)
        self.assertEqual(report["proxy_company_year_rows"],1)
        self.assertEqual(report["x_full_15_ready_rows"],0)
        self.assertEqual(report["proxy_positive_count"],1)
        self.assertEqual(report["official_y1_verified_positives"],0)
        self.assertEqual(report["x_coverage_by_gate"],{"MOPS_X_SOURCE_NOT_PROVIDED":1})
        self.assertEqual(build(self.proxy,self.out),report)

    def test_all_15_true_original_asof_and_same_versions(self):
        report=build(self.proxy,self.out,self.manifest,self.lit,self.facts)
        self.assertEqual(report["x_full_15_ready_rows"],1)
        self.assertEqual(report["x_any_computed_rows"],1)
        with (self.out/"phase2_proxy_x_y_pit_private.csv").open(encoding="utf-8-sig") as f:
            row=next(csv.DictReader(f))
        self.assertEqual(row["roa"],"0.1")
        self.assertEqual(row["current_ratio"],"2")
        self.assertEqual(row["feature_fy"],"2014")
        self.assertEqual(row["prior_feature_fy"],"2013")
        self.assertEqual(row["training_ready"],"true")
        self.assertEqual(row["y_official_annual_24m"],"")

    def test_unverified_prior_is_rejected_without_literature_leakage(self):
        self.arr["1203:2013"]["original_version_verified"]=False
        self.manifest.write_text(json.dumps({"outcomes":self.arr}),encoding="utf-8")
        report=build(self.proxy,self.out,self.manifest,self.lit,self.facts)
        self.assertEqual(report["x_full_15_ready_rows"],0)
        self.assertEqual(report["x_coverage_by_gate"],
                         {"PRIOR_ORIGINAL_VERSION_OR_DATE_NOT_VERIFIED":1})

    def test_late_publication_does_not_pass(self):
        self.arr["1203:2014"]["original_first_public_at"]="2016-03-31"
        self.manifest.write_text(json.dumps({"outcomes":self.arr}),encoding="utf-8")
        report=build(self.proxy,self.out,self.manifest,self.lit,self.facts)
        self.assertEqual(report["x_full_15_ready_rows"],0)
        self.assertEqual(report["x_coverage_by_gate"],
                         {"CURRENT_PUBLICATION_AFTER_PREDICTION_CUTOFF":1})

    def test_mismatched_report_filing_hash_fails_closed(self):
        facts=list(csv.DictReader(self.facts.open(encoding="utf-8-sig")))
        facts[0]["raw_sha256"]="deadbeef"
        write_csv(self.facts,list(facts[0]),facts)
        with self.assertRaisesRegex(ValueError,"annual_fact_version_or_hash_mismatch"):
            build(self.proxy,self.out,self.manifest,self.lit,self.facts)

if __name__=="__main__":
    unittest.main()
