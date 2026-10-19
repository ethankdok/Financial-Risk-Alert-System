"""Round4 research outputs tested only on synthetic financial amounts/flags."""
from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from research.financial_ml import round3_research_models as r3
from research.financial_ml import round4_research_handoff as r4
import test_financial_ml_round3_research_models as r3_tests


class Round4Tests(unittest.TestCase):
    def setUp(self):
        fixture=r3_tests.Round3EvaluationTests(
            "test_transformer_and_catboost_requested_as_separate_architectures")
        fixture.setUp()
        self.addCleanup(fixture.parent.fixture.tmp.cleanup)
        self.fixture=fixture
        self.source=fixture.output
        self.output=fixture.data/"round4_output"
        self.report=r3.run(fixture.data,fixture.bridge,fixture.output,
                           models=("persistence","ridge","random_forest"),
                           epochs=5,seed=20261020)

    def test_validation_permutation_is_numeric_not_fraud(self):
        p=r4.permutation_validation(self.source,self.fixture.data,
                                    repeats=3,seed=20261020)
        self.assertEqual(len(p),24)
        self.assertEqual({row["model"] for row in p},{"ridge","random_forest"})
        self.assertEqual({row["n_validation_windows"] for row in p},{82})
        self.assertTrue(all(row["interpretation"].endswith("NOT_CAUSAL") for row in p))
        self.assertTrue(all(isinstance(row["mean_increase_validation_signed_log_mae"],float)
                            for row in p))

    def test_quarter_consensus_15_sample_grains_and_6_pairs(self):
        votes,pairs=r4.consensus_table(self.source,self.report)
        self.assertEqual(len(votes),15)
        self.assertEqual(len(pairs),6)
        self.assertEqual({p["n_test_quarters"] for p in pairs},{6})
        self.assertTrue(all(0 <= int(v["models_above_fit_p95"]) <=4 for v in votes))
        self.assertTrue(all(p["jaccard_on_unlabeled_quarters"] is None or
                            0<=p["jaccard_on_unlabeled_quarters"]<=1 for p in pairs))
        self.assertEqual({v["uncertainty_or_fraud_label"] for v in votes},{"UNKNOWN"})

    def test_unknown_label_is_never_upgraded_from_votes(self):
        path=self.source/"quarter_unlabeled_validation_test_scores.csv"
        rows=r3_tests.old.fixture_module.read_csv(path)
        rows[0]["verified_fraud_label"]="1"
        r3_tests.old.fixture_module.write_csv(path,rows)
        with self.assertRaisesRegex(ValueError,"fraud_label_or_holdout_violation"):
            r4.consensus_table(self.source,self.report)

    def test_training_permutation_rejects_changed_scaler(self):
        path=self.source/"annual_checkpoints"/"fit_only_preprocessor.joblib"
        import joblib
        obj=joblib.load(path)
        obj["features"]=("FAKE",)
        joblib.dump(obj,path)
        with self.assertRaisesRegex(ValueError,"preprocessor_checkpoint_disagrees"):
            r4.permutation_validation(self.source,self.fixture.data,repeats=3)

    def test_numeric_ranking_never_uses_holdout_to_choose_winner(self):
        models=self.report["annual_numeric_study"]["comparisons"]
        best=min(models,key=lambda x:x["validation_signed_log_mae"])["model"]
        rows=r4.ranking_table(self.report)
        self.assertEqual(sum(r["selected_on_validation"]=="true" for r in rows),1)
        self.assertEqual([r["model"] for r in rows if r["selected_on_validation"]=="true"],[best])

    def test_round4_requires_user_uploaded_real_source_sha_when_given(self):
        with self.assertRaisesRegex(ValueError,"user_uploaded_round3_report_sha_mismatch"):
            r4.build(self.fixture.data,self.fixture.bridge,self.source,
                     self.output, report_sha="0"*64)

    def test_bad_round3_source_topology_is_not_silently_accepted(self):
        d=json.loads((self.source/"round3_real_data_model_report.json").read_text())
        d["fraud_f1"]=0.99
        (self.source/"round3_real_data_model_report.json").write_text(json.dumps(d))
        with self.assertRaisesRegex(ValueError,"label_source_or_policy_changed"):
            r4.read_round3(self.source/"round3_real_data_model_report.json",
                           self.fixture.data,self.fixture.bridge)

    def test_engineering_handoff_metrics_produced_without_assuming_labels(self):
        # The synthetic model run does not have the user's full 9-model and
        # dual-split real topology; mock ONLY the already independently tested
        # Round3 paper acceptance, not the permutation/model execution.
        with patch.object(r4,"read_round3",return_value=self.report):
            result=r4.build(self.fixture.data,self.fixture.bridge,self.source,
                            self.output, repeats=2)
        self.assertTrue(result["reserved_1785_excluded"])
        self.assertIsNone(result["supervised_fraud_F1"])
        self.assertEqual(result["diagnostic_permutation_trained_regression_models"],2)
        self.assertEqual(result["unlabeled_quarter_scores_compared"],15)
        p=self.output/"round4_research_handoff_report.json"
        self.assertTrue(p.exists())
        with self.assertRaisesRegex(FileExistsError,"previous_results_immutable"):
            with patch.object(r4,"read_round3",return_value=self.report):
                r4.build(self.fixture.data,self.fixture.bridge,self.source,
                         self.output, repeats=2)


if __name__=="__main__":
    unittest.main()
