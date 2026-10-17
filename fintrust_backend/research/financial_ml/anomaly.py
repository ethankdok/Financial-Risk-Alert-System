"""Normal-reference-only financial anomaly detection; isolated offline research.

No labels are inferred from lack of a restatement. No fraud label enters training,
threshold selection, feature selection, or preprocessing. Non-case scores are
out-of-time; a reserved case is separately scored and never used for fitting.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, date, timezone
from pathlib import Path

from .pilot import FEATURES, _date

NORMAL_COLUMNS = {"ticker", "fiscal_year", "review_status", "review_source", "reviewed_at", "followup_through"}
MODEL_KINDS = ("isolation_forest", "mlp_autoencoder")
META = {"ticker", "fiscal_year", "filing_version_id", "filing_version_type", "accounting_framework",
        "analysis_mode", "label", "label_source", "outcome_known_at"}


def _csv_rows(path):
    with Path(path).open(newline="", encoding="utf-8-sig") as fp:
        rd = csv.DictReader(fp)
        return list(rd), set(rd.fieldnames or [])


def read_dataset(path):
    rows, headers = _csv_rows(path)
    needed = META | set(FEATURES)
    if missing := needed - headers:
        raise ValueError(f"ML_DATASET_SCHEMA_MISSING: {sorted(missing)}")
    seen = set()
    modes = set()
    for row in rows:
        key = (row["ticker"].strip(), int(row["fiscal_year"]))
        if key in seen:
            raise ValueError(f"DUPLICATE_COMPANY_YEAR: {key}")
        seen.add(key)
        if row["analysis_mode"] not in {"strict", "retrospective"}:
            raise ValueError(f"UNRECOGNIZED_ANALYSIS_MODE: {key}")
        modes.add(row["analysis_mode"])
        for feat in FEATURES:
            v = row[feat]
            if v:
                try:
                    if not math.isfinite(float(v)):
                        raise ValueError
                except (ValueError, OverflowError):
                    raise ValueError(f"INVALID_FINITE_FEATURE: {key} {feat}") from None
        if row["label"] and row["label"] not in {"0", "1"}:
            raise ValueError(f"INVALID_OPTIONAL_LABEL: {key}")
        if row["label"] in {"0", "1"}:
            if not row["label_source"] or not row["outcome_known_at"]:
                raise ValueError(f"LABEL_SOURCE_REQUIRED: {key}")
            _date(row["outcome_known_at"])
    if len(modes) > 1:
        raise ValueError("MIXED_ANALYSIS_MODES: separate strict and retrospective experiments")
    return rows, next(iter(modes), "unknown")


def read_normal_ledger(path, *, min_followup_years=2, reviewed_by=None):
    rows, headers = _csv_rows(path)
    if missing := NORMAL_COLUMNS - headers:
        raise ValueError(f"NORMAL_LEDGER_SCHEMA_MISSING: {sorted(missing)}")
    result = {}
    if min_followup_years < 0:
        raise ValueError("MIN_FOLLOWUP_YEARS_MUST_BE_NONNEGATIVE")
    gate = _date(reviewed_by) if reviewed_by else None
    for row in rows:
        key = (row["ticker"].strip(), int(row["fiscal_year"]))
        if key in result:
            raise ValueError(f"DUPLICATE_NORMAL_LEDGER: {key}")
        status = row["review_status"].strip()
        if status not in {"reviewed_normal", "excluded", "unreviewed", "suspected"}:
            raise ValueError(f"INVALID_NORMAL_STATUS: {key}")
        if status == "reviewed_normal":
            if not row["review_source"].strip() or not row["reviewed_at"].strip() or not row["followup_through"].strip():
                raise ValueError(f"INCOMPLETE_NORMAL_REVIEW: {key}")
            reviewed = _date(row["reviewed_at"])
            followup = date.fromisoformat(row["followup_through"])
            if followup < date(key[1] + min_followup_years, 12, 31):
                raise ValueError(f"INSUFFICIENT_FOLLOWUP: {key}")
            if followup > reviewed.date():
                raise ValueError(f"REVIEW_PRECEDES_FOLLOWUP: {key}")
            if gate and reviewed > gate:
                # Labels determined too late for the chosen research reconstruction date are NOT fit-eligible.
                status = "unreviewed"
        result[key] = {"status": status, "source": row["review_source"].strip()}
    return result


def audit(dataset, output):
    rows, mode = read_dataset(dataset)
    count = Counter()
    missing = Counter()
    for r in rows:
        year = int(r["fiscal_year"])
        count[year] += 1
        for f in FEATURES:
            if not r[f]:
                missing[f] += 1
    payload = {
        "status": "research_dataset_inventory_only", "analysis_mode": mode, "rows": len(rows),
        "companies": len({r["ticker"] for r in rows}), "by_year": dict(sorted(count.items())),
        "candidate_features": list(FEATURES), "missing_by_feature": dict(sorted(missing.items())),
        "labelled_rows": sum(r["label"] in {"0", "1"} for r in rows),
        "warning": "No row is assumed normal from the absence of a restatement; training requires a reviewed normal ledger",
    }
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    (out / "anomaly_readiness.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def scaffold_ledger(dataset, output):
    rows, _ = read_dataset(dataset)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["ticker", "fiscal_year", "review_status", "review_source", "reviewed_at", "followup_through"])
        for row in sorted(rows, key=lambda r: (r["ticker"], int(r["fiscal_year"]))):
            w.writerow([row["ticker"], row["fiscal_year"], "unreviewed", "", "", ""])
    return {"status": "review_required", "candidates": len(rows), "path": str(target), "reviewed_normal": 0}


def _split(rows, ledger, *, train_through, val_from, val_through, test_from,
           split_policy, seed, reserved_ticker):
    if not (train_through < val_from <= val_through < test_from):
        raise ValueError("CHRONOLOGY_REQUIRED: train_through < val_from <= val_through < test_from")
    train, val, test, case = [], [], [], []
    reasons = Counter()
    def group(ticker):
        value = int(hashlib.sha256(f"{seed}:{ticker}".encode()).hexdigest()[:12], 16) / float(0xffffffffffff)
        if value < 0.7:
            return "train"
        if value < 0.85:
            return "val"
        return "test"
    for row in rows:
        ticker, yr = row["ticker"].strip(), int(row["fiscal_year"])
        if ticker == reserved_ticker:
            case.append(row)
            continue
        normal = ledger.get((ticker, yr), {}).get("status") == "reviewed_normal"
        # A known positive cannot ever become a 'normal' reference even if the ledger is inconsistent.
        if row["label"] == "1" and normal:
            raise ValueError(f"CONTRADICTORY_POSITIVE_AND_NORMAL_LEDGER: {ticker} {yr}")
        bucket = group(ticker) if split_policy == "company_disjoint" else None
        if yr <= train_through:
            if not normal:
                reasons["train_not_reviewed_normal"] += 1
            elif bucket is None or bucket == "train":
                train.append(row)
            else:
                reasons["train_group_withheld"] += 1
        elif val_from <= yr <= val_through:
            if not normal:
                reasons["val_not_reviewed_normal"] += 1
            elif bucket is None or bucket == "val":
                val.append(row)
            else:
                reasons["val_group_withheld"] += 1
        elif yr >= test_from:
            if bucket is None or bucket == "test":
                test.append(row)
            else:
                reasons["test_group_withheld"] += 1
        else:
            reasons["between_windows"] += 1
    assert not ({(r["ticker"], r["fiscal_year"]) for r in train} & {(r["ticker"], r["fiscal_year"]) for r in test})
    if split_policy == "company_disjoint":
        a,b,c = ({r["ticker"] for r in group_rows} for group_rows in (train,val,test))
        assert not (a & b or a & c or b & c)
    return train, val, test, case, dict(sorted(reasons.items()))


def train(dataset, ledger_path, output, *, train_through, val_from, val_through, test_from,
          model_kind="isolation_forest", split_policy="temporal", reserved_ticker="1785",
          seed=42, quantile=0.95, min_train=30, min_val=10, min_companies=5,
          min_followup_years=2, reviewed_by=None):
    if model_kind not in MODEL_KINDS:
        raise ValueError(f"UNKNOWN_MODEL: {model_kind}")
    if split_policy not in {"temporal", "company_disjoint"}:
        raise ValueError("UNKNOWN_SPLIT_POLICY")
    if not 0.5 <= quantile < 1:
        raise ValueError("THRESHOLD_QUANTILE_OUT_OF_RANGE")
    rows, mode = read_dataset(dataset)
    ledger = read_normal_ledger(ledger_path, min_followup_years=min_followup_years, reviewed_by=reviewed_by)
    train_rows, val_rows, test_rows, case_rows, rejections = _split(
        rows, ledger, train_through=train_through, val_from=val_from,
        val_through=val_through, test_from=test_from, split_policy=split_policy,
        seed=seed, reserved_ticker=reserved_ticker)
    if len(train_rows) < min_train or len(val_rows) < min_val or len({r["ticker"] for r in train_rows}) < min_companies:
        raise ValueError("NORMAL_REFERENCE_INSUFFICIENT: train={} from {} companies, validation={}; need train>={}, companies>={}, val>={}".format(
            len(train_rows),len({r['ticker'] for r in train_rows}),len(val_rows),min_train,min_companies,min_val))
    if not test_rows and not case_rows:
        raise ValueError("NO_TEST_OR_CASE_ROWS")

    import numpy as np
    from sklearn.ensemble import IsolationForest
    from sklearn.impute import SimpleImputer
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import RobustScaler
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support, average_precision_score, confusion_matrix

    def arr(batch):
        return np.array([[float(r[f]) if r[f] else np.nan for f in FEATURES] for r in batch], dtype=float).reshape(len(batch),len(FEATURES))
    Xraw = arr(train_rows)
    feature_indices = [i for i in range(len(FEATURES)) if np.isfinite(Xraw[:,i]).sum() >= max(3, math.ceil(0.5*len(train_rows)))]
    if len(feature_indices) < 2:
        raise ValueError("NOT_ENOUGH_OBSERVED_FINANCIAL_FEATURES_IN_TRAIN")
    features = [FEATURES[i] for i in feature_indices]
    imputer = SimpleImputer(strategy="median")
    scaler = RobustScaler()
    train_imp = imputer.fit_transform(Xraw[:,feature_indices]); X = scaler.fit_transform(train_imp)
    def transform(batch):
        if not batch:
            return np.empty((0,len(features)),dtype=float)
        return scaler.transform(imputer.transform(arr(batch)[:,feature_indices]))
    V = transform(val_rows); T = transform(test_rows); C = transform(case_rows)
    if model_kind == "isolation_forest":
        model = IsolationForest(n_estimators=300, contamination="auto", random_state=seed, n_jobs=-1)
        model.fit(X)
        score = lambda xx: -model.score_samples(xx) if len(xx) else np.array([])
    else:
        hidden=max(4,min(16,len(features)))
        model=MLPRegressor(hidden_layer_sizes=(hidden, max(2,hidden//2),hidden), activation="tanh",
                           solver="adam", alpha=0.05, learning_rate_init=0.0005,
                           max_iter=1000, early_stopping=True, validation_fraction=0.2,
                           n_iter_no_change=30, random_state=seed)
        model.fit(X, X)
        score=lambda xx: np.mean((model.predict(xx)-xx)**2,axis=1) if len(xx) else np.array([])
    vs=score(V)
    # No positives or case rows ever influence threshold selection.
    threshold=float(np.quantile(vs,quantile))
    def output_rows(batch, xx):
        scores=score(xx)
        return [dict(ticker=r["ticker"],fiscal_year=int(r["fiscal_year"]),
                     analysis_mode=r["analysis_mode"],filing_version_type=r["filing_version_type"],
                     label=r["label"],label_source=r["label_source"],
                     anomaly_score=float(s),threshold=threshold,flagged=int(s>threshold))
                for r,s in zip(batch,scores)]
    predictions=output_rows(test_rows,T)
    case_predictions=output_rows(case_rows,C)
    evaluated=[r for r in predictions if r["label"] in {"0","1"}]
    metrics={"labeled_test_samples":len(evaluated),"positive_test_samples":sum(r["label"]=="1" for r in evaluated)}
    if len(evaluated)>0 and len({r["label"] for r in evaluated})==2:
        y=[int(r["label"]) for r in evaluated]
        yhat=[r["flagged"] for r in evaluated]
        precision,recall,f1,_=precision_recall_fscore_support(y,yhat,average="binary",zero_division=0)
        metrics.update(accuracy=float(accuracy_score(y,yhat)),precision_positive=float(precision),
                       recall_positive=float(recall),f1_positive=float(f1),
                       average_precision=float(average_precision_score(y,[r["anomaly_score"] for r in evaluated])),
                       confusion_matrix_0_1=confusion_matrix(y,yhat,labels=[0,1]).tolist(),
                       evaluation_status="both_classes_available")
    else:
        metrics["evaluation_status"]="not_computable_without_both_independently_labeled_classes"
    report={"status":"normal_reference_model_trained", "model":model_kind,"analysis_mode":mode,
            "retrospective_only":mode!="strict" or reviewed_by is None,
            "training_class":"reviewed_normal_only", "normal_ledger":str(ledger_path),
            "train_rows":len(train_rows),"validation_normal_rows":len(val_rows),"test_rows":len(test_rows),
            "held_out_case_rows":len(case_rows),"train_companies":len({r['ticker'] for r in train_rows}),
            "validation_companies":len({r['ticker'] for r in val_rows}),
            "test_companies":len({r['ticker'] for r in test_rows}),
            "train_through":train_through,"val_window":[val_from,val_through],"test_from":test_from,
            "split_policy":split_policy,"reserved_ticker":reserved_ticker,
            "selected_features":features,"fit_missing_values_only_in_training":True,
            "threshold_source":"normal_validation_quantile_only","threshold_quantile":quantile,
            "threshold":threshold,"expected_normal_false_positive_rate_approx":1-quantile,
            "reviewed_by":reviewed_by,"min_followup_years":min_followup_years,
            "reject_counts":rejections,"test_metrics":metrics,
            "warnings":["Absence of a sanction does not prove normality: reviewed cohort is a conditional reference population.",
                       "Chronological split alone may retain company identity across years; run company_disjoint as an additional robustness study.",
                       "The reserved case is never fitted or threshold-tuned; retrospective/restated case scores are NOT ex-ante predictions.",
                       "F1/accuracy are reported only for an independently labeled test subset containing both classes."]}
    dest=Path(output);dest.mkdir(parents=True,exist_ok=True)
    (dest/"anomaly_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for name,batch in [("anomaly_test_scores.csv",predictions),("anomaly_reserved_case_scores.csv",case_predictions)]:
        with (dest/name).open("w",encoding="utf-8",newline="") as fh:
            writer=csv.DictWriter(fh,fieldnames=["ticker","fiscal_year","analysis_mode","filing_version_type","label","label_source","anomaly_score","threshold","flagged"])
            writer.writeheader();writer.writerows(batch)
    return report


def main(argv=None):
    parser=argparse.ArgumentParser(description="Financial ML normal-only anomaly research; no DB writes")
    actions=parser.add_subparsers(dest="command",required=True)
    a=actions.add_parser("audit",help="Inspect candidate dataset without assuming normal labels")
    a.add_argument("--dataset",required=True);a.add_argument("--output",required=True)
    b=actions.add_parser("scaffold-ledger",help="Write UNREVIEWED cohort candidates for manual/official evidence review")
    b.add_argument("--dataset",required=True);b.add_argument("--output",required=True)
    t=actions.add_parser("train",help="Train normal-only model; validation normals set anomaly threshold")
    t.add_argument("--dataset",required=True);t.add_argument("--normal-ledger",required=True);t.add_argument("--output",required=True)
    t.add_argument("--train-through",type=int,required=True);t.add_argument("--val-from",type=int,required=True)
    t.add_argument("--val-through",type=int,required=True);t.add_argument("--test-from",type=int,required=True)
    t.add_argument("--model",choices=MODEL_KINDS,default="isolation_forest")
    t.add_argument("--split-policy",choices=["temporal","company_disjoint"],default="temporal")
    t.add_argument("--reserve-ticker",default="1785");t.add_argument("--seed",type=int,default=42)
    t.add_argument("--quantile",type=float,default=0.95);t.add_argument("--min-train",type=int,default=30)
    t.add_argument("--min-val",type=int,default=10);t.add_argument("--min-companies",type=int,default=5)
    t.add_argument("--min-followup-years",type=int,default=2)
    t.add_argument("--reviewed-by",help="ISO timestamp; prevent using retrospectively reviewed normals in an earlier research reconstruction")
    args=parser.parse_args(argv)
    if args.command=="audit":
        result=audit(args.dataset,args.output)
    elif args.command=="scaffold-ledger":
        result=scaffold_ledger(args.dataset,args.output)
    else:
        result=train(args.dataset,args.normal_ledger,args.output,
                     train_through=args.train_through,val_from=args.val_from,val_through=args.val_through,
                     test_from=args.test_from,model_kind=args.model,split_policy=args.split_policy,
                     reserved_ticker=args.reserve_ticker,seed=args.seed,quantile=args.quantile,
                     min_train=args.min_train,min_val=args.min_val,min_companies=args.min_companies,
                     min_followup_years=args.min_followup_years,reviewed_by=args.reviewed_by)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())