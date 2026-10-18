"""Hermetic Phase 3 literature/account-source bridge tests."""
from __future__ import annotations
import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.services.financial_research.literature_inputs import MAPPING_INDEX, MAPPINGS
from research.financial_ml import phase3_literature_bridge as m
from research.financial_ml.finmind_bulk_stage import DATASETS, URL
from research.financial_ml.finmind_cross_industry_pilot import FIELDS


class Phase3LiteratureBridgeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.raw=self.root/"finmind_cross_industry_raw"
        self.ticker="2330"
        self.dataset=self.root/"finmind_scaled_120"/"finmind_scaled_cohort.csv"
        self.dataset.parent.mkdir(parents=True)
        with self.dataset.open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(dict(ticker=self.ticker,company_name="TSMC",
                industry_category="半導體業",market="twse",
                source_snapshot_date="2026-10-18",
                historical_eligibility="UNVERIFIED",normal_label_status="UNREVIEWED"))
        for dataset in DATASETS:
            self.write_archive(dataset,[])

    def write_archive(self,dataset,records):
        path=self.raw/self.ticker/(dataset+".json")
        path.parent.mkdir(parents=True,exist_ok=True)
        doc={"source":URL,"ticker":self.ticker,"dataset":dataset,
             "period":["2013-01-01","2025-12-31"],
             "period_semantics":"QUARTERLY_UNVERIFIED_ANNUAL_AGGREGATION",
             "original_filing_vintage":"UNKNOWN","records":records}
        path.write_text(json.dumps(doc),encoding="utf-8")
        return path

    def row(self,ds,typ,value,year=2015,month="12-31"):
        return dict(stock_id="2330",date=f"{year}-{month}",type=typ,value=value)

    def sources(self):
        return {family:m.family_archive(self.raw,"2330",family)
                for family in m.DATASET}

    def test_cogs_revenue_total_assets_aliases_are_unapproved_candidates(self):
        income=[]
        for i,quarter in enumerate(m.QUARTERS,1):
            income.extend([self.row(DATASETS[0],"Revenue",i*10,month=quarter),
                           self.row(DATASETS[0],"CostOfGoodsSold",i*5,month=quarter)])
        self.write_archive(DATASETS[0],income)
        self.write_archive(DATASETS[1],[self.row(DATASETS[1],"TotalAssets",100)])
        src=self.sources()
        for name,expected in (("sales","100"),("cogs","50"),
                              ("total_assets","100")):
            row=m.item_candidate("2330",2015,MAPPING_INDEX[name],src)
            self.assertEqual(row["candidate_annual_value"],expected)
            self.assertEqual(row["status"],"candidate_amount_only_unapproved")
            self.assertEqual(row["training_admitted"],"false")
            self.assertEqual(row["asof_publication_verified"],"false")

    def test_no_quarter_imputation_and_ratio_never_amount(self):
        self.write_archive(DATASETS[0],[
            self.row(DATASETS[0],"Revenue",10,month="03-31"),
            self.row(DATASETS[0],"Revenue",20,month="06-30"),
            self.row(DATASETS[0],"OperatingExpenses_per",0.4,month="12-31")])
        item=m.item_candidate("2330",2015,MAPPING_INDEX["sales"],self.sources())
        self.assertEqual(item["candidate_annual_value"],"")
        self.assertEqual(item["status"],"incomplete_income_quarters")

    def test_accounts_receivable_multiline_never_silently_a_single_item(self):
        self.write_archive(DATASETS[1],[
            self.row(DATASETS[1],"AccountsReceivableNet",150),
            self.row(DATASETS[1],"BillsReceivableNet",15)])
        entry=m.item_candidate("2330",2015,MAPPING_INDEX["receivables"],self.sources())
        self.assertEqual(entry["status"],"multiline_evidence_only_needs_method_review")
        self.assertEqual(entry["candidate_annual_value"],"")

    def test_missing_or_empty_archive_is_not_zero(self):
        entry=m.item_candidate("2330",2015,MAPPING_INDEX["sales"],self.sources())
        self.assertEqual(entry["status"],"provider_empty_response")
        self.assertEqual(entry["candidate_annual_value"],"")

    def test_mismatched_one_of_alias_values_never_pick_first(self):
        lines=[self.row(DATASETS[0],"OperatingRevenue",10,month="03-31"),
               self.row(DATASETS[0],"OperatingRevenue",20,month="06-30"),
               self.row(DATASETS[0],"OperatingRevenue",30,month="09-30"),
               self.row(DATASETS[0],"OperatingRevenue",40,month="12-31"),
               self.row(DATASETS[0],"Revenue",11,month="03-31"),
               self.row(DATASETS[0],"Revenue",20,month="06-30"),
               self.row(DATASETS[0],"Revenue",30,month="09-30"),
               self.row(DATASETS[0],"Revenue",40,month="12-31")]
        self.write_archive(DATASETS[0],lines)
        item=m.item_candidate("2330",2015,MAPPING_INDEX["sales"],self.sources())
        self.assertEqual(item["status"],"candidate_alias_values_conflict")
        self.assertEqual(item["candidate_annual_value"],"")

    def test_issue_not_imputed_and_t_minus_two_dependency_explicit(self):
        account_index={}
        for year in range(2013,2016):
            for metric in MAPPINGS:
                account_index[(year,metric.metric)]={
                    "status":"candidate_amount_only_unapproved"}
        result={row["feature"]:row for row in m.needed_features(2015,account_index)}
        self.assertEqual(len(result),15)
        self.assertEqual(result["d_issue"]["computed_value"],"")
        self.assertEqual(result["d_issue"]["model_label"],"UNKNOWN")
        self.assertIn("ISSUANCE_POSITIVE",result["d_issue"]["readiness"])
        self.assertEqual(result["d_ch_cs"]["readiness"],
                         "ALL_INPUTS_CANDIDATE_ONLY_NOT_OFFICIAL")
        earlier={x["feature"]:x for x in m.needed_features(2014,account_index)}
        self.assertIn("outside_source_range",earlier["d_ch_cs"]["candidate_requirements_missing"])

    def test_end_to_end_without_official_mops_data_never_returns_verified_15(self):
        reportdir=self.root/"phase12_integrated_verification"
        reportdir.mkdir()
        (reportdir/"phase12_gate_report.json").write_text(json.dumps({
            "phase2_raw":{"missing_archives":0,"quarantined_issuers":[],
                          "cohort_companies":1}}),encoding="utf-8")
        report=m.run(self.root,self.root/"result",start_year=2014,end_year=2015)
        self.assertEqual(report["company_years"],2)
        self.assertEqual(report["account_evidence_rows"],2*len(MAPPINGS))
        self.assertEqual(report["component_feasibility_rows"],30)
        self.assertEqual(report["finmind_training_15_feature_rows_admitted"],0)
        self.assertEqual(report["official_xbrl_feature_report"]["company_year_rows"],0)
        self.assertTrue((self.root/"result"/"finmind_15_feature_feasibility.csv").is_file())

    def test_conflicting_raw_archive_and_fake_prior_phase2_are_blocked(self):
        file=self.write_archive(DATASETS[0],[
            self.row(DATASETS[0],"Revenue",100),
            self.row(DATASETS[0],"Revenue",200)])
        with self.assertRaisesRegex(ValueError,"quarantined_source"):
            m.family_archive(self.raw,self.ticker,"income")
        reportdir=self.root/"phase12_integrated_verification"
        reportdir.mkdir()
        (reportdir/"phase12_gate_report.json").write_text(json.dumps({
            "phase2_raw":{"missing_archives":1,"quarantined_issuers":[],
                          "cohort_companies":1}}),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"incomplete_or_quarantined"):
            m.run(self.root,self.root/"result")


if __name__=="__main__":
    unittest.main()
