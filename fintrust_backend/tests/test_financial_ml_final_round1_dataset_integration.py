"""Finalization round1: source-verified, source-tier-disjoint dataset QA tests.

All data in this test are synthetic fixtures; no real issuer outcomes are
created. Real study acceptance runs offline on the user's existing archives.
"""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import final_round1_dataset_integration as m
from research.financial_ml.finmind_cross_industry_pilot import FIELDS as COHORT_FIELDS
from research.financial_ml.phase13_quarterly_temporal_features import OBS_FIELDS


def save(path,fields,rows):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader();w.writerows(rows)


def sha(bytes_data):
    return hashlib.sha256(bytes_data).hexdigest()


class Round1DataIntegrationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data=Path(tmp.name)/"financial_ml"
        self.data.mkdir()
        self.out=self.data/"final_round1"
        self.tickers=[str(4000+x) for x in range(120)]
        self.cohort=[
            {"ticker":t,"company_name":f"TEST-{t}",
             "industry_category":"半導體業" if i<24 else "其他研究產業",
             "market":"twse","source_snapshot_date":"2026-10-19",
             "historical_eligibility":"UNVERIFIED",
             "normal_label_status":"UNREVIEWED"} for i,t in enumerate(self.tickers)]
        save(self.data/"finmind_scaled_120"/"finmind_scaled_cohort.csv",
             COHORT_FIELDS,self.cohort)

    def make_annual(self):
        panel=[]; staged=[]
        for t in self.tickers:
            for y in range(2013,2026):
                row={"ticker":t,"fiscal_year":y,"candidate_observed":12,
                     "candidate_total":12,"complete_12_candidate_metrics":"True",
                     "training_admitted":"false","original_asof_verified":"false",
                     **{f:"1" for f in m.METRICS}}
                panel.append(row)
                for f in m.METRICS:
                    staged.append({
                        "ticker":t,"fiscal_year":y,"source_family":"balance",
                        "candidate_mops_metric":f,"candidate_annual_value":"1",
                        "source_sha256":"a"*64,
                        "status":"candidate_annual_value",
                        "training_admitted":"false",
                        "publication_asof_verified":"false",
                        "label_status":"UNREVIEWED",
                    })
        self.annual_panel=self.data/"finmind_scaled_sequence_readiness"/"company_year_candidate_panel.csv"
        save(self.annual_panel,
             ("ticker","fiscal_year","candidate_observed","candidate_total",
              "complete_12_candidate_metrics","training_admitted",
              "original_asof_verified",*m.METRICS),panel)
        self.staged=self.data/"finmind_scaled_annual_candidates"/"finmind_annual_candidate_lines.csv"
        save(self.staged,
             ("ticker","fiscal_year","source_family","candidate_mops_metric",
              "candidate_annual_value","source_sha256","status",
              "training_admitted","publication_asof_verified","label_status"),staged)

    def make_paper(self):
        base=self.data/"phase3_literature_integrated"
        provider=base/"finmind_provisional_paper_component_values.csv"
        official=base/"mops_official_15_features"/"literature_15_features.csv"
        cols=("ticker","fiscal_year",*m.FEATURES)
        save(provider,cols,[{"ticker":"4000","fiscal_year":2014,
                             **{x:"1.25" for x in m.FEATURES}}])
        save(official,cols,[{"ticker":"5001","fiscal_year":2014,
                             **{x:"2.25" for x in m.FEATURES}}])
        register=[]
        for tier,t,val in [("FINMIND_PROVISIONAL","4000","1.25"),
                           ("MOPS_OFFICIAL_RETROSPECTIVE","5001","2.25")]:
            group=m.issuer_partition(t)
            time=m.temporal_partition(2014)
            row={name:"" for name in m.SPLIT_COLUMNS}
            row.update(
                ticker=t,fiscal_year="2014",evidence_tier=tier,
                issuer_split=group,temporal_split=time,
                joint_strict_split=group if group==time else "outside_joint_evaluation",
                development_event_candidate="false",
                full_15_features="true",available_feature_count="15",
                source_raw_sha256="d"*64 if tier=="MOPS_OFFICIAL_RETROSPECTIVE" else "",
                dataset_sha256=m.digest(official if tier=="MOPS_OFFICIAL_RETROSPECTIVE" else provider),
                first_filing_publication_verified="false",original_vintage_verified="false",
                outcome_label="UNKNOWN",outcome_known_at_verified="false",
                negative_control_reviewed="false",
                approved_supervised_training="false",
                approved_supervised_validation="false",
                approved_supervised_test="false",
                feature_vector_json=json.dumps({x:val for x in m.FEATURES}),
            )
            register.append(row)
        self.paper_register=self.data/"phase4_taiwan_research_dataset"/"taiwan_research_split_register.csv"
        save(self.paper_register,m.SPLIT_COLUMNS,register)
        phase4={
            "cohort_issuer_count":120,"source_tiers_not_fused":True,
            "eligible_for_supervised_financial_fraud_training":False,
            "labels_approved_positive":0,"labels_approved_negative":0,
            "final_holdout_excluded":True,"evidence_rows":2,
            "source_hashes":{
                "cohort":m.digest(self.data/"finmind_scaled_120"/"finmind_scaled_cohort.csv"),
                "provider_candidate":m.digest(provider),
                "official_retrospective":m.digest(official),
            }
        }
        self.phase4_file=self.data/"phase4_taiwan_research_dataset"/"phase4_dataset_integrated_report.json"
        self.phase4_file.write_text(json.dumps(phase4),encoding="utf-8")

    def archive(self,root,ticker,period,bytes_data):
        h=sha(bytes_data)
        relative=f"{ticker}/{period}/{h}.xhtml"
        path=root/"raw"/relative
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(bytes_data)
        return h,relative

    def make_quarters(self):
        root=self.data/"phase14_multiissuer_quarterly_comparison"
        official=[]; manifest={};observations=[]
        for t in self.tickers[:12]:
            for period in m.FROZEN_PERIODS:
                data=f"synthetic financial contents {t} {period}".encode()
                h,rel=self.archive(root,t,period,data)
                source={name:"" for name in m.SOURCE_COLUMNS}
                source.update(
                    ticker=t,reporting_period=period,
                    source_status=m.VALID,raw_sha256=h,
                    archive_relative_path=rel,
                    official_url=f"https://mopsov.twse.com.tw/mops/web/placeholder?co_id={t}",
                    original_filing_version_verified="false",
                    first_publication_verified="false",
                    normal_label_approved="false",training_admitted="false",
                    outcome_label="UNKNOWN")
                official.append(source)
                manifest[f"{t}:{period}"]={
                    "ticker":t,"reporting_period":period,
                    "source_status":m.VALID,"raw_sha256":h,"raw_path":rel,
                    "outcome_label":"UNKNOWN","normal_label_approved":False,
                    "original_asof_verified":False}
                observations.append(self.obs(t,period,h))
        save(root/"multiissuer_official_quarter_sources.csv",
             m.SOURCE_COLUMNS,official)
        (root/"quarterly_acquisition_results.json").write_text(
            json.dumps({"outcomes":manifest}),encoding="utf-8")
        (root/"phase14_integrated_report.json").write_text(json.dumps({
            "final_holdout_1785_excluded":True,
            "verified_true_negative_company_quarters":0,
            "verified_false_filing_positive_company_quarters":0,
            "supervised_ml_rows_admitted":0,
            "official_quarters_context_and_primary_TWD_validated":144,
        }),encoding="utf-8")
        save(root/"multiissuer_quarter_twd_observations.csv",
             OBS_FIELDS,observations)

        croot=self.data/"phase12_kangyou_quarterly_panel"
        case=[];cases={};casesobs=[]
        priorroot=(self.data/"phase11_case_quarterly_and_paper_gaps"/
                   "official_quarterly_source")
        for period in m.FROZEN_PERIODS:
            parent=priorroot if period=="2020Q1" else croot
            h,rel=self.archive(parent,"6452",period,
                f"synthetic case evidence 6452 {period}".encode())
            meta={
                "ticker":"6452","reporting_period":period,
                "source_status":"QUARTER_CONTEXT_VALIDATED_VINTAGE_UNKNOWN",
                "raw_sha256":h,"historical_first_publication_verified":"false",
                "historical_first_original_version_verified":"false",
                "independently_verified_fraud_outcome":"UNKNOWN",
                "admitted_for_model_training":"false",
            }
            case.append({**{x:"" for x in m.KANGYOU_SOURCE_COLUMNS},**meta})
            casesobs.append(self.obs("6452",period,h))
            if period=="2020Q1":
                prior={"reporting_period":period,"raw_path":rel,"raw_sha256":h}
            else:
                cases[period]={"raw_path":rel,"raw_sha256":h}
        save(croot/"quarterly_case_official_source_index.csv",
             m.KANGYOU_SOURCE_COLUMNS,case)
        (croot/"quarterly_acquisition_results.json").write_text(
            json.dumps({"outcomes":cases}),encoding="utf-8")
        (croot/"phase12_integrated_report.json").write_text(json.dumps({
            "issuer":"6452","candidate_quarters":12,
            "official_quarters_context_scope_validated":12,
            "confirmed_period_outcome_labels":0,
            "historical_original_filing_vintages_verified":0,
            "final_holdout_1785_excluded":True
        }),encoding="utf-8")
        priorhome=self.data/"phase11_case_quarterly_and_paper_gaps"
        (priorhome/"phase11_integrated_report.json").write_text(json.dumps({
            "quarterly_source_status":prior
        }),encoding="utf-8")
        save(self.data/"phase13_kangyou_quarterly_temporal_features"/
             "quarterly_twd_source_observations.csv",OBS_FIELDS,casesobs)

    def obs(self,ticker,period,hash_value):
        return {**{key:"" for key in OBS_FIELDS},
            "ticker":ticker,"reporting_period":period,
            "concept_key":"http://example.com/ifrs|Assets",
            "source_namespace":"http://example.com/ifrs",
            "source_local_name":"Assets","period_grain":"instant",
            "source_unit":"TWD","value_decimal":"100",
            "source_sha256":hash_value,
            "reconciliation_status":"CANDIDATE_CONSISTENT_REPETITIONS"}

    def make_all(self):
        self.make_annual();self.make_paper();self.make_quarters()

    def test_full_synthetic_source_linkage_yields_real_unit_counts_not_fake_labels(self):
        self.make_all()
        report=m.run(self.data,self.out)
        self.assertEqual(report["annual_12_amount_candidate_company_years"],1560)
        self.assertEqual(report["annual_12_amount_full_12_company_years"],1560)
        self.assertEqual(report["annual_paper_15_source_tier_rows"],2)
        self.assertEqual(report["quarter_issuer_period_source_rows"],156)
        self.assertEqual(report["quarter_research_issuer_count"],13)
        self.assertEqual(report["quarter_comparison_source_period_validated"],144)
        self.assertEqual(report["quarter_known_case_source_period_validated"],12)
        self.assertEqual(report["quarter_exact_concepts_present_all_12_quarters_comparison"],12)
        self.assertEqual(report["quarter_exact_concepts_present_all_12_quarters_case"],1)
        self.assertEqual(report["approved_negative_labels"],0)
        self.assertEqual(report["fraud_supervised_training_rows_admitted"],0)
        self.assertTrue(report["annual_source_tiers_never_silently_fused"])
        self.assertTrue(report["last_event_holdout_1785_excluded"])

    def test_annual_numeric_window_count_is_company_year_not_account_line(self):
        self.make_annual()
        _,idx,_=m.read_annual_amounts(self.data,set(self.tickers))
        rows=m.annual_window_register(idx)
        self.assertEqual(sum(r["lookback_years"]==3 for r in rows),120*10)
        self.assertEqual(sum(r["lookback_years"]==5 for r in rows),120*8)
        self.assertEqual(sum(r["all_12_amounts_present"]=="true" for r in rows),2160)
        self.assertTrue(all(r["approved_for_supervised_training"]=="false" for r in rows))

    def test_tampered_single_annual_source_amount_fails_against_12_wide_panel(self):
        self.make_annual()
        _,idx,_=m.read_annual_amounts(self.data,set(self.tickers))
        rows=m.csv_rows(self.staged,
             ("ticker","fiscal_year","candidate_mops_metric","candidate_annual_value",
              "source_family","status","source_sha256","training_admitted",
              "publication_asof_verified","label_status"))
        rows[0]["candidate_annual_value"]="200"
        save(self.staged,list(rows[0]),rows)
        with self.assertRaisesRegex(ValueError,"annual_12_panel_does_not_match"):
            m.verify_annual_source_stage(self.data,idx)

    def test_tampered_register_features_fail_vs_original_sha_frozen_paper(self):
        self.make_paper()
        rows=m.csv_rows(self.paper_register,m.SPLIT_COLUMNS)
        row=rows[0]
        vec=json.loads(row["feature_vector_json"])
        vec["b_GMI"]="999"
        row["feature_vector_json"]=json.dumps(vec)
        save(self.paper_register,m.SPLIT_COLUMNS,rows)
        phase4=json.loads(self.phase4_file.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError,"paper_15_feature_vector_differs"):
            m.read_paper_features(self.data,set(self.tickers),phase4)

    def test_no_forged_normal_label_from_quarter_comparison(self):
        self.make_quarters()
        p=self.data/"phase14_multiissuer_quarterly_comparison"/"multiissuer_official_quarter_sources.csv"
        rows=m.csv_rows(p,m.SOURCE_COLUMNS)
        rows[0]["normal_label_approved"]="true"
        save(p,m.SOURCE_COLUMNS,rows)
        with self.assertRaisesRegex(ValueError,"quarterly_false_normal_label"):
            m.read_official_quarterly_sources(self.data,set(self.tickers))

    def test_corrupt_SHA_content_is_not_silently_overwritten(self):
        self.make_quarters()
        root=self.data/"phase14_multiissuer_quarterly_comparison"
        manifest=json.loads((root/"quarterly_acquisition_results.json").read_text(encoding="utf-8"))
        row=next(iter(manifest["outcomes"].values()))
        (root/"raw"/row["raw_path"]).write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError,"archive_sha256_mismatch"):
            m.read_official_quarterly_sources(self.data,set(self.tickers))

    def test_1785_holdout_rejected_not_train_or_comparison(self):
        self.make_annual()
        with self.assertRaisesRegex(ValueError,"reserved_1785"):
            m.safe_ticker("1785")
        with self.assertRaisesRegex(ValueError,"reserved_1785"):
            m.safe_ticker("345")
        panel=m.csv_rows(self.annual_panel,
            ("ticker","fiscal_year","candidate_observed",*m.METRICS))
        panel[0]["ticker"]="1785"
        save(self.annual_panel,list(panel[0]),panel)
        with self.assertRaisesRegex(ValueError,"reserved_1785"):
            m.read_annual_amounts(self.data,set(self.tickers))

    def test_annual_paper_source_hash_file_swap_fails_closed(self):
        self.make_paper()
        path=self.data/"phase3_literature_integrated"/"finmind_provisional_paper_component_values.csv"
        with path.open("a",encoding="utf-8") as f:
            f.write("\n")
        phase4=json.loads(self.phase4_file.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError,"source_hash_changed"):
            m.read_paper_features(self.data,set(self.tickers),phase4)

    def test_source_path_escape_and_missing_archive_are_blocked(self):
        path=self.data/"root"
        path.mkdir()
        with self.assertRaisesRegex(ValueError,"source_path_escape"):
            m.verify_bytes(path,"../outside",sha(b"outside"))
        with self.assertRaisesRegex(ValueError,"source_path_escape"):
            m.verify_bytes(path,"missing",sha(b"missing"))


if __name__=="__main__":
    unittest.main()
