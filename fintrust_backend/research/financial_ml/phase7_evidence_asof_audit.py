"""Phase7: recover official case documents and audit retrospective-as-of gaps.

Does not infer fraud labels. "Archived" means bytes saved with SHA, not that
the legal finding/earliest notice/original company financial filing is approved.
Optional user-saved HTML import is marked as unverified provenance.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from datetime import date, datetime, timezone

from .phase1_case_registry import validate
from .phase6_official_evidence_recovery import (
    ROOT_SEED, MAX_BYTES, archive_official, company_mentioned,
    visible_document, run as phase6_run,
)

# Verify document identity using official docket numbers and topic, not a
# company name alone. 2025 civil remand NEVER proves its plaintiff's claims
# on every alleged filing period.
CASE_DOCUMENT_MARKERS = {
    "judicial_3027_trial_2025": "113年度金訴字第29號",
    "judicial_8299_appeal_2025": "113年度金上更一字第2號",
    "judicial_8299_supreme_remand_20251119": "114年度台上字第859號",
    "sfipc_6452_civil_claim_2023": "有關康友自救會於112年5月12日",
}
SOURCE_FIELDS = (
    "case_id","ticker","source_id","source_type","source_url",
    "collection_status","document_identity_status","company_mentioned",
    "expected_docket_or_title_mentioned","file_sha256","import_method",
    "verified_original_financial_filing","first_market_disclosure_time_verified",
    "outcome_label_approved","error_category"
)
ASOF_FIELDS = (
    "ticker","case_id","affected_fiscal_year","historical_input_year",
    "historical_role","required_source","original_publication_time",
    "original_filing_version_sha256","filing_status",
    "case_outcome_status","label_approved","heldout_1785_excluded",
    "review_note"
)


def write_csv(path,columns,rows):
    with Path(path).open("w",encoding="utf-8",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def judge_identity(case,source,raw):
    text=visible_document(raw)
    # Normalize spacing, full-width characters, and punctuation only.
    compact=re.sub(r"\s+","",text)
    wanted=CASE_DOCUMENT_MARKERS[source["source_id"]]
    if source["kind"]=="JUDICIAL_JUDGMENT":
        court_page=bool(re.search("法院.{0,15}判決",compact))
    else:
        court_page=("投保中心" in compact or "投資人及期貨交易人保護中心" in compact)
    return {
        "company_mentioned":company_mentioned(text,case),
        "expected_marker_mentioned":wanted in compact,
        "official_document_context":court_page,
        "identity_supported_by_document":(
            company_mentioned(text,case) and wanted in compact and court_page),
        "warning":"Text matching is document identity evidence, not authenticated HTTP provenance."
    }


def import_saved_official(manifest,seed,root):
    """Explicitly import a browser-saved official HTML; no unsanctioned labels.

    Local file paths are supplied only in an explicitly passed CSV manifest.
    A forged local HTML is not certified official even with matching docket.
    """
    cases=validate(seed)
    refs={s["source_id"]:(c,s) for c in cases for s in c["sources"]
          if s["source_id"] in CASE_DOCUMENT_MARKERS}
    with Path(manifest).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if set(reader.fieldnames or [])!={"source_id","local_file"}:
            raise ValueError("import_manifest_must_contain_source_id_local_file_only")
        requests=list(reader)
    if len(requests)>len(refs) or len({x["source_id"] for x in requests})!=len(requests):
        raise ValueError("duplicate_or_excess_imports")
    results=[]
    for item in requests:
        source_id=item["source_id"]
        if source_id not in refs:
            raise ValueError("unknown_source_id_not_in_reviewed_official_seed")
        case,source=refs[source_id]
        local=Path(item["local_file"])
        if (local.is_symlink() or not local.is_file()
            or local.suffix.lower() not in (".html",".htm",".txt")
            or not 500<=local.stat().st_size<=MAX_BYTES):
            raise ValueError("invalid_local_source_file_or_size:"+source_id)
        raw=local.read_bytes()
        identity=judge_identity(case,source,raw)
        if not identity["identity_supported_by_document"]:
            results.append({"source_id":source_id,
                            "status":"LOCAL_DOCUMENT_IDENTITY_NOT_CONFIRMED",
                            "archived":False,"identity":identity})
            continue
        case_root=Path(root)/"official_case_bytes"/case["case_id"]
        target=case_root/(source_id+".html")
        receipt=case_root/(source_id+".json")
        digest=hashlib.sha256(raw).hexdigest()
        if target.exists() or receipt.exists():
            if not target.is_file() or not receipt.is_file():
                raise ValueError("existing_archive_orphaned:"+source_id)
            prior=json.loads(receipt.read_text(encoding="utf-8"))
            if (hashlib.sha256(target.read_bytes()).hexdigest()!=digest
                or prior.get("sha256")!=digest
                or prior.get("url")!=source["url"]):
                raise ValueError("existing_archive_identity_or_digest_collision:"+source_id)
            results.append({"source_id":source_id,
                            "status":"LOCAL_IMPORT_IDENTICAL_EXISTING_ARCHIVE",
                            "archived":True,"identity":identity})
            continue
        case_root.mkdir(parents=True,exist_ok=True)
        record={
            "schema":"phase6_official_source_receipt_v1",
            "case_id":case["case_id"],"source_id":source_id,
            "url":source["url"],"final_url":None,
            "sha256":digest,"bytes":len(raw),
            "content_type":"text/html; unverified browser-saved",
            "fetched_at_utc":datetime.now(timezone.utc).isoformat(),
            "method":"MANUAL_IMPORTED_BROWSER_SAVE_ORIGIN_UNVERIFIED",
            "source_publication_at":None,"first_case_disclosure_at":None,
            "period_specific_label_approved":False,
            "document_identity_checked_locally":True,
            "legal_findings_reviewed":False,
            "verified_original_publication_version":False
        }
        target.write_bytes(raw)
        receipt.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",
                           encoding="utf-8")
        results.append({"source_id":source_id,
                        "status":"LOCAL_ARCHIVED_UNVERIFIED_OFFICIAL_PROVENANCE",
                        "archived":True,"identity":identity})
    return results


def audit(data_root,output,*,retrieve=False,imports=None,fetcher=None,pace_seconds=0.0):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
    cases=validate(seed)
    # If manual import is provided, preserve it without overwriting; Phase6
    # reuse checks its bytes and provenance metadata.
    imported=import_saved_official(imports,seed,output) if imports else []
    if not 0<=pace_seconds<=60:
        raise ValueError("invalid_official_source_request_interval")
    call_opts={"retrieve":retrieve,"pace_seconds":pace_seconds}
    if fetcher is not None:
        call_opts["fetcher"]=fetcher
    previous=phase6_run(ROOT_SEED,output,**call_opts)
    per_source={}
    for item in previous["per_source_diagnostics"]:
        per_source[item["source_id"]]=item
    source_rows=[]
    evidence_ok=Counter()
    status_count=Counter()
    for case in cases:
        for source in case["sources"]:
            if source["kind"]=="SECONDARY_NEWS_CONTEXT_NOT_LABEL_EVIDENCE":
                continue
            ref=source["source_id"]
            loc=output/"official_case_bytes"/case["case_id"]/(ref+".html")
            receipt=loc.with_suffix(".json")
            state=per_source[ref]
            result={"company_mentioned":False,"expected_marker_mentioned":False,
                    "identity_supported_by_document":False}
            digest=""
            mode=""
            if loc.exists() and receipt.exists() and state.get("collection_status") not in (
                    "ARCHIVE_TAMPER_OR_IDENTITY_CONFLICT",
                    "BROKEN_PRIOR_ARCHIVE_REQUIRES_REVIEW"):
                body=loc.read_bytes()
                metadata=json.loads(receipt.read_text(encoding="utf-8"))
                digest=hashlib.sha256(body).hexdigest()
                if metadata.get("sha256")!=digest or metadata.get("url")!=source["url"]:
                    raise ValueError("existing_source_archive_digest_or_url_conflict:"+ref)
                result=judge_identity(case,source,body)
                mode=metadata.get("method","")
            documented=result["identity_supported_by_document"]
            status=("CONTENT_IDENTITY_SUPPORTED_PROVENANCE_REVIEW_OPEN"
                    if documented else
                    "ARCHIVED_CONTENT_IDENTITY_INSUFFICIENT"
                    if digest else "NO_ARCHIVED_OFFICIAL_BYTES")
            evidence_ok[status]+=1
            status_count[state["collection_status"]]+=1
            source_rows.append({
                "case_id":case["case_id"],"ticker":case["ticker"],"source_id":ref,
                "source_type":source["kind"],"source_url":source["url"],
                "collection_status":state["collection_status"],
                "document_identity_status":status,
                "company_mentioned":str(result["company_mentioned"]).lower(),
                "expected_docket_or_title_mentioned":str(result["expected_marker_mentioned"]).lower(),
                "file_sha256":digest,"import_method":mode,
                "verified_original_financial_filing":"false",
                "first_market_disclosure_time_verified":"false",
                "outcome_label_approved":"false",
                "error_category":state.get("error_category",""),
            })
    write_csv(output/"phase7_official_source_review.csv",SOURCE_FIELDS,source_rows)
    gaps=[]
    for case in cases:
        for affected in case["affected_fiscal_years"]:
            for fy in range(affected-2,affected+1):
                gaps.append({
                    "ticker":case["ticker"],"case_id":case["case_id"],
                    "affected_fiscal_year":affected,
                    "historical_input_year":fy,
                    "historical_role":"TARGET" if fy==affected else "PRIOR_YEAR",
                    "required_source":"ORIGINAL_MOPS_FILING_AS_FIRST_PUBLISHED",
                    "original_publication_time":"",
                    "original_filing_version_sha256":"",
                    "filing_status":"UNKNOWN_ORIGINAL_VERSION_NEEDS_RECOVERY",
                    "case_outcome_status":"POTENTIAL_CASE_PERIOD_REVIEW_PENDING",
                    "label_approved":"false","heldout_1785_excluded":"true",
                    "review_note":"No assumption that latest database values represent pre-correction filing."
                })
    write_csv(output/"phase7_original_filing_asof_gap_queue.csv",ASOF_FIELDS,gaps)
    report={
        "status":"PHASE7_OFFICIAL_CONTENT_IDENTITY_AND_PIT_GAPS_RESEARCH_ONLY",
        "case_count":len(cases),
        "affected_company_year_candidates":sum(len(c["affected_fiscal_years"]) for c in cases),
        "primary_source_count":len(source_rows),
        "original_filing_requirements":len(gaps),
        "official_source_archive_counts":dict(status_count),
        "content_identity_diagnostic_counts":dict(evidence_ok),
        "archived_primary_sources_with_docket_and_company":evidence_ok[
            "CONTENT_IDENTITY_SUPPORTED_PROVENANCE_REVIEW_OPEN"],
        "manual_import_results":imported,
        "source_failures":[{"ticker":x["ticker"],"source_id":x["source_id"],
                            "error_category":x["error_category"],
                            "collection_status":x["collection_status"]}
                           for x in source_rows if x["document_identity_status"]!="CONTENT_IDENTITY_SUPPORTED_PROVENANCE_REVIEW_OPEN"],
        "verified_original_financial_reports":0,
        "verified_original_publication_times":0,
        "first_public_disclosure_times_verified":0,
        "approved_taiwan_misstatement_labels":0,
        "approved_negative_controls":0,
        "supervised_ex_ante_ml_admitted_rows":0,
        "holdout_1785_untouched":True,
        "production_db_writes":0,
        "phase6_upgraded_report":"phase6_evidence_readiness.json",
        "warnings":[
            "Document keyword/docket match is not independent website identity attestation.",
            "Manually saved HTML authenticity requires provenance review.",
            "A subsequent court finding is NOT an outcome label available at an earlier training cutoff.",
            "Original MOPS filing and earliest market notice remain independent missing research tasks."
        ]
    }
    (output/"phase7_evidence_asof_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="One-shot Phase7 official document and original-vintage gaps audit")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--retrieve-official",action="store_true")
    p.add_argument("--manual-import-manifest",default="")
    p.add_argument("--pace-seconds",type=float,default=2.0)
    options=p.parse_args(argv)
    print(json.dumps(audit(options.data_root,options.output,
                          retrieve=options.retrieve_official,
                          imports=options.manual_import_manifest or None,
                          pace_seconds=options.pace_seconds),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
