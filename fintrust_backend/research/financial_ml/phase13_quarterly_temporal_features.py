"""Phase13: same-concept, same-accounting-period quarterly TWD feature candidates.

Reads all twelve cached 6452 official iXBRL sources from Phase11/12.
Emits a source-level financial observation catalog and matched-quarter
changes. Nothing is classified as known false or known normal.

Explicitly separated: instant (balance), true-quarter duration, Jan1-YTD
duration and other. Full fiscal/quarter facts are NEVER summed/interchanged.
Computations are descriptive; all 2026-retrieved source vintages remain
unverified as originally public in the affected historical periods.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.normalization import _is_statement_namespace
from app.services.historical_audit.xbrl_document import parse_xbrl_document
from .official_batch import atomic_json
from .phase12_kangyou_quarterly_panel import (
    FROZEN_PERIODS, LATEST_CACHED, SOURCE_STATUS_OK, TICKER,
    analyze_document, freeze_plan, quarter_parts, read_phase11_prior,
    verify_prior_results, validate_cached,
)
from .phase6_official_evidence_recovery import ROOT_SEED

OBS_FIELDS=("ticker","reporting_period","concept_key","source_namespace",
    "source_local_name","period_grain","source_unit","value_decimal",
    "source_period_start","source_period_end","observation_count",
    "source_sha256","reconciliation_status",
    "source_original_vintage_verified","candidate_mapping_approved",
    "outcome_label","model_training_admitted")
SIGNAL_FIELDS=("ticker","reporting_period","prior_period",
    "comparison","concept_key","source_local_name","period_grain",
    "source_unit","prior_value_decimal","current_value_decimal",
    "delta_decimal","relative_change_abs_prior",
    "current_source_sha256","prior_source_sha256",
    "strict_same_concept_and_grain","historical_vintage_approved",
    "outcome_label","model_training_admitted")
COVERAGE_FIELDS=("concept_key","source_local_name","period_grain",
    "reporting_period_count","total_12_reporting_periods",
    "min_reporting_period","max_reporting_period","missing_periods",
    "numeric_currency_unit","approved_financial_feature")
QUARTER_FIELDS=("ticker","reporting_period","raw_sha256",
    "candidate_source_status","all_numeric_period_facts",
    "filtered_primary_TWD_nondimensional_observations",
    "accepted_unique_concept_grain_values","conflicting_concept_grain_values",
    "unit_or_dimension_filtered_not_source_zero",
    "historical_first_publication_verified","confirmed_outcome_label",
    "supervised_training_approved")
GRAINS=("instant","quarter_duration","ytd_duration","other_duration")


def write_csv(path, fields, rows):
    with Path(path).open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fields)
        w.writeheader();w.writerows(rows)


def period_grain(context,period):
    year,quarter,start,end=quarter_parts(period)
    if context.instant==end:
        return "instant",end.isoformat(),end.isoformat()
    if context.end!=end or context.start is None:
        return None
    if context.start==start:
        return "quarter_duration",start.isoformat(),end.isoformat()
    if context.start==date(year,1,1):
        return "ytd_duration",context.start.isoformat(),end.isoformat()
    return "other_duration",context.start.isoformat(),end.isoformat()


def extract_source(raw,period,sha):
    doc=parse_xbrl_document(raw)
    if doc.entity_identifiers and doc.entity_identifiers!={TICKER}:
        raise ValueError("quarterly_financial_fact_entity_mismatch")
    if doc.statement_scope()[0]!="consolidated":
        raise ValueError("quarterly_financial_fact_not_consolidated")
    diag=analyze_document(raw,period)
    if not diag["matches_requested_period_and_scope"]:
        raise ValueError("quarterly_financial_fact_wrong_period")
    # A context may hold comparative facts: accept only actual requested
    # period-end, never the prior year in a current-period source.
    cells=defaultdict(list)
    eligible=0
    for fact in doc.numeric_facts:
        ctx=doc.contexts.get(fact.context_ref)
        if (ctx is None or ctx.dimensional or fact.is_nil or fact.value is None
            or not _is_statement_namespace(fact.namespace)
            or doc.units.get(fact.unit_ref or "","").lower()!="iso4217:twd"):
            continue
        ident=period_grain(ctx,period)
        if ident is None:
            continue
        grain,start,end=ident
        eligible+=1
        # Namespace included. Do not equate similarly named tags in different
        # taxonomy versions without an independently reviewed mapping.
        key=f"{fact.namespace}|{fact.local_name}"
        cells[(key,grain,start,end)].append(fact.value)
    observations=[]
    conflicting=[]
    for (key,grain,start,end),numbers in sorted(cells.items()):
        unique=set(numbers)
        conflict=len(unique)>1
        if conflict:
            conflicting.append({
                "reporting_period":period,"concept_key":key,
                "period_grain":grain,"reason":"SAME_CONCEPT_GRAIN_DIFFERENT_TWD_VALUES"
            })
        namespace,name=key.rsplit("|",1)
        observations.append({
            "ticker":TICKER,"reporting_period":period,
            "concept_key":key,"source_namespace":namespace,
            "source_local_name":name,"period_grain":grain,
            "source_unit":"TWD",
            "value_decimal":str(numbers[0]) if not conflict else "",
            "source_period_start":start,"source_period_end":end,
            "observation_count":len(numbers),"source_sha256":sha,
            "reconciliation_status":"DUPLICATE_CONFLICT_QUARANTINED"
                if conflict else "CANDIDATE_CONSISTENT_REPETITIONS",
            "source_original_vintage_verified":"false",
            "candidate_mapping_approved":"false",
            "outcome_label":"UNKNOWN","model_training_admitted":"false",
        })
    return observations,diag,eligible,conflicting


def cached_documents(data_root):
    root=Path(data_root)
    period_root=root/"phase12_kangyou_quarterly_panel"
    report=json.loads((period_root/"phase12_integrated_report.json").read_text(encoding="utf-8"))
    if (report.get("issuer")!=TICKER
        or report.get("candidate_quarters")!=12
        or report.get("official_quarters_context_scope_validated")!=12
        or report.get("historical_original_filing_vintages_verified")!=0
        or report.get("confirmed_period_outcome_labels")!=0
        or report.get("financial_misstatement_supervised_training_rows")!=0
        or report.get("final_holdout_1785_excluded") is not True):
        raise ValueError("phase12_real_source_or_historical_label_gate")
    seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
    planned,_=freeze_plan(seed)
    manifest=period_root/"quarterly_acquisition_results.json"
    sources=verify_prior_results(manifest,planned)
    prior=read_phase11_prior(root)
    if set(sources)!=set(FROZEN_PERIODS)-{LATEST_CACHED}:
        raise ValueError("missing_one_or_more_expected_phase12_source_quarters")
    archive=RawEvidenceArchive(period_root/"raw")
    earlier=RawEvidenceArchive(
        root/"phase11_case_quarterly_and_paper_gaps"/"official_quarterly_source"/"raw")
    for period in FROZEN_PERIODS:
        source=prior if period==LATEST_CACHED else validate_cached(sources[period],archive)
        if source.get("status")!=SOURCE_STATUS_OK:
            raise ValueError("case_quarter_source_not_validated")
        store=earlier if period==LATEST_CACHED else archive
        raw=store.read(source["raw_path"])
        if hashlib.sha256(raw).hexdigest()!=source["raw_sha256"]:
            raise ValueError("quarter_source_raw_sha256_mismatch")
        yield period,source,raw


def derive_signals(observations):
    """Keep only real same-taxonomy, same-currency, same-grain changes.

    For stocks and exact-quarter flows compare previous quarter and same
    quarter prior year. For YTD cumulative flows compare only Q vs same Q
    last year; never Q3-YTD versus Q2-YTD as a quarter change.
    """
    rows={}
    for row in observations:
        if row["reconciliation_status"]!="CANDIDATE_CONSISTENT_REPETITIONS":
            continue
        if row["period_grain"]=="other_duration":
            continue
        key=(row["reporting_period"],row["concept_key"],row["period_grain"])
        if key in rows:
            raise ValueError("multiple_unreconciled_values_in_same_quarter")
        rows[key]=row
    output=[]
    for (period,concept,grain),cur in sorted(rows.items()):
        idx=FROZEN_PERIODS.index(period)
        pairs=[]
        if grain in ("instant","quarter_duration") and idx>=1:
            pairs.append(("QOQ_SAME_GRAIN",FROZEN_PERIODS[idx-1]))
        if idx>=4:
            pairs.append(("YOY_SAME_QUARTER_SAME_GRAIN",FROZEN_PERIODS[idx-4]))
        for comparison,previous in pairs:
            older=rows.get((previous,concept,grain))
            if older is None:
                continue
            curr=Decimal(cur["value_decimal"])
            prev=Decimal(older["value_decimal"])
            delta=curr-prev
            # Abs denominator explicitly documents signed cashflows/equity.
            relative=str(delta/abs(prev)) if prev else ""
            output.append({
                "ticker":TICKER,"reporting_period":period,
                "prior_period":previous,"comparison":comparison,
                "concept_key":concept,"source_local_name":cur["source_local_name"],
                "period_grain":grain,"source_unit":"TWD",
                "prior_value_decimal":str(prev),
                "current_value_decimal":str(curr),
                "delta_decimal":str(delta),
                "relative_change_abs_prior":relative,
                "current_source_sha256":cur["source_sha256"],
                "prior_source_sha256":older["source_sha256"],
                "strict_same_concept_and_grain":"true",
                "historical_vintage_approved":"false",
                "outcome_label":"UNKNOWN","model_training_admitted":"false",
            })
    return output


def coverage_rows(observations):
    by_concept=defaultdict(set)
    for row in observations:
        if row["reconciliation_status"]=="CANDIDATE_CONSISTENT_REPETITIONS" and row[
                "period_grain"]!="other_duration":
            by_concept[(row["concept_key"],row["period_grain"])].add(row["reporting_period"])
    result=[]
    for (key,grain),have in sorted(by_concept.items()):
        _,name=key.rsplit("|",1)
        result.append({
            "concept_key":key,"source_local_name":name,"period_grain":grain,
            "reporting_period_count":len(have),
            "total_12_reporting_periods":12,
            "min_reporting_period":min(have),"max_reporting_period":max(have),
            "missing_periods":"|".join(x for x in FROZEN_PERIODS if x not in have),
            "numeric_currency_unit":"TWD","approved_financial_feature":"false"
        })
    return result


def run(data_root,output):
    out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    observations=[]
    summary=[]
    conflicts=[]
    for period,source,raw in cached_documents(data_root):
        lines,diag,eligible,issues=extract_source(raw,period,source["raw_sha256"])
        observations.extend(lines)
        conflicts.extend(issues)
        summary.append({
            "ticker":TICKER,"reporting_period":period,
            "raw_sha256":source["raw_sha256"],
            "candidate_source_status":source["status"],
            "all_numeric_period_facts":diag["numeric_current_period_facts"],
            "filtered_primary_TWD_nondimensional_observations":eligible,
            "accepted_unique_concept_grain_values":sum(
                r["reconciliation_status"]=="CANDIDATE_CONSISTENT_REPETITIONS"
                for r in lines),
            "conflicting_concept_grain_values":len(issues),
            "unit_or_dimension_filtered_not_source_zero":
                diag["numeric_current_period_facts"]-eligible,
            "historical_first_publication_verified":"false",
            "confirmed_outcome_label":"UNKNOWN","supervised_training_approved":"false"
        })
    signals=derive_signals(observations)
    coverage=coverage_rows(observations)
    write_csv(out/"quarterly_twd_source_observations.csv",OBS_FIELDS,observations)
    write_csv(out/"quarterly_same_grain_change_candidates.csv",SIGNAL_FIELDS,signals)
    write_csv(out/"quarterly_concept_coverage.csv",COVERAGE_FIELDS,coverage)
    write_csv(out/"quarter_source_quality.csv",QUARTER_FIELDS,summary)
    counts=Counter(s["comparison"] for s in signals)
    report={
        "status":"PHASE13_12_QUARTER_UNLABELED_SAME_GRAIN_FINANCIAL_FEATURE_CANDIDATES",
        "issuer":TICKER,
        "official_source_quarters_read":len(summary),
        "input_phase12_sha256":hashlib.sha256(
            (Path(data_root)/"phase12_kangyou_quarterly_panel"/
             "phase12_integrated_report.json").read_bytes()).hexdigest(),
        "total_primary_statement_TWD_period_observations":sum(
            r["filtered_primary_TWD_nondimensional_observations"] for r in summary),
        "unique_concept_grain_quarter_candidates":len(observations),
        "conflicting_concept_grain_quarters_quarantined":len(conflicts),
        "candidate_concepts_with_observations":len(coverage),
        "same_grain_change_candidates":len(signals),
        "same_grain_change_types":dict(sorted(counts.items())),
        "independent_issuer_count":1,
        "independent_true_misstatement_labels":0,
        "model_training_rows_admitted":0,
        "genuine_historical_original_filing_versions_verified":0,
        "first_publication_times_verified":0,
        "no_2020q1_redownload":True,
        "financial_zero_not_inferred_from_missing_concept":True,
        "never_sum_ytd_into_single_quarter":True,
        "b_eight_d_seven_formulas_computed_from_quarters":False,
        "is_this_a_valid_multi_company_ml_dataset":False,
        "2020q1_alleged_reporting_period_not_full_fy2020":True,
        "1785_final_holdout_excluded":True,
        "network_requests":0,"production_db_writes":0,
        "limitations":[
            "All observations are 2026-accessible retrospective filings whose original pre-revision publication versions remain unverified.",
            "Namespace URI and exact fact name must match across periods; taxonomy version transitions may reduce comparability and are NOT silently collapsed.",
            "No source concept is independently approved as a Beneish/Dechow COMPUSTAT input by this technical extraction.",
            "Matched-quarter changes are descriptive measurement candidates, not early fraud warning predictions or fraud probabilities.",
            "A single issuer and 12 potentially overlapping retrospective quarters cannot substantiate supervised false-financial-statement detection accuracy.",
            "Current official litigation alleges a range of quarterly reports; every company-quarter outcome remains UNKNOWN."
        ]
    }
    atomic_json(out/"phase13_integrated_report.json",report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Retrospective MOPS TWD quarter facts, strict same-concept/grain changes")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args(argv)
    print(json.dumps(run(a.data_root,a.output),ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
