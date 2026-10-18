"""One Phase8 invocation: verified judiciary compatibility + historical-filing PIT intake."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .phase7_evidence_asof_audit import audit as collect_case_sources
from .phase8_original_filing_intake import intake_report


def run(data_root, *, retrieve=True):
    root=Path(data_root)
    evidence=root/"phase7_official_case_asof_recovery"
    outcome=root/"phase8_case_original_filing_recovery"
    source_manifest=root/"phase7_official_manual_imports.csv"
    filing_manifest=root/"phase8_original_filing_intake.csv"
    phase7=collect_case_sources(
        root,evidence,retrieve=retrieve,
        imports=source_manifest if source_manifest.is_file() else None,
        pace_seconds=2.0 if retrieve else 0.0)
    phase8=intake_report(
        root,evidence,outcome,
        import_manifest=filing_manifest if filing_manifest.is_file() else None)
    combined={
        "status":"PHASE8_TLS_AND_ORIGINAL_FILING_RECOVERY_EXECUTED_PIT_APPROVAL_PENDING",
        "official_case_sources_expected":phase7["primary_source_count"],
        "official_case_content_identity_passed":phase7[
            "archived_primary_sources_with_docket_and_company"],
        "official_case_source_failures":phase7["source_failures"],
        "original_filing_company_years_needed":phase8["unique_source_year_requirements"],
        "historical_year_window_slot_requirements":phase8["phase7_year_window_slots"],
        "prior_official_year_archives_sha_verified":phase8[
            "existing_official_hash_verified_years"],
        "manual_original_filing_candidates_imported":phase8[
            "user_submitted_original_candidate_years"],
        "verified_original_filing_versions":phase8[
            "independently_verified_original_versions"],
        "first_disclosure_time_verified":phase7[
            "first_public_disclosure_times_verified"],
        "positive_labels_admitted":0,"negative_labels_admitted":0,
        "supervised_model_training_admitted":False,
        "holdout_1785_never_used":True,
        "production_db_writes":0,
        "collection_network_opt_in":retrieve,
        "source_reports":{
            "case_official":str(evidence/"phase7_evidence_asof_report.json"),
            "original_vintage":str(outcome/"phase8_original_filing_readiness.json")
        },
        "source_sha256":{
            "case_official_report":hashlib.sha256(
                (evidence/"phase7_evidence_asof_report.json").read_bytes()).hexdigest(),
            "historical_filing_gap":hashlib.sha256(
                (outcome/"original_case_filing_source_intake.csv").read_bytes()).hexdigest()
        },
        "scientific_warning":"Archived court documents and retrospectively filed XBRL do NOT "
            "certify actual pre-correction issuer filings, disclosure times, "
            "verified outcome labels or ex-ante fraud prediction."
    }
    outcome.mkdir(parents=True,exist_ok=True)
    (outcome/"phase8_integrated_report.json").write_text(
        json.dumps(combined,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return combined


def main(argv=None):
    p=argparse.ArgumentParser(description="One Phase8 official verified-HTTPS and original filing intake pass")
    p.add_argument("--data-root",required=True)
    p.add_argument("--no-network",action="store_true")
    args=p.parse_args(argv)
    print(json.dumps(run(args.data_root,retrieve=not args.no_network),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
