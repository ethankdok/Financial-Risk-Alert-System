"""Round3 synthetic end-to-end: realistic frozen 535 annual / 399 sequence
windows, 144 quarter source rows and 2,232 observed 24-feature cells.
NO confirmed misconduct labels or financial accuracy claims.
"""
from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from research.financial_ml import round3_research_models as stage
import test_financial_ml_round2_closeout_round3_bridge as old


class Round3EvaluationTests(unittest.TestCase):
    def setUp(self):
        parent = old.Round2CloseoutTests("test_complete_offline_integrity_and_strictly_blocked_round3")
        parent.setUp()
        self.addCleanup(parent.fixture.tmp.cleanup)
        self.parent=parent
        self.data=parent.data
        self.frozen = self.data / "final_round1_integrated_ml_dataset"
        self.output=self.data / "round3_model_study"
        self.make_realistic_annual()
        self.make_realistic_quarters()
        # The unchanged Round2 acceptance ledger is intentionally independent
        # of newly generated synthetic final-round1 feature views.
        parent.rewrite_review_hashes([0, 5])
        from research.financial_ml import round2_closeout_round3_bridge as bridge
        bridge.build(self.data, parent.review, parent.out)
        self.bridge=parent.out

    def make_realistic_annual(self):
        rows=old.fixture_module.read_csv(self.parent.annual_path)
        for idx,r in enumerate(rows):
            issuer=int(r["ticker"])-2201
            year=int(r["fiscal_year"])
            # 39 full sequences (507 observed) + one 12-year sequence
            # (12 observed) + 16 isolated yearly observations = 535.
            complete = (issuer<39 or (issuer==39 and year<=2024)
                        or (40<=issuer<56 and year==2015))
            r["complete_candidate_vector"]=str(complete).lower()
            r["original_publication_verified"]="false"
            r["original_filing_vintage_verified"]="false"
            for k,name in enumerate(stage.METRICS):
                r[name]=str(round(1000.0+issuer*50.0+
                                  (year-2013)*80.0+(k+1)*25.0+
                                  (issuer%5)*(year%3),3)) if complete else ""
        old.fixture_module.write_csv(self.parent.annual_path,rows)
        self.assertEqual(sum(r["complete_candidate_vector"]=="true" for r in rows),535)
        self.assertEqual(len(stage.annual_windows(self.parent.annual_path)),399)

    def make_realistic_quarters(self):
        rows=old.fixture_module.read_csv(self.parent.fixture.sparse_path)
        seen=0
        for i,r in enumerate(rows):
            ticker,period=r["ticker"],r["reporting_period"]
            issuer=stage.issuer_partition(ticker)
            clock=("fit" if period<="2018Q4"
                   else "validation" if period<"2019Q3" else "test")
            n=16 if i<72 else 15
            r["issuer_split"]=issuer
            r["time_split"]=clock
            r["joint_strict_split"]=issuer if issuer==clock else "outside_joint_evaluation"
            r["original_filing_vintage_verified"]="false"
            r["historical_publication_verified"]="false"
            r["negative_label_approved"]="false"
            for k in range(24):
                fid=f"qf_{k+1:02d}"
                present=(k-(i%24))%24<n
                r[fid]=str(round(0.15*i+5*k+10,3)) if present else ""
                r[fid+"_observed"]=str(present).lower()
            r["observed_selected_feature_count"]=str(n)
            seen+=n
        self.assertEqual(seen,2232)
        old.fixture_module.write_csv(self.parent.fixture.sparse_path,rows)
        dictionary = old.fixture_module.read_csv(self.parent.dict_path)
        for feature in dictionary:
            feature["candidate_source_tier"] = "MOPS_OFFICIAL_RETROSPECTIVE_QUARTER"
        old.fixture_module.write_csv(self.parent.dict_path, dictionary)

    def test_full_annual_regression_and_quarter_novelty_metrics(self):
        report=stage.run(self.data,self.bridge,self.output,
                         models=("persistence","ridge","random_forest"),
                         epochs=5,seed=41)
        self.assertFalse(report["fraud_supervised_training_allowed"])
        self.assertIsNone(report["fraud_f1"])
        self.assertIsNone(report["fraud_pr_auc"])
        annual=report["annual_numeric_study"]
        self.assertEqual(annual["sample_count"],399)
        self.assertTrue(annual["holdout_not_used_to_pick_model"])
        self.assertFalse(annual["historical_issuer_disjoint"])
        self.assertEqual(set(annual["time_partition_counts"]),{"fit","validation","holdout"})
        self.assertEqual(len(annual["comparisons"]),3)
        self.assertTrue(all(c["status"]=="FIT_NUMERIC_PROXY_ONLY" for c in annual["comparisons"]))
        for c in annual["comparisons"]:
            self.assertGreaterEqual(float(c["holdout_scaled_rmse"]),0)
            self.assertGreaterEqual(float(c["validation_signed_log_mae"]),0)
        q=report["quarter_unlabeled_study"]
        self.assertEqual(q["raw_company_quarters"],144)
        self.assertEqual(q["feature_count"],24)
        self.assertEqual(len(q["models"]),4)
        self.assertTrue(all(v["independent_verified_labels"]==0
                            for v in q["models"]))
        self.assertEqual(len(old.fixture_module.read_csv(
            self.output/"annual_numeric_prediction_per_financial_field.csv")),3*2*12)
        self.assertEqual(len(old.fixture_module.read_csv(
            self.output/"quarter_unlabeled_model_comparison.csv")),4)

    def test_no_supervised_fraud_training_if_release_gate_forged(self):
        p=self.bridge/"round3_release_gates.json"
        content=json.loads(p.read_text(encoding="utf-8"))
        content["supervised_fraud_train_allowed"]=True
        p.write_text(json.dumps(content),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"release_gate_not_research_only"):
            stage.run(self.data,self.bridge,self.output,models=("persistence","ridge"))

    def test_frozen_annual_source_tampered_rejected(self):
        p=self.parent.annual_path
        with p.open("a",encoding="utf-8") as f:
            f.write("tamper")
        with self.assertRaisesRegex(ValueError,"source_sha256_mismatch"):
            stage.run(self.data,self.bridge,self.output,models=("persistence","ridge"))

    def test_missing_true_vs_zero_quarter_flags_rejected(self):
        p=self.parent.fixture.sparse_path
        rows=old.fixture_module.read_csv(p)
        rows[0]["qf_01"]="0"
        rows[0]["qf_01_observed"]="false"
        old.fixture_module.write_csv(p,rows)
        # Re-sign the synthetic transfer ledger to exercise actual values gate.
        transfer=self.bridge/"round3_research_source_manifest.csv"
        manifest=old.fixture_module.read_csv(transfer)
        for item in manifest:
            if item["source_id"]=="COMPARISON_QUARTER_FIT_ONLY_24_FEATURES":
                item["source_sha256"]=stage.digest(p)
        old.fixture_module.write_csv(transfer,manifest)
        for report_file,field in (("round2_closure_and_round3_preflight.json",
                                   "round3_source_manifest_sha256"),
                                  ("round3_release_gates.json",
                                   "source_transfer_manifest_sha256")):
            dst=self.bridge/report_file
            entry=json.loads(dst.read_text(encoding="utf-8"))
            entry[field]=stage.digest(transfer)
            dst.write_text(json.dumps(entry),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"missingness_flag_conflicts"):
            stage.run(self.data,self.bridge,self.output,models=("persistence","ridge"))

    def test_no_overwrite_of_completed_experiment(self):
        stage.run(self.data,self.bridge,self.output,models=("persistence","ridge"),epochs=5)
        p=self.output/"round3_real_data_model_report.json"
        contents=p.read_bytes()
        with self.assertRaisesRegex(FileExistsError,"experiment_must_remain_immutable"):
            stage.run(self.data,self.bridge,self.output,models=("persistence","ridge"),epochs=5)
        self.assertEqual(p.read_bytes(),contents)

    def test_mismatched_frozen_round1_quarter_timing_is_rejected(self):
        p=self.parent.fixture.sparse_path
        rows=old.fixture_module.read_csv(p)
        rows[0]["time_split"]="test"
        old.fixture_module.write_csv(p,rows)
        transfer=self.bridge/"round3_research_source_manifest.csv"
        manifest=old.fixture_module.read_csv(transfer)
        for item in manifest:
            if item["source_id"]=="COMPARISON_QUARTER_FIT_ONLY_24_FEATURES":
                item["source_sha256"]=stage.digest(p)
        old.fixture_module.write_csv(transfer,manifest)
        for report_file,field in (("round2_closure_and_round3_preflight.json",
                                   "round3_source_manifest_sha256"),
                                  ("round3_release_gates.json",
                                   "source_transfer_manifest_sha256")):
            dst=self.bridge/report_file
            data=json.loads(dst.read_text(encoding="utf-8"))
            data[field]=stage.digest(transfer)
            dst.write_text(json.dumps(data),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"leakage_partition_changed"):
            stage.run(self.data,self.bridge,self.output,models=("persistence","ridge"))

    def test_zero_label_metrics_are_never_numeric(self):
        report=stage.run(self.data,self.bridge,self.output,
                         models=("persistence","ridge"),epochs=5)
        for field in ("fraud_precision","fraud_recall","fraud_f1",
                      "fraud_pr_auc","fraud_roc_auc","fraud_confusion_matrix"):
            self.assertIsNone(report[field])

    def test_transformer_and_catboost_requested_as_separate_architectures(self):
        self.assertTrue({"transformer","lstm","gru","tcn","catboost"}.issubset(
            stage.ANNUAL_MODELS))
        self.assertNotIn("1785",stage.SOURCE_MAP)
        self.assertEqual(len(stage.METRICS),12)


if __name__=="__main__":
    unittest.main()
