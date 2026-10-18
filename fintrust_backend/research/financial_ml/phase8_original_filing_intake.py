"""Phase8: truthful original-filing PIT evidence intake and source-level gap resolution.

No court-source document, source hash, or vendor latest-value may by itself
certify that a pre-correction MOPS report was originally public at a given
historical time. This is an immutable evidence archive and review package,
NOT a supervised training label generator.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from .phase1_case_registry import validate
from .phase6_official_evidence_recovery import ROOT_SEED

QUEUE_COLUMNS=("ticker","case_id","affected_fiscal_year",
               "historical_input_year","historical_role","required_source",
               "original_publication_time","original_filing_version_sha256",
               "filing_status","case_outcome_status","label_approved",
               "heldout_1785_excluded","review_note")
INTAKE_COLUMNS=("ticker","fiscal_year","local_report_file",
                "claimed_mops_original_publication_at",
                "mops_original_notice_file",
                "original_filing_document_id","review_notes")
OUTPUT_COLUMNS=(
    "ticker","fiscal_year","target_year_demands","accounting_regime",
    "local_original_candidate_status","local_source_sha256","bytes_archived",
    "claimed_mops_original_publication_at","original_notice_sha256",
    "original_filing_document_id","archived_raw_report_path",
    "prior_official_archives","official_archives_sha_verified",
    "publication_time_independently_verified","original_version_independently_verified",
    "safe_for_historical_features","supervised_label",
    "outcome_known_at_verified","training_admitted","reason"
)
MAX_REPORT_BYTES=35_000_000
MAX_NOTICE_BYTES=12_000_000


def table(path,columns,rows):
    with Path(path).open("w",encoding="utf-8",newline="") as handle:
        w=csv.DictWriter(handle,fieldnames=columns);w.writeheader();w.writerows(rows)


def read_table(path,needed):
    with Path(path).open(encoding="utf-8-sig",newline="") as handle:
        rdr=csv.DictReader(handle)
        if set(needed)-set(rdr.fieldnames or []):
            raise ValueError("missing_filing_recovery_queue_columns")
        return list(rdr)


def case_needs(queue_path,case_seed):
    rows=read_table(queue_path,QUEUE_COLUMNS)
    cases=validate(case_seed)
    case_map={c["ticker"]:c for c in cases}
    target={k:set(c["affected_fiscal_years"]) for k,c in case_map.items()}
    needs=defaultdict(set)
    for row in rows:
        ticker=row["ticker"]
        if ticker=="1785" or ticker not in case_map:
            raise ValueError("heldout_or_unknown_case_company_in_filing_queue")
        target_year=int(row["affected_fiscal_year"])
        year=int(row["historical_input_year"])
        if target_year not in target[ticker] or year not in range(target_year-2,target_year+1):
            raise ValueError("candidate_year_outside_frozen_case_window")
        if row["label_approved"].lower()!="false" or row["heldout_1785_excluded"].lower()!="true":
            raise ValueError("falsified_case_outcome_or_holdout")
        if row["original_filing_version_sha256"] or row["original_publication_time"]:
            raise ValueError("unapproved_original_filing_previously_promoted")
        needs[(ticker,year)].add(target_year)
    expected={(ticker,year) for ticker,affected in target.items()
              for target_year in affected
              for year in range(target_year-2,target_year+1)}
    if set(needs)!=expected:
        raise ValueError("incomplete_original_filing_case_window_coverage")
    return needs


def verified_archive_references(data_root,ticker,year):
    """Search only local MOPS historical-audit archives; never infer originals."""
    manifest=Path(data_root)/"official_batch"/"acquisition_results.json"
    if not manifest.is_file():
        return {"status":"NO_OFFICIAL_HISTORICAL_ARCHIVE_MANIFEST",
                "matched_archives":0,"hash_verified_archives":0}
    content=json.loads(manifest.read_text(encoding="utf-8"))
    outcomes=content.get("outcomes")
    if not isinstance(outcomes,dict):
        raise ValueError("invalid_existing_mops_historical_manifest")
    entry=outcomes.get(f"{ticker}:{year}")
    if not isinstance(entry,dict):
        return {"status":"NO_OFFICIAL_HISTORICAL_ARCHIVE_FOR_CASE_PERIOD",
                "matched_archives":0,"hash_verified_archives":0}
    if str(entry.get("ticker"))!=ticker or int(entry.get("fiscal_year",0))!=year:
        raise ValueError("archive_identity_mismatch_with_requested_case_year")
    if entry.get("status")!="validated":
        return {"status":"OFFICIAL_ARCHIVE_STATUS_UNVERIFIED",
                "matched_archives":1,"hash_verified_archives":0}
    if not entry.get("archive_path") or not entry.get("content_hash"):
        return {"status":"OFFICIAL_ARCHIVE_MISSING_RETRIEVAL_PROVENANCE",
                "matched_archives":1,"hash_verified_archives":0}
    from .literature_dataset import archive_bytes
    # archive_bytes validates path and archived content-hash without network.
    archive_bytes(Path(data_root)/"official_batch",entry)
    return {
        "status":"OFFICIAL_ARCHIVED_BYTES_VERIFIED_ORIGINAL_VINTAGE_UNKNOWN",
        "matched_archives":1,"hash_verified_archives":1,
        "filing_version_type":entry.get("filing_version_type",""),
        "original_publication_at_verified":False
    }


def _aware_time(value):
    if not value:
        return ""
    try:
        stamp=datetime.fromisoformat(value)
    except ValueError:
        raise ValueError("invalid_claimed_mops_publication_datetime") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("mops_claimed_timestamp_requires_explicit_timezone")
    return stamp.isoformat()


def archive_local(root,ticker,year,report_path,notice_path):
    paths=(Path(report_path),Path(notice_path))
    for file,limit in zip(paths,(MAX_REPORT_BYTES,MAX_NOTICE_BYTES)):
        if not file.is_file() or file.is_symlink() or not 100<=file.stat().st_size<=limit:
            raise ValueError("bad_original_source_archive_input")
    data=[p.read_bytes() for p in paths]
    hashes=[hashlib.sha256(v).hexdigest() for v in data]
    folder=Path(root)/ticker/str(year)
    folder.mkdir(parents=True,exist_ok=True)
    payload=[]
    for file,raw,digest in zip(paths,data,hashes):
        ext=file.suffix.lower()
        if ext not in (".pdf",".xml",".xhtml",".html",".htm",".zip",".txt"):
            raise ValueError("unsupported_historical_filing_evidence_type")
        stored=folder/(digest+ext)
        if stored.exists():
            if hashlib.sha256(stored.read_bytes()).hexdigest()!=digest:
                raise ValueError("existing_original_archive_tampered")
        else:
            stored.write_bytes(raw)
        payload.append(str(stored))
    return hashes,payload,len(data[0])


def intake_report(data_root,phase7_root,output,*,import_manifest=None):
    data_root=Path(data_root);phase7_root=Path(phase7_root)
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
    needs=case_needs(phase7_root/"phase7_original_filing_asof_gap_queue.csv",seed)
    requests={}
    if import_manifest:
        entries=read_table(import_manifest,INTAKE_COLUMNS)
        for line in entries:
            key=(line["ticker"],int(line["fiscal_year"]))
            if key in requests or key not in needs:
                raise ValueError("duplicate_or_outside_case_filing_intake")
            if line["original_filing_document_id"].strip()=="":
                raise ValueError("missing_mops_filing_document_identity")
            line["claimed_mops_original_publication_at"]=_aware_time(
                line["claimed_mops_original_publication_at"])
            requests[key]=line
    rows=[];stats=Counter()
    for (ticker,year),targets in sorted(needs.items()):
        archive=verified_archive_references(data_root,ticker,year)
        item=requests.get((ticker,year))
        row={
            "ticker":ticker,"fiscal_year":year,
            "target_year_demands":"|".join(map(str,sorted(targets))),
            "accounting_regime":("PRE_TIFRS_GAAP_NEEDS_HISTORICAL_MAPPING"
                                 if year<=2012 else "TIFRS_CANDIDATE_SCOPE_NEEDS_REVIEW"),
            "local_original_candidate_status":"NO_USER_SUPPLIED_ORIGINAL_VERSION",
            "local_source_sha256":"","bytes_archived":0,
            "claimed_mops_original_publication_at":"",
            "original_notice_sha256":"","original_filing_document_id":"",
            "archived_raw_report_path":"",
            "prior_official_archives":archive["matched_archives"],
            "official_archives_sha_verified":archive["hash_verified_archives"],
            "publication_time_independently_verified":"false",
            "original_version_independently_verified":"false",
            "safe_for_historical_features":"false",
            "supervised_label":"UNKNOWN","outcome_known_at_verified":"false",
            "training_admitted":"false",
            "reason":archive["status"]
        }
        if item is not None:
            sha,files,bytesize=archive_local(
                out/"original_filing_review_bytes",ticker,year,
                item["local_report_file"],item["mops_original_notice_file"])
            row.update(
                local_original_candidate_status="MANUAL_SOURCE_BYTES_ARCHIVED_NEEDS_PUBLISHER_REVIEW",
                local_source_sha256=sha[0],
                bytes_archived=bytesize,
                original_notice_sha256=sha[1],
                archived_raw_report_path=files[0],
                claimed_mops_original_publication_at=item["claimed_mops_original_publication_at"],
                original_filing_document_id=item["original_filing_document_id"],
                reason="MANUAL_BYTES_AND_CLAIMED_PUBLICATION_DO_NOT_CERTIFY_ORIGINAL_VERSION"
            )
        rows.append(row)
        stats[row["local_original_candidate_status"]]+=1
    table(out/"original_case_filing_source_intake.csv",OUTPUT_COLUMNS,rows)
    report={
        "status":"PHASE8_ORIGINAL_MOPS_FILING_VERSION_INTAKE_NO_LABELS_APPROVED",
        "case_issuer_count":len({t for t,y in needs}),
        "unique_source_year_requirements":len(needs),
        "phase7_year_window_slots":sum(len(c["affected_fiscal_years"])*3 for c in validate(seed)),
        "candidate_archive_states":dict(stats),
        "existing_official_hash_verified_years":sum(r["official_archives_sha_verified"] for r in rows),
        "user_submitted_original_candidate_years":len(requests),
        "independently_verified_original_versions":0,
        "verified_historical_publication_times":0,
        "historical_asof_admitted_features":0,
        "supervised_positive_labels_approved":0,
        "supervised_negative_labels_approved":0,
        "holdout_1785_excluded":True,
        "production_db_writes":0,
        "warnings":[
            "Source bytes and even a claimed historical MOPS date require independent publication proof and accounting regime review.",
            "FY2012 and earlier may use pre-TIFRS standards; never coerce GAAP into TIFRS.",
            "A retrospective validated MOPS instance is not proof the as-original document was on the historical market.",
            "Court document or lawsuit does not automatically grant confirmed-fraud issuer-year labels."
        ]
    }
    (out/"phase8_original_filing_readiness.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Offline case-filing original-vintage evidence intake, not training")
    p.add_argument("--data-root",required=True)
    p.add_argument("--phase7-root",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--manual-filing-manifest",default="")
    a=p.parse_args(argv)
    print(json.dumps(intake_report(a.data_root,a.phase7_root,a.output,
                    import_manifest=a.manual_filing_manifest or None),
                    ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
