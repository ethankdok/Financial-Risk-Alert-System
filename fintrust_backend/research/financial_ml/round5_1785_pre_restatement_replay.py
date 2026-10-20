"""1785 retrospective pre-restatement model application using archived official notice.

This module deliberately uses the PRE columns in the November 2016 MOPS
restatement notice, NEVER post-restatement as model features.

Only the already-selected frozen Round3 persistence baseline may operate
feature-wise when the historical 12-vector is partially observed. Full
Ridge/RF/neural predictions are BLOCKED if any required input is absent.
This is a HINDSIGHT evaluation of originally reported *numbers as described
by the 2016 notice*, not proven first-public as-of-2016-May early warning.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.services.financial_research.decimal_math import parse_decimal, to_twd, text as exact_text
# Local copy of the official evidence-export CSV contract. Do not import
# evidence_export here: that acquisition service depends on FastAPI/pydantic
# and has no role in frozen offline model scoring.
COMPARISON_FIELDS = (
    "ticker","evidence_type","period","fiscal_year","statement_scope",
    "accounting_framework","statement_type","pre_label","post_label",
    "canonical_metric","sign_factor","pre_restatement_value",
    "post_restatement_value","difference","published_unit","disclosed_at",
    "availability_status","point_in_time_eligible","pre_value_semantics",
    "source_url","announcement_key","content_hash",
)
PRE_VALUE_SEMANTICS = (
    "as previously reported according to the company's 2016-11-13 restatement notice "
    "(may differ from the first-published figure)"
)
from app.services.historical_audit.package_verify import verify_package
from .annual_panel_readiness import METRICS
from .final_1785_case_replay import STRICT_SHA, ROUND3_SHA, digest
from .round4_research_handoff import read_round3

FORECAST_COLS=(
    "ticker","forecast_year","input_latest_fiscal_year","metric",
    "model","model_fitted_with_1785","forecast_twd",
    "observed_pre_twd","observed_post_twd",
    "error_vs_pre_twd","error_vs_post_twd",
    "restatement_adjustment_twd","normalized_pre_surprise",
    "input_basis","interpretation",
)
RESTATEMENT_COLS=(
    "ticker","fiscal_year","metric","pre_twd","post_twd","delta_post_minus_pre_twd",
    "pre_as_2016_notice_previous_report","derived_from_pre_gross_less_expense","announcement_key",
    "disclosed_at","source_sha256","statement_scope","accounting_framework",
)
COVERAGE_COLS=("fiscal_year","metric","has_pre_notice_value","source_status")
ALLOWED_YEARS=(2013,2014,2015)
NOVEMBER="2016-11-13"
STUDY_MODE="RETROSPECTIVE_PRE_RESTATEMENT_NOTICE_REPLAY"


def official_pre_pairs(strict_zip):
    target=Path(strict_zip)
    if digest(target)!=STRICT_SHA:
        raise ValueError("1785_strict_zip_frozen_sha_mismatch")
    outcome=verify_package(target)
    if outcome.get("status")!="verified" or outcome.get("mode")!="strict_point_in_time":
        raise ValueError("1785_strict_zip_semantic_verification_failed")
    root="fintrust_historical_research_dataset/"
    with zipfile.ZipFile(target) as arc:
        manifest=json.loads(arc.read(root+"manifest.json").decode("utf-8"))
        if (manifest.get("mode")!="strict_point_in_time"
            or str(manifest.get("case",{}).get("ticker"))!="1785"
            or manifest.get("parameters",{}).get("as_of")!="2016-11-14"):
            raise ValueError("1785_notice_archive_wrong_case_time")
        contents=arc.read(root+"data/restatement_comparisons.csv").decode("utf-8-sig")
    reader=csv.DictReader(io.StringIO(contents))
    if not set(COMPARISON_FIELDS).issubset(reader.fieldnames or []):
        raise ValueError("1785_restatement_source_schema_missing")
    all_rows=list(reader)
    if len(all_rows)!=158:
        raise ValueError("1785_expected_frozen_158_official_restatement_rows")
    counts=Counter(r["statement_scope"] for r in all_rows)
    if counts!={"consolidated":79,"individual":79}:
        raise ValueError("1785_restatement_statement_scope_count_changed")
    results={}
    sources={}
    official_expenses={}
    for row in all_rows:
        if (row["ticker"]!="1785" or row["evidence_type"]!="official_restatement_comparison"
            or row["statement_scope"] not in ("consolidated","individual")
            or row["pre_value_semantics"]!=PRE_VALUE_SEMANTICS
            or row["disclosed_at"][:10]!=NOVEMBER
            or row["availability_status"] not in ("verified","verified_notice","published","public","available") 
               and not row["availability_status"].startswith("verified_")
            or row["point_in_time_eligible"].lower()!="true"):
            raise ValueError("1785_comparison_evidence_identity_or_publication_changed")
        if row["statement_scope"]!="consolidated":
            continue
        year=int(row["fiscal_year"])
        if year not in ALLOWED_YEARS: continue
        if row["accounting_framework"]!="TIFRS":
            raise ValueError("1785_wrong_TIFRS_pre_accounting_regime")
        metric=row["canonical_metric"]
        is_operating_expense=(metric not in METRICS and
                              row["pre_label"]=="營業費用合計" and
                              row["post_label"]=="營業費用合計")
        if metric not in METRICS and not is_operating_expense:
            continue
        if row["published_unit"]!="TWD_thousand":
            raise ValueError("1785_official_comparison_not_thousand_twd")
        factor=int(row["sign_factor"])
        if factor not in (-1,1):
            raise ValueError("1785_invalid_notice_sign_factor")
        raw_pre=parse_decimal(row["pre_restatement_value"])
        raw_post=parse_decimal(row["post_restatement_value"])
        raw_delta=parse_decimal(row["difference"])
        if raw_pre is None or raw_post is None or raw_delta is None:
            continue
        if raw_post-raw_pre != raw_delta:
            raise ValueError("1785_official_pre_post_difference_inconsistent")
        pre=to_twd(raw_pre,"TWD_thousand")*factor
        post=to_twd(raw_post,"TWD_thousand")*factor
        if is_operating_expense:
            # Unmapped *official* income-statement row: expense amounts are
            # signed negative in the notice. Derive operating income from
            # same-year PRE gross profit and PRE operating expenses alone.
            # POST values are derived separately and NEVER enter prediction.
            if year in official_expenses:
                raise ValueError("1785_duplicate_official_operating_expense")
            if pre>0 or post>0:
                raise ValueError("1785_official_expense_sign_unexpected")
            official_expenses[year]=(pre,post,row)
            continue
        key=(year,metric)
        if key in results:
            raise ValueError(f"1785_duplicate_consolidated_year_metric:{year}:{metric}")
        results[key]=(pre,post)
        sources[key]=row
    for year,(expense_pre,expense_post,expense_source) in official_expenses.items():
        gp=results.get((year,"gross_profit"))
        if gp is None or (year,"operating_income") in results:
            continue
        results[(year,"operating_income")]=(
            gp[0]+expense_pre,gp[1]+expense_post)
        sources[(year,"operating_income")]={
            **expense_source,
            "_derived_pre_formula":"PRE gross_profit + PRE signed operating_expenses",
            "_derived_post_formula":"POST gross_profit + POST signed operating_expenses",
        }
    if not results:
        raise ValueError("1785_no_pre_restatement_consolidated_amounts")
    return results,sources,{"archive":outcome,"source_scope_counts":dict(counts),
                            "source_rows":len(all_rows),
                            "archive_sha256":digest(target)}


def load_locked_persistence(round3_root, round3_report):
    """Authorize only the validation-selected Round3 model; 1785 never fits it.

    Persistence is yhat_t=x_(t-1). In the pipeline signed-log and fit-only
    RobustScaler algebra cancel, so exact original pre-side TWD is preserved.
    """
    import joblib
    root=Path(round3_root)
    src=root/"round3_real_data_model_report.json"
    if digest(src)!=ROUND3_SHA:
        raise ValueError("1785_round3_original_report_sha256_mismatch")
    if (round3_report["annual_numeric_study"]["selected_model_by_validation_only"]
        !="persistence"):
        raise ValueError("1785_forbidden_hindsight_model_selection")
    obj=joblib.load(root/"annual_checkpoints"/"fit_only_preprocessor.joblib")
    if (obj.get("study_only") is not True or tuple(obj.get("features",()))!=METRICS
        or obj.get("seed")!=round3_report["experiment_seed"]):
        raise ValueError("1785_frozen_train_only_preprocessor_mismatch")
    scaler=obj.get("scaler")
    if scaler is None or len(scaler.center_)!=len(METRICS) or len(scaler.scale_)!=len(METRICS):
        raise ValueError("1785_frozen_12_field_scaler_not_loaded")
    if any(not math.isfinite(float(x)) or float(x)==0
           for x in scaler.scale_):
        raise ValueError("1785_nonfinite_frozen_scaler")
    return obj


def replay(pairs, sources, model_bundle):
    """One-year numerical persistence on AVAILABLE pre-side fields only.

    2014/15 comparisons: prior-year PRE -> year PRE, compare POST only
    as outcome (not feature). 2016 forecast: 2015 PRE with 2013-15
    three-year same-field verified coverage; NEVER 2015 POST.
    """
    import numpy as np
    scaler=model_bundle["scaler"]
    features={name:i for i,name in enumerate(METRICS)}
    def locked_prediction(raw,index):
        # Recompute frozen signed-log/RobustScaler and inverse. This executes
        # the selected baseline's mathematical operation, not a new fit.
        amount=float(raw)
        if not math.isfinite(amount):
            raise ValueError("1785_pre_notice_amount_nonfinite")
        encoded=math.copysign(math.log1p(abs(amount)),amount)
        normalized=(encoded-float(scaler.center_[index]))/float(scaler.scale_[index])
        decoded=normalized*float(scaler.scale_[index])+float(scaler.center_[index])
        result=math.copysign(math.expm1(abs(decoded)),decoded)
        if not math.isfinite(result) or not math.isclose(result,amount,rel_tol=1e-9,abs_tol=1e-3):
            raise ValueError("1785_frozen_persistence_scaler_failed_roundtrip")
        # Decimal is exact; the roundtrip above proves the frozen model path.
        return raw
    forecasts=[]
    for target in (2014,2015,2016):
        for metric,ind in features.items():
            # 2014 or 2015 is one-year retrospective comparison;
            # 2016 is same exact model but verifies 3 input fiscal years.
            years=range(2013,2016) if target==2016 else (target-1,)
            if not all((y,metric) in pairs for y in years):
                continue
            prior=pairs[(target-1,metric)][0]  # ONLY PRE side
            guessed=locked_prediction(prior,ind)
            this=pairs.get((target,metric))
            pre= this[0] if this else None
            post=this[1] if this else None
            change=(post-pre) if pre is not None and post is not None else None
            normalized=(2*abs(guessed-pre)/(abs(guessed)+abs(pre)+Decimal(1))
                        if pre is not None else None)
            forecasts.append({
                "ticker":"1785","forecast_year":target,
                "input_latest_fiscal_year":target-1,"metric":metric,
                "model":"persistence","model_fitted_with_1785":"false",
                "forecast_twd":exact_text(guessed),
                "observed_pre_twd":exact_text(pre),
                "observed_post_twd":exact_text(post),
                "error_vs_pre_twd":exact_text(abs(guessed-pre)) if pre is not None else "",
                "error_vs_post_twd":exact_text(abs(guessed-post)) if post is not None else "",
                "restatement_adjustment_twd":exact_text(change),
                "normalized_pre_surprise":exact_text(normalized),
                "input_basis":"consolidated_TIFRS_pre_as_reported_in_2016_notice",
                "interpretation":"HINDSIGHT_FINANCIAL_AMOUNT_NOT_FRAUD_PROBABILITY",
            })
    return forecasts


def csv_output(path,fields,rows):
    with Path(path).open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.DictWriter(f,fieldnames=fields,extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def run(*, strict_zip,data_root,round2_bridge_root,round3_root,output):
    strict_zip=Path(strict_zip)
    round3_root=Path(round3_root)
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("1785_pre_restatement_replay_output_already_exists")
    model_report=read_round3(
        round3_root/"round3_real_data_model_report.json",
        Path(data_root),Path(round2_bridge_root))
    model_bundle=load_locked_persistence(round3_root,model_report)
    pairs,sources,provenance=official_pre_pairs(strict_zip)
    forecasts=replay(pairs,sources,model_bundle)
    annual=[]
    for (year,metric),(pre,post) in sorted(pairs.items()):
        row=sources[(year,metric)]
        annual.append({
            "ticker":"1785","fiscal_year":year,"metric":metric,
            "pre_twd":exact_text(pre),"post_twd":exact_text(post),
            "delta_post_minus_pre_twd":exact_text(post-pre),
            "pre_as_2016_notice_previous_report":"true",
            "derived_from_pre_gross_less_expense":str(bool(row.get("_derived_pre_formula"))).lower(),
            "announcement_key":row["announcement_key"],
            "disclosed_at":row["disclosed_at"],
            "source_sha256":row["content_hash"],
            "statement_scope":row["statement_scope"],
            "accounting_framework":row["accounting_framework"],
        })
    matrix=[{
        "fiscal_year":year,"metric":m,
        "has_pre_notice_value":str((year,m) in pairs).lower(),
        "source_status":"PRE_AS_DISCLOSED_2016_NOV"
                         if (year,m) in pairs else "NOT_OBSERVED"
    } for year in ALLOWED_YEARS for m in METRICS]
    count_2016=sum(int(x["forecast_year"])==2016 for x in forecasts)
    count_2015=sum(int(x["forecast_year"])==2015 for x in forecasts)
    if count_2015==0 and count_2016==0:
        raise ValueError("1785_pre_numbers_insufficient_for_any_numeric_replay")
    big2015=sorted(
        (r for r in forecasts if r["forecast_year"]==2015 and
         r["observed_pre_twd"] not in ("",None)),
        key=lambda x:Decimal(x["error_vs_pre_twd"]),reverse=True)
    report={
        "status":"1785_PRE_RESTATEMENT_NUMERIC_REPLAY_REAL_NOTICE_VALUES",
        "ticker":"1785","model":"frozen_round3_validation_selected_persistence",
        "model_chosen_before_final_case":True,
        "model_retrained_on_1785":False,
        "source_mode":STUDY_MODE,"official_notice_disclosure":"2016-11-13",
        "strict_archive":provenance,
        "scopes_used":["consolidated"],"accounting_regimes_used":["TIFRS"],
        "years_observed":[2013,2014,2015],
        "official_pre_post_metric_pairs":len(pairs),
        "derived_pre_post_operating_income_years":sum(
            bool(x.get("_derived_pre_formula")) for x in sources.values()),
        "forecast_record_count":len(forecasts),
        "2015_numeric_forecast_count":count_2015,
        "2016_three_year_same_feature_numeric_forecast_count":count_2016,
        "2016_full_twelve_metric_vector_available":count_2016==12,
        "2015_greatest_pre_number_forecast_deviations":big2015[:5],
        "actual_fraud_accuracy":None,"actual_fraud_precision":None,
        "actual_fraud_recall":None,"actual_fraud_f1_score":None,
        "fraud_probability":None,
        "caveat":"Numbers labeled PRE are transcribed from Nov-2016 retrospective official notices, not independently proven first-published availability before May-2016.",
        "post_restatement_not_used_as_feature":True,
        "future_restatement_not_leaked_into_prediction":True,
        "no_network_requests":True,"no_production_database_writes":True,
        "outputs":[
            "1785_pre_vs_post_official_amounts.csv",
            "1785_frozen_persistence_pre_only_predictions.csv",
            "1785_original_pre_feature_coverage.csv",
            "1785_pre_restatement_replay_report.json",
        ],
    }
    output.mkdir(parents=True,exist_ok=True)
    csv_output(output/"1785_pre_vs_post_official_amounts.csv",RESTATEMENT_COLS,annual)
    csv_output(output/"1785_frozen_persistence_pre_only_predictions.csv",FORECAST_COLS,forecasts)
    csv_output(output/"1785_original_pre_feature_coverage.csv",COVERAGE_COLS,matrix)
    (output/"1785_pre_restatement_replay_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="1785 actual pre-restatement official annual amounts, frozen baseline")
    for a in ("strict-zip","data-root","round2-bridge-root","round3-root","output"):
        p.add_argument("--"+a,required=True)
    x=p.parse_args(argv)
    result=run(strict_zip=x.strict_zip,data_root=x.data_root,
               round2_bridge_root=x.round2_bridge_root,
               round3_root=x.round3_root,output=x.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
