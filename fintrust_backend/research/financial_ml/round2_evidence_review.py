"""Round2 offline reviewer packet. Evidence status != verified supervision.

Reuses Phase1/7/8/10 and Round1 manifests. Never upgrades UNKNOWN to 0/1,
never changes archives, and keeps final case 1785 outside all research rows.
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

CASE_FIELDS = (
    "case_id", "ticker", "reporting_period", "sample_grain",
    "court_or_claim_status", "report_status", "official_source_sha256",
    "official_content_identity", "original_as_first_published_status",
    "earliest_market_notice_status", "paper_components", "paper_total",
    "independent_period_outcome", "supervised_training_admitted",
    "review_blockers",
)
CONTROL_FIELDS = (
    "ticker", "reporting_period", "sample_grain", "source_status",
    "source_sha256", "original_as_first_published_status",
    "historical_listing_status", "followup_negative_review",
    "independent_period_outcome", "supervised_training_admitted",
    "review_blockers",
)
REVIEW_FIELDS = (
    "sample_key", "ticker", "reporting_period", "sample_grain",
    "proposed_class", "original_version_sha256", "original_filing_publication_at",
    "first_misstatement_disclosure_at", "outcome_primary_document_sha256",
    "outcome_primary_document_locator", "outcome_known_at",
    "normal_followup_end_at", "normal_screening_evidence_sha256",
    "reviewer_id", "method_owner_approval", "decision_status",
)
CASE_QUARTERS = (
    "2017Q2", "2017Q3", "2017Q4", "2018Q1", "2018Q2", "2018Q3",
    "2018Q4", "2019Q1", "2019Q2", "2019Q3", "2019Q4", "2020Q1",
)
ROUND1_HASH_KEYS = {
    "case_official_15_paper_candidate_separate.csv": None,
    "phase10_case_official_paper_features.csv":
        "phase10_case_official_paper_features.csv:5",
    "quarterly_issuer_period_source_index.csv": None,
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_csv(path, required):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        source = csv.DictReader(handle)
        if not set(required).issubset(source.fieldnames or ()):
            raise ValueError("round2_source_schema_missing:" + Path(path).name)
        items = list(source)
    if not items:
        raise ValueError("round2_empty_source:" + Path(path).name)
    return items


def write_csv(path, fields, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def require_unapproved(row, fields):
    for field in fields:
        if str(row.get(field, "")).strip().lower() != "false":
            raise ValueError("round2_source_approval_forged:" + field)


def require_unknown(row, key):
    if row.get(key) != "UNKNOWN":
        raise ValueError("round2_source_outcome_forged:" + key)


def source_table(root, path, required):
    candidate = root / path
    if not candidate.is_file():
        raise ValueError("round2_required_previous_result_missing:" + str(path))
    return read_csv(candidate, required), candidate


def build(data_root, output_root):
    data, out = Path(data_root), Path(output_root)
    baseline_dir = data / "final_round1_integrated_ml_dataset"
    round1_path = baseline_dir / "round1_dataset_readiness_report.json"
    if not round1_path.is_file():
        raise ValueError("round2_round1_accepted_report_missing")
    baseline = json.loads(round1_path.read_text(encoding="utf-8"))
    if (baseline.get("status") !=
            "FINALIZATION_ROUND1_REAL_TAIWAN_DATA_INTEGRATED_RESEARCH_TIERS_QA"
        or baseline.get("last_event_holdout_1785_excluded") is not True
        or any(baseline.get(x) != 0 for x in (
            "approved_positive_labels", "approved_negative_labels",
            "fraud_supervised_training_rows_admitted",
            "original_first_filing_versions_verified",
            "first_publication_times_verified"))):
        raise ValueError("round2_prior_acceptance_or_outcome_contract_changed")
    seed_path = Path(__file__).with_name("phase1_case_sources_seed.json")
    cases = validate(json.loads(seed_path.read_text(encoding="utf-8")))
    case_map = {str(c["ticker"]): c for c in cases}
    expected = {(str(c["ticker"]), str(year)) for c in cases
                for year in c["affected_fiscal_years"]}
    if len(expected) != 7 or "1785" in case_map:
        raise ValueError("round2_frozen_case_seed_not_7_years")

    paper, paper_path = source_table(
        data, Path("phase10_case_official_paper_audit") /
        "phase10_case_official_paper_features.csv",
        ("ticker", "fiscal_year", "source_sha256", "official_xbrl_status",
         "components_computed", "components_required", "outcome_label",
         "approved_positive_label", "approved_negative_label",
         "original_filing_vintage_verified",
         "historical_filing_publication_at_verified",
         "original_notice_publication_at_verified",
         "admitted_for_supervised_learning"))
    original_13, original_path = source_table(
        data, Path("final_round1_integrated_ml_dataset") /
        "case_official_15_paper_candidate_separate.csv",
        ("ticker", "fiscal_year", "source_sha256", "label_status",
         "training_admitted"))
    quarters, quarters_path = source_table(
        data, Path("final_round1_integrated_ml_dataset") /
        "quarterly_issuer_period_source_index.csv",
        ("ticker", "reporting_period", "data_role", "source_status",
         "source_sha256", "label_status", "training_admitted"))
    sparse, sparse_path = source_table(
        data, Path("final_round1_integrated_ml_dataset") /
        "quarterly_sparse_feature_matrix.csv",
        ("ticker", "reporting_period", "source_sha256", "source_status",
         "label_status", "training_admitted"))
    official, official_path = source_table(
        data, Path("phase7_official_case_asof_recovery") /
        "phase7_official_source_review.csv",
        ("ticker", "source_id", "document_identity_status", "file_sha256",
         "first_market_disclosure_time_verified", "outcome_label_approved"))
    vintage, vintage_path = source_table(
        data, Path("phase8_case_original_filing_recovery") /
        "original_case_filing_source_intake.csv",
        ("ticker", "fiscal_year", "local_original_candidate_status",
         "local_source_sha256", "publication_time_independently_verified",
         "original_version_independently_verified", "supervised_label",
         "training_admitted"))
    phase8_report = data / "phase8_case_original_filing_recovery" / "phase8_integrated_report.json"
    if not phase8_report.is_file():
        raise ValueError("round2_phase8_integrated_report_missing")
    phase8 = json.loads(phase8_report.read_text(encoding="utf-8"))
    if (phase8.get("holdout_1785_never_used") is not True
        or phase8.get("positive_labels_admitted") != 0
        or phase8.get("negative_labels_admitted") != 0
        or phase8.get("supervised_model_training_admitted") is not False):
        raise ValueError("round2_phase8_approval_or_holdout_changed")
    if digest(paper_path) != baseline["input_sha256"][
            "phase10_case_official_paper_features.csv:5"]:
        raise ValueError("round2_prior_round1_case_source_changed")

    original_index = {}
    for r in original_13:
        key = (r["ticker"], r["fiscal_year"])
        if key in original_index or r["ticker"] not in case_map:
            raise ValueError("round2_case_original_index_duplicate_or_unknown")
        require_unknown(r, "label_status")
        require_unapproved(r, ("training_admitted",))
        original_index[key] = r
    paper_index = {}
    for r in paper:
        key = (r["ticker"], r["fiscal_year"])
        if key in paper_index or key not in original_index:
            raise ValueError("round2_case_paper_index_duplicate_or_unknown")
        require_unknown(r, "outcome_label")
        require_unapproved(r, (
            "approved_positive_label", "approved_negative_label",
            "admitted_for_supervised_learning",
            "original_filing_vintage_verified",
            "historical_filing_publication_at_verified",
            "original_notice_publication_at_verified"))
        if (r["source_sha256"] != original_index[key]["source_sha256"]
            or int(r["components_required"]) != 15
            or not 0 <= int(r["components_computed"]) <= 15):
            raise ValueError("round2_paper_original_evidence_disagreement")
        paper_index[key] = r
    if len(paper_index) != 13 or set(paper_index) != set(original_index):
        raise ValueError("round2_incomplete_13_case_research_source_years")

    sources_by_case = {ticker: [] for ticker in case_map}
    seen_sources = set()
    for row in official:
        ticker, source_id = row["ticker"], row["source_id"]
        if ticker not in sources_by_case or source_id in seen_sources:
            raise ValueError("round2_invalid_or_duplicate_case_legal_source")
        seen_sources.add(source_id)
        require_unapproved(row, (
            "first_market_disclosure_time_verified", "outcome_label_approved"))
        sha = row["file_sha256"]
        if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError("round2_case_legal_source_sha_invalid")
        sources_by_case[ticker].append(row)
    if len(seen_sources) != 4:
        raise ValueError("round2_expected_four_primary_legal_sources")

    vintage_index = {}
    for row in vintage:
        key = (row["ticker"], row["fiscal_year"])
        if key in vintage_index or key not in paper_index:
            raise ValueError("round2_case_original_vintage_duplicate_or_unknown")
        require_unknown(row, "supervised_label")
        require_unapproved(row, ("training_admitted",))
        vintage_index[key] = row
    if set(vintage_index) != set(paper_index):
        raise ValueError("round2_case_vintage_13_years_incomplete")

    case_year_rows = []
    for ticker, year in sorted(expected):
        case = case_map[ticker]
        paper_row, first = paper_index[(ticker, year)], vintage_index[(ticker, year)]
        identity = any(s["document_identity_status"] ==
                       "CONTENT_IDENTITY_SUPPORTED_PROVENANCE_REVIEW_OPEN"
                       for s in sources_by_case[ticker])
        blockers = ["AFFECTED_PERIOD_INDEPENDENT_ADJUDICATION",
                    "FIRST_PUBLIC_MARKET_DISCLOSURE_ARCHIVE",
                    "METHOD_OWNER_REVIEW"]
        if not identity:
            blockers.append("PRIMARY_LEGAL_DOCUMENT_IDENTITY")
        if (first["original_version_independently_verified"] != "true"
            or first["publication_time_independently_verified"] != "true"):
            blockers.append("AS_FIRST_PUBLISHED_FILING_AND_TIMESTAMP")
        if int(paper_row["components_computed"]) < 15:
            blockers.append("INCOMPLETE_ORIGINAL_PAPER_15")
        case_year_rows.append({
            "case_id": case["case_id"], "ticker": ticker,
            "reporting_period": year, "sample_grain": "ANNUAL_CANDIDATE",
            "court_or_claim_status": case["legal_status"],
            "report_status": paper_row["official_xbrl_status"],
            "official_source_sha256": paper_row["source_sha256"],
            "official_content_identity": str(identity).lower(),
            "original_as_first_published_status":
                first["local_original_candidate_status"],
            "earliest_market_notice_status": "NOT_INDEPENDENTLY_VERIFIED",
            "paper_components": paper_row["components_computed"],
            "paper_total": 15,
            "independent_period_outcome": "UNKNOWN",
            "supervised_training_admitted": "false",
            "review_blockers": "|".join(blockers),
        })

    quarter_index = {}
    for r in quarters:
        key = (r["ticker"], r["reporting_period"])
        if key in quarter_index or r["ticker"] == "1785":
            raise ValueError("round2_duplicate_or_holdout_quarter")
        require_unknown(r, "label_status")
        require_unapproved(r, ("training_admitted",))
        quarter_index[key] = r
    if (len(quarter_index) != 156
        or len([r for r in quarters if r["data_role"] ==
                "ALLEGED_EVENT_PERIOD_NOT_CONFIRMED_POSITIVE"]) != 12):
        raise ValueError("round2_quarter_index_not_frozen_156")
    case_quarters = []
    for period in CASE_QUARTERS:
        row = quarter_index.get(("6452", period))
        if row is None or row["data_role"] != "ALLEGED_EVENT_PERIOD_NOT_CONFIRMED_POSITIVE":
            raise ValueError("round2_case_quarter_missing_or_role_promoted")
        case_quarters.append({
            "case_id": case_map["6452"]["case_id"], "ticker": "6452",
            "reporting_period": period, "sample_grain": "QUARTER_ALLEGATION",
            "court_or_claim_status": case_map["6452"]["legal_status"],
            "report_status": row["source_status"],
            "official_source_sha256": row["source_sha256"],
            "official_content_identity": "not_a_legal_outcome",
            "original_as_first_published_status": "UNVERIFIED",
            "earliest_market_notice_status": "NOT_INDEPENDENTLY_VERIFIED",
            "paper_components": "", "paper_total": "",
            "independent_period_outcome": "UNKNOWN",
            "supervised_training_admitted": "false",
            "review_blockers": "PERIOD_SPECIFIC_LEGAL_FINDING|AS_FIRST_PUBLISHED_FILING_AND_TIMESTAMP|FIRST_PUBLIC_MARKET_DISCLOSURE_ARCHIVE|METHOD_OWNER_REVIEW",
        })

    sparse_index = {}
    for row in sparse:
        key = (row["ticker"], row["reporting_period"])
        if key in sparse_index:
            raise ValueError("round2_duplicate_quarter_sparse_matrix")
        require_unknown(row, "label_status")
        require_unapproved(row, ("training_admitted",))
        sparse_index[key] = row
    controls = []
    for key, row in sorted(quarter_index.items()):
        if row["data_role"] != "UNLABELED_MULTIISSUER_COMPARISON":
            continue
        ticker, period = key
        if ticker in case_map or ticker == "1785":
            raise ValueError("round2_case_promoted_into_normal_comparison")
        other = sparse_index.get(key)
        if (other is None or row["source_sha256"] != other["source_sha256"]
            or row["source_status"] != other["source_status"]):
            raise ValueError("round2_quarter_sparse_source_disagreement")
        blockers = ["HISTORICAL_LISTING_AND_FOLLOWUP",
                    "INDEPENDENT_NORMAL_REVIEW", "ORIGINAL_REPORT_VERSION",
                    "FILING_PUBLISH_TIMESTAMP", "METHOD_OWNER_REVIEW"]
        if not row["source_sha256"]:
            blockers.append("OFFICIAL_QUARTER_SOURCE_MISSING")
        controls.append({
            "ticker": ticker, "reporting_period": period,
            "sample_grain": "QUARTER_COMPARISON_UNLABELED",
            "source_status": row["source_status"],
            "source_sha256": row["source_sha256"],
            "original_as_first_published_status": "UNVERIFIED",
            "historical_listing_status": "UNVERIFIED",
            "followup_negative_review": "UNREVIEWED",
            "independent_period_outcome": "UNKNOWN",
            "supervised_training_admitted": "false",
            "review_blockers": "|".join(blockers),
        })
    if (len(controls) != 144 or len(sparse_index) != 144
        or len({r["ticker"] for r in controls}) != 12):
        raise ValueError("round2_comparison_not_frozen_12_by_12")

    review = []
    for row in case_year_rows + case_quarters + controls:
        proposal = ("REVIEW_POSITIVE_ONLY" if row.get("case_id")
                    else "REVIEW_NORMAL_ONLY")
        key = row["ticker"] + ":" + row["reporting_period"]
        review.append({
            "sample_key": key, "ticker": row["ticker"],
            "reporting_period": row["reporting_period"],
            "sample_grain": row["sample_grain"],
            "proposed_class": proposal,
            "original_version_sha256": "", "original_filing_publication_at": "",
            "first_misstatement_disclosure_at": "",
            "outcome_primary_document_sha256": "",
            "outcome_primary_document_locator": "", "outcome_known_at": "",
            "normal_followup_end_at": "", "normal_screening_evidence_sha256": "",
            "reviewer_id": "", "method_owner_approval": "false",
            "decision_status": "NOT_REVIEWED",
        })
    # Stable internal key: same issuer/year and issuer/quarter are distinct,
    # and no holdout or duplicate annual/quarter key exists.
    if len({(r["sample_grain"], r["sample_key"]) for r in review}) != len(review):
        raise ValueError("round2_duplicate_review_sample_key")
    # Never overwrite a human-edited review template or a previous audit run.
    # Reprocessing must use a new output directory after archival/review.
    if out.exists() and any(out.glob("round2_*.csv")):
        raise FileExistsError("round2_existing_review_packet_preserve_reviewers")
    if (out / "round2_evidence_review_report.json").exists():
        raise FileExistsError("round2_existing_review_report_preserve_inputs")
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "round2_case_year_review.csv", CASE_FIELDS, case_year_rows)
    write_csv(out / "round2_case_quarter_review.csv", CASE_FIELDS, case_quarters)
    write_csv(out / "round2_unreviewed_comparison_quarters.csv",
              CONTROL_FIELDS, controls)
    write_csv(out / "round2_independent_review_template.csv",
              REVIEW_FIELDS, review)
    input_paths = (round1_path, seed_path, paper_path, original_path,
                   quarters_path, sparse_path, official_path, vintage_path,
                   phase8_report)
    report = {
        "status": "ROUND2_REVIEW_PACKET_BUILT_SUPERVISED_ADMISSION_BLOCKED",
        "round1_status": baseline["status"],
        "candidate_case_company_years": len(case_year_rows),
        "separate_alleged_case_quarters": len(case_quarters),
        "unreviewed_comparison_issuer_quarters": len(controls),
        "comparison_issuers": len({r["ticker"] for r in controls}),
        "case_annual_complete_retrospective_15": sum(
            int(r["paper_components"]) == 15 for r in case_year_rows),
        "case_legal_sources_with_content_identity": sum(
            r["document_identity_status"] ==
            "CONTENT_IDENTITY_SUPPORTED_PROVENANCE_REVIEW_OPEN"
            for r in official),
        "case_source_status": dict(Counter(r["report_status"] for r in case_year_rows)),
        "comparison_source_status": dict(Counter(r["source_status"] for r in controls)),
        "review_template_rows": len(review),
        "original_filing_vintages_certified": 0,
        "first_market_disclosure_certified": 0,
        "reviewed_fraud_positives": 0,
        "reviewed_healthy_negatives": 0,
        "supervised_fraud_training_admitted": 0,
        "holdout_1785_excluded": True,
        "unknown_is_never_normal": True,
        "no_automatic_legal_or_filing_certification": True,
        "zero_network_requests": True,
        "zero_production_writes": True,
        "input_sha256": {str(i): digest(p) for i, p in enumerate(input_paths)},
        "next_required": (
            "Human document provenance, period-specific legal decision, "
            "original first-filed report timestamps, independent negative "
            "followup and methodological signoff. A filled template by "
            "itself is NOT admission or proof of label status."
        ),
    }
    (out / "round2_evidence_review_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Round2 offline source/label review packet")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.data_root, args.output),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
