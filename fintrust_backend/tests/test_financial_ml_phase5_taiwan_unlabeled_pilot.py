"""Offline empirical Phase5 study tests: true Taiwan split, no fraud labels."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.phase4_taiwan_dataset_gate import issuer_partition
from research.financial_ml.literature_dataset import FEATURES
from research.financial_ml.phase5_taiwan_unlabeled_pilot import (
    MIN_REQUIRED_INPUTS, read_audited_data, run,
)


class TaiwanUnlabeledPilotTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.register=self.root/"taiwan_research_split_register.csv"
        self.report=self.root/"phase4_dataset_integrated_report.json"
        self.header=[
            "ticker","fiscal_year","evidence_tier","issuer_split",
            "temporal_split","joint_strict_split","development_event_candidate",
            "outcome_label","approved_supervised_training",
            "approved_supervised_validation","approved_supervised_test",
            "first_filing_publication_verified","original_vintage_verified",
            "feature_vector_json",
        ]
        self.rows=[]
        for issuer in range(2400,2500):
            ticker=str(issuer)
            group=issuer_partition(ticker)
            for year in range(2016,2026):
                time=("fit" if year<=2020 else
                      "validation" if year<=2022 else "test")
                components={name:"" if name=="d_issue" or index>=8 else
                    str(1.0+(issuer%31)*0.03+(year-2016)*0.008+index*0.1)
                    for index,name in enumerate(FEATURES)}
                self.rows.append(dict(
                    ticker=ticker,fiscal_year=str(year),
                    evidence_tier="FINMIND_PROVISIONAL",
                    issuer_split=group,temporal_split=time,
                    joint_strict_split=group if group==time else "outside_joint_evaluation",
                    development_event_candidate="false",outcome_label="UNKNOWN",
                    approved_supervised_training="false",
                    approved_supervised_validation="false",
                    approved_supervised_test="false",
                    first_filing_publication_verified="false",
                    original_vintage_verified="false",
                    feature_vector_json=json.dumps(components)))
        self.info={
            "eligible_for_supervised_financial_fraud_training":False,
            "labels_approved_positive":0,
            "labels_approved_negative":0,
            "final_holdout_excluded":True,
            "source_tiers_not_fused":True,
            "case_development_candidate_ids":["3027","6452","8299"]
        }
        self.save()

    def save(self):
        with self.register.open("w",encoding="utf-8",newline="") as fh:
            w=csv.DictWriter(fh,fieldnames=self.header)
            w.writeheader()
            w.writerows(self.rows)
        self.report.write_text(json.dumps(self.info),encoding="utf-8")

    def test_experimental_source_requires_deliberate_opt_in(self):
        with self.assertRaisesRegex(ValueError,"experimental_unverified"):
            run(self.register,self.report,self.root/"out")

    def test_real_company_and_time_split_does_not_leak(self):
        samples,stats=read_audited_data(self.register,self.report)
        self.assertIsNotNone(samples)
        self.assertGreaterEqual(len(samples["fit"]),30)
        self.assertGreaterEqual(len(samples["validation"]),5)
        self.assertGreaterEqual(len(samples["test"]),5)
        companies=[{s[0] for s in samples[name]}
                   for name in ("fit","validation","test")]
        self.assertFalse(companies[0]&companies[1])
        self.assertFalse(companies[0]&companies[2])
        self.assertFalse(companies[1]&companies[2])
        self.assertTrue(all(s[1]<=2020 for s in samples["fit"]))
        self.assertTrue(all(2021<=s[1]<=2022 for s in samples["validation"]))
        self.assertTrue(all(s[1]>=2023 for s in samples["test"]))

    def test_four_distinct_unsupervised_estimators_fit_without_labels(self):
        result=run(self.register,self.report,self.root/"out",experimental_allow_unverified_data=True)
        self.assertEqual(result["status"],
                         "PROXY_MODEL_FAMILIES_FIT_NOT_FINANCIAL_MISSTATEMENT_DETECTION")
        self.assertEqual(result["unsupervised_fit_only_technical_models_trained"],4)
        self.assertFalse(result["accuracy_recall_pr_auc_f1_reported"])
        self.assertFalse(result["uses_frozen_1785"])
        self.assertEqual(result["labels_approved"],0)
        self.assertTrue((self.root/"out"/"unlabeled_method_comparison.csv").exists())
        with (self.root/"out"/"unknown_label_holdout_proxy_scores.csv").open(
                encoding="utf-8",newline="") as f:
            scored=list(csv.DictReader(f))
        self.assertTrue(scored)
        self.assertEqual({r["verified_financial_misstatement_label"] for r in scored},
                         {"UNKNOWN"})
        self.assertTrue(all(r["can_assert_historical_early_warning"]=="false"
                            for r in scored))

    def test_reserved_case_or_promoted_outcome_rejected(self):
        self.rows[0]["ticker"]="1785"
        self.save()
        with self.assertRaisesRegex(ValueError,"reserved_case"):
            read_audited_data(self.register,self.report)
        self.rows[0]["ticker"]="2400"
        self.rows[0]["outcome_label"]="1"
        self.save()
        with self.assertRaisesRegex(ValueError,"unapproved_label"):
            read_audited_data(self.register,self.report)

    def test_no_original_asof_evidence_can_be_self_approved(self):
        self.rows[0]["original_vintage_verified"]="true"
        self.save()
        with self.assertRaisesRegex(ValueError,"asof_promotion"):
            read_audited_data(self.register,self.report)
        self.rows[0]["original_vintage_verified"]="false"
        self.info["labels_approved_negative"]=100
        self.save()
        with self.assertRaisesRegex(ValueError,"provenance_or_label_gate"):
            read_audited_data(self.register,self.report)

    def test_issue_missing_never_zero_even_as_proxy(self):
        item=next(x for x in self.rows if x["ticker"]=="2401" and x["fiscal_year"]=="2016")
        vector=json.loads(item["feature_vector_json"])
        vector["d_issue"]="0"
        item["feature_vector_json"]=json.dumps(vector)
        self.save()
        with self.assertRaisesRegex(ValueError,"unverified_issue"):
            read_audited_data(self.register,self.report)

    def test_case_development_candidate_flags_cannot_be_edited(self):
        self.rows[0]["development_event_candidate"]="true"
        self.save()
        with self.assertRaisesRegex(ValueError,"candidate_flag"):
            read_audited_data(self.register,self.report)

    def test_duplicate_source_year_rejected(self):
        self.rows.append(dict(self.rows[0]))
        self.save()
        with self.assertRaisesRegex(ValueError,"duplicate_evidence_source"):
            read_audited_data(self.register,self.report)

    def test_partial_financial_sources_do_not_autofill_missing_financial_items(self):
        item=next(x for x in self.rows if x["ticker"]=="2401" and x["fiscal_year"]=="2016")
        one=json.loads(item["feature_vector_json"])
        for i,f in enumerate(FEATURES):
            one[f]=str(i) if i<MIN_REQUIRED_INPUTS-1 else ""
        item["feature_vector_json"]=json.dumps(one)
        self.save()
        sampled,stats=read_audited_data(self.register,self.report)
        self.assertGreater(stats["excluded"].get("fewer_than_4_observed_paper_features",0),0)

    def test_strict_split_insufficient_samples_gracefully_stops_no_fit(self):
        self.rows=self.rows[:5]
        self.save()
        res=run(self.register,self.report,self.root/"out",experimental_allow_unverified_data=True)
        self.assertEqual(res["status"],"UNLABELED_PROXY_BLOCKED_INSUFFICIENT_STRICT_SPLIT_COVERAGE")
        self.assertFalse((self.root/"out"/"unknown_label_holdout_proxy_scores.csv").exists())

    def test_official_retroactive_rows_are_not_merged_into_finmind_model(self):
        official=dict(self.rows[0])
        official["evidence_tier"]="MOPS_OFFICIAL_RETROSPECTIVE"
        self.rows.append(official)
        self.save()
        _,summary=read_audited_data(self.register,self.report)
        self.assertEqual(summary["excluded"]["separate_official_retrospective_tier"],1)


if __name__=="__main__":
    unittest.main()
