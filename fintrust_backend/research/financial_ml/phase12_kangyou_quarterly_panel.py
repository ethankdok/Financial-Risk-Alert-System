"""Phase12: actual 12-quarter official MOPS retrospective case-source cohort.

Acquire ONLY the 11 missing Kangyou (6452) quarters FY2017Q2–FY2019Q4.
Reuse and SHA-verify the already acquired FY2020Q1 Phase11 original bytes.
Classify each period's true XBRL contexts (instant, quarter-duration, YTD)
WITHOUT applying annual Beneish/Dechow formulas to incomplete quarters.

The historical "as originally filed" version/publication timestamp and exact
per-quarter alleged outcome are NOT independently verified. All labels UNKNOWN.
No training/deployment/production DB writes or final holdout 1785.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.sources import (
    OfficialSourceFetcher, ensure_official_url, mops_annual_url,
)
from app.services.historical_audit.xbrl_document import detect_format, parse_xbrl_document
from .official_batch import atomic_json
from .phase1_case_registry import validate
from .phase6_official_evidence_recovery import ROOT_SEED
from .phase11_case_quarterly_gap_analysis import case_reporting_periods

TICKER = "6452"
FROZEN_PERIODS = tuple(
    f"{y}Q{q}" for y in range(2017, 2021) for q in range(1, 5)
    if (2017, 2) <= (y, q) <= (2020, 1)
)
LATEST_CACHED = "2020Q1"
SOURCE_STATUS_OK = "QUARTER_CONTEXT_VALIDATED_VINTAGE_UNKNOWN"
ALLOWED_ARCHIVE_FORMATS = frozenset({"xbrl_instance", "inline_xbrl", "zip"})
MAX_NEW_OFFICIAL_REQUESTS = 11
FIELDS = (
    "ticker", "reporting_period", "period_start", "period_end",
    "source_url", "source_status", "source_archive", "raw_sha256",
    "retrieval_origin", "document_format", "statement_scope",
    "period_end_contexts", "numeric_current_period_facts",
    "numeric_instant_facts", "numeric_quarter_duration_facts",
    "numeric_ytd_duration_facts", "numeric_other_duration_facts",
    "historical_first_original_version_verified",
    "historical_first_publication_verified",
    "independently_verified_fraud_outcome",
    "admitted_for_model_training", "annual_beneish_dechow_computed"
)


def quarter_parts(period):
    if not re.fullmatch(r"20[0-9]{2}Q[1-4]", period):
        raise ValueError("invalid_quarter_identity")
    year, q = int(period[:4]), int(period[-1])
    if period not in FROZEN_PERIODS:
        raise ValueError("quarter_not_in_frozen_case_registry")
    start = date(year, 1+3*(q-1), 1)
    end = date(year, q*3, (31 if q in (1, 4) else 30))
    # March 31, June 30, September 30 and December 31.
    return year, q, start, end


def source_url(period):
    y, q, _, _ = quarter_parts(period)
    return ensure_official_url(mops_annual_url(TICKER, y).replace("season=4", f"season={q}"))


def freeze_plan(seed):
    cases = validate(seed)
    listing = [r["reporting_period"] for r in case_reporting_periods(seed)
               if r["ticker"] == TICKER]
    if tuple(listing) != FROZEN_PERIODS or len(listing) != 12 or "1785" in (
            r["ticker"] for r in case_reporting_periods(seed)):
        raise ValueError("frozen_kangyou_quarterly_registry_mismatch")
    planned = [{"ticker": TICKER, "period": p,
                "source_url": source_url(p)} for p in FROZEN_PERIODS]
    new = [r for r in planned if r["period"] != LATEST_CACHED]
    if len(new) != MAX_NEW_OFFICIAL_REQUESTS:
        raise ValueError("quarterly_acquisition_request_cap_violation")
    return planned, new


def analyze_document(raw, period):
    year, q, start, end = quarter_parts(period)
    doc = parse_xbrl_document(raw)
    scope, _ = doc.statement_scope()
    current = {}
    counts = Counter()
    for id_, ctx in doc.contexts.items():
        if ctx.dimensional:
            continue
        # Do not infer this quarter from historic/comparative contexts ending
        # in OTHER quarters.
        if ctx.instant == end or ctx.end == end:
            current[id_] = ctx
    for fact in doc.numeric_facts:
        ctx = current.get(fact.context_ref)
        if ctx is None or fact.value is None or fact.is_nil:
            continue
        counts["numeric_current_period_facts"] += 1
        if ctx.instant == end:
            counts["numeric_instant_facts"] += 1
        elif ctx.start == start and ctx.end == end:
            counts["numeric_quarter_duration_facts"] += 1
        elif ctx.start == date(year, 1, 1) and ctx.end == end:
            counts["numeric_ytd_duration_facts"] += 1
        else:
            counts["numeric_other_duration_facts"] += 1
    return {
        "document_format": doc.document_format,
        "statement_scope": scope,
        "period_end_contexts": len(current),
        "numeric_current_period_facts": counts["numeric_current_period_facts"],
        "numeric_instant_facts": counts["numeric_instant_facts"],
        "numeric_quarter_duration_facts": counts["numeric_quarter_duration_facts"],
        "numeric_ytd_duration_facts": counts["numeric_ytd_duration_facts"],
        "numeric_other_duration_facts": counts["numeric_other_duration_facts"],
        "matches_requested_period_and_scope":bool(
            len(current)>0 and scope == "consolidated"
            and counts["numeric_current_period_facts"]>0),
        "annual_beneish_dechow_computed": False,
        "first_publication_verified": False,
        "original_filing_vintage_verified": False,
    }


def read_phase11_prior(data_root):
    root = Path(data_root)/"phase11_case_quarterly_and_paper_gaps"
    report = json.loads((root/"phase11_integrated_report.json").read_text(encoding="utf-8"))
    if report.get("holdout_1785_excluded") is not True or report.get(
            "confirmed_positive_labels") != 0 or report.get("supervised_early_warning_samples") != 0:
        raise ValueError("phase11_prior_fraud_label_or_holdout_gate")
    prior=report.get("quarterly_source_status",{})
    if (prior.get("ticker") != TICKER
            or prior.get("reporting_period") != LATEST_CACHED
            or prior.get("source_url") != source_url(LATEST_CACHED)
            or prior.get("acquisition_status") !=
                    "QUARTERLY_XBRL_CONTEXT_FOUND_VINTAGE_UNKNOWN"
            or prior.get("verified_historical_original") is not False
            or prior.get("misstatement_label") != "UNKNOWN"):
        raise ValueError("phase11_2020q1_source_does_not_satisfy_contract")
    archive = RawEvidenceArchive(root/"official_quarterly_source"/"raw")
    raw = archive.read(prior["raw_path"])
    if hashlib.sha256(raw).hexdigest() != prior["raw_sha256"]:
        raise ValueError("phase11_q1_2020_source_digest_mismatch")
    diagnostic = analyze_document(raw, LATEST_CACHED)
    if not diagnostic["matches_requested_period_and_scope"]:
        raise ValueError("phase11_q1_2020_source_no_longer_validates")
    return {
        "ticker":TICKER, "reporting_period":LATEST_CACHED,
        "source_url":source_url(LATEST_CACHED),
        "status":SOURCE_STATUS_OK, "raw_path":prior["raw_path"],
        "raw_sha256":prior["raw_sha256"], "source_archive":"PHASE11_RAW",
        "diagnostic":diagnostic, "retrieval_origin":"PHASE11_VERIFIED_CACHE",
        "historical_original_verified":False, "outcome_label":"UNKNOWN",
    }


def verify_prior_results(store, planned):
    if not store.exists():
        return {}
    payload=json.loads(store.read_text(encoding="utf-8"))
    expected={x["period"]:x["source_url"] for x in planned
              if x["period"] != LATEST_CACHED}
    results=payload.get("outcomes")
    if not isinstance(results, dict) or not set(results).issubset(expected):
        raise ValueError("quarterly_replay_manifest_unauthorized_period")
    for period, row in results.items():
        if (row.get("ticker")!=TICKER or row.get("source_url")!=expected[period]
                or row.get("reporting_period") != period
                or row.get("outcome_label") != "UNKNOWN"
                or row.get("historical_original_verified") is not False):
            raise ValueError("quarterly_replay_manifest_identity_or_label_conflict")
    return results


def validate_cached(row, raw_archive):
    if not row.get("raw_path"):
        return None
    raw=raw_archive.read(row["raw_path"])
    if hashlib.sha256(raw).hexdigest()!=row.get("raw_sha256"):
        raise ValueError("quarter_source_sha256_mismatch")
    real=analyze_document(raw,row["reporting_period"])
    if real != row.get("diagnostic"):
        raise ValueError("quarter_source_cached_diagnostic_disagreement")
    if row.get("status") == SOURCE_STATUS_OK and not real[
            "matches_requested_period_and_scope"]:
        raise ValueError("quarter_source_previous_validation_not_reproducible")
    return row


async def acquire(data_root,output, *, execute=False, fetcher=None):
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
    planned,new=freeze_plan(seed)
    prior=read_phase11_prior(data_root)
    target=output/"quarterly_acquisition_results.json"
    outcomes=verify_prior_results(target,planned)
    raw_archive=RawEvidenceArchive(output/"raw")
    old_cached=0
    for period,row in outcomes.items():
        if row.get("raw_path"):
            validate_cached(row,raw_archive)
            old_cached+=1
    requests=0
    if execute:
        fetcher=fetcher or OfficialSourceFetcher(
            min_interval_seconds=2.0,max_attempts=2)
    for row in new:
        period,url=row["period"],row["source_url"]
        previous=outcomes.get(period)
        if previous and previous.get("raw_path"):
            continue
        if not execute:
            continue
        response=await fetcher.fetch(
            url,expect=("xbrl_instance","inline_xbrl","zip"))
        requests+=1
        current={
            "ticker":TICKER,"reporting_period":period,"source_url":url,
            "status":response.status,"raw_path":"","raw_sha256":"",
            "source_archive":"PHASE12_RAW","retrieval_origin":"HTTPS_OFFICIAL_CANDIDATE",
            "diagnostic":None,"historical_original_verified":False,
            "outcome_label":"UNKNOWN",
        }
        if response.status=="ok" and response.content:
            format_name=detect_format(response.content)
            if format_name not in ALLOWED_ARCHIVE_FORMATS:
                current["status"]="INVALID_OFFICIAL_QUARTERLY_FORMAT"
            else:
                stored=raw_archive.store(
                    ticker=TICKER,period=period,content=response.content,
                    detected_format=format_name,retrieval=response.metadata())
                current.update(raw_path=stored.relative_path,
                               raw_sha256=stored.content_hash)
                try:
                    diag=analyze_document(response.content,period)
                    current["diagnostic"]=diag
                    current["status"]=(SOURCE_STATUS_OK if diag[
                        "matches_requested_period_and_scope"]
                        else "QUARTER_CONTEXT_OR_SCOPE_QUARANTINED")
                except (ValueError,RuntimeError,OSError) as exc:
                    current["status"]="QUARTER_XBRL_PARSE_FAILED"
                    current["parse_error_type"]=type(exc).__name__
        outcomes[period]=current
        atomic_json(target,{"schema":"phase12_quarterly_raw_v1",
                            "outcomes":outcomes,
                            "final_1785_holdout":True,
                            "all_positive_labels_approved":False})
        print(f"[Phase12 {requests}/{len(new)}] {TICKER} {period}: "
              f"{current['status']}",flush=True)

    results={**outcomes,LATEST_CACHED:prior}
    index=[]
    for item in planned:
        period=item["period"]
        result=results.get(period)
        status=result["status"] if result else "NOT_REQUESTED"
        _,_,start,end=quarter_parts(period)
        diag=result.get("diagnostic") if result else None
        index.append({
            "ticker":TICKER,"reporting_period":period,
            "period_start":start.isoformat(),"period_end":end.isoformat(),
            "source_url":item["source_url"],"source_status":status,
            "source_archive":result.get("source_archive","") if result else "",
            "raw_sha256":result.get("raw_sha256","") if result else "",
            "retrieval_origin":result.get("retrieval_origin","") if result else "",
            "document_format":diag.get("document_format","") if diag else "",
            "statement_scope":diag.get("statement_scope","") if diag else "",
            "period_end_contexts":diag.get("period_end_contexts",0) if diag else 0,
            "numeric_current_period_facts":diag.get("numeric_current_period_facts",0) if diag else 0,
            "numeric_instant_facts":diag.get("numeric_instant_facts",0) if diag else 0,
            "numeric_quarter_duration_facts":diag.get("numeric_quarter_duration_facts",0) if diag else 0,
            "numeric_ytd_duration_facts":diag.get("numeric_ytd_duration_facts",0) if diag else 0,
            "numeric_other_duration_facts":diag.get("numeric_other_duration_facts",0) if diag else 0,
            "historical_first_original_version_verified":"false",
            "historical_first_publication_verified":"false",
            "independently_verified_fraud_outcome":"UNKNOWN",
            "admitted_for_model_training":"false",
            "annual_beneish_dechow_computed":"false",
        })
    with (output/"quarterly_case_official_source_index.csv").open(
            "w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader();writer.writerows(index)
    totals=Counter(x["source_status"] for x in index)
    valid=[r for r in index if r["source_status"]==SOURCE_STATUS_OK]
    source_paths={
        "phase11_q1_2020_sha256":prior["raw_sha256"],
        "phase11_verified_original_filing":False,
    }
    report={
        "status":"PHASE12_6452_QUARTERLY_RETROSPECTIVE_SOURCE_PANEL_ONLY",
        "issuer":TICKER,"candidate_quarters":12,
        "new_quarters_planned":len(new),
        "quarterly_sources_checked":len(index),
        "official_quarters_context_scope_validated":len(valid),
        "reused_verified_2020Q1_from_phase11":True,
        "cached_reused_prior_phase12":old_cached,
        "new_network_requests":requests,
        "source_status_counts":dict(sorted(totals.items())),
        "unavailable_or_quarantined_quarters":[
            {"period":x["reporting_period"],"status":x["source_status"]}
            for x in index if x["source_status"]!=SOURCE_STATUS_OK],
        "quarterly_numeric_current_period_facts":sum(
            int(r["numeric_current_period_facts"]) for r in valid),
        "quarterly_exact_duration_facts":sum(
            int(r["numeric_quarter_duration_facts"]) for r in valid),
        "quarterly_ytd_duration_facts":sum(
            int(r["numeric_ytd_duration_facts"]) for r in valid),
        "historical_original_filing_vintages_verified":0,
        "first_publication_times_verified":0,
        "confirmed_period_outcome_labels":0,
        "audited_negative_control_labels":0,
        "annual_literature_scores_calculated_from_quarters":0,
        "financial_misstatement_supervised_training_rows":0,
        "lightweight_quarterly_context_only":True,
        "final_holdout_1785_excluded":True,"production_db_writes":0,
        "phase11_source_2020q1":source_paths,
        "phase11_integrated_report_sha256":hashlib.sha256(
            (Path(data_root)/"phase11_case_quarterly_and_paper_gaps"/
             "phase11_integrated_report.json").read_bytes()).hexdigest(),
        "warnings":[
            "12 official quarter files, if acquired, represent CURRENT available historical documents, not necessarily original as-first-published 2017–2020 versions.",
            "SFIPC official litigation covers alleged 2017Q2–2020Q1 quarter range; no source in this pipeline confirms that each filing is a convicted positive.",
            "Quarter/YTD/instant contexts are catalogued separately; no annual Beneish or Dechow formula values are inferred from quarterly figures.",
            "No quarter anomaly score is a verified false-report label. The development set never includes 1785.",
        ],
    }
    atomic_json(output/"phase12_integrated_report.json",report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Phase12 bounded official 6452 2017Q2–2020Q1 quarterly retrospective source acquisition")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--execute",action="store_true")
    args=p.parse_args(argv)
    print(json.dumps(asyncio.run(acquire(
        args.data_root,args.output,execute=args.execute)),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
