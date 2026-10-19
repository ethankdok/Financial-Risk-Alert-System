"""Phase 9: acquire bounded official *current archival* MOPS annual XBRL for case years.

Reuses Phase3 official source downloader, immutable SHA archive, and XBRL
normalizer. A 2026 download of a 2014 report is NOT proved the original 2014
filing. No first publication, fraud label, or training admission is inferred.
Final case 1785 is excluded. FY2012 is pre-TIFRS and not fed into TIFRS XBRL.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from app.services.historical_audit.sources import mops_annual_url, ensure_official_url
from .official_batch import acquire as acquire_official_batch, MAX_REQUESTS, atomic_json
from .phase1_case_registry import validate
from .phase6_official_evidence_recovery import ROOT_SEED
from .phase8_original_filing_intake import OUTPUT_COLUMNS, case_needs, read_table

ARCHIVE_TABLE=(
    "ticker","fiscal_year","accounting_regime","historical_role",
    "mops_xbrl_url","acquisition_status","source_raw_sha256",
    "source_relative_archive_path","xbrl_statement_scope",
    "xbrl_filing_version_type","xbrl_facts_normalized",
    "historical_original_filing_version_verified",
    "source_publication_timestamp_verified",
    "first_misstatement_disclosure_time_verified",
    "financial_statement_misstatement_label",
    "approved_for_historical_model_training","not_original_reason"
)
NO_ORIGINAL="2026-retrieved official XBRL may be restated/replaced; no independently verified initial filing bytes or earliest publication date"
LEGACY="FY2012 pre-TIFRS GAAP: original report PDF/issuer historical release must be recovered separately"


def write_rows(path,fields,rows):
    with Path(path).open("w",encoding="utf-8",newline="") as f:
        wr=csv.DictWriter(f,fieldnames=fields)
        wr.writeheader();wr.writerows(rows)


def plan(phase7_root,phase8_root):
    """Derive exact 13 required issuer-years from case source, fail closed."""
    seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
    cases=validate(seed)
    requests=case_needs(
        Path(phase7_root)/"phase7_original_filing_asof_gap_queue.csv",seed)
    inventory=Path(phase8_root)/"original_case_filing_source_intake.csv"
    intake=read_table(inventory,OUTPUT_COLUMNS)
    keys={(r["ticker"],int(r["fiscal_year"])) for r in intake}
    if len(keys)!=len(intake) or keys!=set(requests) or len(keys)!=13:
        raise ValueError("phase8_case_original_version_intake_identity_or_coverage_mismatch")
    for row in intake:
        if (row["supervised_label"]!="UNKNOWN" or
                row["training_admitted"].lower()!="false" or
                row["original_version_independently_verified"].lower()!="false" or
                row["publication_time_independently_verified"].lower()!="false"):
            raise ValueError("phase8_source_or_label_admission_not_permitted")
    selected=[]
    manual=[]
    for (ticker,year),targets in sorted(requests.items()):
        if ticker=="1785" or not re.fullmatch(r"[0-9]{4}",ticker):
            raise ValueError("holdout_or_unexpected_issuer")
        if year<=2012:
            manual.append({"ticker":ticker,"fiscal_year":year,
                           "target_year_demands":sorted(targets),
                           "reason":LEGACY,"status":"LEGACY_ORIGINAL_PDF_REQUIRES_SEPARATE_SOURCE"})
            continue
        url=ensure_official_url(mops_annual_url(ticker,year))
        selected.append({
            "ticker":ticker,"fiscal_year":year,"source_url":url,
            "historical_listing_status":"UNVERIFIED",
            "historical_industry_status":"UNVERIFIED",
            "normal_label_status":"UNREVIEWED",
            "training_admitted":False,
        })
    if len(selected)>MAX_REQUESTS or len(selected)!=12 or len(manual)!=1:
        raise ValueError("unexpected_case_year_xbrl_request_count")
    return selected,manual


def validate_manifest(manifest,planned):
    """Audit actual downloader results, checking archive bytes for successes."""
    folder=Path(manifest).parent
    obj=json.loads(Path(manifest).read_text(encoding="utf-8"))
    outcomes=obj.get("outcomes")
    if not isinstance(outcomes,dict):
        raise ValueError("broken_official_acquisition_manifest")
    expected={(x["ticker"],int(x["fiscal_year"])) for x in planned}
    if len(outcomes)!=len(expected):
        raise ValueError("official_case_manifest_unexpected_number_of_issuer_years")
    from app.services.historical_audit.archive import RawEvidenceArchive
    archive=RawEvidenceArchive(folder/"raw")
    for key,row in outcomes.items():
        if not isinstance(row,dict):
            raise ValueError("broken_case_source_result")
        ticker,year=str(row.get("ticker")),int(row.get("fiscal_year",0))
        if key!=f"{ticker}:{year}" or (ticker,year) not in expected or ticker=="1785":
            raise ValueError("official_case_manifest_contains_unauthorized_source")
        if row.get("source_url")!=mops_annual_url(ticker,year):
            raise ValueError("unexpected_downloaded_mops_source_url")
        if row.get("training_admitted") is not False or row.get("normal_label_status")!="UNREVIEWED":
            raise ValueError("false_training_or_normal_label_in_acquired_source")
        if row.get("archive_path"):
            data=archive.read(row["archive_path"])
            digest=hashlib.sha256(data).hexdigest()
            if digest!=row.get("content_hash"):
                raise ValueError("official_case_archive_sha256_mismatch")
            if row.get("source_kind") not in (
                    "mops_xbrl_zip","mops_inline_xbrl","mops_xbrl_instance"):
                raise ValueError("unverified_xbrl_source_kind")
    return outcomes


def assess(planned,legacy,manifest,*,execute=False):
    reports=[]
    counters=Counter()
    outcomes=validate_manifest(manifest,planned) if execute else {}
    for item in planned:
        ticker,year=item["ticker"],item["fiscal_year"]
        source=outcomes.get(f"{ticker}:{year}",{})
        status=source.get("status","not_requested")
        counters[status]+=1
        reports.append({
            "ticker":ticker,"fiscal_year":year,"accounting_regime":"TIFRS_RETRIEVAL_CANDIDATE",
            "historical_role":"TARGET_AND_PRIOR_YEAR_SOURCE_NOT_LABEL",
            "mops_xbrl_url":item["source_url"],
            "acquisition_status":status,
            "source_raw_sha256":source.get("content_hash",""),
            "source_relative_archive_path":source.get("archive_path",""),
            "xbrl_statement_scope":source.get("statement_scope",""),
            "xbrl_filing_version_type":source.get("filing_version_type",""),
            "xbrl_facts_normalized":len(source.get("facts",[])),
            "historical_original_filing_version_verified":"false",
            "source_publication_timestamp_verified":"false",
            "first_misstatement_disclosure_time_verified":"false",
            "financial_statement_misstatement_label":"UNKNOWN",
            "approved_for_historical_model_training":"false",
            "not_original_reason":NO_ORIGINAL
        })
    for old in legacy:
        reports.append({
            "ticker":old["ticker"],"fiscal_year":old["fiscal_year"],
            "accounting_regime":"PRE_TIFRS_GAAP",
            "historical_role":"PRIOR_YEAR_SOURCE_NOT_LABEL",
            "mops_xbrl_url":"","acquisition_status":old["status"],
            "source_raw_sha256":"","source_relative_archive_path":"",
            "xbrl_statement_scope":"","xbrl_filing_version_type":"",
            "xbrl_facts_normalized":0,
            "historical_original_filing_version_verified":"false",
            "source_publication_timestamp_verified":"false",
            "first_misstatement_disclosure_time_verified":"false",
            "financial_statement_misstatement_label":"UNKNOWN",
            "approved_for_historical_model_training":"false",
            "not_original_reason":LEGACY
        })
        counters[old["status"]]+=1
    return sorted(reports,key=lambda r:(r["ticker"],r["fiscal_year"])),counters


async def run(data_root,*,execute=False,fetcher=None,processor=None):
    root=Path(data_root)
    phase7=root/"phase7_official_case_asof_recovery"
    phase8=root/"phase8_case_original_filing_recovery"
    out=root/"phase9_case_mops_xbrl_candidates"
    out.mkdir(parents=True,exist_ok=True)
    planned,legacy=plan(phase7,phase8)
    atomic_json(out/"phase9_mops_request_plan.json",{
        "source_tier":"MOPS_CURRENT_ARCHIVE_ORIGINAL_VINTAGE_UNKNOWN",
        "requests":[{"ticker":p["ticker"],"fiscal_year":p["fiscal_year"],
                     "source_url":p["source_url"]} for p in planned],
        "excluded_legacy_pre_TIFRS":legacy,
        "execute":bool(execute),"final_1785_heldout":True})
    result=await acquire_official_batch(
        planned,out,execute=execute,fetcher=fetcher,processor=processor)
    records,counts=assess(planned,legacy,out/"acquisition_results.json",execute=execute)
    write_rows(out/"phase9_case_mops_version_review.csv",ARCHIVE_TABLE,records)
    approved=sum(r["historical_original_filing_version_verified"]=="true" for r in records)
    report={
        "status":("PHASE9_OFFICIAL_CASE_YEAR_RETROSPECTIVE_ARCHIVE_REVIEW_ONLY"
                  if execute else "PHASE9_DRY_RUN_NO_FINANCIAL_DOWNLOAD"),
        "case_companies":3,"required_company_years":len(records),
        "unique_tifrs_xbrl_requests":len(planned),
        "legacy_gaap_years_not_automatically_fetched":len(legacy),
        "legacy_gaap_years":legacy,
        "network_requests":result.get("network_requests",0),
        "source_acquisition_counts":dict(sorted(counts.items())),
        "xbrl_archived_with_sha_verified":sum(bool(r["source_raw_sha256"]) for r in records),
        "xbrl_parsed_validated":sum(r["acquisition_status"]=="validated" for r in records),
        "pre_restated_original_filing_versions_approved":approved,
        "original_source_publication_times_verified":0,
        "first_public_disclosure_times_verified":0,
        "material_misstatement_positive_labels_approved":0,
        "audited_negative_labels_approved":0,
        "approved_supervised_model_rows":0,
        "holdout_1785_excluded":True,
        "original_filing_submission_versions_are_not_inferred":True,
        "real_official_content_is_retrospective_until_vintage_proof":True,
        "production_db_writes":0,
        "input_source_hashes":{
            "phase8_original_review":hashlib.sha256(
                (phase8/"original_case_filing_source_intake.csv").read_bytes()).hexdigest(),
            "phase7_case_needs":hashlib.sha256(
                (phase7/"phase7_original_filing_asof_gap_queue.csv").read_bytes()).hexdigest()
        },
        "limitations":[
            "MOPS may return a later corrected or refiled XBRL for a historical fiscal year.",
            "Historical first-public versions and notices have not been independently retrieved or timestamp-verified.",
            "FY2012 is a different Taiwan GAAP regime, not safely interchangeable with TIFRS.",
            "Judicial later findings cannot create pre-event training labels without separate knowledge-time checks.",
            "No source in this phase can enter supervised train/validation/test solely because its SHA matched."
        ],
    }
    atomic_json(out/"phase9_integrated_report.json",report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Official 12-company-year MOPS XBRL case evidence candidate batch, research-only")
    p.add_argument("--data-root",required=True)
    p.add_argument("--execute",action="store_true")
    args=p.parse_args(argv)
    print(json.dumps(asyncio.run(run(args.data_root,execute=args.execute)),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
