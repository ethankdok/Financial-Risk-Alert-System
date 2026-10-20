"""Three-stage FY2013–2015 acceptance tests. ALL test observations synthetic."""
from __future__ import annotations
import csv
import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from research.financial_ml import fy2013_2015_stage1_freeze as a
from research.financial_ml import fy2013_2015_stage2_labels as b
from research.financial_ml import fy2013_2015_stage3_supervised as c
from research.financial_ml.round3_research_models import ANNUAL_COLUMNS

def write(path,fields,rows):
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="raise")
        w.writeheader()
        w.writerows(rows)
def read(path):
    with path.open(encoding="utf-8-sig",newline="") as f:
        return list(csv.DictReader(f))

class ThreeStages(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.round1=self.root/"mock_frozen_round1.csv"
        cohort=a.cohort()
        rows=[]
        for t in cohort:
            for y in range(2013,2026):
                r={col:"" for col in ANNUAL_COLUMNS}
                r.update(ticker=t,fiscal_year=y,
                         complete_candidate_vector="true",
                         label_status="UNKNOWN",training_admitted="false")
                for j,col in enumerate(a.METRICS):
                    r[col]=str(1_000_000+int(t)*14+j*100+101*y)
                rows.append(r)
        write(self.round1,ANNUAL_COLUMNS,rows)

    def test_stage1_exact_three_year_360_data_not_13_years(self):
        report=a.locked_2013_15_candidate_panel(self.round1,self.root/"step1")
        self.assertEqual(report["issuer_year_rows"],360)
        self.assertEqual(report["years"],[2013,2014,2015])
        rows=read(self.root/"step1"/"fy2013_2015_exact_360_financial_source_audit.csv")
        self.assertEqual(len(rows),360)
        self.assertEqual({int(r["fiscal_year"]) for r in rows},{2013,2014,2015})
        self.assertTrue(all(r["approved_for_supervision"]=="false" for r in rows))
        self.assertTrue(all(r["numeric_source_tier"]=="FINMIND_PROVISIONAL_NOT_ORIGINAL"
                            for r in rows))

    def test_stage2_real_censor_no_auto_zero(self):
        a.locked_2013_15_candidate_panel(self.round1,self.root/"step1")
        m=b.make_queue(self.root/"step1"/"fy2013_2015_exact_360_financial_source_audit.csv",
                       self.root/"step2")
        self.assertEqual(m["issuer_years"],360)
        x=read(self.root/"step2"/"fy2013_15_360_manual_0_1_review_QUEUE.csv")
        self.assertEqual(len(x),360)
        self.assertTrue(all(r["human_label"]=="UNKNOWN" for r in x))
        self.assertTrue(all(r["revenue"]=="" for r in x))

    def test_two_manual_0_1_verification_with_archive_hashes(self):
        a.locked_2013_15_candidate_panel(self.round1,self.root/"step1")
        b.make_queue(self.root/"step1"/"fy2013_2015_exact_360_financial_source_audit.csv",
                     self.root/"step2")
        reviews=self.root/"step2"/"fy2013_15_360_manual_0_1_review_QUEUE.csv"
        rows=read(reviews)
        evidence=self.root/"evidence";evidence.mkdir()
        def doc(name):
            p=evidence/name
            p.write_bytes((b"SIMULATED TEST EVIDENCE DO NOT USE FOR REAL TRAINING "+name.encode())*2)
            return name,hashlib.sha256(p.read_bytes()).hexdigest()
        for idx,label in ((0,"1"),(1,"0")):
            r=rows[idx]
            fy=int(r["fiscal_year"])
            paper,paper_sha=doc(f"original_{idx}.pdf")
            search,search_sha=doc(f"official_correction_search_{idx}.json")
            notice,notice_sha=doc(f"official_event_{idx}.txt")
            r.update({
                "human_label":label,
                "original_first_filing_relative_path":paper,
                "original_sha256":paper_sha,
                "original_published_at":f"{fy+1}-03-20T12:00:00+08:00",
                "original_is_consolidated_TIFRS_first_version":"true",
                "original_12_amounts_verified_and_double_reviewed":"true",
                "event_status":(b.OUTCOME_TYPES[0] if label=="1" else b.OUTCOME_TYPES[1]),
                "event_affected_fiscal_year":str(fy),
                "event_official_notice_relative_path":notice,
                "event_official_notice_sha256":notice_sha,
                "event_issued_at":f"{fy+2}-03-20T12:00:00+08:00",
                "official_correction_search_archive_relative_path":search,
                "official_correction_search_archive_sha256":search_sha,
                "full_five_year_search_verified":"true",
                "no_known_later_restatement":"true",
                "reviewer_A":"different_reviewer_a",
                "reviewer_B":"different_reviewer_b",
                "method_owner_approved":"true",
            })
            for k in a.METRICS:r[k]=str(1000+idx*7)
        write(reviews,b.LABEL_FIELDS,rows)
        x=b.approve(reviews,evidence,self.root/"approved")
        self.assertEqual(x["approved_positives"],1)
        self.assertEqual(x["approved_negatives"],1)
        self.assertEqual(x["approved_issuer_years"],2)
        output=c.train(self.root/"approved"/"fy2013_15_approved_original_0_1.csv",
                       self.root/"approved"/"fy2013_15_stage2_label_gate.json",
                       self.root/"evaluated")
        self.assertIsNone(output["test_f1"])
        self.assertEqual(output["status"],"STOPPED_NOT_ENOUGH_CERTIFIED_YEAR_MATCHED_0_1")

    def test_positive_same_fy_late_notice_cannot_be_misplaced(self):
        self.assertEqual(b.add_five_years(b.timestamp("2014-03-31T00:00:00+08:00")).year,2019)

    def test_true_synthetic_supervised_end_to_end_without_leakage(self):
        # Directly tests model engine using an artifact stamped SYNTHETIC.
        # These are absolutely not real approved issuer labels.
        path=self.root/"synthetic_approved.csv"
        rows=[]
        for i,t in enumerate(a.cohort()):
            for y in a.YEARS:
                label=str(int(i%2==0))
                r={
                    "ticker":t,"fiscal_year":y,
                    "label":label,"label_target":b.TARGET,
                    "original_sha256":"a"*64,
                    "original_published_at":f"{y+1}-03-31T00:00:00+08:00",
                    "outcome_archive_sha256":"b"*64,
                    "reviewer_A":"A","reviewer_B":"B",
                    "review_window_end":f"{y+6}-03-31T00:00:00+08:00"
                }
                for j,m in enumerate(a.METRICS):
                    r[m]=str(1_000_000+j*1070+i*300+
                             (800_000 if label=="1" else -300_000)+y*23)
                rows.append(r)
        write(path,b.ACCEPTED_FIELDS,rows)
        gate=self.root/"synth_gate.json"
        gate.write_text(json.dumps({
            "status":"FY1315_HUMAN_REVIEW_GATE_COMPLETE",
            "approved_panel_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "this_test_uses_only_synthetic_samples":True,
        }))
        output=c.train(path,gate,self.root/"model")
        self.assertEqual(output["status"],
                         "FY1315_APPROVED_0_1_SUPERVISED_MODEL_EVALUATED")
        self.assertEqual(output["model_input_years"],[2013,2014,2015])
        self.assertTrue(0<=output["test_f1"]<=1)
        detail=output["classifier_evaluation"]
        self.assertEqual(set(detail["holdout_metrics_by_fiscal_year"]),
                         {"2013","2014","2015"})
        self.assertEqual(detail["feature_count"],18)
        self.assertEqual(output["test_confusion_matrix"]["tp"]+
                         output["test_confusion_matrix"]["tn"]+
                         output["test_confusion_matrix"]["fp"]+
                         output["test_confusion_matrix"]["fn"],
                         detail["holdout_rows"])
        self.assertTrue((self.root/"model"/
                         "fy2013_15_approved_supervised_model.joblib").is_file())

    def test_wrong_2016_in_approved_rows_hard_fail(self):
        p=self.root/"fake_labels.csv"
        r={f:"" for f in b.ACCEPTED_FIELDS}
        r.update(ticker="2330",fiscal_year="2016",label="1",
                 label_target=b.TARGET,original_sha256="c"*64)
        write(p,b.ACCEPTED_FIELDS,[r])
        with self.assertRaisesRegex(ValueError,"not_approved_original_fiscal_sample"):
            c.load_approved(p)

if __name__=="__main__":
    unittest.main()
