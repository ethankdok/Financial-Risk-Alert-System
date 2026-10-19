"""Round2 engineering closeout + strictly blocked Round3 fraud-classifier preflight.

Reads and hashes the already-accepted real-source research products. Legal
document byte identity, approved period outcome, first historical filing
vintage, and market notice publication are independent certification gates.
Never promotes a reviewer worksheet, hash receipt or provisional issuer
into a fraud/normal label. No network, retraining or DB writes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from .phase1_case_registry import validate
from .round2_evidence_review import (
    CASE_FIELDS, CONTROL_FIELDS, REVIEW_FIELDS, digest, read_csv,
    require_unknown, require_unapproved, write_csv,
)

BASE_FILES = (
    "final_round1_integrated_ml_dataset/round1_dataset_readiness_report.json",
    "phase1_case_sources_seed.json",
    "phase10_case_official_paper_audit/phase10_case_official_paper_features.csv",
    "final_round1_integrated_ml_dataset/case_official_15_paper_candidate_separate.csv",
    "final_round1_integrated_ml_dataset/quarterly_issuer_period_source_index.csv",
    "final_round1_integrated_ml_dataset/quarterly_sparse_feature_matrix.csv",
    "phase7_official_case_asof_recovery/phase7_official_source_review.csv",
    "phase8_case_original_filing_recovery/original_case_filing_source_intake.csv",
    "phase8_case_original_filing_recovery/phase8_integrated_report.json",
)
ROUND2_FILES = (
    "round2_case_year_review.csv", "round2_case_quarter_review.csv",
    "round2_unreviewed_comparison_quarters.csv",
    "round2_independent_review_template.csv",
)
TRANSFER_FIELDS = (
    "source_id", "file_path", "source_sha256", "sample_grain",
    "independent_sample_count", "source_tier", "safe_current_use",
    "fraud_supervised_use", "historical_asof_certified", "transfer_warning",
)
CASE_SOURCE_FIELDS = (
    "case_id", "ticker", "source_id", "official_url", "archive_file_sha256",
    "receipt_integrity", "content_identity", "official_domain_provenance",
    "legal_period_outcome_approved", "first_public_revelation_verified",
    "blockers",
)
BLOCKERS = (
    "FIRST_PUBLISHED_ORIGINAL_REPORT_UNVERIFIED",
    "INDEPENDENT_FILING_PUBLICATION_TIME_UNVERIFIED",
    "PERIOD_SPECIFIC_OUTCOME_REVIEW_PENDING",
    "CLEAN_NEGATIVE_FOLLOWUP_NOT_APPROVED",
    "FIRST_MARKET_DISCLOSURE_TIMESTAMP_UNVERIFIED",
    "METHOD_OWNER_SIGNOFF_MISSING",
)


def csv_table(path, fields):
    rows = read_csv(path, fields)
    return rows


def require_no_existing_outputs(out):
    names = (
        "round2_closure_and_round3_preflight.json",
        "round2_official_document_archive_audit.csv",
        "round3_research_source_manifest.csv",
        "round3_release_gates.json",
    )
    if any((out / name).exists() for name in names):
        raise FileExistsError("round2_closeout_outputs_existing_preserve_review_history")


def safe_archive(root, relative, expected_sha):
    """Verify only pre-existing files under data root; never trust path input."""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha or ""):
        raise ValueError("round2_invalid_primary_document_sha")
    base = Path(root).resolve()
    target = (base / relative).resolve()
    if not target.is_relative_to(base) or not target.is_file() or target.is_symlink():
        raise ValueError("round2_primary_document_path_escape_or_missing")
    if digest(target) != expected_sha:
        raise ValueError("round2_primary_document_archived_bytes_changed")
    return target


def audit_official_legal_files(data, seed):
    root = data / "phase7_official_case_asof_recovery"
    csv_path = root / "phase7_official_source_review.csv"
    actual = csv_table(csv_path, (
        "case_id", "ticker", "source_id", "source_url",
        "file_sha256", "document_identity_status",
        "first_market_disclosure_time_verified", "outcome_label_approved"))
    expected = {}
    for case in seed:
        for source in case["sources"]:
            if source["kind"] == "SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE":
                continue
            expected[source["source_id"]] = (case, source)
    if len(expected) != 4 or len(actual) != 4:
        raise ValueError("round2_legal_source_frozen_inventory_changed")
    rows = []
    for item in actual:
        source_id = item["source_id"]
        if source_id not in expected:
            raise ValueError("round2_unknown_legal_primary_source")
        case, source = expected.pop(source_id)
        if (item["ticker"] != case["ticker"]
            or item["case_id"] != case["case_id"]
            or item["source_url"] != source["url"]):
            raise ValueError("round2_legal_source_registry_identity_conflict")
        require_unapproved(item, (
            "first_market_disclosure_time_verified", "outcome_label_approved"))
        sha = item["file_sha256"]
        integrity = "NO_ARCHIVED_PRIMARY_BYTES"
        if sha:
            path = Path("official_case_bytes") / case["case_id"] / (source_id + ".html")
            archived = safe_archive(root, path, sha)
            receipt = archived.with_suffix(".json")
            if not receipt.is_file() or receipt.is_symlink():
                raise ValueError("round2_legal_primary_archive_receipt_missing")
            meta = json.loads(receipt.read_text(encoding="utf-8"))
            if meta.get("sha256") != sha or meta.get("url") != source["url"]:
                raise ValueError("round2_legal_primary_receipt_hash_or_url_mismatch")
            integrity = "RAW_BYTES_AND_ORIGIN_CLAIM_RECEIPT_HASH_MATCH"
        if (item["document_identity_status"] ==
            "CONTENT_IDENTITY_SUPPORTED_PROVENANCE_REVIEW_OPEN" and not sha):
            raise ValueError("round2_content_identity_without_archived_bytes")
        rows.append({
            "case_id": case["case_id"], "ticker": case["ticker"],
            "source_id": source_id, "official_url": source["url"],
            "archive_file_sha256": sha,
            "receipt_integrity": integrity,
            "content_identity": item["document_identity_status"],
            "official_domain_provenance": "REQUIRES_INDEPENDENT_REVIEW",
            "legal_period_outcome_approved": "false",
            "first_public_revelation_verified": "false",
            "blockers": "PRIMARY_URL_ACQUISITION_AUTHENTICITY_REVIEW|PERIOD_SPECIFIC_LEGAL_ADJUDICATION|FIRST_MARKET_NOTICE",
        })
    if expected:
        raise ValueError("round2_missing_legal_primary_source_ids")
    return rows


def build(data_root, round2_root, out_root, *, expected_report_sha256=None):
    data, current, out = map(Path, (data_root, round2_root, out_root))
    if out.resolve() == current.resolve():
        raise ValueError("round2_closeout_must_not_overwrite_original_review_packet")
    if out.exists():
        require_no_existing_outputs(out)
    report_path = current / "round2_evidence_review_report.json"
    if not report_path.is_file():
        raise ValueError("round2_accepted_report_missing")
    if expected_report_sha256 is not None and digest(report_path) != expected_report_sha256:
        raise ValueError("round2_accepted_report_sha_mismatch")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    expected = {"candidate_case_company_years": 7,
                "separate_alleged_case_quarters": 12,
                "unreviewed_comparison_issuer_quarters": 144,
                "review_template_rows": 163,
                "original_filing_vintages_certified": 0,
                "first_market_disclosure_certified": 0,
                "reviewed_fraud_positives": 0,
                "reviewed_healthy_negatives": 0,
                "supervised_fraud_training_admitted": 0,
                "holdout_1785_excluded": True,
                "unknown_is_never_normal": True,
                "no_automatic_legal_or_filing_certification": True,
                "zero_network_requests": True,
                "zero_production_writes": True}
    if (report.get("status") != "ROUND2_REVIEW_PACKET_BUILT_SUPERVISED_ADMISSION_BLOCKED"
        or any(report.get(k) != v for k, v in expected.items())):
        raise ValueError("round2_prior_status_or_blocked_outcome_changed")

    inputs = [data / path if i != 1 else Path(__file__).with_name(
        "phase1_case_sources_seed.json") for i, path in enumerate(BASE_FILES)]
    recorded = report.get("input_sha256", {})
    if set(recorded) != set(map(str, range(9))):
        raise ValueError("round2_input_sha_manifest_not_nine_entries")
    for i, path in enumerate(inputs):
        if not path.is_file() or digest(path) != recorded[str(i)]:
            raise ValueError("round2_prior_accepted_input_changed:" + str(i))
    evidence = validate(json.loads(inputs[1].read_text(encoding="utf-8")))
    if len(evidence) != 3 or {c["ticker"] for c in evidence} != {"3027", "8299", "6452"}:
        raise ValueError("round2_changed_case_registry_or_holdout")

    case = csv_table(current / ROUND2_FILES[0], CASE_FIELDS)
    alleged = csv_table(current / ROUND2_FILES[1], CASE_FIELDS)
    controls = csv_table(current / ROUND2_FILES[2], CONTROL_FIELDS)
    template = csv_table(current / ROUND2_FILES[3], REVIEW_FIELDS)
    expected_counts = (7, 12, 144, 163)
    if tuple(map(len, (case, alleged, controls, template))) != expected_counts:
        raise ValueError("round2_evidence_sample_unit_counts_changed")
    positions = set()
    for sample in case + alleged + controls:
        ticker = sample["ticker"]
        grain = sample["sample_grain"]
        period = sample["reporting_period"]
        if ticker == "1785" or not re.fullmatch(r"[0-9]{4}", ticker):
            raise ValueError("round2_holdout_or_bad_issuer_in_review")
        key = (ticker, period, grain)
        if key in positions:
            raise ValueError("round2_duplicate_review_sample_unit")
        positions.add(key)
        require_unknown(sample, "independent_period_outcome")
        require_unapproved(sample, ("supervised_training_admitted",))
        if not sample["review_blockers"]:
            raise ValueError("round2_missing_period_review_blocker")
    for sample in case:
        if sample["sample_grain"] != "ANNUAL_CANDIDATE":
            raise ValueError("round2_case_annual_grain_promoted")
    for sample in alleged:
        if sample["ticker"] != "6452" or sample["sample_grain"] != "QUARTER_ALLEGATION":
            raise ValueError("round2_alleged_case_quarter_promoted")
    for sample in controls:
        if sample["ticker"] in {"3027", "8299", "6452"} or sample[
                "sample_grain"] != "QUARTER_COMPARISON_UNLABELED":
            raise ValueError("round2_comparison_case_leakage")
    template_positions = set()
    for item in template:
        p = (item["ticker"], item["reporting_period"], item["sample_grain"])
        if (p not in positions or p in template_positions
            or item["sample_key"] != item["ticker"] + ":" + item["reporting_period"]):
            raise ValueError("round2_human_review_template_identity_mismatch")
        template_positions.add(p)
        if item["method_owner_approval"] != "false" or item["decision_status"] != "NOT_REVIEWED":
            raise ValueError("round2_human_review_template_approval_not_verified")
        if any(item[f] for f in (
            "original_version_sha256", "original_filing_publication_at",
            "first_misstatement_disclosure_at", "outcome_primary_document_sha256",
            "outcome_known_at", "normal_followup_end_at",
            "normal_screening_evidence_sha256", "reviewer_id")):
            raise ValueError("round2_review_form_claims_not_independently_verified")
    if template_positions != positions:
        raise ValueError("round2_human_review_template_missing_units")

    legal_rows = audit_official_legal_files(data, evidence)
    frozen = data / "final_round1_integrated_ml_dataset"
    annual = csv_table(frozen / "annual_12_amount_candidate_index.csv",
                       ("ticker", "fiscal_year", "complete_candidate_vector",
                        "label_status", "training_admitted", "source_sha256"))
    paper = csv_table(frozen / "annual_original_15_paper_candidate_index.csv",
                      ("ticker", "fiscal_year", "evidence_tier",
                       "complete_candidate_vector", "training_admitted",
                       "label_status"))
    sparse = csv_table(frozen / "quarterly_sparse_feature_matrix.csv",
                       ("ticker", "reporting_period", "sample_key", "issuer_split",
                        "time_split", "joint_strict_split", "source_status",
                        "source_sha256", "label_status", "training_admitted",
                        "observed_selected_feature_count", "selected_feature_count"))
    features = csv_table(frozen / "quarterly_fit_selected_feature_dictionary.csv",
                         ("feature_id", "concept_key", "period_grain",
                          "fit_issuer_quarters", "fit_distinct_issuers",
                          "supervised_training_admitted"))
    if (len(annual) != 1560 or len(paper) != 1624
        or len(sparse) != 144 or len(features) != 24):
        raise ValueError("round3_frozen_dataset_size_changed")
    for r in annual + paper + sparse:
        require_unknown(r, "label_status")
        require_unapproved(r, ("training_admitted",))
        if r["ticker"] == "1785":
            raise ValueError("round3_reserved_holdout_training_contamination")
    if sum(r["complete_candidate_vector"] == "true" for r in annual) != 535:
        raise ValueError("round3_annual_full_amount_coverage_changed")
    if sum(r["complete_candidate_vector"] == "true" for r in paper
           if r["evidence_tier"] == "MOPS_OFFICIAL_RETROSPECTIVE") != 11:
        raise ValueError("round3_published_paper_15_coverage_changed")
    for r in sparse:
        key = (r["ticker"], r["reporting_period"])
        if key not in {(x["ticker"], x["reporting_period"]) for x in controls}:
            raise ValueError("round3_sparse_source_not_in_reviewed_quarter_inventory")
        n = int(r["observed_selected_feature_count"])
        if not 0 <= n <= 24 or int(r["selected_feature_count"]) != 24:
            raise ValueError("round3_quarter_feature_count_conflict")
    for f in features:
        require_unapproved(f, ("supervised_training_admitted",))
        if (int(f["fit_distinct_issuers"]) < 3
            or f["feature_id"] not in sparse[0]):
            raise ValueError("round3_feature_dictionary_not_fit_only_or_not_in_matrix")

    round1_report = json.loads(inputs[0].read_text(encoding="utf-8"))
    if (round1_report.get("annual_12_amount_full_12_company_years") != 535
        or round1_report.get("quarter_fit_only_selected_exact_concept_grain_features") != 24
        or round1_report.get("quarter_sparse_observed_selected_feature_cells") !=
            sum(int(x["observed_selected_feature_count"]) for x in sparse)):
        raise ValueError("round3_round1_report_numeric_consistency_conflict")

    transfer = [
        ("FINMIND_PROVISIONAL_ANNUAL_AMOUNTS",
         "annual_12_amount_candidate_index.csv", annual, "COMPANY_YEAR",
         "FINMIND_PROVISIONAL_12_AMOUNTS", "RETROSPECTIVE_AMOUNT_FORECASTING_ONLY",
         "financial amounts are not verified fraud labels"),
        ("ORIGINAL_PAPER_FEATURE_RETROSPECTIVE",
         "annual_original_15_paper_candidate_index.csv", paper,
         "ISSUER_YEAR_SOURCE_TIER", "FINMIND_VS_MOPS_NOT_FUSED",
         "RETROSPECTIVE_MISSINGNESS_AND_FORMULA_COMPARISON_ONLY",
         "11 official retrospective fully available paper-feature years, not authentic original-vintage years"),
        ("COMPARISON_QUARTER_FIT_ONLY_24_FEATURES",
         "quarterly_sparse_feature_matrix.csv", sparse,
         "COMPANY_QUARTER", "MOPS_RETROSPECTIVE_24_EXACT_CONCEPTS",
         "UNLABELED_MISSINGNESS_AND_ANOMALY_ENGINEERING_ONLY",
         "fit-only feature selection; no true negatives or original historical vintages"),
    ]
    transfer_rows = []
    for name, filename, records, grain, tier, use, warning in transfer:
        path = frozen / filename
        transfer_rows.append({
            "source_id": name, "file_path": filename,
            "source_sha256": digest(path),
            "sample_grain": grain, "independent_sample_count": len(records),
            "source_tier": tier, "safe_current_use": use,
            "fraud_supervised_use": "BLOCKED",
            "historical_asof_certified": "false",
            "transfer_warning": warning,
        })
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "round2_official_document_archive_audit.csv",
              CASE_SOURCE_FIELDS, legal_rows)
    write_csv(out / "round3_research_source_manifest.csv",
              TRANSFER_FIELDS, transfer_rows)
    closeout = {
        "status": "ROUND2_ENGINEERING_CLOSEOUT_VERIFIED_HUMAN_GROUND_TRUTH_PENDING",
        "accepted_round2_report_sha256": digest(report_path),
        "round2_source_sha256_verified": len(inputs),
        "review_packet_csv_count": len(ROUND2_FILES),
        "case_annual_review_rows": len(case),
        "case_quarter_review_rows": len(alleged),
        "unreviewed_comparison_quarters": len(controls),
        "reviewer_template_rows": len(template),
        "official_legal_sources_hashed_against_archived_bytes": sum(
            row["receipt_integrity"] ==
            "RAW_BYTES_AND_ORIGIN_CLAIM_RECEIPT_HASH_MATCH" for row in legal_rows),
        "legal_sources_content_identity_supported_not_outcome": sum(
            row["content_identity"] ==
            "CONTENT_IDENTITY_SUPPORTED_PROVENANCE_REVIEW_OPEN" for row in legal_rows),
        "official_legal_source_retrieval_provenance_independently_verified": 0,
        "original_first_filed_versions_independently_certified": 0,
        "original_filing_first_publication_times_certified": 0,
        "first_market_revelation_dates_certified": 0,
        "adjudicated_case_periods": 0,
        "independently_followed_up_normal_periods": 0,
        "reviewed_positive_labels": 0,
        "reviewed_negative_labels": 0,
        "supervised_fraud_training_admitted": 0,
        "round2_engineering_gates_passed": True,
        "round2_research_label_acceptance_passed": False,
        "holdout_1785_untouched": True,
        "network_calls": 0, "production_db_writes": 0,
        "unresolved_gates": list(BLOCKERS),
        "round3_source_manifest_sha256": digest(out / "round3_research_source_manifest.csv"),
    }
    release = {
        "status": "ROUND3_PREPARED_RESEARCH_ONLY_NO_FRAUD_CLASSIFIER_FIT",
        "dataset_stage_ready": True,
        "reproducible_source_tiers_kept_separate": True,
        "annual_provisional_full_12_amount_company_years": 535,
        "paper_original_formula_official_retrospective_complete_years": 11,
        "quarter_unlabeled_comparison_rows": 144,
        "quarter_fit_only_features": 24,
        "quarter_observed_feature_cells": 2232,
        "supervised_fraud_train_allowed": False,
        "supervised_fraud_validation_allowed": False,
        "supervised_fraud_test_allowed": False,
        "literature_baseline_fraud_auc_allowed": False,
        "historical_asof_case_replay_allowed": False,
        "unlabeled_anomaly_diagnostics_allowed": True,
        "amount_forecasting_research_only_allowed": True,
        "final_1785_holdout_restricted": True,
        "supervised_blockers": list(BLOCKERS),
        "source_transfer_manifest_sha256": digest(out / "round3_research_source_manifest.csv"),
    }
    (out / "round2_closure_and_round3_preflight.json").write_text(
        json.dumps(closeout, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (out / "round3_release_gates.json").write_text(
        json.dumps(release, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return closeout, release


def main(argv=None):
    parser = argparse.ArgumentParser(description="Round2 archived source integrity and Round3 training preflight")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--round2-review-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--expected-round2-sha256", default="")
    args = parser.parse_args(argv)
    result, release = build(args.data_root, args.round2_review_root, args.output,
                            expected_report_sha256=args.expected_round2_sha256 or None)
    print(json.dumps({"round2": result, "round3": release},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
