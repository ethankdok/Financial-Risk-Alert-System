"""Phase 1: provenance-first Taiwan material financial misstatement case registry.

This is a RESEARCH CANDIDATE registry, deliberately separate from the
production case_labels module and from ML feature extraction. No candidate
may become a supervised 0/1 label until version, public time, source archive,
reporting scope and independent method review pass. No API or DB writes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

SEED_SCHEMA = "tw_financial_misstatement_case_registry_v1"
ALLOWED_ROLES = {"DEVELOPMENT_CANDIDATE"}
LEGAL_CATEGORIES = {
    "FIRST_INSTANCE_CRIMINAL_JUDGMENT_NOT_FINALITY_VERIFIED",
    "APPELLATE_COURT_FINDINGS_REQUIRE_EXACT_PERIOD_AND_FINALITY_REVIEW",
    "SUPREME_CIVIL_REMAND_WITH_SEPARATE_FINAL_CRIMINAL_CASE_REFERENCED",
    "OFFICIAL_CIVIL_CLAIM_NOT_ADJUDICATED_FOR_ALL_AFFECTED_PERIODS",
}
INCIDENT_CATEGORIES = {
    "MATERIAL_FINANCIAL_MISSTATEMENT_COURT_FINDING",
    "REPORTED_MISSTATEMENT_AND_REQUIRED_RESTATEMENT",
    "OFFICIALLY_DOCUMENTED_ALLEGED_FINANCIAL_MISSTATEMENT",
}
EVIDENCE_KINDS = {
    "JUDICIAL_JUDGMENT",
    "INVESTOR_PROTECTION_CENTER_STATEMENT",
    "SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE",
}
FIELDS = (
    "case_id", "ticker", "company", "fiscal_year", "statement_scope",
    "incident_type", "legal_status", "mechanism",
    "affected_reporting_period_description",
    "candidate_outcome_state", "supervised_label", "candidate_first_public_notice_at",
    "first_public_disclosure_primary_archived", "legal_evidence_document_date",
    "source_document_dates", "source_ids", "review_missing",
    "original_filing_pit_verified", "source_text_archived",
    "admitted_into_model_training", "admitted_into_model_validation",
    "admitted_into_model_test", "holdout_1785_excluded",
)


def _aware_datetime(value, name):
    if not isinstance(value, str) or not value:
        raise ValueError(f"missing_{name}")
    try:
        result = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(f"invalid_{name}") from None
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"datetime_must_be_timezone_aware:{name}")
    return result


def _safe_source(source):
    if not isinstance(source, dict):
        raise ValueError("source_must_be_object")
    if source.get("kind") not in EVIDENCE_KINDS:
        raise ValueError("unknown_source_kind")
    url = source.get("url", "")
    parsed = urlparse(url)
    # Only known evidence domains are allowed in this explicitly reviewed seed.
    domains = {
        "judgment.judicial.gov.tw",
        "www.sfipc.org.tw",
        "news.pts.org.tw",
    }
    if parsed.scheme != "https" or parsed.hostname not in domains:
        raise ValueError("unreviewed_or_non_https_evidence_url")
    try:
        date.fromisoformat(source["source_document_date"])
    except (ValueError, KeyError, TypeError):
        raise ValueError("invalid_source_document_date") from None
    digest = source.get("archive_sha256")
    if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("bad_evidence_archive_sha256")
    if not isinstance(source.get("source_id"), str) or not source["source_id"]:
        raise ValueError("missing_source_id")
    if not source.get("support") or not source.get("source_text_location"):
        raise ValueError("missing_source_quote_locator")
    return digest is not None


def validate(seed):
    if not isinstance(seed, dict) or seed.get("schema_version") != SEED_SCHEMA:
        raise ValueError("unknown_case_seed_schema")
    hold = seed.get("reserved_final_holdout", {})
    if (hold.get("ticker") != "1785" or hold.get("in_any_training_or_hyperparameter_selection") is not False):
        raise ValueError("1785_holdout_must_be_reserved")
    transfer = seed.get("transfer_policy", {})
    if (transfer.get("auto_admit_foreign_examples") is not False
            or transfer.get("auto_admit_synthetic_labels") is not False
            or not transfer.get("required_before_claiming_transfer_success")):
        raise ValueError("unsafe_external_or_synthetic_label_policy")
    cases = seed.get("candidates")
    if not isinstance(cases, list) or not cases:
        raise ValueError("case_registry_empty_or_invalid")
    known_cases, known_sources, known_years = set(), set(), set()
    for case in cases:
        ticker = str(case.get("ticker") or "")
        if ticker == "1785" or not re.fullmatch(r"[0-9]{4}", ticker):
            raise ValueError("case_holdout_or_bad_ticker")
        if case.get("country") != "TW" or case.get("role") not in ALLOWED_ROLES:
            raise ValueError("case_not_taiwan_development_candidate")
        if (case.get("legal_status") not in LEGAL_CATEGORIES
                or case.get("incident_type") not in INCIDENT_CATEGORIES):
            raise ValueError("case_event_category_not_reviewed")
        if not case.get("mechanism") or case.get("statement_scope") != "consolidated":
            raise ValueError("scope_or_accounting_mechanism_missing")
        cid = case.get("case_id")
        if not isinstance(cid, str) or not cid or cid in known_cases:
            raise ValueError("duplicate_or_empty_case_id")
        known_cases.add(cid)
        years = case.get("affected_fiscal_years")
        if (not isinstance(years, list) or not years
                or any(not isinstance(y, int) or isinstance(y, bool) or y < 2013 or y > 2025 for y in years)
                or len(set(years)) != len(years)):
            raise ValueError("invalid_or_duplicate_affected_year")
        notice = case.get("initial_disclosure_candidate_at")
        if notice is not None:
            _aware_datetime(notice, "first_notice_candidate")
        try:
            date.fromisoformat(case["legal_evidence_document_date"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("bad_legal_evidence_document_date") from None
        if case.get("legal_evidence_online_publication_time_verified") is not False:
            raise ValueError("judgment_document_date_is_not_a_public_timestamp")
        if case.get("first_public_disclosure_primary_archived") is not False:
            raise ValueError("unverified_first_disclosure_must_not_be_promoted")
        review = case.get("review")
        mandatory = ("first_notice_archived", "affected_period_reviewed",
                     "judgment_paragraph_checked", "original_filing_availability_verified",
                     "label_method_owner_approved")
        if not isinstance(review, dict) or any(review.get(key) is not False for key in mandatory):
            raise ValueError("manual_review_flags_cannot_be_preapproved")
        sources = case.get("sources")
        if not isinstance(sources, list) or not sources:
            raise ValueError("missing_case_sources")
        authoritative = False
        for source in sources:
            _safe_source(source)
            if source["source_id"] in known_sources:
                raise ValueError("duplicate_evidence_source_id")
            known_sources.add(source["source_id"])
            if source["kind"] != "SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE":
                authoritative = True
        if not authoritative:
            raise ValueError("only_secondary_evidence_for_case")
        for year in years:
            key = (ticker, year)
            if key in known_years:
                raise ValueError("duplicate_company_year_case_claim")
            known_years.add(key)
    return cases


def extract(seed_file, output):
    source_path = Path(seed_file)
    raw = source_path.read_bytes()
    seed = json.loads(raw)
    cases = validate(seed)
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    flattened = []
    evidence = []
    for case in cases:
        cid = case["case_id"]
        status = ("COURT_DECISION_REVIEW_PENDING"
                  if case["incident_type"] == "MATERIAL_FINANCIAL_MISSTATEMENT_COURT_FINDING"
                  else "UNRESOLVED_CASE_REVIEW_PENDING")
        for source in case["sources"]:
            evidence.append({
                "case_id": cid, "source_id": source["source_id"], "kind": source["kind"],
                "url": source["url"], "source_document_date": source["source_document_date"],
                "archive_sha256": source["archive_sha256"] or "",
                "source_text_location": source["source_text_location"],
                "archive_verified": "false"
            })
        missing = [k for k, ready in case["review"].items() if not ready]
        if any(s["archive_sha256"] is None for s in case["sources"]):
            missing.append("full_primary_source_bytes_sha256")
        if case["initial_disclosure_candidate_at"] is None:
            missing.append("dated_first_public_disclosure")
        for year in sorted(case["affected_fiscal_years"]):
            flattened.append({
                "case_id": cid, "ticker": case["ticker"], "company": case["company"],
                "fiscal_year": year, "statement_scope": case["statement_scope"],
                "incident_type": case["incident_type"], "legal_status": case["legal_status"],
                "mechanism": case["mechanism"],
                "affected_reporting_period_description": case["affected_reporting_period_description"],
                "candidate_outcome_state": status,
                "supervised_label": "UNKNOWN",
                "candidate_first_public_notice_at": case["initial_disclosure_candidate_at"] or "",
                "first_public_disclosure_primary_archived": "false",
                "legal_evidence_document_date": case["legal_evidence_document_date"],
                "source_document_dates": "|".join(s["source_document_date"] for s in case["sources"]),
                "source_ids": "|".join(s["source_id"] for s in case["sources"]),
                "review_missing": "|".join(sorted(missing)),
                "original_filing_pit_verified": "false",
                "source_text_archived": "false",
                "admitted_into_model_training": "false",
                "admitted_into_model_validation": "false",
                "admitted_into_model_test": "false",
                "holdout_1785_excluded": "true"
            })
    with (target / "taiwan_case_year_candidates.csv").open(
            "w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(flattened)
    evidence_fields = ("case_id", "source_id", "kind", "url",
                       "source_document_date", "archive_sha256",
                       "source_text_location", "archive_verified")
    with (target / "taiwan_case_evidence_register.csv").open(
            "w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=evidence_fields)
        writer.writeheader()
        writer.writerows(evidence)
    report = {
        "status": "PHASE1_CASE_CANDIDATE_REVIEW_ONLY_NO_OUTCOME_LABELS_ADMITTED",
        "source_seed_sha256": hashlib.sha256(raw).hexdigest(),
        "candidate_cases": len(cases),
        "candidate_company_years": len(flattened),
        "case_tickers": sorted(c["ticker"] for c in cases),
        "evidence_reference_count": len(evidence),
        "archived_primary_source_count": 0,
        "candidate_year_categories": dict(Counter(r["candidate_outcome_state"] for r in flattened)),
        "approved_positive_labels": 0, "approved_negative_labels": 0,
        "training_rows_admitted": 0, "validation_rows_admitted": 0,
        "test_rows_admitted": 0, "first_notice_original_archive_verified": False,
        "original_financial_report_pit_version_verified": False,
        "holdout_case": "1785", "reserved_holdout_used": False,
        "foreign_or_synthetic_auto_approved": False,
        "source_policy": seed["transfer_policy"],
        "production_db_writes": 0, "network_requests": 0,
        "next_gates": [
            "archive_official_court_and_original_MOPS_notice_bytes_and_SHA256",
            "review_judgment_findings_vs_allegations_and_trial_appeal_finality",
            "confirm_exact_issuer_filing_period_scope_and_pre_correction_version",
            "verify_first_notice_public_time_and_filing_original_publication_time",
            "freeze_separate_dev_validation_and_holdout_case_assignments",
            "review_US_and_synthetic_domain_transfer_on_Taiwan_only_data_before_usage"
        ],
        "warning": ("Case candidates, including confirmed court-document descriptions, "
                    "are NOT blindly admitted 1/0 labels. Source archive, precise "
                    "public knowledge time, reporting scope, legal basis and human "
                    "approval remain required. 1785 is strictly held out.")
    }
    (target / "phase1_case_readiness.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Phase1 official evidence case catalogue, no label admission")
    p.add_argument("--seed-file", default=str(Path(__file__).with_name("phase1_case_sources_seed.json")))
    p.add_argument("--output", required=True)
    args = p.parse_args(argv)
    print(json.dumps(extract(args.seed_file, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
