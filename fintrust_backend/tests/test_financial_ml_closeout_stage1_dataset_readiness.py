"""Closeout Stage1: synthetic-only regression for real-data matrix builder.

Test fixtures use nonactual financial amounts. No fabricated sources are
written into the user's true archived research folder or source cohorts.
"""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import closeout_stage1_dataset_readiness as m
from research.financial_ml.annual_panel_readiness import METRICS
from research.financial_ml.finmind_cross_industry_pilot import FIELDS as C_FIELDS
from research.financial_ml.literature_dataset import FEATURES
from research.financial_ml.phase4_taiwan_dataset_gate import SPLIT_COLUMNS
from research.financial_ml.phase14_multiissuer_quarterly_cohort import SOURCE_COLUMNS
from research.financial_ml.phase13_quarterly_temporal_features import OBS_FIELDS


def dump_csv(path, fields, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def load_csv(path):
    with path.open("r",encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f))


class Stage1DatasetIntegrityTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.out=self.root/"stage1"
        self.make_cohort()
        self.make_annual()
        self.make_paper()
        self.make_quarters()

    def make_cohort(self):
        self.cohort=self.root/"finmind_scaled_120"/"finmind_scaled_cohort.csv"
        rows=[]
        for i in range(120):
            ticker=str(2001+i)
            rows.append({"ticker":ticker,"company_name":f"FixtureCompany{i}",
                         "industry_category":f"FixtureIndustry{i%12}",
                         "market":"twse","source_snapshot_date":"2026-10-19",
                         "historical_eligibility":"UNVERIFIED",
                         "normal_label_status":"UNREVIEWED"})
        dump_csv(self.cohort,C_FIELDS,rows)
        self.firms=rows[:12]

    def make_annual(self):
        self.panel=self.root/"finmind_scaled_sequence_readiness"/"company_year_candidate_panel.csv"
        self.raw_annual=self.root/"finmind_scaled_annual_candidates"/"finmind_annual_candidate_lines.csv"
        rows=[];lines=[]
        for ticker in ("2001","2002"):
            for year in (2016,2017,2018,2019,2020,2021,2022,2023):
                missing=(ticker=="2002" and year==2018)
                values={key:(str(20+year%3) if not(missing and key==METRICS[-1]) else "")
                        for key in METRICS}
                rows.append({
                    "ticker":ticker,"fiscal_year":year,
                    "complete_12_candidate_metrics":str(not missing),
                    "training_admitted":"false","original_asof_verified":"false",
                    **values
                })
                for metric,value in values.items():
                    lines.append({
                        "ticker":ticker,"fiscal_year":year,
                        "candidate_mops_metric":metric,"candidate_annual_value":value,
                        "source_sha256":"a"*64 if value else "",
                        "status":"candidate_annual_value" if value else "missing_december_value",
                        "training_admitted":"false",
                        "publication_asof_verified":"false",
                        "label_status":"UNREVIEWED"
                    })
        self.panel_rows=rows
        self.line_rows=lines
        self.panel_cols=("ticker","fiscal_year","complete_12_candidate_metrics",
                         "training_admitted","original_asof_verified",*METRICS)
        self.line_cols=("ticker","fiscal_year","candidate_mops_metric","candidate_annual_value",
                        "source_sha256","status","training_admitted",
                        "publication_asof_verified","label_status")
        dump_csv(self.panel,self.panel_cols,rows)
        dump_csv(self.raw_annual,self.line_cols,lines)

    def make_paper(self):
        root=self.root/"phase4_taiwan_research_dataset"
        self.paper=root/"taiwan_research_split_register.csv"
        self.report4=root/"phase4_dataset_integrated_report.json"
        rows=[]
        for ticker,year,tier,completeness in (
                ("2001",2017,"FINMIND_PROVISIONAL",6),
                ("2002",2018,"MOPS_OFFICIAL_RETROSPECTIVE",15)):
            group=m.issuer_partition(ticker)
            time=m.annual_temporal(year)
            features={k:("1.125" if i<completeness else "")
                      for i,k in enumerate(FEATURES)}
            row={key:"" for key in SPLIT_COLUMNS}
            row.update({
                "ticker":ticker,"fiscal_year":year,
                "evidence_tier":tier,"issuer_split":group,
                "temporal_split":time,"joint_strict_split":m.joint_split(group,time),
                "development_event_candidate":"false",
                "full_15_features":str(completeness==15).lower(),
                "available_feature_count":str(completeness),
                "source_raw_sha256":"b"*64 if tier.startswith("MOPS") else "",
                "dataset_sha256":"c"*64,
                "first_filing_publication_verified":"false",
                "original_vintage_verified":"false",
                "outcome_label":"UNKNOWN",
                "approved_supervised_training":"false",
                "approved_supervised_validation":"false",
                "approved_supervised_test":"false",
                "feature_vector_json":json.dumps(features),
            })
            rows.append(row)
        self.paper_rows=rows
        dump_csv(self.paper,SPLIT_COLUMNS,rows)
        self.report4.write_text(json.dumps({
            "final_holdout_excluded":True,"labels_approved_positive":0,
            "labels_approved_negative":0,"source_tiers_not_fused":True,
            "eligible_for_supervised_financial_fraud_training":False
        }),encoding="utf-8")

    def make_quarters(self):
        self.phase14=self.root/"phase14_multiissuer_quarterly_comparison"
        self.phase14.mkdir(parents=True)
        self.qsources=self.phase14/"multiissuer_official_quarter_sources.csv"
        self.qobservations=self.phase14/"multiissuer_quarter_twd_observations.csv"
        sources=[];obs=[];manifest={}
        for firm in self.firms:
            ticker=firm["ticker"]
            for period in m.FROZEN_PERIODS:
                payload=f"fixture-mops-original-not-certified:{ticker}:{period}".encode()
                h=hashlib.sha256(payload).hexdigest()
                path=f"{ticker}/{period}/{h}.xml"
                raw=self.phase14/"raw"/path
                raw.parent.mkdir(parents=True,exist_ok=True)
                raw.write_bytes(payload)
                row={k:"" for k in SOURCE_COLUMNS}
                row.update({
                    "ticker":ticker,
                    "industry_category":firm["industry_category"],
                    "market":"twse","reporting_period":period,
                    "source_status":m.Q_VALID,"official_url":f"https://mopsov.twse.com.tw/{ticker}/{period}",
                    "raw_sha256":h,"archive_relative_path":path,
                    "original_filing_version_verified":"false",
                    "first_publication_verified":"false",
                    "outcome_label":"UNKNOWN","normal_label_approved":"false",
                    "training_admitted":"false"
                })
                sources.append(row)
                manifest[f"{ticker}:{period}"]={
                    "ticker":ticker,"reporting_period":period,
                    "source_status":m.Q_VALID,
                    "raw_sha256":h
                }
                for concept,grain in (
                        ("Assets","instant"),("Revenue","quarter_duration"),
                        ("OnlyAvailableInTestPeriod","instant")):
                    if concept=="OnlyAvailableInTestPeriod" and period<"2019Q4":
                        continue
                    if concept=="OnlyAvailableInTestPeriod" and ticker!="2001":
                        continue
                    obj={k:"" for k in OBS_FIELDS}
                    obj.update({
                        "ticker":ticker,"reporting_period":period,
                        "concept_key":"http://example.com/ifrs-full|"+concept,
                        "source_local_name":concept,"source_namespace":"http://example.com/ifrs-full",
                        "period_grain":grain,"source_unit":"TWD",
                        "value_decimal":"100","source_sha256":h,
                        "reconciliation_status":"CANDIDATE_CONSISTENT_REPETITIONS",
                        "source_original_vintage_verified":"false",
                        "candidate_mapping_approved":"false",
                        "outcome_label":"UNKNOWN","model_training_admitted":"false",
                    })
                    obs.append(obj)
        dump_csv(self.qsources,SOURCE_COLUMNS,sources)
        dump_csv(self.qobservations,OBS_FIELDS,obs)
        self.quarter_sources=sources
        self.quarter_observations=obs
        plan={
            "selected_company_metadata":[{
                "ticker":x["ticker"],"industry_category":x["industry_category"],
                "market":"twse"} for x in self.firms
            ],"source_cohort_sha256":m.digest(self.cohort)
        }
        (self.phase14/"frozen_phase14_plan.json").write_text(json.dumps(plan),encoding="utf-8")
        self.manifest=self.phase14/"quarterly_acquisition_results.json"
        self.manifest.write_text(json.dumps({
            "outcomes":manifest,"holdout_1785":True,
            "positive_labels":0,"negative_labels":0
        }),encoding="utf-8")
        self.quarter_report=self.phase14/"phase14_integrated_report.json"
        self.save_quarter_report()

    def save_quarter_report(self):
        self.quarter_report.write_text(json.dumps({
            "selected_issuers":12,"official_quarter_jobs":144,
            "verified_true_negative_company_quarters":0,
            "verified_false_filing_positive_company_quarters":0,
            "supervised_ml_rows_admitted":0,
            "final_holdout_1785_excluded":True,
            "source_cohort_SHA256":m.digest(self.cohort),
            "primary_source_assembly_SHA256":m.digest(self.manifest),
            "official_quarters_context_and_primary_TWD_validated":144
        }),encoding="utf-8")

    def run_stage(self):
        return m.make_report(self.root,self.out,max_features=6)

    def test_all_three_feature_matrix_views_and_true_row_sizes(self):
        report=self.run_stage()
        self.assertEqual(report["frozen_cohort_issuer_count"],120)
        self.assertEqual(report["annual_provisional_company_years"],16)
        self.assertEqual(report["annual_12_metric_complete_company_years"],15)
        self.assertEqual(report["paper_feature_source_tier_rows"],2)
        self.assertEqual(report["paper_full_15_candidate_company_year_rows_by_tier"][
                         "MOPS_OFFICIAL_RETROSPECTIVE"],1)
        self.assertEqual(report["quarterly"]["source_quarters"],144)
        self.assertEqual(report["quarterly"]["official_validated_quarters"],144)
        self.assertEqual(report["quarterly"]["fit_only_feature_candidates"],2)
        self.assertEqual(report["model_ready_supervised_positive_labels"],0)
        self.assertEqual(report["model_ready_supervised_negative_labels"],0)
        self.assertEqual(report["model_ready_supervised_training_rows"],0)
        self.assertTrue(report["frozen_1785_holdout_preserved"])
        self.assertEqual(len(load_csv(self.out/"quarterly_sparse_feature_matrix.csv")),144)
        self.assertEqual(len(load_csv(self.out/"paper_15_source_tier_matrix.csv")),2)

    def test_no_source_value_imputed_as_zero(self):
        self.run_stage()
        annual=load_csv(self.out/"annual_12_provisional_metric_matrix.csv")
        missing=next(x for x in annual if x["ticker"]=="2002" and x["fiscal_year"]=="2018")
        self.assertEqual(missing[METRICS[-1]],"")
        self.assertEqual(missing["full_12_metric_observation"],"false")
        self.assertEqual(missing["financial_fraud_label"],"UNKNOWN")

    def test_three_and_five_year_numeric_history_not_fraud_samples(self):
        report=self.run_stage()
        self.assertGreater(report["three_year_history_numeric_forecast_opportunities"][
                           "total_complete_financial_numeric_forecast_windows"],0)
        self.assertEqual(report["three_year_history_numeric_forecast_opportunities"][
                         "approved_fraud_supervised_windows"],0)

    def test_time_and_issuer_joint_split_are_disjoint(self):
        self.run_stage()
        q=load_csv(self.out/"quarterly_sparse_feature_matrix.csv")
        by_group={"fit":set(),"validation":set(),"test":set()}
        for row in q:
            if row["strict_joint_split"] in by_group:
                by_group[row["strict_joint_split"]].add(row["ticker"])
        self.assertFalse(by_group["fit"]&by_group["test"])
        self.assertFalse(by_group["fit"]&by_group["validation"])
        self.assertTrue(all(row["training_admitted"]=="false" for row in q))

    def test_fit_only_feature_selection_cannot_see_test_only_taxonomy(self):
        self.run_stage()
        chosen=load_csv(self.out/"quarterly_fit_selected_feature_dictionary.csv")
        self.assertEqual(len(chosen),2)
        self.assertNotIn("OnlyAvailableInTestPeriod",
                         {x["source_local_name"] for x in chosen})
        self.assertTrue(all(x["feature_admitted_for_supervised_training"]=="false"
                            for x in chosen))

    def test_finmind_annual_source_value_swap_is_detected(self):
        rows=load_csv(self.raw_annual)
        rows[0]["candidate_annual_value"]="99999999"
        dump_csv(self.raw_annual,self.line_cols,rows)
        with self.assertRaisesRegex(ValueError,"annual_panel_source_value_mismatch"):
            self.run_stage()

    def test_known_fraud_label_cannot_be_sneaked_into_paper_register(self):
        rows=load_csv(self.paper)
        rows[0]["outcome_label"]="1"
        dump_csv(self.paper,SPLIT_COLUMNS,rows)
        with self.assertRaisesRegex(ValueError,"unreviewed_label_or_source_promoted"):
            self.run_stage()

    def test_source_quarter_sha_integrity_is_checked_on_disk(self):
        row=self.quarter_sources[0]
        file=self.phase14/"raw"/row["archive_relative_path"]
        file.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError,"quarter_raw_bytes_do_not_match_sha"):
            self.run_stage()

    def test_phase14_manifest_modified_after_acceptance_is_rejected(self):
        s=self.manifest.read_text(encoding="utf-8")
        self.manifest.write_text(s+" ",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"phase14_manifest_sha_changed"):
            self.run_stage()

    def test_quarter_source_missing_raw_sha_prohibited(self):
        rows=load_csv(self.qsources)
        rows[0]["raw_sha256"]=""
        dump_csv(self.qsources,SOURCE_COLUMNS,rows)
        with self.assertRaisesRegex(ValueError,"quarterly_manifest_source_index_disagreement|quarter_source_sha_missing"):
            self.run_stage()

    def test_quarter_fact_from_wrong_source_refused(self):
        rows=load_csv(self.qobservations)
        rows[0]["source_sha256"]="0"*64
        dump_csv(self.qobservations,OBS_FIELDS,rows)
        with self.assertRaisesRegex(ValueError,"financial_fact_source_sha_not_matching_quarter"):
            self.run_stage()

    def test_source_row_forged_healthy_label_refused(self):
        rows=load_csv(self.qsources)
        rows[0]["normal_label_approved"]="true"
        dump_csv(self.qsources,SOURCE_COLUMNS,rows)
        with self.assertRaisesRegex(ValueError,"unreviewed_label_or_source_promoted"):
            self.run_stage()

    def test_research_cohort_and_case_not_auto_negative(self):
        self.run_stage()
        self.assertTrue(all(x["financial_fraud_label"]=="UNKNOWN"
            for x in load_csv(self.out/"annual_12_provisional_metric_matrix.csv")))
        self.assertTrue(all(x["financial_fraud_label"]=="UNKNOWN"
            for x in load_csv(self.out/"paper_15_source_tier_matrix.csv")))
        self.assertTrue(all(x["outcome_label"]=="UNKNOWN"
            for x in load_csv(self.out/"quarterly_sparse_feature_matrix.csv")))


if __name__=="__main__":
    unittest.main()
