"""Round8 manual labels and fail-closed supervised classifier synthetic tests."""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import round8_human_supervised_classifier as study


def write(path,fields,rows):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)


class Round8Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.ev=self.root/"evidence";self.ev.mkdir()

    def fake_original_source(self):
        p=self.root/"annual_12_amount_candidate_index.csv"
        from research.financial_ml.round3_research_models import ANNUAL_COLUMNS
        rows=[]
        for ticker in ("2330","2317"):
            for yr in (2013,2014,2015):
                x={k:"1" for k in study.METRICS}
                rows.append({
                    "ticker":ticker,"fiscal_year":yr,
                    "complete_candidate_vector":"true",
                    "original_publication_verified":"false",
                    "original_filing_vintage_verified":"false",
                    "label_status":"UNKNOWN","training_admitted":"false",
                    **x})
        write(p,ANNUAL_COLUMNS,rows)
        return p

    def test_review_packet_never_labels_unreviewed_as_zero(self):
        p=self.fake_original_source()
        out=self.root/"review"
        m=study.prepare_labels(p,out)
        self.assertEqual(m["reviewable_full_numeric_candidate_years"],6)
        x=study.rows_from_csv(out/"round8_human_label_review_queue.csv",
                              study.REVIEW_FIELDS)
        self.assertEqual({y["proposed_outcome"] for y in x},{"UNKNOWN"})
        self.assertEqual(m["approved_training_records"],0)
        self.assertEqual(len(study.rows_from_csv(
            out/"round8_approved_original_supervised_panel_TEMPLATE.csv",
            study.PANEL_FIELDS)),0)

    def test_existing_cohort_fake_zero_is_blocked(self):
        p=self.fake_original_source()
        t=p.read_text(encoding="utf-8-sig").replace("UNKNOWN","0")
        p.write_text(t,encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"provisional_label_promotion_forbidden"):
            study.prepare_labels(p,self.root/"bad")

    def test_without_evidence_no_supervised_accuracy_or_f1(self):
        out=self.root/"blocked"
        result=study.run(self.root/"nonexistent.csv",self.ev,out)
        self.assertIsNone(result["real_supervised_f1"])
        self.assertIsNone(result["real_supervised_accuracy"])
        self.assertIsNone(result["selected_model"])
        self.assertFalse((out/"random_forest_officially_reviewed_experiment.joblib").exists())

    def test_never_train_on_blind_1785(self):
        row={x:"" for x in study.PANEL_FIELDS}
        row.update(ticker="1785",fiscal_year="2015",
                   label="1",sample_grain="issuer_fiscal_year")
        p=self.root/"panel.csv";write(p,study.PANEL_FIELDS,[row])
        with self.assertRaisesRegex(ValueError,"never_train_on_final_case_1785"):
            study.approved_rows(p,self.ev)

    def test_zero_does_not_mean_no_known_news(self):
        row={x:"" for x in study.PANEL_FIELDS}
        row.update(ticker="2330",fiscal_year="2015",label="0",
                   approval_status="DRAFT",sample_grain="issuer_fiscal_year")
        p=self.root/"panel.csv";write(p,study.PANEL_FIELDS,[row])
        approved,issues=study.approved_rows(p,self.ev)
        self.assertEqual(approved,[])
        self.assertEqual(issues,{"UNAPPROVED_OR_UNCERTIFIED":1})

    def evidence(self,name,first=None):
        f=self.ev/name
        f.write_bytes(first or (name+" independent synthetic audit content").encode())
        return name,study.sha(f)

    def row(self,ticker,year,label,idx):
        orig,osh=self.evidence(f"{ticker}_{year}.pdf",b"%PDF-1.4 synthetic research object not genuine financial data")
        timestamp,ths=self.evidence(f"{ticker}_{year}_first.txt")
        evidence,eh=self.evidence(f"{ticker}_{year}_audit.txt")
        features={k:str((10000+idx*13+i)*(-1 if (label==1 and i==4) else 1))
                  for i,k in enumerate(study.METRICS)}
        return {
            "ticker":ticker,"fiscal_year":year,"sample_grain":"issuer_fiscal_year",
            "label":str(label),"approval_status":"APPROVED",
            "reviewer_a":"Auditor A","reviewer_b":"Auditor B",
            "method_owner_approval":"APPROVED",
            "outcome_definition":(
                "REGULATOR_OR_COURT_CONFIRMED_MISSTATEMENT_AFFECTED_YEAR"
                if label else "OFFICIAL_FOLLOWUP_NO_IDENTIFIED_MISSTATEMENT"),
            "outcome_document_path":evidence,"outcome_document_sha256":eh,
            "outcome_publication_at":f"{year+2}-03-01T00:00:00+08:00",
            "negative_followup_end_at":f"{year+3}-01-02T00:00:00+08:00" if not label else "",
            "original_report_path":orig,"original_report_sha256":osh,
            "original_filing_publication_at":f"{year+1}-03-31T00:00:00+08:00",
            "first_publication_notice_path":timestamp,
            "first_publication_notice_sha256":ths,
            "original_vintage_verified":"true",
            "finance_double_review_status":"DOUBLE_REVIEWED_ORIGINAL_PDF",
            **features}

    def test_approve_positive_and_two_year_negative_documents(self):
        good=[self.row("3201",2017,1,0),
              self.row("3202",2017,0,1)]
        p=self.root/"approved.csv";write(p,study.PANEL_FIELDS,good)
        accepted,c=study.approved_rows(p,self.ev)
        self.assertEqual(len(accepted),2)
        self.assertEqual(c,{"APPROVED_POSITIVE":1,"APPROVED_NEGATIVE":1})

    def test_synthetic_research_models_predict_only_on_approved_split(self):
        records=[]
        groups=[
            ("fit",2017,5,10),
            ("validation",2021,2,2),
            ("test",2023,2,2),
        ]
        i=0
        for _,year,pos,neg in groups:
            for cls,count in ((1,pos),(0,neg)):
                for _ in range(count):
                    i+=1
                    records.append(self.row(str(4000+i),year,cls,i))
        p=self.root/"approved.csv";write(p,study.PANEL_FIELDS,records)
        samples,_=study.approved_rows(p,self.ev)
        outcome=study.study(samples,self.root/"trained")
        self.assertEqual(outcome["status"],
                         "ROUND8_SUPERVISED_APPROVED_ORIGINAL_LABELLED_EXPERIMENT")
        self.assertIn(outcome["selected_model"],["logistic_regression","random_forest"])
        self.assertTrue(outcome["issuer_disjoint_and_time_ordered"])
        self.assertTrue(0<=outcome["real_supervised_f1"]<=1)
        self.assertTrue(0<=outcome["real_supervised_pr_auc"]<=1)
        self.assertTrue(all(x["test_holdout"]["tp"]+x["test_holdout"]["tn"]+
                            x["test_holdout"]["fp"]+x["test_holdout"]["fn"]==4
                            for x in outcome["comparisons"]))
        self.assertTrue(outcome["final_holdout_1785_excluded"])

    def test_sample_without_enough_validated_positive_is_blocked(self):
        samples=[{"ticker":str(4000+i),"fiscal_year":2017,"label":0,
                  "features":[1000.] *12} for i in range(30)]
        report=study.study(samples,self.root/"not_ready")
        self.assertIsNone(report["real_supervised_f1"])
        self.assertIsNone(report["real_supervised_pr_auc"])
        self.assertEqual(report["status"],
                         "ROUND8_SUPERVISED_LABELS_PENDING_SUFFICIENT_APPROVAL")

    def test_cross_split_repeated_company_does_not_fit(self):
        samples=[]
        for y in (2018,2021,2023):
            for i in range(22):
                samples.append({"ticker":str(5000+i),"fiscal_year":y,
                                "label":i%2,"features":[i+1.]*12})
        result=study.study(samples,self.root/"overlap")
        self.assertFalse(result["issuer_disjoint_and_time_ordered"])
        self.assertIsNone(result["real_supervised_accuracy"])

    def test_local_original_api_reader_only_exposes_double_review(self):
        import sqlite3
        from app.services.financial_research.original_ai1_research_reader import get_1785_original_ai1
        path=self.root/"research_case.sqlite3"
        db=sqlite3.connect(path)
        db.execute("""CREATE TABLE original_1785_financial_facts(
            ticker TEXT,fiscal_year INTEGER,metric TEXT,value_twd TEXT,
            unit TEXT,filing_version_type TEXT,source_pdf_sha256 TEXT,
            pdf_page INTEGER,statement_scope TEXT,accounting_framework TEXT,
            review_status TEXT,original_first_publication_verified INTEGER,
            model_training_admitted INTEGER)""")
        db.execute("INSERT INTO original_1785_financial_facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            "1785",2015,"revenue","123000","TWD","original","a"*64,6,
            "consolidated","TIFRS","DOUBLE_REVIEWED_ORIGINAL_PDF",0,0))
        db.commit();db.close()
        result=get_1785_original_ai1(path)
        self.assertEqual(result["observed_original_pdf_amount_cells"],1)
        self.assertEqual(result["records"][0]["value_twd"],"123000")
        self.assertFalse(result["historical_original_publication_time_certified"])
        self.assertFalse(result["sample_admitted_to_fraud_training"])

    def test_1785_blind_scoring_requires_training_completion(self):
        modeldir=self.root/"not_trained";modeldir.mkdir()
        (modeldir/"round8_supervised_classification_report.json").write_text(
            '{"status":"ROUND8_SUPERVISED_LABELS_PENDING_SUFFICIENT_APPROVAL"}')
        with self.assertRaisesRegex(ValueError,"requires_approved_frozen_classifier"):
            study.score_reserved_1785(self.root/"not_ready.sqlite3",modeldir,
                                      self.root/"case_output")

    def test_complete_1785_original_stays_out_of_fit_but_scores(self):
        import sqlite3
        import numpy as np
        import joblib
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import RobustScaler
        from sklearn.pipeline import Pipeline
        data=self.root/"original_1785.sqlite3"
        con=sqlite3.connect(data)
        con.execute("""CREATE TABLE original_1785_financial_facts(
            ticker TEXT,fiscal_year INTEGER,metric TEXT,value_twd TEXT,
            unit TEXT,filing_version_type TEXT,source_pdf_sha256 TEXT,
            pdf_page INTEGER,statement_scope TEXT,accounting_framework TEXT,
            review_status TEXT,original_first_publication_verified INTEGER,
            model_training_admitted INTEGER)""")
        for year in (2013,2014,2015):
            for k,metric in enumerate(study.METRICS):
                con.execute("INSERT INTO original_1785_financial_facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
                    "1785",year,metric,str((year-2010)*10000+k*300),
                    "TWD","original","a"*64,6,"consolidated","TIFRS",
                    "DOUBLE_REVIEWED_ORIGINAL_PDF",0,0))
        con.commit();con.close()
        modeldir=self.root/"trained";modeldir.mkdir()
        x=np.vstack([np.arange(18)+20,np.arange(18)+200,
                     np.arange(18)+50,np.arange(18)+500])
        y=np.array([0,1,0,1])
        pipe=Pipeline([("scaler",RobustScaler()),
                       ("classifier",LogisticRegression())])
        pipe.fit(x,y)
        joblib.dump(pipe,modeldir/"logistic_regression_officially_reviewed_experiment.joblib")
        (modeldir/"round8_supervised_classification_report.json").write_text(
            json.dumps({
                "status":"ROUND8_SUPERVISED_APPROVED_ORIGINAL_LABELLED_EXPERIMENT",
                "final_holdout_1785_excluded":True,
                "selected_model":"logistic_regression",
                "comparisons":[{"model":"logistic_regression",
                                "decision_threshold_validation_selected":0.4}]
            }))
        result=study.score_reserved_1785(data,modeldir,self.root/"score")
        self.assertEqual(len(result["periods"]),3)
        self.assertEqual({r["fiscal_year"] for r in result["periods"]},
                         {2013,2014,2015})
        self.assertTrue(all(0<=r["supervised_misstatement_score"]<=1
                            for r in result["periods"]))
        self.assertFalse(result["supervised_training_included_1785"])
        self.assertFalse(result["historical_asof_alert_claim_allowed"])

    def test_original_api_reader_fails_closed_on_production_promotion(self):
        import sqlite3
        from app.services.financial_research.original_ai1_research_reader import get_1785_original_ai1
        path=self.root/"review.sqlite3"
        db=sqlite3.connect(path)
        db.execute("""CREATE TABLE original_1785_financial_facts(
            ticker TEXT,fiscal_year INTEGER,metric TEXT,value_twd TEXT,
            unit TEXT,filing_version_type TEXT,source_pdf_sha256 TEXT,
            pdf_page INTEGER,statement_scope TEXT,accounting_framework TEXT,
            review_status TEXT,original_first_publication_verified INTEGER,
            model_training_admitted INTEGER)""")
        db.execute("INSERT INTO original_1785_financial_facts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            "1785",2015,"revenue","123000","TWD","original","a"*64,6,
            "consolidated","TIFRS","DOUBLE_REVIEWED_ORIGINAL_PDF",0,1))
        db.commit();db.close()
        with self.assertRaisesRegex(ValueError,"data_quality_regressed"):
            get_1785_original_ai1(path)

    def test_evidence_file_hash_is_checked(self):
        e,sha=self.evidence("report.pdf",b"%PDF mock original")
        with self.assertRaisesRegex(ValueError,"hash_changed"):
            study.verify_file(self.ev,e,"0"*64)


if __name__=="__main__":
    unittest.main()
