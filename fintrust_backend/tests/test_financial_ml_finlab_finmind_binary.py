"""Synthetic FinMind finance and independently supplied binary outcomes only."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.annual_panel_readiness import FIELDNAMES, METRICS
from research.financial_ml.finlab_finmind_binary import (
    build, labels, finmind_panel, finmind_union, mops_panel, make_review_template, x_metrics
)

SHAS = "a" * 64
TARGET = "DOCUMENTED_ANNUAL_CONSOLIDATED_CORE_FINANCIAL_CORRECTION_OR_RESTATEMENT_OBSERVED_BY_ASOF"

def save(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, columns, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

class FinlabFinmindBinaryTest(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.annual=self.root/"finmind.csv"
        self.silver=self.root/"silver.csv"
        self.proxy=self.root/"proxy.csv"
        self.review=self.root/"review.csv"
        self.dest=self.root/"output"
        self.frows=[]
        families={"revenue":"income","cost_of_goods_sold":"income","gross_profit":"income",
            "operating_income":"income","net_income":"income","total_assets":"balance",
            "current_assets":"balance","current_liabilities":"balance",
            "total_liabilities":"balance","inventory":"balance",
            "cash_and_cash_equivalents":"balance","operating_cash_flow":"cashflow"}
        for idx in range(1201, 1209):
            for fy in range(2013,2024):
                baseline=1000+idx+fy
                vals={"revenue":baseline,"cost_of_goods_sold":baseline*.65,
                    "gross_profit":baseline*.35,"operating_income":baseline*.12,
                    "net_income":baseline*.09,
                    "total_assets":baseline*2,"current_assets":baseline*.8,
                    "current_liabilities":baseline*.4,
                    "total_liabilities":baseline*1.1,
                    "inventory":baseline*.25,"cash_and_cash_equivalents":baseline*.3,
                    "operating_cash_flow":baseline*.08}
                for metric in METRICS:
                    self.frows.append({"ticker":str(idx),"fiscal_year":fy,
                      "source_family":families[metric],"candidate_mops_metric":metric,
                      "status":"candidate_annual_value","candidate_annual_value":str(vals[metric]),
                      "source_sha256":SHAS,"training_admitted":"false",
                      "publication_asof_verified":"false","label_status":"UNREVIEWED",
                      "source_quarters_found":"4"})
        save(self.annual,FIELDNAMES,self.frows)
        self.srows=[]
        for fy in (2021,2022,2023,2024):
            for idx in range(1201,1209):
                self.srows.append({"ticker":str(idx),"fiscal_year":fy,
                                   "y":int(idx%2==0),"target":TARGET,
                                   "evidence_grade":"SILVER_SYNTHETIC",
                                   "exploratory_label_only":"true"})
        save(self.silver,("ticker","fiscal_year","y","target","evidence_grade",
                          "exploratory_label_only"),self.srows)
        self.prows=[]
        for cy in range(2016,2024):
            for idx in range(1201,1209):
                self.prows.append({"ticker":str(idx),"calendar_year":cy,
                    "y_tej_calendar_proxy":str(int(idx%2==0)),
                    "split":"train" if cy<=2020 else "validation" if cy<=2022 else "test",
                    "label_provenance":"TEJ_INFORMATION_TRANSPARENCY_PROXY_NOT_TT2",
                    "feature_asof_date":f"{cy-1}-12-31",
                    "max_safe_annual_financial_fy":str(cy-2),
                    "y_official_annual_24m":""})
        save(self.proxy,("ticker","calendar_year","y_tej_calendar_proxy","split",
                         "label_provenance","feature_asof_date",
                         "max_safe_annual_financial_fy","y_official_annual_24m"),self.prows)

    def test_tej_alignment_no_y_in_x(self):
        report=build(self.annual,self.proxy,"tej_proxy",self.dest,train=False)
        self.assertEqual(report["matched_feature_rows"],64)
        self.assertEqual(report["matched_class_counts"],{"positive":32,"negative":32})
        self.assertEqual(report["by_split"]["train"]["joined"],40)
        self.assertEqual(report["feature_nonmissing"]["roa"],64)
        self.assertTrue(report["label_outcome_fields_never_used_as_features"])
        rows=list(csv.DictReader((self.dest/"finlab_finmind_xy_private.csv").open(encoding="utf-8-sig")))
        first=next(x for x in rows if x["target_year"]=="2016")
        self.assertEqual(first["x_fiscal_year"],"2014")
        self.assertEqual(first["prior_x_fiscal_year"],"2013")
        self.assertNotIn("y_tej_calendar_proxy",rows[0])
        self.assertEqual(first["x_retrospective_only"],"true")
        self.assertFalse(report["all_x_publication_vintages_independently_verified"])

    def test_silver_training_and_unbalanced_holdout_reporting(self):
        report=build(self.annual,self.silver,"silver",self.dest,train=True)
        self.assertEqual(report["matched_feature_rows"],32)
        self.assertEqual(report["by_split"]["train"]["joined"],16)
        self.assertEqual(report["by_split"]["validation"]["joined"],8)
        self.assertEqual(report["by_split"]["test"]["joined"],8)
        self.assertEqual(report["by_target_year"]["2022"]["positive"],4)
        self.assertEqual(report["period_rule"],"affected FY(t) uses FinMind FY(t-1) and FY(t-2)")
        self.assertIn(report["training"]["status"],
            ("FITTED_RETROSPECTIVE_RESEARCH_ONLY","DEPENDENCY_NOT_INSTALLED"))
        if report["training"]["status"]=="FITTED_RETROSPECTIVE_RESEARCH_ONLY":
            self.assertTrue(any(m["model"]=="dummy" and m["status"]=="FITTED"
                                for m in report["training"]["models"]))
            self.assertIsNotNone(report["training"]["models"][0]["test"]["pr_auc_average_precision"])

    def test_duplicate_y_and_future_X_are_rejected_or_not_present(self):
        save(self.silver,("ticker","fiscal_year","y","target","evidence_grade",
                          "exploratory_label_only"),self.srows+[self.srows[0]])
        with self.assertRaisesRegex(ValueError,"DUPLICATE_OR_CONFLICTING_Y_LABEL"):
            labels(self.silver,"silver")
        cur={"net_income":10,"total_assets":100,"operating_cash_flow":5}
        self.assertEqual(x_metrics(cur,{})["revenue_growth"],"")
        self.assertEqual(x_metrics(cur,{})["roa"],"0.1")

    def test_holdout_and_y1_proxy_contamination(self):
        self.prows[0]["y_official_annual_24m"]="1"
        save(self.proxy,("ticker","calendar_year","y_tej_calendar_proxy","split",
                         "label_provenance","feature_asof_date",
                         "max_safe_annual_financial_fy","y_official_annual_24m"),self.prows)
        with self.assertRaisesRegex(ValueError,"PROXY_Y1_OR_ASOF_CONTAMINATION"):
            labels(self.proxy,"tej_proxy")
        self.prows[0]["y_official_annual_24m"]=""
        self.prows[0]["max_safe_annual_financial_fy"]="2015"
        save(self.proxy,("ticker","calendar_year","y_tej_calendar_proxy","split",
                         "label_provenance","feature_asof_date",
                         "max_safe_annual_financial_fy","y_official_annual_24m"),self.prows)
        with self.assertRaisesRegex(ValueError,"PROXY_Y1_OR_ASOF_CONTAMINATION"):
            labels(self.proxy,"tej_proxy")

    def test_finmind_wrong_hash_and_provenance_rejected(self):
        self.frows[0]["source_sha256"]="wrong"
        save(self.annual,FIELDNAMES,self.frows)
        with self.assertRaisesRegex(ValueError,"FINMIND_VALUE_OR_HASH_INVALID"):
            finmind_panel(self.annual)
        self.frows[0]["source_sha256"]=SHAS
        self.frows[0]["publication_asof_verified"]="true"
        save(self.annual,FIELDNAMES,self.frows)
        with self.assertRaisesRegex(ValueError,"FINMIND_UNEXPECTED_SOURCE_ADMISSION"):
            finmind_panel(self.annual)

    def test_review_template_never_fabricates_negative(self):
        save(self.review,
             ("ticker","fiscal_year","case_id","rank","mops_notice_url","original_financial_filing_url"),
             [{"ticker":"1201","fiscal_year":"2022","case_id":"case1","rank":"P0",
               "mops_notice_url":"","original_financial_filing_url":""},
              {"ticker":"1785","fiscal_year":"2015","case_id":"holdout","rank":"P0",
               "mops_notice_url":"","original_financial_filing_url":""}])
        report=make_review_template(self.review,self.dest)
        self.assertEqual(report["review_candidates"],1)
        contents=(self.dest/"finlab_human_review_private.csv").read_text(encoding="utf-8-sig")
        self.assertIn("UNKNOWN,pending",contents)
        self.assertNotIn("1785",contents)


    def test_multiple_finmind_csvs_are_reconciled_not_appended(self):
        copy=self.root/"second.csv"
        save(copy,FIELDNAMES,self.frows)
        table,src,conflicts=finmind_union([self.annual,copy])
        self.assertEqual(len(src),2)
        self.assertEqual(len(table),88)
        self.assertEqual(conflicts,{})
        report=build([self.annual,copy],self.proxy,"tej_proxy",self.dest,train=False)
        self.assertEqual(report["matched_feature_rows"],64)

    def test_archive_backed_mops_extends_join_without_fake_inventory(self):
        path=self.root/"mops.csv"
        cols=("ticker","financial_fy","period_end","sector_schema",
              "source_income_sha256","source_balance_sha256","source_cashflow_sha256",
              "revenue","cogs","operating_income","net_income","assets",
              "current_assets","current_liabilities","liabilities","cfo")
        mopsrows=[]
        for fy in range(2013,2022):
            for ticker in ("1211","1212"):
                mopsrows.append(dict(zip(cols,(ticker,str(fy),f"{fy}-12-31",
                   "general_summary",SHAS,SHAS,SHAS,"200","120","25","12",
                   "500","200","100","250","10"))))
        save(path,cols,mopsrows)
        facts,src,skips=mops_panel(path)
        self.assertEqual(len(facts),18)
        self.assertEqual(skips,{})
        for fy in range(2016,2024):
            for ticker in ("1211","1212"):
                self.prows.append({
                    "ticker":ticker,"calendar_year":fy,
                    "y_tej_calendar_proxy":str(int(ticker=="1212")),
                    "split":"train" if fy<=2020 else "validation" if fy<=2022 else "test",
                    "label_provenance":"TEJ_INFORMATION_TRANSPARENCY_PROXY_NOT_TT2",
                    "feature_asof_date":f"{fy-1}-12-31",
                    "max_safe_annual_financial_fy":str(fy-2),
                    "y_official_annual_24m":""})
        save(self.proxy,("ticker","calendar_year","y_tej_calendar_proxy","split",
                         "label_provenance","feature_asof_date",
                         "max_safe_annual_financial_fy","y_official_annual_24m"),self.prows)
        r=build([self.annual],self.proxy,"tej_proxy",self.dest,
                train=False,mops_annual=path)
        self.assertEqual(r["matched_feature_rows"],80)
        self.assertEqual(r["matched_source_counts"]["public_mops_retrospective"],16)
        rows=list(csv.DictReader((self.dest/"finlab_finmind_xy_private.csv")
                                   .open(encoding="utf-8-sig")))
        x=next(x for x in rows if x["ticker"]=="1211" and x["target_year"]=="2016")
        self.assertEqual(x["x_fiscal_year"],"2014")
        self.assertEqual(x["source_x"],"public_mops_retrospective")
        self.assertEqual(x["roa"],"0.024")
        self.assertEqual(x["inventory_growth"],"")
        only=build(None,self.proxy,"tej_proxy",self.root/"mops_only",
                   train=False,mops_annual=path)
        self.assertEqual(only["matched_feature_rows"],16)
        self.assertEqual(only["matched_source_counts"]["public_mops_retrospective"],16)

    def test_mops_invalid_source_sha_not_accepted(self):
        path=self.root/"bad_mops.csv"
        cols=("ticker","financial_fy","period_end","sector_schema",
              "source_income_sha256","source_balance_sha256","source_cashflow_sha256",
              "revenue","cogs","operating_income","net_income","assets",
              "current_assets","current_liabilities","liabilities","cfo")
        row={x:"" for x in cols}
        row.update(ticker="2001",financial_fy="2020",
                   period_end="2020-12-31",sector_schema="general_summary",
                   revenue="3")
        save(path,cols,[row])
        with self.assertRaisesRegex(ValueError,"MOPS_FINANCIAL_FACT_WITHOUT_ARCHIVE_SHA"):
            mops_panel(path)

if __name__=="__main__":
    unittest.main()
