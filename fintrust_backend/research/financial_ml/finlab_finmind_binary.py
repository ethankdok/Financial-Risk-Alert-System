"""FinTrust existing-data binary ML: FinLab-reviewed Y / TEJ proxy Y2 + FinMind financial X.

Use existing LOCAL research exports only. No network, secrets, source modifications,
official-data relabeling, backfilled zeros, or historical early-warning claim.

Input 1: finmind_annual_candidates/finmind_annual_candidate_lines.csv from
          finmind_annual_candidate_stage.py (12 provisional annual quantities).
Input 2, ONE of:
    --label-kind silver: round2_labels/round2_binary_research_labels.csv
    --label-kind tej_proxy: round2_label_cohorts_20261025/tej_calendar_proxy_cohort_private.csv
    --label-kind human: a manually reviewed CSV with
          ticker,fiscal_year,human_label,review_status,evidence_url

Target FY and input FY intentionally differ:
  Silver/Human affected financial FY=t -> historical X from FY t-1, t-2.
  TEJ calendar year t -> historical X from FY t-2, t-3, with cutoff Dec31(t-1).
Both are retrospective research unless independently verified first-public
historical vintages and dates are supplied. FinMind source archive may contain
subsequently amended values; this module never claims a PIT-certified X.

Outputs are PRIVATE under ignored fintrust_backend/data/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from .annual_panel_readiness import METRICS, FIELDNAMES

FEATURES = (
    "roa", "cfo_to_assets", "debt_to_assets", "current_ratio", "gross_margin",
    "operating_margin", "profit_cfo_gap_assets", "revenue_growth",
    "inventory_growth", "assets_growth", "gross_margin_delta",
    "cfo_to_net_income",
)
MODEL_COLS = (
    "ticker", "target_year", "x_fiscal_year", "prior_x_fiscal_year",
    "label_kind", "label_grade", "label", "split", "source_x_present_count",
    "source_x_prior_present_count", "available_feature_count",
    "x_retrospective_only", "source_x", *FEATURES
)
ALLOWED_SILVER = "DOCUMENTED_ANNUAL_CONSOLIDATED_CORE_FINANCIAL_CORRECTION_OR_RESTATEMENT_OBSERVED_BY_ASOF"
ALLOWED_PROXY = "TEJ_INFORMATION_TRANSPARENCY_PROXY_NOT_TT2"
TRAIN_MIN = 8
TRAIN_POS_MIN = 2
TRAIN_NEG_MIN = 2


def read_csv(path, required):
    raw = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "cp950"):
        try:
            decoded = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("CSV_ENCODING_UNRECOGNIZED")
    reader = csv.DictReader(io.StringIO(decoded))
    if not set(required).issubset(reader.fieldnames or ()):
        raise ValueError("CSV_REQUIRED_COLUMNS_MISSING:" +
                         ",".join(sorted(set(required) - set(reader.fieldnames or ()))))
    return list(reader), hashlib.sha256(raw).hexdigest()


def as_num(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        v = float(str(value).strip())
    except (ValueError, TypeError):
        raise ValueError("INVALID_FINANCIAL_NUMBER") from None
    if not math.isfinite(v):
        raise ValueError("NONFINITE_FINANCIAL_NUMBER")
    return v


def div(a, b, *, require_positive=False):
    if a is None or b is None or b == 0 or (require_positive and b < 0):
        return None
    v = a / b
    return v if math.isfinite(v) else None


def sub(a, b):
    return a - b if a is not None and b is not None else None


def formatted(v):
    return "" if v is None else format(v, ".12g")


def finmind_panel(path):
    rows, digest = read_csv(path, FIELDNAMES)
    seen = set()
    facts = defaultdict(dict)
    failures = Counter()
    provenance = defaultdict(set)
    for r in rows:
        ticker = r["ticker"].strip()
        year = int(r["fiscal_year"])
        metric = r["candidate_mops_metric"].strip()
        if (not re.fullmatch(r"[0-9]{4}", ticker) or ticker == "1785"
                or not 2013 <= year <= 2025 or metric not in METRICS):
            raise ValueError("FINMIND_INVALID_COMPANY_YEAR_METRIC")
        key = ticker, year, metric
        if key in seen:
            raise ValueError("FINMIND_DUPLICATE_COMPANY_YEAR_METRIC")
        seen.add(key)
        if (r["training_admitted"].strip().lower() != "false" or
                r["publication_asof_verified"].strip().lower() != "false"
                or r["label_status"] != "UNREVIEWED"):
            raise ValueError("FINMIND_UNEXPECTED_SOURCE_ADMISSION")
        status = r["status"].strip()
        if status == "candidate_annual_value":
            v = as_num(r["candidate_annual_value"])
            if v is None or not re.fullmatch(r"[a-fA-F0-9]{64}", r["source_sha256"].strip()):
                raise ValueError("FINMIND_VALUE_OR_HASH_INVALID")
            facts[ticker, year][metric] = v
        elif status in ("empty_provider_response", "missing_december_value",
                        "missing_income_quarter", "archive_missing"):
            if str(r["candidate_annual_value"]).strip():
                raise ValueError("FINMIND_MISSING_STATUS_WITH_NONEMPTY_VALUE")
            failures[status] += 1
        else:
            raise ValueError("FINMIND_UNKNOWN_STATUS")
        provenance[ticker, r["source_family"]].add(r["source_sha256"].strip())
    if any(len(x) > 1 for x in provenance.values()):
        raise ValueError("FINMIND_INCONSISTENT_SOURCE_ARCHIVE_HASH")
    return facts, digest, dict(failures), len(seen)


def labels(path, kind):
    req = ({"ticker", "fiscal_year", "y", "target", "evidence_grade",
            "exploratory_label_only"} if kind == "silver" else
           {"ticker", "calendar_year", "y_tej_calendar_proxy", "split",
            "label_provenance", "feature_asof_date", "max_safe_annual_financial_fy",
            "y_official_annual_24m"} if kind == "tej_proxy" else
           {"ticker", "fiscal_year", "human_label", "review_status", "evidence_url"})
    rows, digest = read_csv(path, req)
    retained = {}
    excluded = Counter()
    for row in rows:
        ticker = row["ticker"].strip()
        if not re.fullmatch(r"[0-9]{4}", ticker) or ticker == "1785":
            excluded["NONFOURDIGIT_OR_HOLDOUT"] += 1
            continue
        year = int(row["calendar_year" if kind == "tej_proxy" else "fiscal_year"])
        if kind == "tej_proxy":
            expected = ("train" if 2016 <= year <= 2020 else
                        "validation" if 2021 <= year <= 2022 else
                        "test" if year == 2023 else None)
            if expected is None or row["split"] != expected:
                raise ValueError("PROXY_CHRONOLOGICAL_SPLIT_MISMATCH")
            if (row["label_provenance"] != ALLOWED_PROXY or
                    row["feature_asof_date"] != f"{year - 1}-12-31" or
                    row["max_safe_annual_financial_fy"] != str(year-2) or
                    row["y_official_annual_24m"].strip()):
                raise ValueError("PROXY_Y1_OR_ASOF_CONTAMINATION")
            value = row["y_tej_calendar_proxy"].strip()
            grade = ALLOWED_PROXY
        elif kind == "silver":
            if (row["target"] != ALLOWED_SILVER or
                    row["exploratory_label_only"].strip().lower() != "true"):
                raise ValueError("SILVER_TARGET_OR_GRADE_CHANGED")
            value = row["y"].strip()
            grade = row["evidence_grade"]
            expected = ("train" if year <= 2022 else
                        "validation" if year == 2023 else "test")
        else:
            if row["review_status"].strip().lower() not in ("reviewed", "approved"):
                excluded["HUMAN_UNREVIEWED"] += 1
                continue
            if not row["evidence_url"].strip().startswith("https://"):
                raise ValueError("HUMAN_REVIEWED_REQUIRES_EVIDENCE_URL")
            value = row["human_label"].strip()
            grade = "HUMAN_REVIEWED_NOT_INDEPENDENT_GOLD"
            expected = ("train" if year <= 2022 else
                        "validation" if year == 2023 else "test")
        if value not in ("0", "1"):
            if kind == "human" and value.upper() in ("UNKNOWN", ""):
                excluded["HUMAN_UNKNOWN"] += 1
                continue
            raise ValueError("INVALID_BINARY_LABEL")
        key = (ticker, year)
        if key in retained:
            raise ValueError("DUPLICATE_OR_CONFLICTING_Y_LABEL")
        retained[key] = {
            "ticker": ticker, "target_year": year, "label": int(value),
            "split": expected, "label_grade": grade,
            "x_fiscal_year": year - (2 if kind == "tej_proxy" else 1)
        }
    return retained, digest, dict(excluded), len(rows)


def x_metrics(current, previous):
    curr = lambda k: current.get(k)
    prev = lambda k: previous.get(k)
    assets = curr("total_assets")
    rev = curr("revenue")
    x = {
        "roa": div(curr("net_income"), assets, require_positive=True),
        "cfo_to_assets": div(curr("operating_cash_flow"), assets, require_positive=True),
        "debt_to_assets": div(curr("total_liabilities"), assets, require_positive=True),
        "current_ratio": div(curr("current_assets"), curr("current_liabilities"), require_positive=True),
        "gross_margin": div(curr("gross_profit"), rev, require_positive=True),
        "operating_margin": div(curr("operating_income"), rev, require_positive=True),
        "profit_cfo_gap_assets": div(sub(curr("net_income"), curr("operating_cash_flow")),
                                      assets, require_positive=True),
        "revenue_growth": div(sub(rev, prev("revenue")), prev("revenue"), require_positive=True),
        "inventory_growth": div(sub(curr("inventory"), prev("inventory")),
                                prev("inventory"), require_positive=True),
        "assets_growth": div(sub(assets, prev("total_assets")),
                             prev("total_assets"), require_positive=True),
        "gross_margin_delta": sub(
            div(curr("gross_profit"), rev, require_positive=True),
            div(prev("gross_profit"), prev("revenue"), require_positive=True)),
        "cfo_to_net_income": div(curr("operating_cash_flow"), curr("net_income"))
    }
    return {k: formatted(v) for k,v in x.items()}


def _save_csv(path, columns, rows):
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _save(path, buf.getvalue().encode("utf-8-sig"))


def _save(path, content):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.read_bytes() != content:
        raise FileExistsError("EXISTING_OUTPUT_DIFFERS_USE_NEW_OUT_DIRECTORY:" + str(p))
    if not p.exists():
        p.write_bytes(content)


def _scores(y_true, p, threshold):
    from sklearn.metrics import (confusion_matrix, f1_score, precision_score,
                                 recall_score, average_precision_score,
                                 roc_auc_score)
    predicted = [int(z >= threshold) for z in p]
    vals = Counter(y_true)
    both = vals[0] > 0 and vals[1] > 0
    cm = confusion_matrix(y_true, predicted, labels=[0,1])
    order = sorted(range(len(p)), key=lambda i:p[i], reverse=True)
    k = min(20, len(order))
    return {
        "sample_count": len(y_true), "positives": vals[1], "negatives": vals[0],
        "threshold": threshold,
        "precision": precision_score(y_true, predicted, zero_division=0),
        "recall": recall_score(y_true, predicted, zero_division=0),
        "f1": f1_score(y_true, predicted, zero_division=0),
        "pr_auc_average_precision": (average_precision_score(y_true, p) if both else None),
        "roc_auc": (roc_auc_score(y_true,p) if both else None),
        "precision_at_20_or_less": sum(y_true[i] for i in order[:k]) / k if k else None,
        "confusion_tn_fp_fn_tp": [int(cm[0,0]), int(cm[0,1]), int(cm[1,0]), int(cm[1,1])],
        "metrics_have_both_classes": both
    }


def fit_models(data, label_kind):
    result = {"status":"NOT_RUN", "models":[], "selection":"validation PR-AUC, never holdout",
              "warning":"Retrospective provisional FinMind values; NOT a validated historical early-warning model."}
    buckets = {k:[r for r in data if r["split"]==k] for k in ("train","validation","test")}
    trains = buckets["train"]
    if (len(trains)<TRAIN_MIN or
        sum(r["label"]=="1" for r in trains)<TRAIN_POS_MIN or
        sum(r["label"]=="0" for r in trains)<TRAIN_NEG_MIN):
        result.update(status="BLOCKED_TRAIN_CLASS_COUNTS",
                      reason="Need >=8 matched training rows, >=2 positive and >=2 negative.")
        return result
    if not buckets["validation"]:
        result.update(status="BLOCKED_NO_VALIDATION_ROWS")
        return result
    try:
        import numpy as np
        from sklearn.compose import ColumnTransformer
        from sklearn.dummy import DummyClassifier
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
    except ImportError as error:
        result.update(status="DEPENDENCY_NOT_INSTALLED", detail=type(error).__name__)
        return result
    # Select available columns on TRAIN ONLY. Validation and test cannot
    # influence feature choice, medians, scaling, fit or threshold.
    fields = [f for f in FEATURES if any(r[f].strip() for r in trains)]
    if len(fields)<4:
        result.update(status="BLOCKED_FEW_USABLE_FINANCIAL_FEATURES",
                      available_train_feature_count=len(fields))
        return result
    def values(rows):
        return np.array([[as_num(r[f]) if r[f].strip() else np.nan for f in fields]
                         for r in rows],dtype=float)
    def targets(rows):
        return np.array([int(r["label"]) for r in rows],dtype=int)
    def pipeline(estimator,scale):
        steps=[("fill",SimpleImputer(strategy="median",add_indicator=False))]
        if scale:
            steps.append(("scale",StandardScaler()))
        steps.append(("classifier",estimator))
        return Pipeline(steps)
    estimators=[
        ("dummy",pipeline(DummyClassifier(strategy="prior"),False)),
        ("logistic_regression",pipeline(LogisticRegression(max_iter=2000,class_weight="balanced",random_state=42),True)),
        ("random_forest",pipeline(RandomForestClassifier(n_estimators=200,min_samples_leaf=2,class_weight="balanced_subsample",random_state=42,n_jobs=1),False)),
    ]
    try:
        from catboost import CatBoostClassifier
        estimators.append(("catboost",pipeline(
            CatBoostClassifier(iterations=250,depth=4,learning_rate=.04,verbose=False,
                               auto_class_weights="Balanced",random_seed=42,thread_count=1),False)))
    except ImportError:
        result["catboost_status"] = "OPTIONAL_DEPENDENCY_MISSING"
    arr = {s:values(rows) for s,rows in buckets.items()}
    yt = {s:targets(rows) for s,rows in buckets.items()}
    result["features_selected_using_training_only"] = fields
    result["split_counts"] = {s:{"rows":len(buckets[s]),"positive":int(yt[s].sum())}
                              for s in buckets}
    for name, model in estimators:
        try:
            model.fit(arr["train"],yt["train"])
            pval = model.predict_proba(arr["validation"])[:,1].tolist()
            # Fixed neutral threshold 0.5; no test-based optimization.
            validation = _scores(yt["validation"].tolist(),pval,.5)
            out = {"model":name,"status":"FITTED","validation":validation}
            if buckets["test"]:
                ptest = model.predict_proba(arr["test"])[:,1].tolist()
                out["test"] = _scores(yt["test"].tolist(),ptest,.5)
            result["models"].append(out)
        except (ValueError, FloatingPointError) as exc:
            result["models"].append({"model":name,"status":"FIT_ERROR",
                                    "exception_type":type(exc).__name__,
                                    "message":str(exc)[:180]})
    trained=[r for r in result["models"] if r["status"]=="FITTED"]
    result["status"]="FITTED_RETROSPECTIVE_RESEARCH_ONLY" if trained else "NO_MODELS_FITTED"
    if len(buckets["validation"])<30:
        result["sample_warning"]="Validation n<30, conclusions unstable."
    if len(buckets["test"])<30:
        result["test_warning"]="Test n<30, generalization cannot be claimed."
    if trained and all(x["validation"]["metrics_have_both_classes"] for x in trained):
        best=max(trained,key=lambda d:d["validation"]["pr_auc_average_precision"])
        result["validation_selected_model"]=best["model"]
    else:
        result["selection_blocker"]="Validation needs both classes for PR-AUC model selection."
    return result



# Public MOPS all-market CSV comes from the EXISTING public_mops_bulk_annual_panel.py.
# Financial institutions with other statement schemas are not substituted with
# the generic annual features. All provenance remains retrospective.
MOPS_REQUIRED = {
    "ticker","financial_fy","period_end","sector_schema",
    "source_income_sha256","source_balance_sha256","source_cashflow_sha256",
    "revenue","cogs","operating_income","net_income","assets",
    "current_assets","current_liabilities","liabilities","cfo"
}
MOPS_SOURCES = {
    "income":("revenue","cogs","operating_income","net_income"),
    "balance":("assets","current_assets","current_liabilities","liabilities"),
    "cashflow":("cfo",)
}

def finmind_union(paths):
    """Reconcile existing provider exports; contradictory duplicates become missing."""
    path_list=[] if paths is None else ([paths] if isinstance(paths,(str,Path)) else list(paths))
    if not path_list:
        return defaultdict(dict),[],{}
    merged=defaultdict(dict)
    source_info=[]
    collisions=Counter()
    quarantined=set()
    for path in path_list:
        part,digest,failures,cells=finmind_panel(path)
        source_info.append({"filename":Path(path).name, "sha256":digest,
                            "candidate_cells":cells,"missing_status_counts":failures})
        for key,items in part.items():
            for metric,value in items.items():
                marker=(*key,metric)
                if marker in quarantined:
                    continue
                prior=merged[key].get(metric)
                if prior is not None and not math.isclose(prior,value,rel_tol=1e-10,abs_tol=1e-8):
                    quarantined.add(marker)
                    del merged[key][metric]
                    collisions["CONFLICTING_PROVIDER_DUPLICATE_METRIC"]+=1
                else:
                    merged[key][metric]=value
    return merged,source_info,dict(collisions)


def mops_panel(path):
    """Read existing public, all-market nonfinancial statement SUMMARY CSV."""
    if not path:
        return {},None,{}
    rows,digest=read_csv(path,MOPS_REQUIRED)
    output={}
    rejected=Counter()
    for row in rows:
        ticker=row["ticker"].strip()
        fy=int(row["financial_fy"])
        if ticker=="1785":
            rejected["RESERVED_HOLDOUT"]+=1
            continue
        if not re.fullmatch(r"[0-9]{4}",ticker) or not 2013<=fy<=2025:
            rejected["INVALID_TICKER_OR_FY"]+=1
            continue
        if row["sector_schema"]!="general_summary":
            rejected["NON_GENERAL_FINANCIAL_STATEMENT_SCHEMA"]+=1
            continue
        if row["period_end"]!=f"{fy}-12-31":
            rejected["INVALID_FINANCIAL_PERIOD"]+=1
            continue
        key=(ticker,fy)
        if key in output:
            # Reject conflicting cross-market duplicate issuers instead of selecting one.
            output[key]=None
            rejected["DUPLICATE_COMPANY_FY"]+=1
            continue
        facts={}
        mapping={
            "revenue":"revenue",
            "cost_of_goods_sold":"cogs",
            "operating_income":"operating_income",
            "net_income":"net_income",
            "total_assets":"assets",
            "current_assets":"current_assets",
            "current_liabilities":"current_liabilities",
            "total_liabilities":"liabilities",
            "operating_cash_flow":"cfo"
        }
        for family,cols in MOPS_SOURCES.items():
            sha=row[f"source_{family}_sha256"].strip()
            if any(str(row[v]).strip() for v in cols):
                if not re.fullmatch(r"[A-Fa-f0-9]{64}",sha):
                    raise ValueError("MOPS_FINANCIAL_FACT_WITHOUT_ARCHIVE_SHA")
        for dest,src in mapping.items():
            val=as_num(row[src])
            if val is not None:
                facts[dest]=val
        if "revenue" in facts and "cost_of_goods_sold" in facts:
            facts["gross_profit"]=facts["revenue"]-facts["cost_of_goods_sold"]
        output[key]=facts
    return {k:v for k,v in output.items() if v is not None}, {
        "filename":Path(path).name,"sha256":digest,
        "rows":len(rows),"usable_company_fy":sum(v is not None and bool(v) for v in output.values())
    },dict(rejected)


def choose_financial_pair(ticker,current_fy,finmind,mops):
    """Use one consistent provider for BOTH current and previous annual FY.
    Never form a growth ratio from two different providers' amount series.
    Prefer the pair with most usable features. Ties prefer official public summary.
    """
    options=[]
    for source,archive in (("public_mops_retrospective",mops),
                           ("finmind_provisional",finmind)):
        cur=archive.get((ticker,current_fy),{})
        prev=archive.get((ticker,current_fy-1),{})
        if not cur:
            continue
        xs=x_metrics(cur,prev)
        available=sum(bool(v) for v in xs.values())
        score=(available, 1 if source=="public_mops_retrospective" else 0)
        options.append((score,source,cur,prev,xs))
    if not options:
        return None
    _,source,cur,prev,xs=max(options,key=lambda x:x[0])
    return source,cur,prev,xs

def build(annual_lines, labels_csv, label_kind, out, *, train=True, mops_annual=None):
    if label_kind not in ("silver","tej_proxy","human"):
        raise ValueError("UNSUPPORTED_LABEL_KIND")
    financial, finmind_inputs, provider_conflicts = finmind_union(annual_lines)
    public_mops, mops_input, mops_rejected = mops_panel(mops_annual)
    fhash=finmind_inputs[0]["sha256"] if len(finmind_inputs)==1 else None
    status_counts=dict(sum((Counter(x["missing_status_counts"]) for x in finmind_inputs),Counter()))
    source_cells=sum(x["candidate_cells"] for x in finmind_inputs)
    outcomes, yhash, skipped_labels, raw_labels = labels(labels_csv,label_kind)
    rows = []
    omissions = Counter()
    annual = defaultdict(Counter)
    splits=defaultdict(Counter)
    for (ticker,year),y in sorted(outcomes.items(),key=lambda k:(k[0][1],k[0][0])):
        fy=y["x_fiscal_year"]
        selected=choose_financial_pair(ticker,fy,financial,public_mops)
        if selected is None:
            omissions["X_FY_MISSING_OR_ALL_EMPTY"] += 1
            annual[year]["x_not_found"] += 1
            continue
        source_x,current,previous,xs=selected
        n=sum(bool(v) for v in xs.values())
        if n<4:
            omissions["FEWER_THAN_4_FEATURES"] += 1
            annual[year]["too_few_x"] += 1
            continue
        row = {
            "ticker":ticker,"target_year":str(year),"x_fiscal_year":str(fy),
            "prior_x_fiscal_year":str(fy-1),"label_kind":label_kind,
            "label_grade":y["label_grade"],"label":str(y["label"]),
            "split":y["split"],"source_x_present_count":str(len(current)),
            "source_x_prior_present_count":str(len(previous)),
            "available_feature_count":str(n),"x_retrospective_only":"true",
            "source_x":source_x,**xs}
        rows.append(row)
        annual[year]["joined"]+=1
        annual[year]["positive"]+=y["label"]
        splits[y["split"]]["joined"]+=1
        splits[y["split"]]["positive"]+=y["label"]
    outpath=Path(out)
    _save_csv(outpath/"finlab_finmind_xy_private.csv",MODEL_COLS,rows)
    result={
        "schema":"fintrust_existing_finmind_binary_research_v1",
        "research_target":label_kind,
        "target_definition":(ALLOWED_PROXY if label_kind=="tej_proxy" else
                             ALLOWED_SILVER if label_kind=="silver" else
                             "HUMAN_REVIEWED_SOURCE_ATTESTED_NOT_GOLD"),
        "source_sha256":{"finmind_annual_lines":fhash,"labels":yhash,
                         "mops_annual":mops_input["sha256"] if mops_input else None},
        "finmind_inputs":finmind_inputs,
        "finmind_reconciled_company_fy":len(financial),
        "finmind_conflicting_repeated_values":provider_conflicts,
        "public_mops_input":mops_input,
        "public_mops_rejected":mops_rejected,
        "matched_source_counts":dict(Counter(r["source_x"] for r in rows)),
        "finmind_source_candidate_cells":source_cells,
        "finmind_source_status_counts":status_counts,
        "label_input_rows":raw_labels,
        "valid_label_rows":len(outcomes),
        "label_exclusion_counts":skipped_labels,
        "matched_feature_rows":len(rows),
        "matched_class_counts":{"positive":sum(r["label"]=="1" for r in rows),
                                "negative":sum(r["label"]=="0" for r in rows)},
        "unmatched_reasons":dict(omissions),
        "by_target_year":{str(y):{"joined":s["joined"],"positive":s["positive"],
                                   "negative":s["joined"]-s["positive"],
                                   "x_not_found":s["x_not_found"],
                                   "too_few_x":s["too_few_x"]} for y,s in sorted(annual.items())},
        "by_split":{s:{"joined":splits[s]["joined"],
                       "positive":splits[s]["positive"],
                       "negative":splits[s]["joined"]-splits[s]["positive"]}
                    for s in ("train","validation","test")},
        "feature_nonmissing":{f:sum(bool(r[f]) for r in rows) for f in FEATURES},
        "feature_fields":list(FEATURES),
        "label_outcome_fields_never_used_as_features":True,
        "period_rule":("CY(t) uses FinMind FY(t-2) and FY(t-3)" if label_kind=="tej_proxy"
                       else "affected FY(t) uses FinMind FY(t-1) and FY(t-2)"),
        "all_x_publication_vintages_independently_verified":False,
        "official_verified_y1":False,
        "reserved_1785_excluded":True,
        "network_requests":0,"production_writes":0,
        "limitations":[
            "FinMind annual period calculations are candidate mappings, not certified PIT vintages.",
            "Provider may expose post-restatement values: retrospective correlation, not as-filed early warning.",
            "TEJ proxy Y2 != affected-year major financial restatement, and Y2=0 != verified normal.",
            "FinLab keyword candidates are UNKNOWN until individually reviewed; not imported as 0/1.",
            "Silver negatives are secondary-source convenience controls, not officially audited clean companies.",
            "No train/test company disjointness: issuer may occur across multiple years; report temporal holdout only.",
        ]
    }
    result["training"]=fit_models(rows,label_kind) if train else {"status":"DISABLED"}
    payload=(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode("utf-8")
    _save(outpath/"finlab_finmind_binary_report.json",payload)
    return result


def make_review_template(finlab_cases, out):
    rows, source_hash=read_csv(finlab_cases,{"ticker","fiscal_year","case_id","rank",
                                             "mops_notice_url","original_financial_filing_url"})
    col=("case_id","ticker","fiscal_year","rank","mops_notice_url",
         "original_financial_filing_url","human_label","review_status","evidence_url",
         "reviewer_notes")
    seen=set()
    target=[]
    for r in rows:
        key=(r["ticker"].strip(),r["fiscal_year"].strip())
        if key in seen:
            raise ValueError("DUPLICATE_FINLAB_REVIEW_CASE_FY")
        seen.add(key)
        if key[0]=="1785":
            continue
        target.append({**{f:r.get(f,"") for f in col},
                       "human_label":"UNKNOWN","review_status":"pending",
                       "evidence_url":"","reviewer_notes":""})
    _save_csv(Path(out)/"finlab_human_review_private.csv",col,target)
    report={"review_candidates":len(target),"source_sha256":source_hash,
            "approved_labels":0,"warning":"Review template only. Never automatically label 0/1."}
    _save(Path(out)/"finlab_human_review_summary.json",
          (json.dumps(report,ensure_ascii=False,indent=2)+"\n").encode("utf-8"))
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--annual-lines",action="append",help="Existing FinMind provisional annual line CSV; repeat for all existing exports")
    p.add_argument("--mops-annual",help="Previously archived all-market public MOPS annual financial features CSV")
    p.add_argument("--labels",help="Existing research labels CSV")
    p.add_argument("--label-kind",choices=("silver","tej_proxy","human"),default="silver")
    p.add_argument("--finlab-cases",help="Optional existing FinLab case CSV to create human review template")
    p.add_argument("--out",required=True)
    p.add_argument("--no-train",action="store_true")
    args=p.parse_args(argv)
    if args.finlab_cases and not args.annual_lines and not args.labels:
        result=make_review_template(args.finlab_cases,args.out)
    elif (args.annual_lines or args.mops_annual) and args.labels:
        result=build(args.annual_lines,args.labels,args.label_kind,args.out,
                     train=not args.no_train,mops_annual=args.mops_annual)
    else:
        p.error("Provide --labels and at least one X source (--annual-lines/--mops-annual), OR only --finlab-cases")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
