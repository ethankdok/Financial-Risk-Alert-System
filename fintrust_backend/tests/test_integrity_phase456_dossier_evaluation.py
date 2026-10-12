"""Synthetic tests for Phase 4–6 research and B2B services; no DB or network."""
from __future__ import annotations

from copy import deepcopy
import unittest

from app.services.integrity.b2b_dossier import build_dossier
from app.services.integrity.cross_evidence import compose_corroboration
from app.services.integrity.research_evaluation import evaluate_holdout

SHA = "a" * 64


def assessment():
    return {
        "ticker": "2454", "company": "合成公司", "subindustry": "synthetic",
        "review_mode": "CURRENT_REVIEW",
        "temporal_basis": "latest_archived_information_at_request_time",
        "generated_at": "2026-01-01T00:00:00Z",
        "freshness": {"latest_fact_fiscal_year": 2025, "stale_findings": []},
        "financial_findings": [{
            "finding_id": "F1:2025FY", "check_id": "F1_REVENUE_RECEIVABLES_ALIGNMENT",
            "family": "financial_consistency", "status": "descriptive_divergence",
            "evidence_families": ["revenue", "receivables"],
            "evidence_ids": ["fact:one", "fact:two"],
        }],
        "claim_findings": [{
            "finding_id": "F3:claim:one", "check_id": "F3_ISSUER_CLAIM_VERIFICATION",
            "status": "supported", "evidence_families": ["revenue", "issuer_presentation"],
            "evidence_ids": ["fact:one", "claim:one"],
        }],
        "narrative_findings": [],
        "evidence_records": [
            {"evidence_id": "fact:one", "independence": "regulator_published_issuer_data"},
            {"evidence_id": "fact:two", "independence": "regulator_published_issuer_data"},
            {"evidence_id": "claim:one", "independence": "issuer_self_reported"},
        ],
        "data_shift": {"status": "comparable", "calibration_status": "uncalibrated",
                       "drift_level": "uncalibrated"},
        "investigation_priority": {"queue": "requires_verification", "meaning": "document request",
                                   "triggered_by": [{"finding_id": "F1:2025FY"}]},
        "next_checks": [{
            "check_id": "B2B_AR_TERMS", "triggered_by": "F1:2025FY",
            "question_for_counterparty": "請說明應收帳款",
            "documents_to_request": ["應收帳款帳齡表"], "rationale": "盡職調查",
            "condition": "gap", "is_risk_conclusion": False,
        }, {
            "check_id": "B2B_NO_NETWORK_INFERENCE", "triggered_by": None,
            "question_for_counterparty": "不適用", "documents_to_request": [],
            "is_risk_conclusion": False,
        }],
        "missing_data": [{"section": "financial_checks", "item": "F4",
                          "reasons": ["no_verified_nonfinancial_measure_series"]}],
    }


def cohort():
    return [
        {
            "ticker": "2454", "sample_role": "holdout",
            "cutoff_at": "2020-01-01T00:00:00+00:00",
            "data_available_at": "2019-12-01T00:00:00+00:00",
            "score": "0.80", "score_source_sha256": SHA,
            "feature_sources": [{"source_sha256": "b" * 64, "published_at": "2019-11-01T00:00:00Z",
                                 "archive_bytes_verified": True, "source_identity_verified": True}],
            "label_kind": "documented_event", "label_source_sha256": SHA,
            "event_at": "2020-06-01T00:00:00+00:00",
        }, {
            "ticker": "2330", "sample_role": "holdout",
            "cutoff_at": "2020-01-01T00:00:00+00:00",
            "data_available_at": "2019-12-01T00:00:00+00:00",
            "score": "0.20", "score_source_sha256": SHA,
            "feature_sources": [{"source_sha256": "c" * 64, "published_at": "2019-11-01T00:00:00Z",
                                 "archive_bytes_verified": True, "source_identity_verified": True}],
            "label_kind": "verified_no_event", "label_source_sha256": SHA,
            "followup_through": "2021-02-01T00:00:00+00:00",
        },
    ]


def evaluate(rows=None, **kw):
    return evaluate_holdout(cohort() if rows is None else rows, threshold="0.50",
                            threshold_id="predeclared_threshold_v1",
                            experiment_id="synthetic_holdout", **kw)


class CrossEvidenceTests(unittest.TestCase):
    def test_same_issuer_agreement_not_third_party(self):
        result = compose_corroboration(assessment())
        self.assertEqual(result["issuer_claim_agreement_count"], 1)
        self.assertEqual(result["independent_third_party_family_count"], 0)
        self.assertEqual(result["fraud_probability"], None)

    def test_duplicate_source_family_not_double_counted(self):
        result = compose_corroboration(assessment())
        revenue = next(x for x in result["evidence_families"] if x["family"] == "revenue")
        self.assertEqual(len(revenue["finding_ids"]), 2)
        self.assertEqual(revenue["evidence_ids"], ["fact:one", "fact:two"])

    def test_uncalibrated_drift_withholds_level(self):
        result = compose_corroboration(assessment())
        self.assertIsNone(result["narrative"]["drift_level"])
        self.assertFalse(result["narrative"]["eligible_for_monitoring"])

    def test_verified_independent_source_is_distinct(self):
        data = assessment()
        data["evidence_records"].append({"evidence_id": "thirdparty:1", "independence": "independent_third_party",
                                         "source_sha256": "b" * 64})
        data["financial_findings"][0]["evidence_ids"].append("thirdparty:1")
        result = compose_corroboration(data)
        self.assertEqual(result["independent_third_party_family_count"], 2)
        self.assertEqual(result["distinct_verified_third_party_source_artifacts"], 1)

    def test_unanchored_independence_flag_does_not_count_as_verified_third_party(self):
        data = assessment()
        data["evidence_records"].append({"evidence_id": "thirdparty:1", "independence": "independent_third_party"})
        data["financial_findings"][0]["evidence_ids"].append("thirdparty:1")
        result = compose_corroboration(data)
        self.assertEqual(result["independent_third_party_family_count"], 0)
        self.assertEqual(result["distinct_verified_third_party_source_artifacts"], 0)


class B2BTests(unittest.TestCase):
    def test_readonly_dossier_has_no_trade_link_inference(self):
        result = build_dossier(assessment(), "supplier")
        self.assertFalse(result["relationship"]["verified_business_link"])
        self.assertEqual(result["relationship"]["evidence_status"], "user_declared_unverified")
        self.assertFalse(result["persisted"])
        self.assertIsNone(result["supply_disruption_probability"])
        self.assertEqual(result["investigation_queue"]["queue"], "requires_verification")
        self.assertEqual(result["document_requests"][0]["requested_documents"], ["應收帳款帳齡表"])

    def test_refuses_retrospective_relabel_as_current(self):
        data = assessment()
        data["review_mode"] = "RETROSPECTIVE_CASE"
        with self.assertRaises(ValueError):
            build_dossier(data, "customer")

    def test_unknown_relationship_fails_closed(self):
        with self.assertRaises(ValueError):
            build_dossier(assessment(), "linked_supply_chain_detected")


class PITExperimentTests(unittest.TestCase):
    def test_valid_holdout_confusion_matrix_descriptive_only(self):
        result = evaluate()
        self.assertEqual(result["status"], "descriptive_cohort_computable_not_preregistered")
        self.assertEqual(result["confusion_matrix"], {"tp": 1, "fp": 0, "fn": 0, "tn": 1})
        self.assertEqual(result["descriptive_metrics"]["precision"], "1")
        self.assertFalse(result["fraud_prediction_validated"])

    def test_excludes_post_cutoff_score(self):
        rows = cohort()
        rows[0]["data_available_at"] = "2020-02-01T00:00:00Z"
        self.assertEqual(evaluate(rows)["exclusions"][0]["reason"],
                         "score_uses_information_unavailable_at_cutoff")

    def test_score_digest_without_feature_level_lineage_is_not_pit_eligible(self):
        rows = cohort()
        rows[0].pop("feature_sources")
        self.assertEqual(evaluate(rows)["exclusions"][0]["reason"], "feature_level_pit_evidence_missing")

    def test_later_published_component_blocks_hindsight_score(self):
        rows = cohort()
        rows[0]["feature_sources"][0]["published_at"] = "2020-02-01T00:00:00Z"
        self.assertEqual(evaluate(rows)["exclusions"][0]["reason"],
                         "feature_source_not_available_before_cutoff")

    def test_unreviewed_document_bytes_cannot_enter_holdout(self):
        rows = cohort()
        rows[0]["feature_sources"][0]["archive_bytes_verified"] = False
        self.assertEqual(evaluate(rows)["exclusions"][0]["reason"],
                         "feature_source_identity_or_publication_unverified")

    def test_excludes_leakage_from_training_companies(self):
        result = evaluate(training_tickers=["2454"])
        self.assertEqual(result["exclusions"][0]["reason"], "company_leakage_from_training")

    def test_negative_control_requires_complete_followup(self):
        rows = cohort()
        rows[1]["followup_through"] = "2020-02-01T00:00:00Z"
        self.assertEqual(evaluate(rows)["exclusions"][0]["reason"], "negative_control_followup_incomplete")

    def test_undocumented_negative_label_not_assumed(self):
        rows = cohort()
        rows[1]["label_kind"] = None
        self.assertEqual(evaluate(rows)["exclusions"][0]["reason"], "unknown_or_unverified_outcome")

    def test_rejects_naive_publication_instant(self):
        rows = cohort()
        rows[0]["data_available_at"] = "2019-12-01"
        self.assertEqual(evaluate(rows)["exclusions"][0]["reason"], "unknown_cutoff_or_publication_instant")

    def test_rejects_duplicate_company_cutoff(self):
        rows = cohort()
        rows.append(deepcopy(rows[0]))
        self.assertEqual(evaluate(rows)["exclusions"][0]["reason"], "duplicate_company_cutoff")

    def test_threshold_identifier_does_not_prove_preregistration(self):
        result = evaluate()
        self.assertFalse(result["threshold_pre_registered"])
        self.assertEqual(result["preregistration_status"], "unverified_identifier_only")
        self.assertFalse(result["outcome_source_authenticity_independently_verified"])

    def test_invalid_duplicate_does_not_block_a_later_valid_observation(self):
        rows = cohort()
        invalid = deepcopy(rows[0])
        invalid["event_at"] = None
        rows.insert(0, invalid)
        result = evaluate(rows)
        self.assertEqual(result["sample_size_admitted"], 2)
        self.assertEqual(result["exclusions"][0]["reason"], "event_not_verified_in_future_horizon")

    def test_rejects_unregistered_threshold(self):
        with self.assertRaises(ValueError):
            evaluate_holdout(cohort(), threshold="NaN", threshold_id="x", experiment_id="test")


if __name__ == "__main__":
    unittest.main()
