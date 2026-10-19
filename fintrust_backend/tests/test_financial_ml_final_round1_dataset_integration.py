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
                             **{x:("1.25" if x!="d_issue" else "")
                                for x in m.FEATURES}}])
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
                full_15_features="false" if tier=="FINMIND_PROVISIONAL" else "true",
                available_feature_count="14" if tier=="FINMIND_PROVISIONAL" else "15",
                source_raw_sha256="d"*64 if tier=="MOPS_OFFICIAL_RETROSPECTIVE" else "",
                dataset_sha256=m.digest(official if tier=="MOPS_OFFICIAL_RETROSPECTIVE" else provider),
                first_filing_publication_verified="false",original_vintage_verified="false",
                outcome_label="UNKNOWN",outcome_known_at_verified="false",
                negative_control_reviewed="false",
                approved_supervised_training="false",
                approved_supervised_validation="false",
                approved_supervised_test="false",
                feature_vector_json=json.dumps({
                    x:(val if tier!="FINMIND_PROVISIONAL" or x!="d_issue" else "")
                    for x in m.FEATURES}),
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

    def make_case_paper(self):
        folder=self.data/"phase10_case_official_paper_audit"
        path=folder/"phase10_case_official_paper_features.csv"
        self.case_paper_file=path
        rows=[];outcomes={}
        yearset=[("3027",year) for year in range(2013,2017)]+[
            ("8299",year) for year in range(2012,2015)]+[
            ("6452",year) for year in range(2015,2021)]
        self.assertEqual(len(yearset),13)
        for t,y in yearset:
            good=(t,y) not in (("8299",2012),("6452",2020))
            status=("validated" if good else
                "LEGACY_ORIGINAL_PDF_REQUIRES_SEPARATE_SOURCE"
                if y==2012 else "filing_not_found")
            hash_value=sha(f"case official {t}/{y}".encode()) if good else ""
            vector={f:("1.5" if i<15 and good else "")
                    for i,f in enumerate(m.FEATURES)}
            if good and (t,y)!=("3027",2013):
                vector["d_issue"]=""
            count=sum(bool(v) for v in vector.values())
            row={key:"" for key in m.CASE_PAPER_ORIGINAL_COLUMNS}
            row.update(ticker=t,fiscal_year=y,official_xbrl_status=status,
                       source_sha256=hash_value,
                       official_statement_scope="consolidated" if good else "",
                       components_computed=count,
                       original_filing_vintage_verified="false",
                       historical_filing_publication_at_verified="false",
                       original_notice_publication_at_verified="false",
                       outcome_label="UNKNOWN",approved_positive_label="false",
                       approved_negative_label="false",
                       admitted_for_supervised_learning="false",
                       feature_values_json=json.dumps(vector))
            rows.append(row)
            if y>=2013:
                outcomes[f"{t}:{y}"]={
                    "ticker":t,"fiscal_year":y,
                    "status":status,"content_hash":hash_value}
        save(path,m.CASE_PAPER_ORIGINAL_COLUMNS,rows)
        (folder/"phase10_integrated_report.json").write_text(json.dumps({
            "source_issuer_year_rows":13,
            "original_pre_correction_versions_verified":0,
            "verified_positive_labels":0,"verified_negative_labels":0,
            "historical_asof_training_rows_admitted":0,
            "final_holdout_1785_excluded":True,
            "official_archived_xbrl_years":11,
        }),encoding="utf-8")
        manifest=self.data/"phase9_case_mops_xbrl_candidates"/"acquisition_results.json"
        manifest.parent.mkdir(parents=True,exist_ok=True)
        manifest.write_text(json.dumps({"outcomes":outcomes}),encoding="utf-8")

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
        self.make_annual();self.make_paper()
        self.make_case_paper();self.make_quarters()

    def test_full_synthetic_source_linkage_yields_real_unit_counts_not_fake_labels(self):
        self.make_all()
        report=m.run(self.data,self.out)
        self.assertEqual(report["annual_12_amount_candidate_company_years"],1560)
        self.assertEqual(report["annual_12_amount_full_12_company_years"],1560)
        self.assertEqual(report["annual_paper_15_source_tier_rows"],2)
        self.assertEqual(report["development_case_annual_source_years_separate_from_noncase_fit"],13)
        self.assertEqual(report["development_case_annual_official_XBRL_source_years"],11)
        self.assertEqual(report["development_case_full_15_retrospective_years"],1)
        self.assertEqual(report["quarter_issuer_period_source_rows"],156)
        self.assertEqual(report["quarter_research_issuer_count"],13)
        self.assertEqual(report["quarter_sparse_comparison_company_quarters"],144)
        self.assertEqual(report["quarter_fit_only_selected_exact_concept_grain_features"],1)
        self.assertEqual(len(m.csv_rows(self.out/"quarterly_sparse_feature_matrix.csv",
                                           m.QUARTER_MATRIX_BASE)),144)
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

    def test_case_paper_source_sha_tampering_never_promotes_positive(self):
        self.make_case_paper()
        rows=m.csv_rows(self.case_paper_file,m.CASE_PAPER_ORIGINAL_COLUMNS)
        row=next(r for r in rows if r["official_xbrl_status"]=="validated")
        row["source_sha256"]="0"*64
        save(self.case_paper_file,m.CASE_PAPER_ORIGINAL_COLUMNS,rows)
        with self.assertRaisesRegex(ValueError,"case_paper_official_sha"):
            m.read_case_paper_features(self.data)

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

    def test_unverified_issue_from_finmind_is_never_fabricated(self):
        self.make_paper()
        src=self.data/"phase3_literature_integrated"/"finmind_provisional_paper_component_values.csv"
        rows=m.csv_rows(src,("ticker","fiscal_year",*m.FEATURES))
        rows[0]["d_issue"]="1"
        save(src,("ticker","fiscal_year",*m.FEATURES),rows)
        p=json.loads(self.phase4_file.read_text(encoding="utf-8"))
        p["source_hashes"]["provider_candidate"]=m.digest(src)
        register=m.csv_rows(self.paper_register,m.SPLIT_COLUMNS)
        r=next(x for x in register if x["evidence_tier"]=="FINMIND_PROVISIONAL")
        r["dataset_sha256"]=m.digest(src)
        v=json.loads(r["feature_vector_json"])
        v["d_issue"]="1"
        r["feature_vector_json"]=json.dumps(v)
        r["available_feature_count"]="15"
        r["full_15_features"]="true"
        save(self.paper_register,m.SPLIT_COLUMNS,register)
        with self.assertRaisesRegex(ValueError,"unverified_FinMind_d_issue"):
            m.read_paper_features(self.data,set(self.tickers),p)

    def test_annual_paper_source_hash_file_swap_fails_closed(self):
        self.make_paper()
        path=self.data/"phase3_literature_integrated"/"finmind_provisional_paper_component_values.csv"
        with path.open("a",encoding="utf-8") as f:
            f.write("\n")
        phase4=json.loads(self.phase4_file.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError,"source_hash_changed"):
            m.read_paper_features(self.data,set(self.tickers),phase4)

    def test_missing_source_value_does_not_turn_into_financial_zero(self):
        self.make_annual()
        panel=m.csv_rows(self.annual_panel,("ticker","fiscal_year",*m.METRICS))
        panel[0]["net_income"]=""
        panel[0]["candidate_observed"]="11"
        panel[0]["complete_12_candidate_metrics"]="False"
        save(self.annual_panel,list(panel[0]),panel)
        staged=m.csv_rows(self.staged,(
            "ticker","fiscal_year","candidate_mops_metric","candidate_annual_value",
            "source_family","status","source_sha256","training_admitted",
            "publication_asof_verified","label_status"))
        changed=next(r for r in staged if r["ticker"]=="4000"
                     and r["fiscal_year"]=="2013"
                     and r["candidate_mops_metric"]=="net_income")
        changed["status"]="missing_income_quarter"
        changed["candidate_annual_value"]=""
        save(self.staged,list(staged[0]),staged)
        items,index,_=m.read_annual_amounts(self.data,set(self.tickers))
        m.verify_annual_source_stage(self.data,index)
        self.assertEqual(index[("4000",2013)]["net_income"],"")
        self.assertEqual(index[("4000",2013)]["complete_candidate_vector"],"false")
        self.assertEqual(index[("4000",2013)]["observed_feature_count"],11)

    def test_unavailable_official_quarter_is_not_a_normal_case_or_fabricated_sample(self):
        self.make_quarters()
        folder=self.data/"phase14_multiissuer_quarterly_comparison"
        p=folder/"multiissuer_official_quarter_sources.csv"
        rows=m.csv_rows(p,m.SOURCE_COLUMNS)
        previous=rows[0]
        sha_before=previous["raw_sha256"]
        previous["source_status"]="filing_not_found"
        previous["raw_sha256"]=""
        previous["archive_relative_path"]=""
        save(p,m.SOURCE_COLUMNS,rows)
        manifest=folder/"quarterly_acquisition_results.json"
        obj=json.loads(manifest.read_text(encoding="utf-8"))
        item=obj["outcomes"][previous["ticker"]+":"+previous["reporting_period"]]
        item["source_status"]="filing_not_found"
        item["raw_sha256"]=""
        item["raw_path"]=""
        manifest.write_text(json.dumps(obj),encoding="utf-8")
        report=folder/"phase14_integrated_report.json"
        j=json.loads(report.read_text(encoding="utf-8"))
        j["official_quarters_context_and_primary_TWD_validated"]=143
        report.write_text(json.dumps(j),encoding="utf-8")
        indexed,_,_=m.read_official_quarterly_sources(self.data,set(self.tickers))
        missing=[r for r in indexed if r["data_role"]==
                 "UNLABELED_MULTIISSUER_COMPARISON"
                 and r["financial_issuer_quarter_observation"]=="false"]
        self.assertEqual(len(missing),1)
        self.assertEqual(missing[0]["label_status"],"UNKNOWN")
        self.assertEqual(missing[0]["negative_label_approved"],"false")
        self.assertEqual(missing[0]["source_sha256"],"")
        self.assertTrue(sha_before)

    def test_nonstandard_period_same_concept_different_starts_are_allowed(self):
        self.make_all()
        # Original quarterly XBRL can carry several incomparable start dates
        # for other_duration. These should stay in source evidence, not model.
        p=self.data/"phase14_multiissuer_quarterly_comparison"/"multiissuer_quarter_twd_observations.csv"
        rows=m.csv_rows(p,OBS_FIELDS)
        for start in ("2017-02-01","2017-02-05"):
            r=dict(rows[0])
            r.update(concept_key="http://example.com/ifrs|OtherDuration",
                     source_local_name="OtherDuration",
                     source_period_start=start,period_grain="other_duration")
            rows.append(r)
        save(p,OBS_FIELDS,rows)
        report=m.run(self.data,self.out)
        self.assertEqual(report["quarter_sparse_comparison_company_quarters"],144)
        dictionary=m.csv_rows(self.out/"quarterly_fit_selected_feature_dictionary.csv",
                              m.QUARTER_FEATURE_DICTIONARY)
        self.assertTrue(all("OtherDuration" not in r["concept_key"] for r in dictionary))

    def test_quarter_fit_only_feature_dictionary_excludes_test_only_sources(self):
        self.make_all()
        p=self.data/"phase14_multiissuer_quarterly_comparison"/"multiissuer_quarter_twd_observations.csv"
        rows=m.csv_rows(p,OBS_FIELDS)
        fit_issuers=[ticker for ticker in self.tickers[:12]
                     if m.issuer_partition(ticker)=="fit"][:3]
        self.assertEqual(len(fit_issuers),3)
        for ticker in fit_issuers:
            original=next(r for r in rows if r["ticker"]==ticker
                          and r["reporting_period"]=="2019Q4")
            extra=dict(original)
            extra.update(concept_key="http://example.com/ifrs|TestOnly",
                         source_local_name="TestOnly")
            rows.append(extra)
        save(p,OBS_FIELDS,rows)
        m.run(self.data,self.out)
        dictionary=m.csv_rows(self.out/"quarterly_fit_selected_feature_dictionary.csv",
                              m.QUARTER_FEATURE_DICTIONARY)
        self.assertEqual([r["concept_key"] for r in dictionary],
                         ["http://example.com/ifrs|Assets"])
        matrix=m.csv_rows(self.out/"quarterly_sparse_feature_matrix.csv",m.QUARTER_MATRIX_BASE)
        self.assertTrue(all(r["training_admitted"]=="false"
                            and r["label_status"]=="UNKNOWN" for r in matrix))
        self.assertNotIn("6452",{r["ticker"] for r in matrix})

    def test_quarter_actual_numeric_zero_is_observed_not_missing(self):
        self.make_all()
        p=self.data/"phase14_multiissuer_quarterly_comparison"/"multiissuer_quarter_twd_observations.csv"
        rows=m.csv_rows(p,OBS_FIELDS)
        rows[0]["value_decimal"]="0"
        save(p,OBS_FIELDS,rows)
        m.run(self.data,self.out)
        matrix=m.csv_rows(self.out/"quarterly_sparse_feature_matrix.csv",m.QUARTER_MATRIX_BASE)
        item=next(r for r in matrix if r["ticker"]==rows[0]["ticker"]
                  and r["reporting_period"]==rows[0]["reporting_period"])
        self.assertEqual(item["qf_01"],"0")
        self.assertEqual(item["qf_01_observed"],"true")

    def test_quarter_exact_taxonomy_claim_mismatch_rejected(self):
        self.make_all()
        p=self.data/"phase14_multiissuer_quarterly_comparison"/"multiissuer_quarter_twd_observations.csv"
        rows=m.csv_rows(p,OBS_FIELDS)
        rows[0]["source_local_name"]="ForgedName"
        save(p,OBS_FIELDS,rows)
        with self.assertRaisesRegex(ValueError,"quarter_source_exact_concept_identity_changed"):
            m.run(self.data,self.out)

    def test_source_path_escape_and_missing_archive_are_blocked(self):
        path=self.data/"root"
        path.mkdir()
        with self.assertRaisesRegex(ValueError,"source_path_escape"):
            m.verify_bytes(path,"../outside",sha(b"outside"))
        with self.assertRaisesRegex(ValueError,"source_path_escape"):
            m.verify_bytes(path,"missing",sha(b"missing"))


if __name__=="__main__":
    unittest.main()
