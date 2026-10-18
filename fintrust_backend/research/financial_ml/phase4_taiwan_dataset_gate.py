"""Phase 4 Taiwan-only historical feature register, dual-axis splits and source disputes.

NO MODEL TRAINING. NO fake "normal" labels. NO approved feature admissions.
Computes immutable issuer/time splits for the official and provider-candidate
observations independently. Annual fiscal year is NOT a filing publication date.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .literature_dataset import FEATURES
from .finmind_cross_industry_pilot import read_universe
from .phase1_case_registry import validate as validate_cases

SCHEMA = "taiwan_misstatement_research_split_v1"
CASE_REGISTRY = Path(__file__).with_name("phase1_case_sources_seed.json")
TIME_BANDS = {"fit":(2013,2020), "validation":(2021,2022), "test":(2023,2025)}
SPLIT_COLUMNS = (
    "ticker","fiscal_year","evidence_tier","issuer_split","temporal_split",
    "joint_strict_split","development_event_candidate","full_15_features",
    "available_feature_count","official_source","filing_version_type",
    "source_raw_sha256","dataset_sha256",
    "first_filing_publication_verified","original_vintage_verified",
    "outcome_label","outcome_known_at_verified","negative_control_reviewed",
    "approved_supervised_training","approved_supervised_validation",
    "approved_supervised_test","availability_status","feature_vector_json",
)
DISPUTE_COLUMNS = (
    "ticker","fiscal_year","statement","finmind_type","mops_metric",
    "finmind_q4","finmind_four_quarter_sum","official_annual_value",
    "signed_q4_minus_official","absolute_q4_discrepancy",
    "q4_relative_difference","sum_relative_difference",
    "q4_within_0_1_percent","sum_within_0_1_percent",
    "other_same_year_account_comparisons","possible_causes_to_check",
    "provider_archive_sha256","mops_raw_sha256","resolution_status",
)


def read_csv(path, required):
    path=Path(path)
    with path.open(encoding="utf-8-sig",newline="") as fh:
        reader=csv.DictReader(fh)
        missing=set(required)-set(reader.fieldnames or ())
        if missing:
            raise ValueError("unrecognized_dataset_columns:"+",".join(sorted(missing)))
        return list(reader),hashlib.sha256(path.read_bytes()).hexdigest()


def finite_or_blank(value,context):
    if value is None or str(value).strip()=="":
        return ""
    try:
        d=Decimal(str(value))
    except (InvalidOperation,ValueError):
        raise ValueError("invalid_financial_value:"+context) from None
    if not d.is_finite():
        raise ValueError("nonfinite_financial_value:"+context)
    return format(d,"f")


def issuer_partition(ticker,seed=20261019):
    """SHA-based group split, not a row random split (all years stay together)."""
    if ticker=="1785" or not re.fullmatch(r"[0-9]{4}",ticker):
        raise ValueError("invalid_or_heldout_ticker")
    # First 64 digest bits, stable between Python platforms/processes.
    key=int(hashlib.sha256(f"{seed}:TW:{ticker}".encode()).hexdigest()[:16],16)
    bucket=key/(16**16)
    return "fit" if bucket<0.70 else "validation" if bucket<0.85 else "test"


def temporal_partition(year):
    for label,(start,end) in TIME_BANDS.items():
        if start<=year<=end:
            return label
    raise ValueError("unsupported_fiscal_year_for_asof_split")


def audited_evidence_rows(provider_csv,official_csv,cohort,case_ids,seed):
    """Two evidence tiers can overlap; NEVER silently coalesce the different vintages."""
    all_rows=[]
    counts=Counter()
    sources=[
        ("FINMIND_PROVISIONAL",provider_csv,{
            "ticker","fiscal_year","component_source","complete_15_paper_features_training_approved",
            "label_status","candidate_components_with_values",*FEATURES}),
        ("MOPS_OFFICIAL_RETROSPECTIVE",official_csv,{
            "ticker","fiscal_year","raw_sha256","filing_version_type","analysis_mode",
            "training_label","accounting_framework","statement_scope","components_computed",*FEATURES}),
    ]
    seen=set()
    for origin,path,columns in sources:
        items,data_hash=read_csv(path,columns)
        for row in items:
            ticker=row["ticker"].strip()
            if ticker=="1785" or not re.fullmatch("[0-9]{4}",ticker):
                raise ValueError("reserved_or_invalid_issuer_in_feature_source")
            year=int(row["fiscal_year"])
            temporal=temporal_partition(year)
            if ticker not in cohort and origin=="FINMIND_PROVISIONAL":
                raise ValueError("provider_issuer_outside_frozen_taiwan_cohort")
            key=(origin,ticker,year)
            if key in seen:
                raise ValueError("duplicate_issuer_year_within_source_tier")
            seen.add(key)
            if origin=="FINMIND_PROVISIONAL":
                if (row["component_source"]!="FINMIND_UNAPPROVED_CANDIDATE_ONLY"
                        or row["complete_15_paper_features_training_approved"].lower()!="false"
                        or row["label_status"]!="UNKNOWN"):
                    raise ValueError("unapproved_provider_label_or_feature_promotion")
                if row["d_issue"].strip() or int(row["candidate_components_with_values"])>14:
                    raise ValueError("unverified_dechow_issue_cannot_be_imputed_or_computed")
                version="UNKNOWN_FINMIND_SOURCE_VINTAGE"
                raw_hash=""
            else:
                if (row["analysis_mode"]!="retrospective"
                        or row["training_label"]!="UNREVIEWED"
                        or row["accounting_framework"]!="TIFRS"
                        or row["statement_scope"]!="consolidated"):
                    raise ValueError("unapproved_official_outcome_or_scope")
                version=row["filing_version_type"]
                raw_hash=row["raw_sha256"]
                if not re.fullmatch("[0-9a-f]{64}",raw_hash):
                    raise ValueError("invalid_official_raw_sha")
            features={name:finite_or_blank(row[name],name) for name in FEATURES}
            observed=sum(bool(v) for v in features.values())
            if origin=="MOPS_OFFICIAL_RETROSPECTIVE" and observed!=int(row["components_computed"]):
                raise ValueError("official_feature_count_conflict")
            if origin=="FINMIND_PROVISIONAL" and observed!=int(row["candidate_components_with_values"]):
                raise ValueError("provider_feature_count_conflict")
            group=issuer_partition(ticker,seed)
            strict=group if temporal==group else "outside_joint_evaluation"
            case=ticker in case_ids
            all_rows.append({
                "ticker":ticker,"fiscal_year":year,"evidence_tier":origin,
                "issuer_split":group,"temporal_split":temporal,
                "joint_strict_split":strict,
                "development_event_candidate":str(case).lower(),
                "full_15_features":str(observed==15).lower(),
                "available_feature_count":observed,
                "official_source":str(origin=="MOPS_OFFICIAL_RETROSPECTIVE").lower(),
                "filing_version_type":version,"source_raw_sha256":raw_hash,
                "dataset_sha256":data_hash,
                "first_filing_publication_verified":"false",
                "original_vintage_verified":"false",
                "outcome_label":"UNKNOWN",
                "outcome_known_at_verified":"false",
                "negative_control_reviewed":"false",
                "approved_supervised_training":"false",
                "approved_supervised_validation":"false",
                "approved_supervised_test":"false",
                "availability_status":"RETROSPECTIVE_ONLY_NOT_ASOF_CERTIFIED",
                "feature_vector_json":json.dumps(features,sort_keys=True),
            })
            counts[(origin,temporal)] += 1
    return all_rows,counts


def disputes(cross_csv,out):
    """Resolve NO_MATCH triage numerically, WITHOUT inventing its cause."""
    if not Path(cross_csv).is_file():
        return {"status":"OFFICIAL_COMPARISON_FILE_NOT_FOUND","disputes":0},[]
    required=(
        "ticker","year","statement","finmind_type","mops_metric",
        "finmind_q4_value","finmind_four_quarter_sum","mops_annual_value",
        "candidate_preference","provider_archive_sha256","mops_raw_sha256",
        "q4_relative_difference","sum_relative_difference"
    )
    rows,_=read_csv(cross_csv,required)
    same_year=defaultdict(list)
    for row in rows:
        if row["ticker"]=="1785":
            raise ValueError("final_holdout_in_source_reconciliation")
        same_year[(row["ticker"],row["year"])].append(row)
    triage=[]
    for row in rows:
        if row["candidate_preference"] not in ("NO_MATCH","BOTH_AGREE_AMBIGUOUS"):
            continue
        q4=finite_or_blank(row["finmind_q4_value"],"q4")
        official=finite_or_blank(row["mops_annual_value"],"official")
        val=Decimal(q4) if q4 else None
        expected=Decimal(official) if official else None
        signed=val-expected if val is not None and expected is not None else None
        absdiff=abs(signed) if signed is not None else None
        observed=[]
        for peer in same_year[(row["ticker"],row["year"])]:
            if peer is row:
                continue
            other=finite_or_blank(peer["q4_relative_difference"],"peer_deviation")
            if peer["statement"]=="balance" and other and Decimal(other)!=0:
                observed.append(peer["mops_metric"]+":"+other)
        suggestions=("statement-vintage/revision, consolidation and account taxonomy"
                     if row["statement"]=="balance" else
                     "cumulative-versus-quarter flow, statement period, revisions and cashflow line identity")
        triage.append({
            "ticker":row["ticker"],"fiscal_year":row["year"],
            "statement":row["statement"],"finmind_type":row["finmind_type"],
            "mops_metric":row["mops_metric"],"finmind_q4":q4,
            "finmind_four_quarter_sum":finite_or_blank(row["finmind_four_quarter_sum"],"four_sum"),
            "official_annual_value":official,
            "signed_q4_minus_official":format(signed,"f") if signed is not None else "",
            "absolute_q4_discrepancy":format(absdiff,"f") if absdiff is not None else "",
            "q4_relative_difference":finite_or_blank(row["q4_relative_difference"],"q4rel"),
            "sum_relative_difference":finite_or_blank(row["sum_relative_difference"],"sumrel"),
            "q4_within_0_1_percent":str(signed is not None and
                absdiff/max(abs(expected),Decimal("1"))<=Decimal("0.001")).lower(),
            "sum_within_0_1_percent":str(
                row.get("sum_within_tolerance","").lower()=="true").lower(),
            "other_same_year_account_comparisons":"|".join(observed),
            "possible_causes_to_check":suggestions,
            "provider_archive_sha256":row["provider_archive_sha256"],
            "mops_raw_sha256":row["mops_raw_sha256"],
            "resolution_status":"UNRESOLVED_DO_NOT_AUTO_APPROVE"
        })
    return {
        "status":"SOURCE_DISPUTES_RETAINED_FOR_MANUAL_PRIMARY_FILING_REVIEW",
        "disputes":len(triage),"issuer_years":sorted({x["ticker"]+":"+x["fiscal_year"] for x in triage}),
        "threshold_changed":False,"no_match_override_applied":False
    },triage


WINDOW_COLUMNS=(
    "ticker","evidence_tier","start_year","target_year","window_years",
    "observed_feature_cells","required_feature_cells","missing_years",
    "complete_15_window","issuer_split","temporal_split","joint_strict_split",
    "asof_publication_verified","approved_for_training"
)


def sequence_windows(rows,spans=(3,5)):
    """No temporal lookahead or source-tier merge. Windows remain unapproved."""
    groups=defaultdict(dict)
    for item in rows:
        key=(item["ticker"],item["evidence_tier"])
        year=item["fiscal_year"]
        if year in groups[key]:
            raise ValueError("duplicate_period_in_sequence_source")
        groups[key][year]=item
    windows=[]
    for (ticker,tier),years in sorted(groups.items()):
        for end in sorted(years):
            for span in spans:
                first=end-span+1
                if first<2013:
                    continue
                observed=0
                missing=[]
                for yr in range(first,end+1):
                    entry=years.get(yr)
                    if entry is None:
                        missing.append(yr)
                    else:
                        observed+=entry["available_feature_count"]
                needed=span*len(FEATURES)
                target=years[end]
                windows.append({
                    "ticker":ticker,"evidence_tier":tier,
                    "start_year":first,"target_year":end,"window_years":span,
                    "observed_feature_cells":observed,"required_feature_cells":needed,
                    "missing_years":"|".join(map(str,missing)),
                    "complete_15_window":str(observed==needed and not missing).lower(),
                    "issuer_split":target["issuer_split"],
                    "temporal_split":target["temporal_split"],
                    "joint_strict_split":target["joint_strict_split"],
                    "asof_publication_verified":"false",
                    "approved_for_training":"false"
                })
    return windows


def save_csv(path,fieldnames,rows):
    with Path(path).open("w",encoding="utf-8",newline="") as fh:
        w=csv.DictWriter(fh,fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def build(data_root,out,*,seed=20261019):
    data_root=Path(data_root);out=Path(out)
    source=data_root/"phase3_literature_integrated"
    report_path=source/"phase3_integrated_report.json"
    prior=json.loads(report_path.read_text(encoding="utf-8"))
    if prior.get("cohort_company_count")!=120 or prior.get("finmind_training_15_feature_rows_admitted")!=0:
        raise ValueError("phase3_unapproved_frozen_cohort_contract_changed")
    cohort_csv=data_root/"finmind_scaled_120"/"finmind_scaled_cohort.csv"
    cohort_items=read_universe(cohort_csv)
    cohort={c["ticker"] for c in cohort_items}
    if len(cohort)!=120:
        raise ValueError("cohort_not_frozen_120_distinct_taiwan_issuers")
    case_seed=json.loads(CASE_REGISTRY.read_text(encoding="utf-8"))
    cases=validate_cases(case_seed)
    case_ids={case["ticker"] for case in cases}
    provider=source/"finmind_provisional_paper_component_values.csv"
    official=source/"mops_official_15_features"/"literature_15_features.csv"
    rows,counts=audited_evidence_rows(provider,official,cohort,case_ids,seed)
    out.mkdir(parents=True,exist_ok=True)
    save_csv(out/"taiwan_research_split_register.csv",SPLIT_COLUMNS,rows)
    seq=sequence_windows(rows)
    save_csv(out/"taiwan_sequence_window_admission.csv",WINDOW_COLUMNS,seq)
    source_pairs=defaultdict(set)
    all_assignments=defaultdict(set)
    for row in rows:
        source_pairs[(row["ticker"],row["fiscal_year"])].add(row["evidence_tier"])
        all_assignments[row["ticker"]].add(row["issuer_split"])
    if any(len(values)!=1 for values in all_assignments.values()):
        raise ValueError("issuer_disjoint_partition_leak")
    overlaps=sorted((ticker,year) for (ticker,year),evidence in source_pairs.items()
                    if len(evidence)==2)
    # Cross-source duplicates are evidence for review, not a source to be silently fused.
    cross_source=[]
    idx={(r["ticker"],r["fiscal_year"],r["evidence_tier"]):r for r in rows}
    for ticker,year in overlaps:
        cand=idx[(ticker,year,"FINMIND_PROVISIONAL")]
        off=idx[(ticker,year,"MOPS_OFFICIAL_RETROSPECTIVE")]
        x=json.loads(cand["feature_vector_json"])
        y=json.loads(off["feature_vector_json"])
        for feature in FEATURES:
            if not x[feature] or not y[feature]:
                continue
            delta=Decimal(x[feature])-Decimal(y[feature])
            cross_source.append({
                "ticker":ticker,"fiscal_year":year,"feature":feature,
                "finmind_candidate":x[feature],"official_retrospective":y[feature],
                "signed_difference":format(delta,"f"),
                "comparison_status":"SOURCE_VERSION_AND_MAPPING_NEEDS_REVIEW"
            })
    save_csv(out/"cross_source_paper_feature_review.csv",(
        "ticker","fiscal_year","feature","finmind_candidate",
        "official_retrospective","signed_difference","comparison_status"),
        cross_source)
    dispute_path=data_root/"phase12_integrated_verification"/"phase2"/"official"/"finmind_mops_annual_crosscheck.csv"
    mismatch_info,mismatches=disputes(dispute_path,out)
    save_csv(out/"mops_source_discrepancy_diagnostics.csv",DISPUTE_COLUMNS,mismatches)
    stats=Counter((row["evidence_tier"],row["joint_strict_split"]) for row in rows)
    completeness=Counter((row["evidence_tier"],row["full_15_features"]) for row in rows)
    time_stats=Counter((row["evidence_tier"],row["temporal_split"]) for row in rows)
    issuer_stats=Counter(issuer_partition(t,seed) for t in all_assignments)
    report={
        "status":"PHASE4_TAIWAN_DATASET_SPLITS_AUDITED_BUT_NO_APPROVED_PREDICTION_DATA",
        "schema_version":SCHEMA,"seed":seed,
        "Taiwan_issuer_count":len(all_assignments),
        "cohort_issuer_count":len(cohort),
        "evidence_rows":len(rows),
        "sequence_window_counts":{str(span):sum(x["window_years"]==span for x in seq) for span in (3,5)},
        "complete15_candidate_sequence_windows":{str(span):sum(x["window_years"]==span and x["complete_15_window"]=="true" for x in seq) for span in (3,5)},
        "sequence_window_training_admitted":0,
        "official_retrospective_rows":sum(r["evidence_tier"]=="MOPS_OFFICIAL_RETROSPECTIVE" for r in rows),
        "finmind_candidate_rows":sum(r["evidence_tier"]=="FINMIND_PROVISIONAL" for r in rows),
        "complete15_by_source":{a:{v:completeness[(a,v)] for v in ("true","false")} for a in
                                ("FINMIND_PROVISIONAL","MOPS_OFFICIAL_RETROSPECTIVE")},
        "time_split_rows":{tier:{name:time_stats[(tier,name)] for name in TIME_BANDS}
                          for tier in ("FINMIND_PROVISIONAL","MOPS_OFFICIAL_RETROSPECTIVE")},
        "issuer_disjoint_company_counts":dict(sorted(issuer_stats.items())),
        "joint_strict_split_rows":{tier:{name:stats[(tier,name)] for name in
                                        (*TIME_BANDS,"outside_joint_evaluation")}
                          for tier in ("FINMIND_PROVISIONAL","MOPS_OFFICIAL_RETROSPECTIVE")},
        "cross_source_overlap_company_years":len(overlaps),
        "cross_source_comparable_feature_cells":len(cross_source),
        "mops_source_disputes":mismatch_info,
        "case_development_candidate_ids":sorted(case_ids),
        "known_case_tickers_never_used_as_verified_negative":True,
        "final_holdout_ticker":"1785","final_holdout_excluded":True,
        "labels_approved_positive":0,"labels_approved_negative":0,
        "train_val_test_supervised_admitted_rows":0,
        "fitting_scalers_permitted":False,
        "strict_asof_original_filing_ready":False,
        "has_frozen_methodological_split_plan":True,
        "official_paper_15_full_row_count":completeness[("MOPS_OFFICIAL_RETROSPECTIVE","true")],
        "eligible_for_supervised_financial_fraud_training":False,
        "temporal_split_caveat":"Fiscal year is NOT publication timestamp; multiple yearly snapshots may be post-restatement.",
        "group_split_caveat":"Joint split includes only samples matching both issuer and time partition; other cells excluded from joint evaluation.",
        "source_tiers_not_fused":True,
        "source_hashes":{
            "phase3_report":hashlib.sha256(report_path.read_bytes()).hexdigest(),
            "cohort":hashlib.sha256(cohort_csv.read_bytes()).hexdigest(),
            "provider_candidate":hashlib.sha256(provider.read_bytes()).hexdigest(),
            "official_retrospective":hashlib.sha256(official.read_bytes()).hexdigest(),
            "phase1_case_seed":hashlib.sha256(CASE_REGISTRY.read_bytes()).hexdigest(),
        },
        "network_requests":0,"production_db_writes":0,"models_trained":0,
        "blockers":[
            "Phase1 officially reviewed period-specific positives and auditable negative controls remain zero",
            "FinMind 24 mappings and original-publication vintage unapproved; 15-feature candidates unusable for true outcome training",
            "MOPS literature official features have limited company-years and original publication times unknown",
            "Beneish/Dechow Issue and multicomponent account mapping need method-owner review",
            "Disputed 2014 2330 Liabilities and 2013 2458 operating cash flow values require original-source analysis",
            "An untouched historical cutoff before the 1785 event needs pre-2016 training labels and original reports"
        ]
    }
    (out/"phase4_dataset_integrated_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="No-label Taiwan real-feature split, group/time leakage checks and MOPS disputes")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--seed",type=int,default=20261019)
    args=p.parse_args(argv)
    print(json.dumps(build(args.data_root,args.output,seed=args.seed),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
