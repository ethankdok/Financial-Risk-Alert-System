"""Finalization round 1: reconcile, DO NOT fuse, Taiwan financial-ML evidence tiers.

Deterministic OFFLINE QA of the existing 120-company FY2013-2025 FinMind
12-amount candidate panel, Phase4 original 15-paper-feature split register,
12-company official quarter comparison and 6452's separately quarantined
12-quarter case evidence. Reports the actual issuer/year/quarter units and
lag-window counts, not 22k XBRL facts as 22k training samples.

This is NOT supervised fraud fitting and cannot label unknown firms normal.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .annual_panel_readiness import METRICS
from .finmind_cross_industry_pilot import read_universe
from .literature_dataset import FEATURES
from .phase10_case_literature_vintage_audit import CASE_COLUMNS as CASE_PAPER_ORIGINAL_COLUMNS
from .phase4_taiwan_dataset_gate import (
    SPLIT_COLUMNS, issuer_partition, temporal_partition,
)
from .phase14_multiissuer_quarterly_cohort import (
    CASE_OR_HOLDOUT, FROZEN_PERIODS, SOURCE_COLUMNS, VALID,
)
from .phase12_kangyou_quarterly_panel import FIELDS as KANGYOU_SOURCE_COLUMNS

SOURCE_REGISTER_COLUMNS=(
    "sample_key","ticker","fiscal_year","evidence_tier","source_kind",
    "observed_feature_count","candidate_feature_count","complete_candidate_vector",
    "issuer_split","temporal_split","joint_strict_split","source_sha256",
    "original_publication_verified","original_filing_vintage_verified",
    "label_status","training_admitted"
)
PAPER_COLUMNS=SOURCE_REGISTER_COLUMNS+FEATURES
ANNUAL_COLUMNS=SOURCE_REGISTER_COLUMNS+METRICS
QUARTER_COLUMNS=(
    "sample_key","ticker","reporting_period","data_role","source_status",
    "source_sha256","financial_issuer_quarter_observation",
    "historical_publication_verified","original_filing_vintage_verified",
    "label_status","negative_label_approved","training_admitted"
)
WINDOW_COLUMNS=(
    "ticker","target_year","lookback_years","needed_fiscal_years",
    "all_12_amounts_present","issuer_split","time_split","joint_strict_split",
    "outcome_label","approved_for_supervised_training"
)
DENSE_COLUMNS=(
    "ticker","feature_name","period_grain","source_tier","quarters_observed",
    "quarters_expected","earliest_period","latest_period",
    "retrospective_not_original_publication",
    "approved_for_supervised_learning"
)
FIT_FEATURE_COLUMNS=(
    "evidence_tier","feature_name","fit_candidate_company_years",
    "fit_years_with_feature","fit_coverage_ratio","all_tier_years_with_feature",
    "approved_as_literature_feature_for_training"
)


def csv_rows(path, required):
    path=Path(path)
    with path.open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if missing:=set(required)-set(reader.fieldnames or ()):
            raise ValueError("incorrect_financial_ml_source_csv_columns:"+path.name+":"+str(sorted(missing)))
        rows=list(reader)
    return rows


def dump_csv(path,columns,items):
    with Path(path).open("w",encoding="utf-8",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction="raise")
        writer.writeheader()
        writer.writerows(items)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_bytes(root,relative,digest_expected):
    """Only read archives underneath the declared SHA source-root."""
    if not relative or not re.fullmatch("[0-9a-f]{64}",digest_expected):
        raise ValueError("source_sha_or_path_missing")
    home=Path(root).resolve()
    src=(home/relative).resolve()
    if not src.is_relative_to(home) or not src.is_file():
        raise ValueError("source_path_escape_or_file_missing")
    if digest(src)!=digest_expected:
        raise ValueError("official_quarter_archive_sha256_mismatch")


def amount(value):
    if str(value).strip()=="":
        return ""
    try:
        x=Decimal(str(value))
    except (InvalidOperation,ValueError):
        raise ValueError("unparseable_candidate_financial_number") from None
    if not x.is_finite():
        raise ValueError("nonfinite_candidate_financial_number")
    return format(x,"f")


def has_false(value):
    return str(value).strip().lower()=="false"


def must_unknown(value):
    return str(value).strip() in ("UNKNOWN","UNREVIEWED")


def safe_ticker(t):
    if not re.fullmatch("[0-9]{4}",str(t)) or t=="1785":
        raise ValueError("reserved_1785_or_invalid_ticker")
    return t


def read_annual_amounts(data,cohort):
    path=data/"finmind_scaled_sequence_readiness"/"company_year_candidate_panel.csv"
    expected={"ticker","fiscal_year","candidate_observed","candidate_total",
              "complete_12_candidate_metrics","training_admitted",
              "original_asof_verified",*METRICS}
    items=csv_rows(path,expected)
    index={}
    result=[]
    for r in items:
        t=safe_ticker(r["ticker"]);y=int(r["fiscal_year"])
        if t not in cohort or not 2013<=y<=2025 or (t,y) in index:
            raise ValueError("annual_amount_candidate_outside_frozen_120_panel")
        if not (has_false(r["training_admitted"]) and has_false(r["original_asof_verified"])):
            raise ValueError("false_annual_amount_approval")
        vec={n:amount(r[n]) for n in METRICS}
        n=sum(bool(x) for x in vec.values())
        if n!=int(r["candidate_observed"]) or int(r["candidate_total"])!=len(METRICS):
            raise ValueError("annual_12_amount_completeness_count_mismatch")
        complete=n==len(METRICS)
        if (r["complete_12_candidate_metrics"].lower()=="true")!=complete:
            raise ValueError("annual_12_amount_complete_flag_mismatch")
        issuer,time=issuer_partition(t),temporal_partition(y)
        joint=issuer if issuer==time else "outside_joint_evaluation"
        row={
            "sample_key":f"FINMIND_12:{t}:{y}","ticker":t,"fiscal_year":y,
            "evidence_tier":"FINMIND_ANNUAL_12_AMOUNT_PROVISIONAL",
            "source_kind":"ANNUAL_12_AMOUNT_CANDIDATE",
            "observed_feature_count":n,"candidate_feature_count":12,
            "complete_candidate_vector":str(complete).lower(),
            "issuer_split":issuer,"temporal_split":time,
            "joint_strict_split":joint,"source_sha256":"",
            "original_publication_verified":"false",
            "original_filing_vintage_verified":"false",
            "label_status":"UNKNOWN","training_admitted":"false",**vec
        }
        index[(t,y)]=row
        result.append(row)
    if len(cohort)!=120 or len(index)!=120*13:
        raise ValueError("annual_120x13_company_year_panel_missing_or_extra")
    return sorted(result,key=lambda r:(r["ticker"],r["fiscal_year"])),index,path



def verify_annual_source_stage(data,index):
    """No staged-value substitutions are allowed in the derived 12-wide panel."""
    path=data/"finmind_scaled_annual_candidates"/"finmind_annual_candidate_lines.csv"
    rows=csv_rows(path,(
        "ticker","fiscal_year","candidate_mops_metric","candidate_annual_value",
        "source_family","status","source_sha256","training_admitted",
        "publication_asof_verified","label_status"
    ))
    seen=set()
    for r in rows:
        t=safe_ticker(r["ticker"]);y=int(r["fiscal_year"]);name=r["candidate_mops_metric"]
        if name not in METRICS or (t,y) not in index:
            raise ValueError("annual_candidate_stage_unknown_issuer_year_metric")
        key=(t,y,name)
        if key in seen:
            raise ValueError("duplicate_original_annual_candidate_stage_metric")
        seen.add(key)
        if (not has_false(r["training_admitted"]) or
            not has_false(r["publication_asof_verified"]) or
            r["label_status"]!="UNREVIEWED"):
            raise ValueError("original_finmind_staged_metric_falsely_approved")
        status=r["status"]
        if status=="candidate_annual_value":
            if not re.fullmatch("[0-9a-f]{64}",r["source_sha256"]):
                raise ValueError("missing_raw_source_sha_for_annual_staged_amount")
            original=amount(r["candidate_annual_value"])
            if not original:
                raise ValueError("staged_annual_source_missing_real_value")
        else:
            if status not in ("empty_provider_response","missing_december_value",
                              "missing_income_quarter","archive_missing"):
                raise ValueError("invalid_annual_finmind_staging_status")
            if r["candidate_annual_value"].strip():
                raise ValueError("missing_annual_stage_contains_invented_amount")
            original=""
        if original!=index[(t,y)][name]:
            raise ValueError("annual_12_panel_does_not_match_staged_original_finmind_data")
    expected={(t,y,name) for (t,y) in index for name in METRICS}
    if seen!=expected:
        raise ValueError("annual_stage_missing_metric_cells_from_frozen_120_panel")
    return path


def paper_original_evidence_index(data,phase4):
    files={
      "FINMIND_PROVISIONAL":(
        data/"phase3_literature_integrated"/
        "finmind_provisional_paper_component_values.csv",
        phase4["source_hashes"]["provider_candidate"]),
      "MOPS_OFFICIAL_RETROSPECTIVE":(
        data/"phase3_literature_integrated"/"mops_official_15_features"/
        "literature_15_features.csv",
        phase4["source_hashes"]["official_retrospective"]),
    }
    result={}
    for tier,(path,expected) in files.items():
        if digest(path)!=expected:
            raise ValueError("original_15_paper_input_csv_source_hash_changed")
        original=csv_rows(path,("ticker","fiscal_year",*FEATURES))
        for r in original:
            key=(tier,r["ticker"],int(r["fiscal_year"]))
            if key in result:
                raise ValueError("duplicate_original_paper_feature_source")
            result[key]=r
    return result

def read_paper_features(data,cohort,phase4):
    path=data/"phase4_taiwan_research_dataset"/"taiwan_research_split_register.csv"
    rows=csv_rows(path,SPLIT_COLUMNS)
    original=paper_original_evidence_index(data,phase4)
    registered={}
    paper=[]
    seen=set()
    for r in rows:
        t=safe_ticker(r["ticker"]); y=int(r["fiscal_year"])
        tier=r["evidence_tier"]
        if tier not in ("FINMIND_PROVISIONAL","MOPS_OFFICIAL_RETROSPECTIVE"):
            raise ValueError("unknown_official_or_vendor_paper_evidence_tier")
        if tier=="FINMIND_PROVISIONAL" and t not in cohort:
            raise ValueError("off_cohort_paper_vendor_issuer")
        key=(tier,t,y)
        if key in seen or not 2013<=y<=2025:
            raise ValueError("paper_feature_duplicate_or_year_outside_study")
        seen.add(key)
        if (r["outcome_label"]!="UNKNOWN"
            or not all(has_false(r[x]) for x in (
                "approved_supervised_training","approved_supervised_validation",
                "approved_supervised_test","first_filing_publication_verified",
                "original_vintage_verified","negative_control_reviewed",
                "outcome_known_at_verified"))):
            raise ValueError("unapproved_source_labeled_or_original_vintage_promoted")
        issuer,time=issuer_partition(t),temporal_partition(y)
        joint=issuer if issuer==time else "outside_joint_evaluation"
        if (r["issuer_split"]!=issuer or r["temporal_split"]!=time
            or r["joint_strict_split"]!=joint):
            raise ValueError("frozen_issuer_year_leakage_split_inconsistent")
        vec=json.loads(r["feature_vector_json"])
        if set(vec)!=set(FEATURES):
            raise ValueError("incorrect_original_Beneish_Dechow_paper_features")
        feat={n:amount(vec[n]) for n in FEATURES}
        source=original.get(key)
        if source is None or any(feat[n]!=amount(source[n]) for n in FEATURES):
            raise ValueError("paper_15_feature_vector_differs_from_original_source")
        if tier=="FINMIND_PROVISIONAL" and feat["d_issue"]:
            raise ValueError("unverified_FinMind_d_issue_must_remain_missing")
        count=sum(bool(x) for x in feat.values())
        if count!=int(r["available_feature_count"]) or (
                r["full_15_features"].lower()=="true")!=(count==len(FEATURES)):
            raise ValueError("paper_component_feature_count_conflict")
        evidence_hash=r["source_raw_sha256"]
        if tier=="MOPS_OFFICIAL_RETROSPECTIVE":
            if not re.fullmatch("[0-9a-f]{64}",evidence_hash):
                raise ValueError("mops_official_archive_sha_invalid")
            if r["dataset_sha256"]!=phase4["source_hashes"]["official_retrospective"]:
                raise ValueError("official_paper_source_file_sha_not_frozen")
        else:
            if evidence_hash or r["dataset_sha256"]!=phase4["source_hashes"]["provider_candidate"]:
                raise ValueError("provider_paper_candidates_not_same_evidence_tier")
        if t in CASE_OR_HOLDOUT and tier=="FINMIND_PROVISIONAL" and (
                r["development_event_candidate"].lower()=="false"):
            raise ValueError("candidate_case_wrongly_non_case_labeled")
        row={
            "sample_key":f"{tier}:{t}:{y}","ticker":t,"fiscal_year":y,
            "evidence_tier":tier,"source_kind":"BENEISH_8_DECHOW_7_PAPER_COMPONENTS",
            "observed_feature_count":count,"candidate_feature_count":15,
            "complete_candidate_vector":str(count==15).lower(),
            "issuer_split":issuer,"temporal_split":time,
            "joint_strict_split":joint,"source_sha256":evidence_hash,
            "original_publication_verified":"false",
            "original_filing_vintage_verified":"false",
            "label_status":"UNKNOWN","training_admitted":"false",**feat,
        }
        paper.append(row)
        registered[key]=row
    if len(rows)!=int(phase4["evidence_rows"]) or seen!=set(original):
        raise ValueError("original_phase4_register_count_or_source_coverage_changed")
    return sorted(paper,key=lambda r:(r["evidence_tier"],r["ticker"],r["fiscal_year"])),path



def read_case_paper_features(data):
    """Separate 2012 legacy and FY2013+ development case annual XBRL sources.

    This is a different report/file provenance tier from Phase4 MOPS and
    cannot be promoted to paper fit data, even if 15/15 columns happen to exist.
    """
    folder=data/"phase10_case_official_paper_audit"
    path=folder/"phase10_case_official_paper_features.csv"
    report=json.loads((folder/"phase10_integrated_report.json").read_text(encoding="utf-8"))
    if (report.get("source_issuer_year_rows")!=13
        or report.get("original_pre_correction_versions_verified")!=0
        or report.get("verified_positive_labels")!=0
        or report.get("verified_negative_labels")!=0
        or report.get("historical_asof_training_rows_admitted")!=0
        or report.get("final_holdout_1785_excluded") is not True):
        raise ValueError("development_case_paper_vintage_or_labels_unapproved")
    manifest_path=data/"phase9_case_mops_xbrl_candidates"/"acquisition_results.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8")).get("outcomes",{})
    rows=csv_rows(path,CASE_PAPER_ORIGINAL_COLUMNS)
    if len(rows)!=13:
        raise ValueError("development_case_13_year_original_source_register_incomplete")
    result=[];seen=set()
    for r in rows:
        t=safe_ticker(r["ticker"]);y=int(r["fiscal_year"])
        if t not in {"3027","6452","8299"} or (t,y) in seen or not 2012<=y<=2020:
            raise ValueError("development_case_official_year_identity_or_duplicate")
        seen.add((t,y))
        if (r["outcome_label"]!="UNKNOWN"
            or not all(has_false(r[k]) for k in (
               "approved_positive_label","approved_negative_label",
               "admitted_for_supervised_learning",
               "original_filing_vintage_verified",
               "historical_filing_publication_at_verified",
               "original_notice_publication_at_verified"))):
            raise ValueError("development_case_outcome_or_original_vintage_false_promotion")
        vec=json.loads(r["feature_values_json"])
        if set(vec)!=set(FEATURES):
            raise ValueError("case_paper_feature_vector_schema_not_original15")
        feat={f:amount(vec[f]) for f in FEATURES}
        count=sum(bool(v) for v in feat.values())
        if count!=int(r["components_computed"]):
            raise ValueError("case_paper_feature_count_not_reproducible")
        good=r["official_xbrl_status"]=="validated"
        if good:
            evidence=manifest.get(f"{t}:{y}")
            if (evidence is None or evidence.get("status")!="validated"
                or evidence.get("content_hash")!=r["source_sha256"]
                or not re.fullmatch("[0-9a-f]{64}",r["source_sha256"])
                or r["official_statement_scope"]!="consolidated"):
                raise ValueError("case_paper_official_sha_or_scope_not_same_source")
        elif count or r["source_sha256"]:
            raise ValueError("case_missing_or_legacy_source_not_valid_feature_year")
        if y==2012 and (good or count):
            raise ValueError("FY2012_legacy_not_approved_TIFRS_paper_data")
        issuer=issuer_partition(t)
        temporal=temporal_partition(y) if y>=2013 else "legacy_pre_TIFRS"
        joint=issuer if issuer==temporal else "outside_joint_evaluation"
        result.append({
            "sample_key":f"MOPS_CASE_RETROSPECTIVE:{t}:{y}",
            "ticker":t,"fiscal_year":y,
            "evidence_tier":"MOPS_DEVELOPMENT_CASE_RETROSPECTIVE",
            "source_kind":"CASE_ORIGINAL_15_PAPER_CANDIDATES_SEPARATE",
            "observed_feature_count":count,
            "candidate_feature_count":15,
            "complete_candidate_vector":str(count==15).lower(),
            "issuer_split":issuer,"temporal_split":temporal,
            "joint_strict_split":joint,
            "source_sha256":r["source_sha256"],
            "original_publication_verified":"false",
            "original_filing_vintage_verified":"false",
            "label_status":"UNKNOWN","training_admitted":"false",**feat
        })
    if sum(bool(x["source_sha256"]) for x in result)!=report["official_archived_xbrl_years"]:
        raise ValueError("case_paper_actual_source_count_mismatch")
    return sorted(result,key=lambda r:(r["ticker"],r["fiscal_year"])),path,manifest_path


def read_official_quarterly_sources(data,cohort):
    """Validate source index, per-quarter SHA and separate 6452 development case."""
    folder=data/"phase14_multiissuer_quarterly_comparison"
    report=json.loads((folder/"phase14_integrated_report.json").read_text(encoding="utf-8"))
    if (report.get("final_holdout_1785_excluded") is not True or
        report.get("verified_true_negative_company_quarters")!=0 or
        report.get("verified_false_filing_positive_company_quarters")!=0 or
        report.get("supervised_ml_rows_admitted")!=0):
        raise ValueError("quarterly_source_admission_gate_failed")
    items=csv_rows(folder/"multiissuer_official_quarter_sources.csv",SOURCE_COLUMNS)
    manifest=json.loads((folder/"quarterly_acquisition_results.json").read_text(encoding="utf-8"))
    old=manifest.get("outcomes")
    if not isinstance(old,dict) or len(items)!=144:
        raise ValueError("official_quarterly_12x12_source_inventory_incomplete")
    result=[];keys=set();companies=set()
    for r in items:
        t=safe_ticker(r["ticker"]);p=r["reporting_period"]
        if t in CASE_OR_HOLDOUT or t not in cohort or p not in FROZEN_PERIODS:
            raise ValueError("unapproved_comparison_issuer_or_period")
        key=(t,p)
        if key in keys:
            raise ValueError("duplicate_issuer_quarter_source")
        keys.add(key);companies.add(t)
        status=r["source_status"];sha=r["raw_sha256"]
        source=old.get(f"{t}:{p}")
        if source is None or (source["source_status"]!=status or
            source.get("raw_sha256","")!=sha or source["outcome_label"]!="UNKNOWN"
            or source["normal_label_approved"] is not False
            or source["original_asof_verified"] is not False):
            raise ValueError("official_quarter_manifest_index_mismatch")
        good=status==VALID
        if good:
            verify_bytes(folder/"raw",source["raw_path"],sha)
        elif sha:
            verify_bytes(folder/"raw",source["raw_path"],sha)
        if (not (has_false(r["original_filing_version_verified"]) and
                has_false(r["first_publication_verified"]) and
                has_false(r["normal_label_approved"]) and
                has_false(r["training_admitted"]))
            or r["outcome_label"]!="UNKNOWN"):
            raise ValueError("quarterly_false_normal_label_or_original_vintage")
        result.append({
            "sample_key":f"MOPS_COMP_QUARTER:{t}:{p}","ticker":t,
            "reporting_period":p,"data_role":"UNLABELED_MULTIISSUER_COMPARISON",
            "source_status":status,"source_sha256":sha,
            "financial_issuer_quarter_observation":str(good).lower(),
            "historical_publication_verified":"false",
            "original_filing_vintage_verified":"false",
            "label_status":"UNKNOWN","negative_label_approved":"false",
            "training_admitted":"false",
        })
    if len(companies)!=12 or sum(r["financial_issuer_quarter_observation"]=="true" for r in result)!=report[
        "official_quarters_context_and_primary_TWD_validated"]:
        raise ValueError("mops_quarterly_validation_report_not_reproduced")

    case_root=data/"phase12_kangyou_quarterly_panel"
    case_report=json.loads((case_root/"phase12_integrated_report.json").read_text(encoding="utf-8"))
    if (case_report.get("issuer")!="6452" or case_report.get("candidate_quarters")!=12
        or case_report.get("official_quarters_context_scope_validated")!=12
        or case_report.get("confirmed_period_outcome_labels")!=0
        or case_report.get("historical_original_filing_vintages_verified")!=0
        or case_report.get("final_holdout_1785_excluded") is not True):
        raise ValueError("case_quarter_evidence_not_unlabeled")
    case_rows=csv_rows(case_root/"quarterly_case_official_source_index.csv",
                       KANGYOU_SOURCE_COLUMNS)
    case_manifest=json.loads((case_root/"quarterly_acquisition_results.json").read_text(encoding="utf-8"))["outcomes"]
    prior=json.loads((data/"phase11_case_quarterly_and_paper_gaps"/
                      "phase11_integrated_report.json").read_text(encoding="utf-8"))["quarterly_source_status"]
    seen=set()
    for r in case_rows:
        p=r["reporting_period"];t=safe_ticker(r["ticker"]);sha=r["raw_sha256"]
        if t!="6452" or p not in FROZEN_PERIODS or p in seen:
            raise ValueError("candidate_case_quarterly_identity_mismatch")
        seen.add(p)
        actual=prior if p=="2020Q1" else case_manifest.get(p)
        if actual is None or sha!=actual["raw_sha256"]:
            raise ValueError("case_quarterly_official_SHA_index_mismatch")
        folder_raw=(data/"phase11_case_quarterly_and_paper_gaps"/"official_quarterly_source"/"raw"
                    if p=="2020Q1" else case_root/"raw")
        verify_bytes(folder_raw,actual["raw_path"],sha)
        if (r["source_status"]!="QUARTER_CONTEXT_VALIDATED_VINTAGE_UNKNOWN"
            or not has_false(r["admitted_for_model_training"])
            or not has_false(r["historical_first_publication_verified"])
            or not has_false(r["historical_first_original_version_verified"])
            or r["independently_verified_fraud_outcome"]!="UNKNOWN"):
            raise ValueError("case_period_fraud_outcome_must_remain_unknown")
        result.append({
            "sample_key":f"MOPS_DEV_CASE_QUARTER:{t}:{p}","ticker":t,
            "reporting_period":p,"data_role":"ALLEGED_EVENT_PERIOD_NOT_CONFIRMED_POSITIVE",
            "source_status":r["source_status"],"source_sha256":sha,
            "financial_issuer_quarter_observation":"true",
            "historical_publication_verified":"false",
            "original_filing_vintage_verified":"false",
            "label_status":"UNKNOWN","negative_label_approved":"false",
            "training_admitted":"false",
        })
    if len(seen)!=12:
        raise ValueError("case_12_quarter_sources_missing")
    return sorted(result,key=lambda r:(r["ticker"],r["reporting_period"])),folder,case_root


def annual_window_register(index,*,lengths=(3,5)):
    result=[]
    for t in sorted({key[0] for key in index}):
        for target in range(2013+min(lengths),2026):
            for span in lengths:
                years=list(range(target-span,target+1))
                if years[0]<2013:
                    continue
                periods=[index.get((t,yr)) for yr in years]
                if not all(periods):
                    continue
                full=all(x["complete_candidate_vector"]=="true" for x in periods)
                group=issuer_partition(t);time=temporal_partition(target)
                result.append({
                    "ticker":t,"target_year":target,"lookback_years":span,
                    "needed_fiscal_years":"|".join(map(str,years)),
                    "all_12_amounts_present":str(full).lower(),
                    "issuer_split":group,"time_split":time,
                    "joint_strict_split":group if group==time else "outside_joint_evaluation",
                    "outcome_label":"UNKNOWN",
                    "approved_for_supervised_training":"false",
                })
    return result


def measure_feature_density(paper):
    bytier=defaultdict(list)
    for r in paper:
        bytier[r["evidence_tier"]].append(r)
    output=[]
    for tier,rows in sorted(bytier.items()):
        fit=[r for r in rows if
             r["joint_strict_split"]=="fit" and r["ticker"] not in CASE_OR_HOLDOUT]
        for feature in FEATURES:
            count=sum(bool(r[feature]) for r in fit)
            output.append({
                "evidence_tier":tier,"feature_name":feature,
                "fit_candidate_company_years":len(fit),
                "fit_years_with_feature":count,
                "fit_coverage_ratio":f"{count/len(fit):.6f}" if fit else "",
                "all_tier_years_with_feature":sum(bool(r[feature]) for r in rows),
                "approved_as_literature_feature_for_training":"false",
            })
    return output


def quarter_feature_density(data,quarter_index):
    approved={(r["ticker"],r["reporting_period"]):r for r in quarter_index}
    files=[
        (data/"phase14_multiissuer_quarterly_comparison"/
         "multiissuer_quarter_twd_observations.csv","MOPS_QUARTER_COMPARISON"),
        (data/"phase13_kangyou_quarterly_temporal_features"/
         "quarterly_twd_source_observations.csv","MOPS_DEV_CASE_QUARTER"),
    ]
    grouped=defaultdict(set)
    for path,tier in files:
        records=csv_rows(path,("ticker","reporting_period","concept_key",
            "period_grain","source_unit","reconciliation_status",
            "source_sha256","value_decimal"))
        encountered=set()
        for row in records:
            t=safe_ticker(row["ticker"]);p=row["reporting_period"]
            source=approved.get((t,p))
            if (source is None or source["source_sha256"]!=row["source_sha256"]
                or ((tier=="MOPS_DEV_CASE_QUARTER")!=(t=="6452"))):
                raise ValueError("quarterly_raw_observation_or_source_SHA_not_registered")
            if source["financial_issuer_quarter_observation"]!="true":
                raise ValueError("unvalidated_quarterly_source_cannot_create_metric")
            key=(t,p,row["concept_key"],row["period_grain"])
            if key in encountered:
                raise ValueError("duplicate_quarter_concept_grain_candidate")
            encountered.add(key)
            if (row["reconciliation_status"]!="CANDIDATE_CONSISTENT_REPETITIONS"
                or row["period_grain"]=="other_duration"):
                continue
            if row["source_unit"]!="TWD" or not amount(row["value_decimal"]):
                raise ValueError("qualified_quarter_value_missing_or_non_TWD")
            grouped[(t,tier,row["concept_key"],row["period_grain"])].add(p)
    output=[]
    for (t,tier,concept,grain),periods in sorted(grouped.items()):
        output.append({
            "ticker":t,"feature_name":concept,"period_grain":grain,
            "source_tier":tier,"quarters_observed":len(periods),
            "quarters_expected":12,"earliest_period":min(periods),
            "latest_period":max(periods),
            "retrospective_not_original_publication":"true",
            "approved_for_supervised_learning":"false"
        })
    return output


def run(data_root,output):
    data=Path(data_root);out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    cohort_file=data/"finmind_scaled_120"/"finmind_scaled_cohort.csv"
    cohort_items=read_universe(cohort_file)
    cohort={r["ticker"] for r in cohort_items}
    phase4_file=data/"phase4_taiwan_research_dataset"/"phase4_dataset_integrated_report.json"
    phase4=json.loads(phase4_file.read_text(encoding="utf-8"))
    if (phase4.get("cohort_issuer_count")!=120 or phase4.get("source_tiers_not_fused") is not True
        or phase4.get("eligible_for_supervised_financial_fraud_training") is not False
        or phase4.get("labels_approved_positive")!=0 or phase4.get("labels_approved_negative")!=0
        or phase4.get("final_holdout_excluded") is not True
        or phase4["source_hashes"]["cohort"]!=digest(cohort_file)):
        raise ValueError("phase4_research_source_split_not_frozen_or_label_leak")
    annual,annual_idx,annual_path=read_annual_amounts(data,cohort)
    staged_path=verify_annual_source_stage(data,annual_idx)
    paper,paper_path=read_paper_features(data,cohort,phase4)
    case_paper,case_paper_path,phase9_manifest=read_case_paper_features(data)
    quarters,qroot,case_root=read_official_quarterly_sources(data,cohort)
    windows=annual_window_register(annual_idx)
    density=measure_feature_density(paper)
    qdensity=quarter_feature_density(data,quarters)
    dump_csv(out/"annual_12_amount_candidate_index.csv",ANNUAL_COLUMNS,annual)
    dump_csv(out/"annual_original_15_paper_candidate_index.csv",PAPER_COLUMNS,paper)
    dump_csv(out/"case_official_15_paper_candidate_separate.csv",PAPER_COLUMNS,case_paper)
    dump_csv(out/"annual_12_amount_sequence_windows.csv",WINDOW_COLUMNS,windows)
    dump_csv(out/"quarterly_issuer_period_source_index.csv",QUARTER_COLUMNS,quarters)
    dump_csv(out/"paper_feature_fit_coverage.csv",FIT_FEATURE_COLUMNS,density)
    dump_csv(out/"quarterly_feature_coverage_by_issuer.csv",DENSE_COLUMNS,qdensity)
    annual_st=Counter(r["complete_candidate_vector"] for r in annual)
    paper_st=Counter((r["evidence_tier"],r["complete_candidate_vector"]) for r in paper)
    win=Counter((r["lookback_years"],r["joint_strict_split"],
                 r["all_12_amounts_present"]) for r in windows)
    qstat=Counter((r["data_role"],r["financial_issuer_quarter_observation"]) for r in quarters)
    qcoverage=Counter((r["source_tier"],r["quarters_observed"]==12) for r in qdensity)
    annual_splits=Counter((r["joint_strict_split"],r["complete_candidate_vector"]) for r in annual)
    annual_issuer_splits={group:len({r["ticker"] for r in annual
                                  if r["issuer_split"]==group})
                          for group in ("fit","validation","test")}
    quarter_status=Counter((r["data_role"],r["source_status"]) for r in quarters)
    input_paths=[cohort_file,phase4_file,annual_path,staged_path,paper_path,
        case_paper_path,phase9_manifest,
        qroot/"multiissuer_official_quarter_sources.csv",
        qroot/"quarterly_acquisition_results.json",
        case_root/"quarterly_case_official_source_index.csv",
        case_root/"quarterly_acquisition_results.json",
        data/"phase13_kangyou_quarterly_temporal_features"/
            "quarterly_twd_source_observations.csv",
        qroot/"multiissuer_quarter_twd_observations.csv"]
    report={
        "status":"FINALIZATION_ROUND1_REAL_TAIWAN_DATA_INTEGRATED_RESEARCH_TIERS_QA",
        "cohort_120_current_listed_issuers":len(cohort),
        "annual_12_amount_candidate_company_years":len(annual),
        "annual_12_amount_full_12_company_years":annual_st["true"],
        "annual_12_amount_missing_or_partial_company_years":annual_st["false"],
        "annual_12_amount_strict_issuer_and_target_year_split":{
            group:{"complete_candidate_company_years":annual_splits[(group,"true")],
                   "incomplete_candidate_company_years":annual_splits[(group,"false")]}
            for group in ("fit","validation","test","outside_joint_evaluation")},
        "annual_issuer_disjoint_company_counts":annual_issuer_splits,
        "annual_paper_15_source_tier_rows":len(paper),
        "annual_paper_15_source_tiers":{
            tier:{"total":sum(r["evidence_tier"]==tier for r in paper),
                  "full_15":paper_st[(tier,"true")]} for tier in
            ("FINMIND_PROVISIONAL","MOPS_OFFICIAL_RETROSPECTIVE")},
        "annual_source_tiers_never_silently_fused":True,
        "development_case_annual_source_years_separate_from_noncase_fit":len(case_paper),
        "development_case_annual_official_XBRL_source_years":sum(
            bool(r["source_sha256"]) for r in case_paper),
        "development_case_full_15_retrospective_years":sum(
            r["complete_candidate_vector"]=="true" for r in case_paper),
        "FY2012_legacy_GAAP_not_converted_to_TIFRS":True,
        "annual_12_amount_is_NOT_Beneish_Dechow_15":True,
        "three_year_history_windows_with_target":sum(r["lookback_years"]==3 for r in windows),
        "three_year_history_complete_12_amount_windows":sum(
            r["lookback_years"]==3 and r["all_12_amounts_present"]=="true" for r in windows),
        "three_year_history_fit_issuer_and_time_disjoint_complete_candidates":
            win[(3,"fit","true")],
        "five_year_history_complete_12_amount_windows":sum(
            r["lookback_years"]==5 and r["all_12_amounts_present"]=="true" for r in windows),
        "quarter_issuer_period_source_rows":len(quarters),
        "quarter_research_issuer_count":len({r["ticker"] for r in quarters}),
        "quarter_sources_by_role_and_status":{
            role:dict(sorted((status,count) for (r,status),count in quarter_status.items()
                             if r==role)) for role in
            ("UNLABELED_MULTIISSUER_COMPARISON","ALLEGED_EVENT_PERIOD_NOT_CONFIRMED_POSITIVE")},
        "quarter_comparison_source_period_validated":qstat[("UNLABELED_MULTIISSUER_COMPARISON","true")],
        "quarter_known_case_source_period_validated":qstat[("ALLEGED_EVENT_PERIOD_NOT_CONFIRMED_POSITIVE","true")],
        "distinct_quarter_concept_and_grain_per_issuer":len(qdensity),
        "quarter_exact_concepts_present_all_12_quarters_comparison":
            qcoverage[("MOPS_QUARTER_COMPARISON",True)],
        "quarter_exact_concepts_present_all_12_quarters_case":
            qcoverage[("MOPS_DEV_CASE_QUARTER",True)],
        "known_case_firms_not_verified_positive":True,
        "unreviewed_comparison_issuers_not_verified_negative":True,
        "last_event_holdout_1785_excluded":True,
        "original_first_filing_versions_verified":0,
        "first_publication_times_verified":0,
        "annual_model_usable_independent_company_years_with_certified_original_and_labels":0,
        "quarterly_model_usable_independent_company_quarters_with_certified_original_and_labels":0,
        "total_financial_account_rows_are_NOT_independent_ml_training_samples":True,
        "selected_quarter_cohort_has_current_listing_survivorship_bias_not_corrected":True,
        "approved_positive_labels":0,"approved_negative_labels":0,
        "fraud_supervised_training_rows_admitted":0,
        "no_ml_model_fitting_in_dataset_round":True,
        "network_requests":0,"production_db_writes":0,
        "input_sha256":{p.name+":"+str(i):digest(p) for i,p in enumerate(input_paths)},
        "next_round_handoff":{
            "round2":"Adjudicate historical as-original filing and event-first-disclosure dates, true positive and truly reviewed normal/unknown periods, while pursuing full 15 paper feature coverage.",
            "training_regression_study_only":"12 annual FinMind provisional amounts; cannot score financial misstatement.",
            "training_fraud_study":"BLOCKED until independently verified outcome and point-in-time fiscal filing data.",
            "strict_company_year_split":"Issuer hash disjoint plus target-year partition, with outside-joint rows excluded."
        },
    }
    with (out/"round1_dataset_readiness_report.json").open("w",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2)
        f.write("\n")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Finalization Round 1: SOURCE-SAFE Taiwan company/quarter ML dataset readout")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    args=p.parse_args(argv)
    print(json.dumps(run(args.data_root,args.output),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
