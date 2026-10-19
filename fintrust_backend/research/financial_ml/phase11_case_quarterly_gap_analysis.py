"""Phase11: actual Taiwan case reporting-period correction and quarter evidence.

One bounded MOPS Q1 2020 source lookup for 6452; exact 15-paper-feature
missing-reason drilldown from Phase10. Does not reinterpret a 2020 annual
MOPS filing-not-found as proof the alleged 2020Q1 report never existed.

All labels UNKNOWN, first-filing availability unverified, 1785 untouched.
No annual Beneish/Dechow formulas computed from a single quarter.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.sources import OfficialSourceFetcher, ensure_official_url, mops_annual_url
from app.services.historical_audit.xbrl_document import detect_format, parse_xbrl_document
from .literature_dataset import FEATURES
from .official_batch import atomic_json
from .phase1_case_registry import validate
from .phase6_official_evidence_recovery import ROOT_SEED

QUARTER_TICKER="6452"
QUARTER_YEAR=2020
QUARTER=1
PRIMARY_URL=ensure_official_url(mops_annual_url(QUARTER_TICKER,QUARTER_YEAR)
                                  .replace("season=4","season=1"))
PERIOD_COLUMNS=(
    "ticker","reporting_period","candidate_case_role","source_scope",
    "historical_original_filing_verified","first_publication_at_verified",
    "legal_outcome_fiscal_period_verified","verified_misstatement_label",
    "approved_for_supervised_training","review_note"
)
ISSUE_COLUMNS=(
    "feature","case_years_missing","observed_missing_reason_instances",
    "reason_codes","requires_original_filing_or_account_mapping_review",
    "missing_is_not_financial_zero","case_selection_not_based_on_label"
)

def table(path,columns,rows):
    with Path(path).open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def case_reporting_periods(seed):
    cases=validate(seed)
    if {c["ticker"] for c in cases}!={"3027","6452","8299"}:
        raise ValueError("phase11_case_registry_mismatch")
    result=[]
    for c in cases:
        ticker=c["ticker"]
        if ticker=="6452":
            if c["affected_fiscal_years"] != [2017,2018,2019,2020]:
                raise ValueError("6452_quarterly_case_scope_changed")
            if "2020 Q1" not in c["affected_reporting_period_description"]:
                raise ValueError("quarterly_allegation_scope_not_grounded_in_case_seed")
            # Quarters Q2 2017 .. Q1 2020 (12 quarters), allegations only.
            parts=[(year,q) for year in range(2017,2021)
                   for q in range(1,5)
                   if (year,q)>=(2017,2) and (year,q)<=(2020,1)]
            for year,q in parts:
                result.append({
                    "ticker":ticker,"reporting_period":f"{year}Q{q}",
                    "candidate_case_role":"OFFICIAL_CIVIL_CLAIM_NOT_PERIOD_CONFIRMED",
                    "source_scope":"QUARTERLY_CLAIM_NOT_ANNUAL_2020",
                    "historical_original_filing_verified":"false",
                    "first_publication_at_verified":"false",
                    "legal_outcome_fiscal_period_verified":"false",
                    "verified_misstatement_label":"UNKNOWN",
                    "approved_for_supervised_training":"false",
                    "review_note":"Investor-protection alleged quarter range; no per-quarter judicial confirmation."
                })
        else:
            for year in c["affected_fiscal_years"]:
                result.append({
                    "ticker":ticker,"reporting_period":f"{year}FY",
                    "candidate_case_role":"JUDICIAL_CONTEXT_PERIOD_REVIEW_PENDING",
                    "source_scope":"ANNUAL_CANDIDATE_EXACT_QUARTERS_PENDING",
                    "historical_original_filing_verified":"false",
                    "first_publication_at_verified":"false",
                    "legal_outcome_fiscal_period_verified":"false",
                    "verified_misstatement_label":"UNKNOWN",
                    "approved_for_supervised_training":"false",
                    "review_note":"Do not treat later judgment or model score as available at filing date."
                })
    return sorted(result,key=lambda r:(r["ticker"],r["reporting_period"]))


def yearly_missing_reasons(phase10_root):
    report=json.loads((Path(phase10_root)/"phase10_integrated_report.json").read_text(encoding="utf-8"))
    if (report.get("final_holdout_1785_excluded") is not True
        or report.get("verified_positive_labels")!=0
        or report.get("historical_asof_training_rows_admitted")!=0):
        raise ValueError("phase10_provenance_gate_rejected")
    expected={feature:report["actual_paper_feature_years"]-count
              for feature,count in report["official_paper_variable_coverage"].items()}
    if set(expected)!=set(FEATURES):
        raise ValueError("original_15_published_paper_features_not_preserved")
    counters=Counter()
    reasons={key:Counter() for key in FEATURES}
    detail=Path(phase10_root)/"official_case_literature"/"literature_missing_reasons.jsonl"
    with detail.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            item=json.loads(line)
            if item.get("stage")!="missing_components":
                continue
            for component in item.get("details",[]):
                feature=component["variable"]
                if feature not in expected:
                    raise ValueError("unknown_case_paper_component_from_extractor")
                counters[feature]+=1
                explanations=component.get("reasons") or []
                if not explanations:
                    reasons[feature][component.get("status") or "EXTRACTOR_UNSPECIFIED"]+=1
                for reason in explanations:
                    if isinstance(reason,dict):
                        label=reason.get("code") or reason.get("reason") or str(reason)
                    else:
                        label=str(reason)
                    reasons[feature][str(label)[:160]]+=1
    if any(counters[feature]!=expected[feature] for feature in FEATURES):
        raise ValueError("phase10_literature_missing_reason_count_not_reproducible")
    issues=[{
        "feature":feature,
        "case_years_missing":expected[feature],
        "observed_missing_reason_instances":counters[feature],
        "reason_codes":json.dumps(dict(reasons[feature].most_common()),ensure_ascii=False),
        "requires_original_filing_or_account_mapping_review":"true",
        "missing_is_not_financial_zero":"true",
        "case_selection_not_based_on_label":"true"
    } for feature in FEATURES]
    return sorted(issues,key=lambda r:(-r["case_years_missing"],r["feature"]))


def _parsed_quarter_metadata(raw):
    document=parse_xbrl_document(raw)
    end="2020-03-31"
    matching=[c for c in document.contexts.values() if
              not c.dimensional and
              ((c.instant and c.instant.isoformat()==end) or
               (c.end and c.end.isoformat()==end))]
    scope,scope_evidence=document.statement_scope()
    return {
        "document_format":document.document_format,
        "reported_scope":scope,
        "scope_evidence":scope_evidence,
        "quarter_end_contexts":len(matching),
        "contexts_total":len(document.contexts),
        "numeric_facts_total":len(document.numeric_facts),
        "source_schema_refs":len(document.schema_refs),
        "q1_2020_context_proven":bool(matching),
        "original_filing_vintage_verified":False,
        "historical_publication_time_verified":False,
        "annual_literature_score_calculated":False
    }


async def acquire_6452_2020q1(output,*,execute=False,fetcher=None):
    """One official URL, fixed case and quarter, raw SHA resume. No annual normalization."""
    root=Path(output)
    root.mkdir(parents=True,exist_ok=True)
    archive=RawEvidenceArchive(root/"raw")
    manifest=root/"quarterly_source_status.json"
    if manifest.exists():
        old=json.loads(manifest.read_text(encoding="utf-8"))
        if old.get("ticker")!=QUARTER_TICKER or old.get("reporting_period")!="2020Q1":
            raise ValueError("quarterly_prior_manifest_identity_conflict")
        if old.get("source_url")!=PRIMARY_URL:
            raise ValueError("quarterly_mops_url_changed_from_approved_source")
        if old.get("raw_path"):
            raw=archive.read(old["raw_path"])
            if hashlib.sha256(raw).hexdigest()!=old["raw_sha256"]:
                raise ValueError("quarterly_cache_source_hash_mismatch")
            old["network_requests_this_run"]=0
            old["cached_reused"]=True
            atomic_json(manifest,old)
            return old
    state={
        "ticker":QUARTER_TICKER,"reporting_period":"2020Q1",
        "source_url":PRIMARY_URL,"acquisition_status":"NOT_REQUESTED",
        "raw_path":"","raw_sha256":"","raw_bytes":0,
        "document_diagnostics":None,
        "network_requests_this_run":0,"cached_reused":False,
        "verified_historical_original":False,"first_publication_verified":False,
        "misstatement_label":"UNKNOWN","model_admitted":False,
        "quarterly_data_used_as_fy2020_annual":False
    }
    if not execute:
        atomic_json(manifest,state)
        return state
    fetcher=fetcher or OfficialSourceFetcher(min_interval_seconds=2.0,max_attempts=2)
    response=await fetcher.fetch(PRIMARY_URL,expect=("xbrl_instance","inline_xbrl","zip"))
    state["network_requests_this_run"]=1
    state["acquisition_status"]=response.status
    if response.status=="ok" and response.content:
        format_name=detect_format(response.content)
        result=archive.store(
            ticker=QUARTER_TICKER,period="2020Q1",
            content=response.content,detected_format=format_name,
            retrieval=response.metadata())
        state.update(raw_path=result.relative_path,
                     raw_sha256=result.content_hash,
                     raw_bytes=len(response.content))
        try:
            diagnostic=_parsed_quarter_metadata(response.content)
            state["document_diagnostics"]=diagnostic
            if diagnostic["q1_2020_context_proven"] and diagnostic["reported_scope"]=="consolidated":
                state["acquisition_status"]="QUARTERLY_XBRL_CONTEXT_FOUND_VINTAGE_UNKNOWN"
            else:
                state["acquisition_status"]="QUARTERLY_XBRL_QUARANTINED_PERIOD_OR_SCOPE"
        except (ValueError,RuntimeError,OSError) as e:
            state["acquisition_status"]="QUARTERLY_XBRL_PARSE_FAILED"
            state["parse_error_category"]=type(e).__name__
    atomic_json(manifest,state)
    return state


async def run(data_root,*,execute=False,fetcher=None):
    base=Path(data_root)
    source=base/"phase10_case_official_paper_audit"
    dest=base/"phase11_case_quarterly_and_paper_gaps"
    dest.mkdir(parents=True,exist_ok=True)
    seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
    periods=case_reporting_periods(seed)
    gaps=yearly_missing_reasons(source)
    table(dest/"case_precise_reporting_period_candidates.csv",PERIOD_COLUMNS,periods)
    table(dest/"paper_feature_missing_reason_priority.csv",ISSUE_COLUMNS,gaps)
    quarter=await acquire_6452_2020q1(dest/"official_quarterly_source",execute=execute,fetcher=fetcher)
    result={
        "status":"PHASE11_TAIWAN_QUARTERLY_EVIDENCE_AND_PAPER_REASON_TRACE_ONLY",
        "case_reporting_period_candidates":len(periods),
        "6452_alleged_quarterly_periods":sum(r["ticker"]=="6452" for r in periods),
        "other_case_annual_period_candidates":sum(r["ticker"]!="6452" for r in periods),
        "6452_2020Q1_not_FY2020_annual":True,
        "year_2020_annual_filing_not_found_not_interpreted_as_2020Q1_not_filed":True,
        "separately_required_8299_TW_GAAP_FY2012":True,
        "phase10_official_15_feature_cells_missing":sum(row["case_years_missing"] for row in gaps),
        "unresolved_paper_features_by_year_missing":{
            row["feature"]:row["case_years_missing"] for row in gaps
        },
        "quarterly_source_status":quarter,
        "network_requests":quarter["network_requests_this_run"],
        "original_company_report_vintages_verified":0,
        "earliest_filing_times_verified":0,
        "confirmed_positive_labels":0,"audited_negative_labels":0,
        "supervised_early_warning_samples":0,
        "holdout_1785_excluded":True,"production_db_writes":0,
        "warnings":[
            "The SFIPC 6452 2017Q2–2020Q1 period scope is an allegation, not 12 confirmed labels.",
            "Quarter 2020Q1 cannot replace FY2020 and cannot directly supply annual Beneish/Dechow scores.",
            "An official MOPS Q1 currently retrieved file may be revised, not original first-released report.",
            "Feature reason codes reflect existing published mapping, not a license to inject invented alias values.",
            "No retrospective archive or legal finding establishes a valid pre-revelation prediction without historical original filing and timestamp."
        ]
    }
    atomic_json(dest/"phase11_integrated_report.json",result)
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description="One-quarter Taiwan misstatement scope and source mapping gap study")
    p.add_argument("--data-root",required=True)
    p.add_argument("--execute",action="store_true")
    args=p.parse_args(argv)
    print(json.dumps(asyncio.run(run(args.data_root,execute=args.execute)),
                     ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
