"""Phase10: actually compute original Beneish8/Dechow7 formulas for 3 Taiwan cases.

Consumes Phase9's locally SHA-verified MOPS XBRL archives and frozen
issuer-years; both values and model scores remain RETROSPECTIVE UNAPPROVED.
Builds exact per-year, per-feature, and case 3-year-window gap reports.
No automatic positive/negative label, no 1785, no actual model training.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .literature_dataset import FEATURES, produce
from .phase1_case_registry import validate
from .phase6_official_evidence_recovery import ROOT_SEED
from .phase8_original_filing_intake import case_needs
from .phase9_case_mops_xbrl_recovery import ARCHIVE_TABLE, validate_manifest

CASE_COLUMNS=(
    "ticker","fiscal_year","official_xbrl_status","source_sha256",
    "official_statement_scope","official_filing_version_type",
    "beneish_components_computed","dechow_components_computed",
    "components_computed","components_required","beneish_score_retrospective",
    "dechow_score_retrospective","original_filing_vintage_verified",
    "historical_filing_publication_at_verified","original_notice_publication_at_verified",
    "outcome_label","approved_positive_label","approved_negative_label",
    "admitted_for_supervised_learning","method","feature_values_json"
)
MISSING_COLUMNS=("ticker","fiscal_year","feature","missing_reason",
                 "source_status","historical_original_version_verified",
                 "missing_not_financial_zero")
WINDOW_COLUMNS=(
    "ticker","target_fiscal_year","candidate_event_review_only",
    "source_years","expected_source_years","archived_years",
    "official_15_feature_cells_observed","official_15_feature_cells_required",
    "full_3yr_literature_sequence","asof_model_training_approved",
    "independent_positive_outcome_approved",
    "missing_source_years","missing_15_feature_cells",
    "warning"
)


def load_csv(path,required):
    with Path(path).open(encoding="utf-8-sig",newline="") as stream:
        rd=csv.DictReader(stream)
        missing=set(required)-set(rd.fieldnames or [])
        if missing:
            raise ValueError("source_table_missing_required_columns:"+",".join(sorted(missing)))
        return list(rd)


def write_csv(path,fields,rows):
    with Path(path).open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def paper_values(row):
    result={}
    for name in FEATURES:
        raw=str(row[name]).strip()
        if raw:
            try:
                value=Decimal(raw)
            except InvalidOperation:
                raise ValueError("non_numeric_published_literature_feature")
            if not value.is_finite():
                raise ValueError("nonfinite_published_literature_feature")
            result[name]=format(value,"f")
        else:
            result[name]=""
    if sum(bool(result[n]) for n in FEATURES)!=int(row["components_computed"]):
        raise ValueError("literature_formula_component_count_conflict")
    return result


def run(data_root,output):
    root=Path(data_root)
    phase9=root/"phase9_case_mops_xbrl_candidates"
    phase7=root/"phase7_official_case_asof_recovery"
    output=Path(output)
    review=phase9/"phase9_case_mops_version_review.csv"
    manifest=phase9/"acquisition_results.json"
    source_rows=load_csv(review,ARCHIVE_TABLE)
    if len(source_rows)!=13:
        raise ValueError("phase9_source_year_inventory_incomplete")
    seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
    cases=validate(seed)
    needs=case_needs(phase7/"phase7_original_filing_asof_gap_queue.csv",seed)
    source_index={}
    for entry in source_rows:
        ticker,year=entry["ticker"],int(entry["fiscal_year"])
        if ticker=="1785" or (ticker,year) not in needs or (ticker,year) in source_index:
            raise ValueError("source_research_case_identity_not_allowed")
        if (entry["financial_statement_misstatement_label"]!="UNKNOWN"
            or entry["approved_for_historical_model_training"].lower()!="false"
            or entry["historical_original_filing_version_verified"].lower()!="false"
            or entry["source_publication_timestamp_verified"].lower()!="false"):
            raise ValueError("unapproved_historical_feature_or_outcome_promotion")
        source_index[(ticker,year)]=entry
    if set(source_index)!=set(needs):
        raise ValueError("case_fiscal_years_must_match_frozen_registry")
    planned=[{
        "ticker":t,"fiscal_year":y
    } for (t,y) in sorted(source_index) if y>=2013]
    raw=validate_manifest(manifest,planned)
    # Existing published Beneish8/Dechow7 engines, without adding any aliases.
    formula_report=produce(manifest,output/"official_case_literature",
                           min_year=2013,max_year=2025)
    actual=load_csv(output/"official_case_literature"/"literature_15_features.csv",
                    ("ticker","fiscal_year","raw_sha256","analysis_mode",
                     "training_label","accounting_framework","statement_scope",
                     "filing_version_type","beneish_m_score","dechow_f_score",
                     "components_computed",*FEATURES))
    feature_index={}
    for record in actual:
        ticker,year=record["ticker"],int(record["fiscal_year"])
        key=(ticker,year)
        if key not in source_index or key in feature_index:
            raise ValueError("literature_feature_extractor_unexpected_or_duplicate_case")
        official=raw.get(f"{ticker}:{year}")
        if not official or official.get("status")!="validated":
            raise ValueError("literature_feature_not_from_validated_XBRL")
        if record["raw_sha256"]!=official["content_hash"]:
            raise ValueError("formula_features_source_sha_conflict")
        if (record["analysis_mode"]!="retrospective"
            or record["training_label"]!="UNREVIEWED"
            or record["accounting_framework"]!="TIFRS"
            or record["statement_scope"]!="consolidated"):
            raise ValueError("unapproved_literature_feature_scope_or_label")
        feature_index[key]=record
    rows=[]
    missing=[]
    for (ticker,year),source in sorted(source_index.items()):
        outcome=feature_index.get((ticker,year))
        values=paper_values(outcome) if outcome else {name:"" for name in FEATURES}
        n=sum(bool(values[x]) for x in FEATURES)
        if n and source["acquisition_status"]!="validated":
            raise ValueError("computed_components_from_unvalidated_source")
        if year<=2012 and (outcome or source["source_raw_sha256"]):
            raise ValueError("pre_tifrs_accounting_data_improperly_used_as_tifrs")
        rows.append({
            "ticker":ticker,"fiscal_year":year,
            "official_xbrl_status":source["acquisition_status"],
            "source_sha256":source["source_raw_sha256"],
            "official_statement_scope":source["xbrl_statement_scope"],
            "official_filing_version_type":source["xbrl_filing_version_type"],
            "beneish_components_computed":sum(bool(values[n]) for n in FEATURES[:8]),
            "dechow_components_computed":sum(bool(values[n]) for n in FEATURES[8:]),
            "components_computed":n,"components_required":15,
            "beneish_score_retrospective":outcome["beneish_m_score"] if outcome else "",
            "dechow_score_retrospective":outcome["dechow_f_score"] if outcome else "",
            "original_filing_vintage_verified":"false",
            "historical_filing_publication_at_verified":"false",
            "original_notice_publication_at_verified":"false",
            "outcome_label":"UNKNOWN",
            "approved_positive_label":"false","approved_negative_label":"false",
            "admitted_for_supervised_learning":"false",
            "method":"ORIGINAL_BENEISH_1999_AND_DECHOW_2011_RETROSPECTIVE_ONLY",
            "feature_values_json":json.dumps(values,sort_keys=True)
        })
        for name in FEATURES:
            if values[name]:
                continue
            reason=("PRE_TIFRS_REPORT_SEPARATE_GAAP_METHOD_NEEDED" if year<=2012
                    else "OFFICIAL_XBRL_UNAVAILABLE_OR_NOT_PARSED"
                    if source["acquisition_status"]!="validated"
                    else "ORIGINAL_PAPER_COMPONENT_SOURCE_OR_HISTORY_MISSING")
            missing.append({
                "ticker":ticker,"fiscal_year":year,
                "feature":name,"missing_reason":reason,
                "source_status":source["acquisition_status"],
                "historical_original_version_verified":"false",
                "missing_not_financial_zero":"true"
            })
    # Model scores can exist even when other components are absent. Retrospective
    # computed scores are preserved ONLY as descriptive features, not fraud risk.
    by_year={(row["ticker"],int(row["fiscal_year"])):row for row in rows}
    windows=[]
    for case in cases:
        for target in case["affected_fiscal_years"]:
            years=list(range(target-2,target+1))
            sources=[by_year[(case["ticker"],year)] for year in years]
            observed=sum(int(row["components_computed"]) for row in sources)
            lack=[year for year,row in zip(years,sources)
                  if row["official_xbrl_status"]!="validated"]
            windows.append({
                "ticker":case["ticker"],"target_fiscal_year":target,
                "candidate_event_review_only":"true",
                "source_years":"|".join(map(str,years)),
                "expected_source_years":3,
                "archived_years":sum(row["official_xbrl_status"]=="validated" for row in sources),
                "official_15_feature_cells_observed":observed,
                "official_15_feature_cells_required":45,
                "full_3yr_literature_sequence":str(observed==45).lower(),
                "asof_model_training_approved":"false",
                "independent_positive_outcome_approved":"false",
                "missing_source_years":"|".join(map(str,lack)),
                "missing_15_feature_cells":45-observed,
                "warning":"RETROSPECTIVE_XBRL_SOURCE_AND_OUTCOME_UNVERIFIED"
            })
    output.mkdir(parents=True,exist_ok=True)
    write_csv(output/"phase10_case_official_paper_features.csv",CASE_COLUMNS,rows)
    write_csv(output/"phase10_case_missing_features.csv",MISSING_COLUMNS,missing)
    write_csv(output/"phase10_case_three_year_windows.csv",WINDOW_COLUMNS,windows)
    count=Counter(row["official_xbrl_status"] for row in rows)
    coverage=Counter()
    for row in rows:
        values=json.loads(row["feature_values_json"])
        coverage.update({name:int(bool(value)) for name,value in values.items()})
    report={
        "status":"PHASE10_CASE_OFFICIAL_LITERATURE_FEATURES_RETROSPECTIVE_ONLY",
        "source_issuer_year_rows":len(rows),
        "official_archived_xbrl_years":count.get("validated",0),
        "source_status_counts":dict(sorted(count.items())),
        "missing_official_years":[{"ticker":r["ticker"],"fiscal_year":r["fiscal_year"],
                                  "status":r["official_xbrl_status"]}
                                 for r in rows if r["official_xbrl_status"]!="validated"],
        "actual_paper_feature_years":len(actual),
        "fully_computed_15_feature_years":sum(row["components_computed"]==15 for row in rows),
        "beneish8_complete_years":sum(row["beneish_components_computed"]==8 for row in rows),
        "dechow7_complete_years":sum(row["dechow_components_computed"]==7 for row in rows),
        "official_paper_variable_coverage":dict(sorted(coverage.items())),
        "year_feature_cells_computed":sum(r["components_computed"] for r in rows),
        "year_feature_cells_required":len(rows)*len(FEATURES),
        "missing_literature_feature_cells":len(missing),
        "candidate_event_three_year_windows":len(windows),
        "complete_three_year_paper_windows":sum(w["full_3yr_literature_sequence"]=="true"
                                               for w in windows),
        "original_pre_correction_versions_verified":0,
        "earliest_filing_publication_times_verified":0,
        "first_market_disclosure_times_verified":0,
        "verified_positive_labels":0,"verified_negative_labels":0,
        "historical_asof_training_rows_admitted":0,
        "final_holdout_1785_excluded":True,
        "production_db_writes":0,"network_requests":0,
        "paper_extraction_report":formula_report,
        "source_manifest_sha256":hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "warning":"Computed Beneish/Dechow scores and 15 paper variables are retrospective "
                 "descriptions of MOPS currently accessible financials; values cannot "
                 "be used for genuine pre-public-revelation 1785-style prediction "
                 "until original statement vintages, first publication times, "
                 "affected-year legal outcomes and clean comparison cohort are approved."
    }
    (output/"phase10_integrated_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Offline official Taiwanese case 15-paper-feature/vintage audit")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    print(json.dumps(run(args.data_root,args.output),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
