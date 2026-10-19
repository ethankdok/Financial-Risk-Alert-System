"""Phase14: 12 non-case Taiwan issuers x 12 quarters of real official MOPS XBRL.

The selection comes from the frozen Phase5 120-issuer multi-industry cohort:
3 semiconductor and 9 other distinct sectors. Every report is independently
archived by SHA. Reuses the source-hashed, same-grain Phase13 extractor and
temporal-signal method, issuer by issuer; never assumes comparison issuers
have been proven normal, never includes 1785 or the 3027/6452/8299 case issuers.

All source vintages remain retrospective and strictly NOT model train-admitted.
This stage acquires + audits source features, NOT supervised anomaly training.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.sources import (
    OfficialSourceFetcher, ensure_official_url, mops_annual_url,
)
from app.services.historical_audit.xbrl_document import detect_format
from .finmind_cross_industry_pilot import read_universe
from .official_batch import atomic_json
from .phase13_quarterly_temporal_features import (
    FROZEN_PERIODS, OBS_FIELDS, SIGNAL_FIELDS,
    extract_source, derive_signals, write_csv,
)

CASE_OR_HOLDOUT = frozenset({"1785", "3027", "6452", "8299"})
SELECTED_ISSUERS = 12
SEMICONDUCTOR_QUOTA = 3
QUARTERS_EACH = len(FROZEN_PERIODS)
EXPECTED_JOBS = SELECTED_ISSUERS * QUARTERS_EACH
MAX_MOPS_REQUESTS = 144
VALID = "OFFICIAL_QUARTER_SAME_GRAIN_CANDIDATE_VINTAGE_UNKNOWN"
SOURCE_COLUMNS = (
    "ticker", "industry_category", "market", "reporting_period",
    "source_status", "official_url", "raw_sha256", "archive_relative_path",
    "xbrl_entity_and_scope_checked", "requested_period_checked",
    "primary_twd_source_observations", "accepted_concept_grain_observations",
    "quarantined_conflicting_concepts", "original_filing_version_verified",
    "first_publication_verified", "outcome_label", "normal_label_approved",
    "training_admitted",
)
QUARTER_COLUMNS = (
    "ticker", "industry_category", "market", "quarters_expected",
    "quarters_source_validated", "financial_observations", "candidate_signals",
    "distinct_concept_grains", "historical_issuer_listing_verified",
    "normal_outcome_label", "supervised_training_approved",
)


def sha_token(seed, text):
    return hashlib.sha256(f"{seed}:{text}".encode("utf-8")).hexdigest()


def selection(cohort_csv, *, seed=143):
    """Reproducible pilot from already declared 120-issuer cohort.

    Current industry classifications are research selection metadata, NOT
    historical as-of industry memberships or ground-truth healthy controls.
    """
    candidates = read_universe(cohort_csv)
    if len(candidates)!=120:
        raise ValueError("phase14_requires_existing_frozen_120_issuer_cohort")
    eligible=[r for r in candidates if r["ticker"] not in CASE_OR_HOLDOUT]
    if len({r["ticker"] for r in eligible})!=len(eligible):
        raise ValueError("duplicate_comparison_company_in_cohort")
    semi=sorted((r for r in eligible if r["industry_category"]=="半導體業"),
                key=lambda r:sha_token(seed,r["ticker"]))
    if len(semi)<SEMICONDUCTOR_QUOTA:
        raise ValueError("not_enough_actual_semiconductor_issuers")
    picked=semi[:SEMICONDUCTOR_QUOTA]
    sectors=defaultdict(list)
    for row in eligible:
        if row["industry_category"]!="半導體業":
            sectors[row["industry_category"]].append(row)
    for sector in sorted(sectors,key=lambda x:sha_token(seed,x)):
        if len(picked)>=SELECTED_ISSUERS:
            break
        picked.append(sorted(sectors[sector],
                             key=lambda r:sha_token(seed,r["ticker"]))[0])
    if (len(picked)!=SELECTED_ISSUERS or
        len({r["ticker"] for r in picked})!=SELECTED_ISSUERS or
        len({r["industry_category"] for r in picked})!=10):
        raise ValueError("insufficient_multi_industry_spread_for_quarterly_validation")
    return sorted(picked,key=lambda r:r["ticker"])


def url_for(ticker, period):
    if not (re.fullmatch(r"[0-9]{4}",ticker) and ticker not in CASE_OR_HOLDOUT):
        raise ValueError("quarterly_comparison_issuer_not_allowed")
    if period not in FROZEN_PERIODS:
        raise ValueError("quarterly_comparison_period_outside_fixed_window")
    year,quarter=int(period[:4]),int(period[-1])
    return ensure_official_url(mops_annual_url(ticker,year).replace(
        "season=4",f"season={quarter}"))


def plan(cohort_csv,output):
    selected=selection(cohort_csv)
    root=Path(output)
    root.mkdir(parents=True,exist_ok=True)
    immutable={
        "status":"PHASE14_CROSS_INDUSTRY_OFFICIAL_QUARTER_SOURCE_PLAN",
        "source_cohort_sha256":hashlib.sha256(Path(cohort_csv).read_bytes()).hexdigest(),
        "selected_company_metadata":[
            {"ticker":r["ticker"],"market":r["market"],
             "industry_category":r["industry_category"]} for r in selected
        ],
        "fixed_quarters":list(FROZEN_PERIODS),
        "source_jobs_planned":EXPECTED_JOBS,
        "selection_method":"frozen_120_cohort_3_semi_plus_9_distinct_other_industries_seed143",
        "all_company_outcomes":"UNKNOWN",
        "all_original_vintages":"UNVERIFIED",
        "final_1785_untouched":True,
    }
    path=root/"frozen_phase14_plan.json"
    if path.exists() and json.loads(path.read_text(encoding="utf-8"))!=immutable:
        raise ValueError("frozen_quarter_source_plan_changed_without_review")
    atomic_json(path,immutable)
    return selected,immutable


def verify_existing(path,selected):
    if not path.exists():
        return {}
    data=json.loads(path.read_text(encoding="utf-8"))
    outcomes=data.get("outcomes")
    if not isinstance(outcomes,dict):
        raise ValueError("prior_quarterly_comparison_manifest_invalid")
    ids={x["ticker"] for x in selected}
    for key,row in outcomes.items():
        if not isinstance(row,dict):
            raise ValueError("prior_comparison_source_invalid_row")
        ticker,period=row.get("ticker"),row.get("reporting_period")
        if key!=f"{ticker}:{period}" or ticker not in ids or period not in FROZEN_PERIODS:
            raise ValueError("prior_quarterly_comparison_source_outside_plan")
        if (row.get("official_url")!=url_for(ticker,period)
            or row.get("outcome_label")!="UNKNOWN"
            or row.get("normal_label_approved") is not False
            or row.get("original_asof_verified") is not False):
            raise ValueError("prior_comparison_source_forged_identity_or_labels")
    return outcomes


def verify_candidate_archive(row,archive):
    if not row.get("raw_path"):
        return None
    raw=archive.read(row["raw_path"])
    if hashlib.sha256(raw).hexdigest()!=row.get("raw_sha256"):
        raise ValueError("prior_quarter_raw_digest_changed")
    observations,diagnostic,eligible,conflicts=extract_source(
        raw,row["reporting_period"],row["raw_sha256"],ticker=row["ticker"])
    if not diagnostic["matches_requested_period_and_scope"]:
        raise ValueError("prior_quarterly_comparison_scope_changed")
    if row.get("source_status")!=VALID:
        raise ValueError("prior_source_archive_status_conflicts_with_bytes")
    if row.get("source_fact_count")!=len(observations):
        raise ValueError("prior_source_archive_observation_count_changed")
    return observations,len(conflicts)


async def run(cohort_csv,output, *, execute=False,fetcher=None,stop_after_failures=8):
    """One bounded run with per-response persistent resume (no background work).

    Missing current-listed issuer historical filings are source gaps, NOT
    company negatives or fraudulent positives. Stop after repeated access
    failures and preserve all already archived evidence.
    """
    selected,frozen=plan(cohort_csv,output)
    root=Path(output)
    archive=RawEvidenceArchive(root/"raw")
    manifest=root/"quarterly_acquisition_results.json"
    outcomes=verify_existing(manifest,selected)
    if execute:
        fetcher=fetcher or OfficialSourceFetcher(
            min_interval_seconds=2.0,max_attempts=2)
    calls=0
    reused=0
    consecutive_access_failures=0
    halted=False
    for company in selected:
        ticker=company["ticker"]
        for period in FROZEN_PERIODS:
            key=f"{ticker}:{period}"
            old=outcomes.get(key)
            if old and old.get("raw_path"):
                verify_candidate_archive(old,archive)
                reused+=1
                continue
            if old and old.get("source_status") in (
                    "filing_not_found", "source_invalid_content",
                    "QUARTER_PRIMARY_CURRENCY_OR_CONTEXT_UNAVAILABLE"):
                continue
            if not execute or halted:
                continue
            if calls>=MAX_MOPS_REQUESTS:
                raise ValueError("phase14_maximum_official_quarter_request_cap")
            official_url=url_for(ticker,period)
            fetched=await fetcher.fetch(
                official_url,expect=("xbrl_instance","inline_xbrl","zip"))
            calls+=1
            outcome={
                "ticker":ticker,"reporting_period":period,
                "official_url":official_url,"source_status":fetched.status,
                "raw_path":"","raw_sha256":"","source_fact_count":0,
                "source_primary_twd_count":0,
                "source_conflicts":0,
                "outcome_label":"UNKNOWN",
                "normal_label_approved":False,
                "original_asof_verified":False,
            }
            if fetched.status=="ok" and fetched.content:
                kind=detect_format(fetched.content)
                if kind not in ("xbrl_instance","inline_xbrl","zip"):
                    outcome["source_status"]="source_invalid_content"
                else:
                    item=archive.store(
                        ticker=ticker,period=period,content=fetched.content,
                        detected_format=kind,retrieval=fetched.metadata())
                    outcome.update(raw_path=item.relative_path,raw_sha256=item.content_hash)
                    try:
                        records,diag,eligible,conflicts=extract_source(
                            fetched.content,period,item.content_hash,ticker=ticker)
                        if diag["matches_requested_period_and_scope"] and records:
                            outcome["source_status"]=VALID
                            outcome["source_fact_count"]=len(records)
                            outcome["source_primary_twd_count"]=eligible
                            outcome["source_conflicts"]=len(conflicts)
                        else:
                            outcome["source_status"]="QUARTER_PRIMARY_CURRENCY_OR_CONTEXT_UNAVAILABLE"
                    except (ValueError,RuntimeError) as exc:
                        outcome["source_status"]="QUARTER_PARSE_OR_IDENTITY_REJECTED"
                        outcome["parse_error_category"]=type(exc).__name__
            outcomes[key]=outcome
            atomic_json(manifest,{"schema":"phase14_official_quarter_v1",
                                  "outcomes":outcomes,
                                  "holdout_1785":True,"positive_labels":0,"negative_labels":0})
            print(f"[Phase14 {calls}/{EXPECTED_JOBS}] {ticker} {period}: "
                  f"{outcome['source_status']}",flush=True)
            if outcome["source_status"] in ("source_unavailable","source_invalid_content"):
                consecutive_access_failures+=1
            else:
                consecutive_access_failures=0
            if consecutive_access_failures>=stop_after_failures:
                halted=True
    # Verify all stored source bytes after the run; never silently treat
    # missing periods as financial zero or completed time-series windows.
    statuses=Counter()
    quarter_rows=[]
    observations=[]
    company_summary=[]
    signals=[]
    for company in selected:
        ticker=company["ticker"]
        company_obs=[]
        valid_periods=0
        for period in FROZEN_PERIODS:
            row=outcomes.get(f"{ticker}:{period}")
            status=row["source_status"] if row else "NOT_REQUESTED"
            statuses[status]+=1
            count=accepted=conflicts=0
            if row and row.get("raw_path"):
                res=verify_candidate_archive(row,archive) if row["source_status"]==VALID else None
                if res is not None:
                    observed,conflicts=res
                    count=row["source_primary_twd_count"]
                    accepted=sum(r["reconciliation_status"]==
                                 "CANDIDATE_CONSISTENT_REPETITIONS" for r in observed)
                    company_obs.extend(observed)
                    valid_periods+=1
            quarter_rows.append({
                "ticker":ticker,"industry_category":company["industry_category"],
                "market":company["market"],"reporting_period":period,
                "source_status":status,"official_url":url_for(ticker,period),
                "raw_sha256":row.get("raw_sha256","") if row else "",
                "archive_relative_path":row.get("raw_path","") if row else "",
                "xbrl_entity_and_scope_checked":str(status==VALID).lower(),
                "requested_period_checked":str(status==VALID).lower(),
                "primary_twd_source_observations":count,
                "accepted_concept_grain_observations":accepted,
                "quarantined_conflicting_concepts":conflicts,
                "original_filing_version_verified":"false",
                "first_publication_verified":"false",
                "outcome_label":"UNKNOWN","normal_label_approved":"false",
                "training_admitted":"false",
            })
        observations.extend(company_obs)
        actual_signals=derive_signals(company_obs,ticker=ticker)
        signals.extend(actual_signals)
        company_summary.append({
            "ticker":ticker,"industry_category":company["industry_category"],
            "market":company["market"],"quarters_expected":QUARTERS_EACH,
            "quarters_source_validated":valid_periods,
            "financial_observations":len(company_obs),
            "candidate_signals":len(actual_signals),
            "distinct_concept_grains":len({(r["concept_key"],r["period_grain"])
                 for r in company_obs if r["reconciliation_status"]==
                 "CANDIDATE_CONSISTENT_REPETITIONS"}),
            "historical_issuer_listing_verified":"false",
            "normal_outcome_label":"UNKNOWN",
            "supervised_training_approved":"false"
        })
    write_csv(root/"multiissuer_official_quarter_sources.csv",SOURCE_COLUMNS,quarter_rows)
    write_csv(root/"multiissuer_quarter_twd_observations.csv",OBS_FIELDS,observations)
    write_csv(root/"multiissuer_quarter_same_grain_changes.csv",SIGNAL_FIELDS,signals)
    write_csv(root/"multiissuer_source_coverage.csv",QUARTER_COLUMNS,company_summary)
    types=Counter(row["comparison"] for row in signals)
    source_sha=hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else ""
    report={
        "status":"PHASE14_CROSS_INDUSTRY_QUARTERLY_SOURCE_COHORT_UNLABELED",
        "selected_issuers":len(selected),
        "selected_semiconductors":sum(x["industry_category"]=="半導體業"
                                     for x in selected),
        "selected_industries":len({x["industry_category"] for x in selected}),
        "selected_boards":dict(sorted(Counter(x["market"] for x in selected).items())),
        "selection_based_on_current_listing_not_historical_survivor_free":True,
        "quarter_periods_per_issuer":QUARTERS_EACH,
        "official_quarter_jobs":EXPECTED_JOBS,
        "new_network_requests_this_run":calls,
        "previous_SHA_archives_reused":reused,
        "source_status_counts":dict(sorted(statuses.items())),
        "official_quarters_context_and_primary_TWD_validated":statuses[VALID],
        "fully_sourced_12_quarter_comparison_issuers":sum(
             r["quarters_source_validated"]==12 for r in company_summary),
        "source_TWD_observation_rows":len(observations),
        "unreviewed_same_grain_changes":len(signals),
        "same_grain_change_types":dict(sorted(types.items())),
        "stopped_for_repeated_access_errors":halted,
        "primary_source_assembly_SHA256":source_sha,
        "source_cohort_SHA256":frozen["source_cohort_sha256"],
        "historically_original_filings_approved":0,
        "filing_first_publication_times_approved":0,
        "verified_true_negative_company_quarters":0,
        "verified_false_filing_positive_company_quarters":0,
        "supervised_ml_rows_admitted":0,
        "case_issuer_6452_kept_separately":True,
        "case_issuer_3027_8299_excluded":True,
        "final_holdout_1785_excluded":True,
        "production_db_writes":0,
        "scientific_warning":"Selected current-listed companies and official 2026-accessible "
          "historic XBRL are only retrospective UNLABELED comparison candidates. "
          "Do not train genuine fraud/normal classifiers, assume 2017 historical "
          "listing, conflate taxonomy-version concept names, or report "
          "historical early-warning accuracy without first-filing/version "
          "and independent outcome evidence.",
    }
    atomic_json(root/"phase14_integrated_report.json",report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Phase14 official multi-industry 12x12 quarterly source-compatibility study")
    p.add_argument("--cohort-csv",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--execute",action="store_true")
    args=p.parse_args(argv)
    print(json.dumps(asyncio.run(run(args.cohort_csv,args.output,
                                     execute=args.execute)),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
