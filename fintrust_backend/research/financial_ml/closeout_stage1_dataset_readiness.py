"""Closeout Stage 1: lineage-preserving Taiwan financial ML dataset readiness.

Three intentionally SEPARATE views:
 A. FinMind twelve provisional annual amounts, 2013–2025;
 B. source-tier-separated candidate Beneish8+Dechow7 from Phase4;
 C. real SHA-archived multi-issuer 2017Q2–2020Q1 MOPS quarter cells.

This is a dataset builder and strict QA, NOT a supervised training script.
No unknowns are made normals, no missing values are set to financial zero,
no current archived filing is represented as verified historical first filing.
Company 1785 is entirely excluded; case issuers are never "healthy" controls.
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

from .annual_panel_readiness import METRICS
from .finmind_cross_industry_pilot import read_universe
from .literature_dataset import FEATURES
from .official_batch import atomic_json
from .phase4_taiwan_dataset_gate import SPLIT_COLUMNS, issuer_partition
from .phase13_quarterly_temporal_features import FROZEN_PERIODS, OBS_FIELDS
from .phase14_multiissuer_quarterly_cohort import SOURCE_COLUMNS, VALID as Q_VALID, url_for

BANNED = frozenset({"1785", "3027", "6452", "8299"})
ANNUAL_COLUMNS = (
    "ticker","fiscal_year","evidence_tier","source_lineage_sha256",
    "observed_metrics","total_metrics","full_12_metric_observation",
    "issuer_split","temporal_split","strict_joint_split",
    "financial_fraud_label","historical_original_filing_verified",
    "training_admitted",*METRICS,
)
PAPER_COLUMNS = (
    "ticker","fiscal_year","evidence_tier","source_raw_sha256",
    "evidence_dataset_sha256","observed_paper_features","complete_15",
    "issuer_split","temporal_split","strict_joint_split",
    "development_event_candidate","historical_original_filing_verified",
    "financial_fraud_label","training_admitted",*FEATURES,
)
META_COLUMNS=("feature_id","concept_key","source_local_name",
              "period_grain","fit_observed_company_quarters",
              "fit_observed_issuers","fit_observed_industries",
              "fit_total_verified_company_quarters",
              "fit_coverage_fraction","feature_admitted_for_supervised_training")
Q_BASE=("ticker","industry_category","market","reporting_period",
        "issuer_split","temporal_split","strict_joint_split","source_status",
        "source_sha256","observed_selected_feature_count",
        "selected_feature_count","source_first_publication_verified",
        "outcome_label","training_admitted")
QUALITY_COLUMNS=("ticker","industry_category","quarters_expected",
                 "quarters_official_validated","selected_feature_cells_present",
                 "selected_feature_cells_possible","company_has_full_12_quarters",
                 "label_reviewed_normal","historical_listing_verified",
                 "source_original_versions_verified")
STATS_COLUMNS=("view","evidence_tier","split","issuer_count","observation_rows",
               "fully_observed_rows","observed_feature_cells",
               "possible_feature_cells","missing_feature_cells",
               "source_vintage_verified_rows","approved_training_rows")


def read_csv(path, required):
    path=Path(path)
    with path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        missing=set(required)-set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"wrong_csv_schema:{path.name}:"+",".join(sorted(missing)))
        rows=list(reader)
    if not rows:
        raise ValueError(f"empty_data_source:{path.name}")
    return rows


def write_csv(path, fields, rows):
    with Path(path).open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite_text(value):
    v=str(value if value is not None else "").strip()
    if not v:
        return ""
    try:
        d=Decimal(v)
    except (InvalidOperation,ValueError):
        raise ValueError("financial_value_not_decimal") from None
    if not d.is_finite():
        raise ValueError("nonfinite_financial_amount")
    return format(d,"f")


def joint_split(issuer,temporal):
    return issuer if issuer==temporal else "outside_joint_evaluation"


def annual_temporal(year):
    if 2013<=year<=2020:
        return "fit"
    if 2021<=year<=2022:
        return "validation"
    if 2023<=year<=2025:
        return "test"
    raise ValueError("annual_target_year_outside_frozen_design")


def quarter_temporal(period):
    if period not in FROZEN_PERIODS:
        raise ValueError("quarter_outside_pilot_interval")
    if period<="2018Q4":
        return "fit"
    if period<="2019Q3":
        return "validation"
    return "test"


def assert_unknown(row, *fields):
    for key in fields:
        if str(row[key]).strip().lower() not in ("false","unknown","unreviewed"):
            raise ValueError("unreviewed_label_or_source_promoted:"+key)


def annual_view(cohort, candidate_panel, annual_line_source, seed):
    panel=read_csv(candidate_panel,(
        "ticker","fiscal_year","training_admitted","original_asof_verified",
        "complete_12_candidate_metrics",*METRICS))
    lines=read_csv(annual_line_source,(
        "ticker","fiscal_year","candidate_mops_metric","candidate_annual_value",
        "source_sha256","status","training_admitted",
        "publication_asof_verified","label_status"))
    source={}
    hashes=defaultdict(set)
    for r in lines:
        ticker=r["ticker"].strip()
        year=int(r["fiscal_year"])
        item=r["candidate_mops_metric"]
        if ticker not in cohort or item not in METRICS or (ticker,year,item) in source:
            raise ValueError("annual_candidate_cell_outside_frozen_cohort_or_duplicate")
        if not 2013<=year<=2025:
            raise ValueError("annual_candidate_period_not_supported")
        assert_unknown(r,"training_admitted","publication_asof_verified","label_status")
        value=finite_text(r["candidate_annual_value"])
        if (r["status"]=="candidate_annual_value")!=(value!=""):
            raise ValueError("financial_source_candidate_missing_status_conflict")
        if value:
            if not re.fullmatch(r"[0-9a-f]{64}",r["source_sha256"]):
                raise ValueError("annual_value_source_digest_missing")
            hashes[(ticker,year)].add(r["source_sha256"])
        source[ticker,year,item]=value
    outcome=[]
    seen=set()
    for row in panel:
        ticker=row["ticker"].strip()
        year=int(row["fiscal_year"])
        if ticker not in cohort or (ticker,year) in seen or not 2013<=year<=2025:
            raise ValueError("annual_panel_outside_frozen_universe_or_duplicate")
        seen.add((ticker,year))
        assert_unknown(row,"training_admitted","original_asof_verified")
        fields={}
        for name in METRICS:
            key=(ticker,year,name)
            if key not in source:
                raise ValueError("annual_panel_cell_not_in_source_table")
            actual=finite_text(row[name])
            if actual!=source[key]:
                raise ValueError(f"annual_panel_source_value_mismatch:{ticker}:{year}:{name}")
            fields[name]=actual
        observed=sum(bool(v) for v in fields.values())
        full=str(row["complete_12_candidate_metrics"]).strip().lower()=="true"
        if full!=(observed==len(METRICS)):
            raise ValueError("annual_panel_completeness_incorrect")
        group=issuer_partition(ticker,seed)
        time=annual_temporal(year)
        outcome.append({
            "ticker":ticker,"fiscal_year":year,"evidence_tier":"FINMIND_PROVISIONAL_ANNUAL",
            "source_lineage_sha256":"|".join(sorted(hashes[ticker,year])),
            "observed_metrics":observed,"total_metrics":len(METRICS),
            "full_12_metric_observation":str(full).lower(),
            "issuer_split":group,"temporal_split":time,
            "strict_joint_split":joint_split(group,time),
            "financial_fraud_label":"UNKNOWN",
            "historical_original_filing_verified":"false",
            "training_admitted":"false",**fields,
        })
    if not outcome or not set(cohort).issuperset({x["ticker"] for x in outcome}):
        raise ValueError("annual_cohort_empty_or_outside_frozen")
    return sorted(outcome,key=lambda x:(x["ticker"],int(x["fiscal_year"])))


def paper_view(register,report_path,seed):
    report=json.loads(Path(report_path).read_text(encoding="utf-8"))
    if (report.get("final_holdout_excluded") is not True
        or report.get("labels_approved_positive")!=0
        or report.get("labels_approved_negative")!=0
        or report.get("source_tiers_not_fused") is not True
        or report.get("eligible_for_supervised_financial_fraud_training") is not False):
        raise ValueError("phase4_fraud_provenance_gate_not_satisfied")
    lines=read_csv(register,SPLIT_COLUMNS)
    seen=set()
    output=[]
    for row in lines:
        ticker=row["ticker"]
        year=int(row["fiscal_year"])
        tier=row["evidence_tier"]
        if (ticker=="1785" or tier not in ("MOPS_OFFICIAL_RETROSPECTIVE","FINMIND_PROVISIONAL")
            or (tier,ticker,year) in seen):
            raise ValueError("paper_register_reserved_case_or_duplicate_source_tier")
        seen.add((tier,ticker,year))
        assert_unknown(row,"approved_supervised_training",
                       "approved_supervised_validation","approved_supervised_test",
                       "original_vintage_verified","first_filing_publication_verified",
                       "outcome_label")
        issuer=issuer_partition(ticker,seed)
        temporal=annual_temporal(year)
        if (row["issuer_split"]!=issuer or row["temporal_split"]!=temporal
            or row["joint_strict_split"]!=joint_split(issuer,temporal)):
            raise ValueError("phase4_frozen_issuer_or_time_split_changed")
        features=json.loads(row["feature_vector_json"])
        if set(features)!=set(FEATURES):
            raise ValueError("paper_15_original_feature_schema_corrupted")
        parsed={key:finite_text(features[key]) for key in FEATURES}
        n=sum(bool(v) for v in parsed.values())
        if (n!=int(row["available_feature_count"])
            or (n==15)!=(row["full_15_features"]=="true")):
            raise ValueError("phase4_paper_feature_coverage_conflict")
        if tier=="MOPS_OFFICIAL_RETROSPECTIVE" and not re.fullmatch(
                r"[0-9a-f]{64}",row["source_raw_sha256"]):
            raise ValueError("official_paper_source_sha_unverified")
        output.append({
            "ticker":ticker,"fiscal_year":year,"evidence_tier":tier,
            "source_raw_sha256":row["source_raw_sha256"],
            "evidence_dataset_sha256":row["dataset_sha256"],
            "observed_paper_features":n,"complete_15":str(n==15).lower(),
            "issuer_split":issuer,"temporal_split":temporal,
            "strict_joint_split":joint_split(issuer,temporal),
            "development_event_candidate":row["development_event_candidate"],
            "historical_original_filing_verified":"false",
            "financial_fraud_label":"UNKNOWN","training_admitted":"false",
            **parsed
        })
    return sorted(output,key=lambda r:(r["evidence_tier"],r["ticker"],int(r["fiscal_year"])))


def quarter_view(cohort,phase14,seed,max_features,cohort_sha):
    root=Path(phase14)
    report=json.loads((root/"phase14_integrated_report.json").read_text(encoding="utf-8"))
    if (report.get("selected_issuers")!=12
        or report.get("official_quarter_jobs")!=144
        or report.get("verified_true_negative_company_quarters")!=0
        or report.get("verified_false_filing_positive_company_quarters")!=0
        or report.get("supervised_ml_rows_admitted")!=0
        or report.get("final_holdout_1785_excluded") is not True):
        raise ValueError("phase14_unapproved_outcome_or_source_plan")
    manifest_path=root/"quarterly_acquisition_results.json"
    if digest(manifest_path)!=report["primary_source_assembly_SHA256"]:
        raise ValueError("phase14_manifest_sha_changed_after_acceptance")
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("holdout_1785") is not True or manifest.get("positive_labels")!=0 or manifest.get("negative_labels")!=0:
        raise ValueError("phase14_manifest_forged_label_or_holdout")
    manifest_rows=manifest.get("outcomes",{})
    sources=read_csv(root/"multiissuer_official_quarter_sources.csv",SOURCE_COLUMNS)
    raw_obs=read_csv(root/"multiissuer_quarter_twd_observations.csv",OBS_FIELDS)
    saved_plan=json.loads((root/"frozen_phase14_plan.json").read_text(encoding="utf-8"))
    selected={r["ticker"]:r for r in saved_plan["selected_company_metadata"]}
    if (len(selected)!=12
        or set(selected)&BANNED
        or not set(selected).issubset(cohort)
        or saved_plan["source_cohort_sha256"]!=report["source_cohort_SHA256"]
        or saved_plan["source_cohort_sha256"]!=cohort_sha):
        raise ValueError("phase14_frozen_cohort_selection_not_reproducible")
    allowed={(ticker,period) for ticker in selected for period in FROZEN_PERIODS}
    index={}
    valid=0
    for r in sources:
        k=(r["ticker"],r["reporting_period"])
        if k not in allowed or k in index:
            raise ValueError("quarter_source_duplicated_or_outside_selection")
        assert_unknown(r,"original_filing_version_verified","first_publication_verified",
                       "outcome_label","normal_label_approved","training_admitted")
        m=manifest_rows.get(f"{k[0]}:{k[1]}")
        if (m is None or m["source_status"]!=r["source_status"]
            or m["raw_sha256"]!=r["raw_sha256"]
            or m.get("raw_path","")!=r["archive_relative_path"]
            or m.get("official_url")!=r["official_url"]
            or r["official_url"]!=url_for(*k)
            or m.get("outcome_label")!="UNKNOWN"
            or m.get("normal_label_approved") is not False
            or m.get("original_asof_verified") is not False):
            raise ValueError("quarterly_manifest_source_index_disagreement")
        if r["industry_category"]!=selected[k[0]]["industry_category"]:
            raise ValueError("quarter_issuer_metadata_changed")
        if r["source_status"]==Q_VALID:
            valid+=1
            if not re.fullmatch(r"[0-9a-f]{64}",r["raw_sha256"]):
                raise ValueError("quarter_source_sha_missing")
            filepath=(root/"raw"/r["archive_relative_path"]).resolve()
            if not filepath.is_relative_to((root/"raw").resolve()):
                raise ValueError("quarter_raw_path_outside_archive")
            if not filepath.is_file() or digest(filepath)!=r["raw_sha256"]:
                raise ValueError("quarter_raw_bytes_do_not_match_sha")
        index[k]=r
    if set(index)!=allowed or valid!=report["official_quarters_context_and_primary_TWD_validated"]:
        raise ValueError("phase14_source_quarter_coverage_changed")
    # Every candidate cell must point back to the exact quarter source SHA.
    observed={}
    for r in raw_obs:
        k=(r["ticker"],r["reporting_period"])
        if k not in index or index[k]["source_status"]!=Q_VALID:
            raise ValueError("financial_fact_without_approved_source_row")
        assert_unknown(r,"outcome_label","model_training_admitted",
                       "source_original_vintage_verified",
                       "candidate_mapping_approved")
        if r["source_sha256"]!=index[k]["raw_sha256"]:
            raise ValueError("financial_fact_source_sha_not_matching_quarter")
        if r["source_unit"]!="TWD" or r["period_grain"] not in (
                "instant","quarter_duration","ytd_duration","other_duration"):
            raise ValueError("quarterly_financial_currency_or_period_grain_mismatch")
        name=r["concept_key"]
        if not name or "|" not in name:
            raise ValueError("missing_exact_taxonomy_concept_identity")
        # Other-duration contexts can legitimately use multiple different
        # starts within the same issuer/quarter/concept. They have no single
        # comparable measurement grain; retain their original Phase14 raw
        # observation table but never flatten them into a unique model cell.
        if r["period_grain"]=="other_duration":
            continue
        key=(k[0],k[1],name,r["period_grain"])
        if key in observed:
            raise ValueError("same_issuer_quarter_concept_grain_duplicated")
        if r["reconciliation_status"]=="CANDIDATE_CONSISTENT_REPETITIONS":
            observed[key]=finite_text(r["value_decimal"])
            if not observed[key]:
                raise ValueError("accepted_source_fact_value_is_blank")
        elif r["reconciliation_status"]=="DUPLICATE_CONFLICT_QUARANTINED":
            if r["value_decimal"].strip():
                raise ValueError("quarantined_conflicting_fact_must_remain_blank")
            observed[key]=""
        else:
            raise ValueError("unknown_source_account_reconciliation_status")
    # Select features using fit-only ISSUERS + fit-only QUARTERS.
    fit_rows=[key for key in sorted(index) if
              issuer_partition(key[0],seed)=="fit"
              and quarter_temporal(key[1])=="fit"
              and index[key]["source_status"]==Q_VALID]
    seen_by_feature=defaultdict(set)
    issuers=defaultdict(set)
    industries=defaultdict(set)
    for (ticker,period,concept,grain),value in observed.items():
        if not value or (ticker,period) not in fit_rows or grain=="other_duration":
            continue
        feature=(concept,grain)
        seen_by_feature[feature].add((ticker,period))
        issuers[feature].add(ticker)
        industries[feature].add(selected[ticker]["industry_category"])
    min_issuers=3
    ranked=sorted((f for f in seen_by_feature
                   if len(issuers[f])>=min_issuers),
                  key=lambda f:(-len(seen_by_feature[f]),-len(issuers[f]),f))
    selected_features=ranked[:max_features]
    mapping=[]
    feature_ids={}
    for n,f in enumerate(selected_features,1):
        fid=f"qf_{n:02d}"
        feature_ids[f]=fid
        mapping.append({
            "feature_id":fid,"concept_key":f[0],
            "source_local_name":f[0].rsplit("|",1)[1],
            "period_grain":f[1],
            "fit_observed_company_quarters":len(seen_by_feature[f]),
            "fit_observed_issuers":len(issuers[f]),
            "fit_observed_industries":len(industries[f]),
            "fit_total_verified_company_quarters":len(fit_rows),
            "fit_coverage_fraction":round(len(seen_by_feature[f])/len(fit_rows),6)
              if fit_rows else 0,
            "feature_admitted_for_supervised_training":"false"
        })
    matrix=[]
    quality=[]
    for ticker in sorted(selected):
        company=selected[ticker]
        valid_quarters=0
        company_observed=0
        for period in FROZEN_PERIODS:
            source=index[ticker,period]
            eligible=source["source_status"]==Q_VALID
            valid_quarters+=int(eligible)
            attrs={}
            nonmissing=0
            for f,fid in feature_ids.items():
                value=observed.get((ticker,period,*f),"") if eligible else ""
                attrs[fid]=value
                attrs[fid+"_observed"]=str(bool(value)).lower()
                nonmissing+=bool(value)
            company_observed+=nonmissing
            issuer=issuer_partition(ticker,seed)
            temporal=quarter_temporal(period)
            matrix.append({
                "ticker":ticker,"industry_category":company["industry_category"],
                "market":company["market"],"reporting_period":period,
                "issuer_split":issuer,"temporal_split":temporal,
                "strict_joint_split":joint_split(issuer,temporal),
                "source_status":source["source_status"],
                "source_sha256":source["raw_sha256"],
                "observed_selected_feature_count":nonmissing,
                "selected_feature_count":len(feature_ids),
                "source_first_publication_verified":"false",
                "outcome_label":"UNKNOWN","training_admitted":"false",**attrs
            })
        quality.append({
            "ticker":ticker,"industry_category":company["industry_category"],
            "quarters_expected":len(FROZEN_PERIODS),
            "quarters_official_validated":valid_quarters,
            "selected_feature_cells_present":company_observed,
            "selected_feature_cells_possible":len(FROZEN_PERIODS)*len(feature_ids),
            "company_has_full_12_quarters":str(valid_quarters==12).lower(),
            "label_reviewed_normal":"false","historical_listing_verified":"false",
            "source_original_versions_verified":"false"
        })
    return matrix,mapping,quality,{
        "source_quarters":len(sources),"official_validated_quarters":valid,
        "source_twd_observation_records":len(raw_obs),
        "fit_only_feature_candidates":len(mapping),
        "fit_company_quarters":len(fit_rows),
        "quarter_unavailable":len(sources)-valid,
        "selected_feature_cells_present":sum(
            int(r["observed_selected_feature_count"]) for r in matrix),
        "selected_feature_cells_possible":len(matrix)*len(mapping),
        "strict_joint_counts":dict(Counter(r["strict_joint_split"] for r in matrix)),
        "selected_company_tickers":sorted(selected),
        "candidate_features_selected_only_on_fit_rows":True,
    }


def statistics(annual,paper,matrix,feature_ids):
    views=[]
    for label,rows,feature_names,tier_key in (
            ("ANNUAL_12_CANDIDATE",annual,METRICS,"evidence_tier"),
            ("PAPER_15_SEPARATE_TIERS",paper,FEATURES,"evidence_tier"),
            ("QUARTER_12_COMPANIES",matrix,feature_ids,"__none__")):
        tiers={r[tier_key] for r in rows} if tier_key!="__none__" else {"MOPS_QUARTER_CURRENT_ARCHIVE"}
        for tier in sorted(tiers):
            sub=[r for r in rows if tier_key=="__none__" or r[tier_key]==tier]
            for split in ("all","fit","validation","test","outside_joint_evaluation"):
                part=[r for r in sub if split=="all" or r["strict_joint_split"]==split]
                count=sum(sum(bool(r[f]) for f in feature_names) for r in part)
                total=len(part)*len(feature_names)
                views.append({
                    "view":label,"evidence_tier":tier,"split":split,
                    "issuer_count":len({r["ticker"] for r in part}),
                    "observation_rows":len(part),
                    "fully_observed_rows":sum(
                        all(bool(r[f]) for f in feature_names) for r in part),
                    "observed_feature_cells":count,"possible_feature_cells":total,
                    "missing_feature_cells":total-count,
                    "source_vintage_verified_rows":0,"approved_training_rows":0
                })
    return views




def annual_sequence_opportunities(annual, history):
    """Prospective next-year NUMERIC forecast windows, not fraud labels."""
    byfirm=defaultdict(dict)
    for r in annual:
        byfirm[r["ticker"]][int(r["fiscal_year"])]=r
    by_split=Counter()
    firms=defaultdict(set)
    for ticker,years in byfirm.items():
        for target in sorted(years):
            if target-history<2013:
                continue
            required=range(target-history,target+1)
            if not all(y in years and years[y]["full_12_metric_observation"]=="true"
                       for y in required):
                continue
            split=years[target]["strict_joint_split"]
            by_split[split]+=1
            firms[split].add(ticker)
    return {"historical_window_years":history,
            "total_complete_financial_numeric_forecast_windows":sum(by_split.values()),
            "candidate_windows_by_strict_split":dict(sorted(by_split.items())),
            "unique_companies_by_strict_split":{
                split:len(firms[split]) for split in
                ("fit","validation","test","outside_joint_evaluation")},
            "approved_fraud_supervised_windows":0}

def make_report(data_root,output,max_features=24,seed=20261019):
    root=Path(data_root)
    out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    cohort_path=root/"finmind_scaled_120"/"finmind_scaled_cohort.csv"
    panel_path=root/"finmind_scaled_sequence_readiness"/"company_year_candidate_panel.csv"
    lines_path=root/"finmind_scaled_annual_candidates"/"finmind_annual_candidate_lines.csv"
    phase4=root/"phase4_taiwan_research_dataset"
    phase14=root/"phase14_multiissuer_quarterly_comparison"
    inputs={
        "frozen_120_cohort":cohort_path,
        "annual_candidate_panel":panel_path,
        "annual_candidate_evidence_lines":lines_path,
        "phase4_paper_register":phase4/"taiwan_research_split_register.csv",
        "phase4_paper_report":phase4/"phase4_dataset_integrated_report.json",
        "phase14_official_report":phase14/"phase14_integrated_report.json",
        "phase14_quarter_raw_manifest":phase14/"quarterly_acquisition_results.json",
        "phase14_quarter_sources":phase14/"multiissuer_official_quarter_sources.csv",
        "phase14_source_observations":phase14/"multiissuer_quarter_twd_observations.csv",
        "phase14_frozen_plan":phase14/"frozen_phase14_plan.json"
    }
    for name,path in inputs.items():
        if not path.is_file():
            raise ValueError("required_existing_input_missing:"+name+":"+str(path))
    frozen=read_universe(cohort_path)
    if len(frozen)!=120:
        raise ValueError("expected_exact_120_frozen_cohort")
    cohort={r["ticker"] for r in frozen}
    if "1785" in cohort:
        raise ValueError("final_holdout_in_frozen_universe")
    # Development case issuers may occur in the 120-row universe, but are
    # never promoted to normal controls or included in the quarter cohort.
    annual=annual_view(cohort,panel_path,lines_path,seed)
    paper=paper_view(inputs["phase4_paper_register"],inputs["phase4_paper_report"],seed)
    quarter,mapping,quality,qt=quarter_view(
        cohort,phase14,seed,max_features,digest(cohort_path))
    metrics=statistics(annual,paper,quarter,[x["feature_id"] for x in mapping])
    write_csv(out/"annual_12_provisional_metric_matrix.csv",ANNUAL_COLUMNS,annual)
    write_csv(out/"paper_15_source_tier_matrix.csv",PAPER_COLUMNS,paper)
    write_csv(out/"quarterly_fit_selected_feature_dictionary.csv",META_COLUMNS,mapping)
    qids=[x["feature_id"] for x in mapping]
    cols=[*Q_BASE,*[x for fid in qids for x in (fid,fid+"_observed")]]
    write_csv(out/"quarterly_sparse_feature_matrix.csv",cols,quarter)
    write_csv(out/"quarterly_issuer_quality.csv",QUALITY_COLUMNS,quality)
    write_csv(out/"data_split_and_missingness.csv",STATS_COLUMNS,metrics)
    sourcehash={k:digest(path) for k,path in inputs.items()}
    full_annual=sum(r["full_12_metric_observation"]=="true" for r in annual)
    report={
        "status":"CLOSEOUT_STAGE1_THREE_TIER_DATASETS_BUILT_NO_OUTCOME_LABELS",
        "design_version":"stage1_annual_paper_quarter_separate_v1",
        "frozen_cohort_issuer_count":len(cohort),
        "annual_provisional_company_years":len(annual),
        "annual_12_metric_complete_company_years":full_annual,
        "annual_12_metric_observed_cells":sum(int(r["observed_metrics"]) for r in annual),
        "annual_12_metric_possible_cells":len(annual)*len(METRICS),
        "paper_feature_source_tier_rows":len(paper),
        "paper_source_tier_rows":dict(Counter(r["evidence_tier"] for r in paper)),
        "paper_full_15_candidate_company_year_rows_by_tier":{
            tier:sum(r["evidence_tier"]==tier and r["complete_15"]=="true" for r in paper)
            for tier in ("FINMIND_PROVISIONAL","MOPS_OFFICIAL_RETROSPECTIVE")},
        "paper_15_observed_cells":sum(int(r["observed_paper_features"]) for r in paper),
        "paper_15_possible_cells":len(paper)*len(FEATURES),
        "quarterly":qt,
        "annual_joint_splits":dict(Counter(r["strict_joint_split"] for r in annual)),
        "three_year_history_numeric_forecast_opportunities":annual_sequence_opportunities(annual,3),
        "five_year_history_numeric_forecast_opportunities":annual_sequence_opportunities(annual,5),
        "model_ready_supervised_positive_labels":0,
        "model_ready_supervised_negative_labels":0,
        "model_ready_supervised_training_rows":0,
        "unsupervised_provisional_feature_views_available":True,
        "frozen_1785_holdout_preserved":True,
        "known_case_3027_6452_8299_not_used_as_negative":True,
        "MOPS_and_FinMind_source_tiers_not_combined":True,
        "annual_and_quarter_financial_grains_not_combined":True,
        "nonexistent_financial_amounts_never_replaced_with_zero":True,
        "fit_only_feature_selection":True,
        "historical_original_versions_approved":0,
        "no_fraud_detection_metric_claim":True,
        "sha256_of_inputs":sourcehash,
        "network_requests":0,"production_db_writes":0,"models_trained":0,
        "next_stage":"Independent fraud/normal/UNKNOWN outcome evidence, as-original "
                     "filing vintage and observed-negative followup review. "
                     "Then define valid supervised training and unbiased final 1785 replay."
    }
    atomic_json(out/"closeout_stage1_integrated_report.json",report)
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Offline canonical Taiwan annual/paper/quarter research matrices and sample QA")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--max-quarter-features",type=int,default=24)
    a=p.parse_args(argv)
    if not 3<=a.max_quarter_features<=64:
        raise ValueError("quarter_candidate_feature_limit_outside_research_bounds")
    print(json.dumps(make_report(a.data_root,a.output,max_features=a.max_quarter_features),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
