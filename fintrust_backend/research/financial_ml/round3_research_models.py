"""Round3: source-gated real-data numeric prediction and UNLABELED novelty benchmark.

Classification precision/recall/F1/PR-AUC are deliberately unavailable when
verified fraud and reviewed healthy labels are both zero. Reuses Phase5
temporal model families and Round1 selected XBRL fields, without new downloads.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

from .annual_panel_readiness import METRICS
from .final_round1_dataset_integration import (
    QUARTER_FEATURE_DICTIONARY, QUARTER_MATRIX_BASE, ANNUAL_COLUMNS,
)
from .phase4_taiwan_dataset_gate import issuer_partition, temporal_partition
from .provisional_sequence_experiment import (
    samples_for_next_year, time_partition, prepare_scaled, fit_model,
)
from .round2_evidence_review import read_csv, write_csv, require_unknown, require_unapproved

ANNUAL_MODELS = ("persistence", "ridge", "random_forest", "mlp", "catboost",
                 "gru", "lstm", "tcn", "transformer")
QUARTER_MODELS = ("isolation_forest", "lof_novelty", "one_class_svm",
                  "pca_reconstruction")
ANNUAL_MODEL_FIELDS = (
    "model", "status", "reason", "fit_company_year_windows",
    "validation_company_year_windows", "holdout_company_year_windows",
    "validation_scaled_mse", "holdout_scaled_mse",
    "validation_scaled_rmse", "holdout_scaled_rmse",
    "validation_scaled_mae", "holdout_scaled_mae",
    "validation_scaled_r2", "holdout_scaled_r2",
    "validation_signed_log_mae", "holdout_signed_log_mae",
    "validation_twd_mae", "holdout_twd_mae",
    "validation_smape", "holdout_smape",
    "fit_epochs", "backend", "outcome_label",
)
PER_FEATURE_FIELDS = ("model", "metric", "split", "n_company_years",
                      "signed_log_mae", "twd_mae", "smape")
QUARTER_MODEL_FIELDS = (
    "model", "fit_quarters", "validation_quarters", "test_quarters",
    "fit_issuers", "validation_issuers", "test_issuers",
    "training_score_p95", "validation_anomaly_fraction_above_fit_p95",
    "test_anomaly_fraction_above_fit_p95",
    "validation_score_median", "test_score_median",
    "validation_score_ks_from_fit", "test_score_ks_from_fit",
    "validation_score_jsd_from_fit", "test_score_jsd_from_fit",
    "independent_verified_labels",
)
QUARTER_SCORE_FIELDS = ("model", "ticker", "reporting_period",
                        "joint_strict_split", "observed_selected_feature_count",
                        "anomaly_proxy_score", "above_fit_score_p95",
                        "verified_fraud_label", "interpretation")
SOURCE_MAP = {
    "FINMIND_PROVISIONAL_ANNUAL_AMOUNTS": "annual_12_amount_candidate_index.csv",
    "ORIGINAL_PAPER_FEATURE_RETROSPECTIVE": "annual_original_15_paper_candidate_index.csv",
    "COMPARISON_QUARTER_FIT_ONLY_24_FEATURES": "quarterly_sparse_feature_matrix.csv",
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=fields, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)


def contract(data_root, bridge_root):
    data, bridge = Path(data_root), Path(bridge_root)
    closeout_path, gate_path = (
        bridge / "round2_closure_and_round3_preflight.json",
        bridge / "round3_release_gates.json")
    closeout = json.loads(closeout_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    if (closeout.get("status") !=
        "ROUND2_ENGINEERING_CLOSEOUT_VERIFIED_HUMAN_GROUND_TRUTH_PENDING"
        or closeout.get("round2_engineering_gates_passed") is not True
        or closeout.get("round2_research_label_acceptance_passed") is not False
        or closeout.get("holdout_1785_untouched") is not True
        or closeout.get("round2_source_sha256_verified") != 9
        or any(closeout.get(x) != 0 for x in (
            "original_first_filed_versions_independently_certified",
            "reviewed_positive_labels", "reviewed_negative_labels",
            "supervised_fraud_training_admitted"))):
        raise ValueError("round3_round2_closeout_contract_unapproved")
    if (gate.get("status") != "ROUND3_PREPARED_RESEARCH_ONLY_NO_FRAUD_CLASSIFIER_FIT"
        or gate.get("dataset_stage_ready") is not True
        or gate.get("unlabeled_anomaly_diagnostics_allowed") is not True
        or gate.get("amount_forecasting_research_only_allowed") is not True
        or gate.get("final_1785_holdout_restricted") is not True
        or any(gate.get(x) is not False for x in (
            "supervised_fraud_train_allowed",
            "supervised_fraud_validation_allowed",
            "supervised_fraud_test_allowed",
            "literature_baseline_fraud_auc_allowed",
            "historical_asof_case_replay_allowed"))):
        raise ValueError("round3_release_gate_not_research_only")
    frozen = data / "final_round1_integrated_ml_dataset"
    transfer_path = bridge / "round3_research_source_manifest.csv"
    if (digest(transfer_path) != closeout["round3_source_manifest_sha256"]
        or digest(transfer_path) != gate["source_transfer_manifest_sha256"]):
        raise ValueError("round3_source_transfer_manifest_changed")
    transfer = read_csv(transfer_path, (
        "source_id", "file_path", "source_sha256", "fraud_supervised_use",
        "historical_asof_certified", "safe_current_use"))
    if {x["source_id"] for x in transfer} != set(SOURCE_MAP) or len(transfer) != 3:
        raise ValueError("round3_source_transfer_inventory_changed")
    for row in transfer:
        if (row["file_path"] != SOURCE_MAP[row["source_id"]]
            or row["fraud_supervised_use"] != "BLOCKED"
            or row["historical_asof_certified"] != "false"
            or not row["safe_current_use"]):
            raise ValueError("round3_source_tier_or_training_policy_changed")
        if digest(frozen / row["file_path"]) != row["source_sha256"]:
            raise ValueError("round3_source_sha256_mismatch:" + row["source_id"])
    return frozen, closeout, gate, {
        "closeout": digest(closeout_path),
        "release_gate": digest(gate_path),
        "transfer_manifest": digest(transfer_path),
    }


def annual_windows(annual_csv):
    import numpy as np
    source = read_csv(annual_csv, ANNUAL_COLUMNS)
    panel = defaultdict(dict)
    if len(source) != 1560:
        raise ValueError("round3_annual_1560_required")
    for r in source:
        ticker, year = r["ticker"], int(r["fiscal_year"])
        if (not re.fullmatch(r"[0-9]{4}", ticker) or ticker == "1785"
            or year not in range(2013, 2026)
            or year in panel[ticker]
            or r["original_publication_verified"] != "false"
            or r["original_filing_vintage_verified"] != "false"):
            raise ValueError("round3_annual_provenance_or_duplicate_violation")
        require_unknown(r, "label_status")
        require_unapproved(r, ("training_admitted",))
        a = []
        for name in METRICS:
            value = r[name].strip()
            number = float(value) if value else float("nan")
            if value and not math.isfinite(number):
                raise ValueError("round3_annual_nonfinite_amount")
            a.append(number)
        row = np.asarray(a, dtype="float64")
        if (r["complete_candidate_vector"] == "true") != bool(np.isfinite(row).all()):
            raise ValueError("round3_annual_complete_flag_disagreement")
        panel[ticker][year] = row
    if len(panel) != 120 or any(len(x) != 13 for x in panel.values()):
        raise ValueError("round3_annual_120_by_13_frozen")
    windows = samples_for_next_year(panel, history=3)
    if len(windows) != 399:
        raise ValueError("round3_annual_complete_3yr_windows_not_399")
    return windows


def signed_log(v):
    import numpy as np
    return np.sign(v) * np.log1p(np.abs(v))


def signed_exp(v):
    import numpy as np
    with np.errstate(over="ignore", invalid="ignore"):
        return np.sign(v) * np.expm1(np.abs(v))


def metrics(true, predicted, scaler):
    import numpy as np
    from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
    delta = predicted - true
    actual_log = scaler.inverse_transform(true)
    predicted_log = scaler.inverse_transform(predicted)
    observed = signed_exp(actual_log)
    inferred = signed_exp(predicted_log)
    finite = np.isfinite(observed).all() and np.isfinite(inferred).all()
    if finite:
        twd_mae = float(np.mean(np.abs(inferred - observed)))
        smape = float(np.mean(2 * np.abs(inferred - observed) /
                             np.maximum(np.abs(inferred) + np.abs(observed), 1.0)))
        if not (math.isfinite(twd_mae) and math.isfinite(smape)):
            finite = False
    return {
        "scaled_mse": float(np.mean(delta ** 2)),
        "scaled_rmse": float(np.sqrt(np.mean(delta ** 2))),
        "scaled_mae": float(np.mean(np.abs(delta))),
        "scaled_r2": float(r2_score(true, predicted, multioutput="uniform_average")),
        "signed_log_mae": float(np.mean(np.abs(predicted_log - actual_log))),
        "twd_mae": twd_mae if finite else None,
        "smape": smape if finite else None,
    }


def regression(frozen, out, *, models, epochs, seed):
    import numpy as np
    from sklearn.multioutput import MultiOutputRegressor
    windows = annual_windows(frozen / SOURCE_MAP["FINMIND_PROVISIONAL_ANNUAL_AMOUNTS"])
    parts = time_partition(windows)
    scaled, scaler = prepare_scaled(parts)  # fit-only signed-log preprocessing
    import joblib
    stage = out / "annual_checkpoints"
    stage.mkdir(parents=True, exist_ok=False)
    joblib.dump({"scaler": scaler, "features": tuple(METRICS),
                 "study_only": True, "seed": seed}, stage / "fit_only_preprocessor.joblib")
    comparisons, per_metric = [], []
    predictions = {}
    for name in models:
        entry = dict.fromkeys(ANNUAL_MODEL_FIELDS, "")
        entry.update(model=name, status="NOT_RUN", outcome_label="UNKNOWN",
                     fit_company_year_windows=len(parts["fit"]),
                     validation_company_year_windows=len(parts["validation"]),
                     holdout_company_year_windows=len(parts["holdout"]))
        try:
            if name == "persistence":
                pred = {"val_prediction": scaled["validation"][0][:, -1, :],
                        "test_prediction": scaled["holdout"][0][:, -1, :],
                        "trained_epochs": 0, "backend": "deterministic_baseline"}
            elif name == "catboost":
                try:
                    from catboost import CatBoostRegressor
                except ImportError:
                    entry.update(status="DEPENDENCY_NOT_INSTALLED",
                                 reason="catboost package not installed")
                    comparisons.append(entry)
                    continue
                x, y = scaled["fit"]
                learner = MultiOutputRegressor(CatBoostRegressor(
                    iterations=160, depth=4, learning_rate=0.05,
                    loss_function="RMSE", random_seed=seed,
                    verbose=False, thread_count=2, l2_leaf_reg=3.0))
                learner.fit(x.reshape(len(x), -1), y)
                pred = {"val_prediction": learner.predict(
                            scaled["validation"][0].reshape(len(scaled["validation"][0]), -1)),
                        "test_prediction": learner.predict(
                            scaled["holdout"][0].reshape(len(scaled["holdout"][0]), -1)),
                        "trained_epochs": 160, "backend": "catboost"}
                joblib.dump(learner, stage / "catboost_experimental.joblib")
            else:
                pred = fit_model(name, scaled, epochs=epochs, seed=seed, output=stage)
            for split, key in (("validation", "val_prediction"),
                               ("holdout", "test_prediction")):
                y = scaled[split][1]
                estimate = np.asarray(pred[key], dtype="float64")
                if estimate.shape != y.shape or not np.isfinite(estimate).all():
                    raise ValueError("round3_invalid_numeric_prediction")
                evaluation = metrics(y, estimate, scaler)
                for label, number in evaluation.items():
                    entry[f"{split}_{label}"] = number
                y_logs, estimate_logs = (
                    scaler.inverse_transform(y), scaler.inverse_transform(estimate))
                actual_dollars, predicted_dollars = signed_exp(y_logs), signed_exp(estimate_logs)
                for i, feature in enumerate(METRICS):
                    finite = np.isfinite(actual_dollars[:, i]).all() and np.isfinite(
                        predicted_dollars[:, i]).all()
                    per_metric.append({
                        "model": name, "metric": feature, "split": split,
                        "n_company_years": len(y),
                        "signed_log_mae": float(np.mean(np.abs(
                            estimate_logs[:,i] - y_logs[:,i]))),
                        "twd_mae": float(np.mean(np.abs(
                            predicted_dollars[:,i] - actual_dollars[:,i]))) if finite else "",
                        "smape": float(np.mean(2 * np.abs(
                            predicted_dollars[:,i] - actual_dollars[:,i]) /
                            np.maximum(np.abs(predicted_dollars[:,i]) +
                                       np.abs(actual_dollars[:,i]), 1.0))) if finite else "",
                    })
            entry.update(status="FIT_NUMERIC_PROXY_ONLY", reason="",
                         fit_epochs=pred["trained_epochs"], backend=pred["backend"])
        except (ImportError, RuntimeError) as err:
            entry.update(status="OPTIONAL_DEPENDENCY_UNAVAILABLE",
                         reason=str(err)[:180])
        comparisons.append(entry)
    completed = [r for r in comparisons if r["status"] == "FIT_NUMERIC_PROXY_ONLY"]
    if len(completed) < 2 or not all(math.isfinite(float(x["validation_signed_log_mae"]))
                                    for x in completed):
        raise ValueError("round3_no_valid_regression_comparison")
    champion = min(completed, key=lambda x: float(x["validation_signed_log_mae"]))["model"]
    dump(out / "annual_numeric_prediction_model_metrics.csv", ANNUAL_MODEL_FIELDS, comparisons)
    dump(out / "annual_numeric_prediction_per_financial_field.csv",
         PER_FEATURE_FIELDS, per_metric)
    return {
        "status": "REAL_UNAPPROVED_FINMIND_NEXT_YEAR_NUMERIC_PREDICTION",
        "sample_count": len(windows),
        "time_partition_counts": {k:len(v) for k,v in parts.items()},
        "time_partition_issuer_counts": {
            k:len({x[0] for x in v}) for k,v in parts.items()},
        "fit_target_years": "2016-2020", "validation_target_years": "2021-2022",
        "single_heldout_evaluation_target_years": "2023-2025",
        "historical_issuer_disjoint": False,
        "selection_metric": "validation_signed_log_mae",
        "selected_model_by_validation_only": champion,
        "holdout_not_used_to_pick_model": True,
        "comparisons": comparisons, "features": list(METRICS),
        "target_is_next_year_financial_amounts_not_fraud": True,
    }


def ks_distance(x, y):
    import numpy as np
    a, b = np.sort(x), np.sort(y)
    grid = np.unique(np.concatenate((a,b)))
    return float(np.max(np.abs(
        np.searchsorted(a,grid,side="right")/len(a) -
        np.searchsorted(b,grid,side="right")/len(b))))


def js_divergence_fit_bins(fit, comparison):
    import numpy as np
    lo, hi = float(min(fit.min(), comparison.min())), float(max(fit.max(),comparison.max()))
    if lo == hi:
        return 0.0
    boundaries = np.linspace(lo, hi, 11)
    a, _ = np.histogram(fit, bins=boundaries)
    b, _ = np.histogram(comparison, bins=boundaries)
    p = (a + 1e-9)/(a.sum() + 10e-9)
    q = (b + 1e-9)/(b.sum() + 10e-9)
    m = (p+q)/2
    return float((np.sum(p*np.log2(p/m))+np.sum(q*np.log2(q/m)))/2)


def quarters(frozen, out, *, seed):
    import numpy as np
    from sklearn.preprocessing import RobustScaler
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.svm import OneClassSVM
    from sklearn.decomposition import PCA
    matrix = read_csv(frozen / "quarterly_sparse_feature_matrix.csv", QUARTER_MATRIX_BASE)
    dictionary = read_csv(frozen / "quarterly_fit_selected_feature_dictionary.csv",
                          QUARTER_FEATURE_DICTIONARY)
    if len(matrix) != 144 or len(dictionary) != 24:
        raise ValueError("round3_frozen_144x24_quarter_matrix_required")
    fids = [f["feature_id"] for f in dictionary]
    if len(set(fids)) != 24:
        raise ValueError("round3_duplicate_quarter_feature_id")
    for feature in dictionary:
        require_unapproved(feature, ("supervised_training_admitted",))
        if int(feature["fit_distinct_issuers"]) < 3:
            raise ValueError("round3_unfitted_feature_selection")
    splits = {"fit": [], "validation": [], "test": []}
    coverage = Counter()
    keys = set()
    for r in matrix:
        ticker, period = r["ticker"], r["reporting_period"]
        if (ticker=="1785" or not re.fullmatch(r"[0-9]{4}",ticker)
            or (ticker,period) in keys):
            raise ValueError("round3_quarter_holdout_or_duplicate")
        keys.add((ticker,period))
        require_unknown(r,"label_status")
        require_unapproved(r,("negative_label_approved","training_admitted",
                              "historical_publication_verified",
                              "original_filing_vintage_verified"))
        part = r["joint_strict_split"]
        issuer = issuer_partition(ticker)
        clock = "fit" if period <= "2018Q4" else "validation" if period < "2019Q3" else "test"
        if (r["issuer_split"] != issuer or r["time_split"] != clock
            or part != (issuer if issuer==clock else "outside_joint_evaluation")):
            raise ValueError("round3_quarter_leakage_partition_changed")
        values, masks = [], []
        for fid in fids:
            raw = r[fid].strip()
            present = r[fid+"_observed"] == "true"
            if present != bool(raw):
                raise ValueError("round3_quarter_missingness_flag_conflicts")
            val = float(raw) if present else float("nan")
            if present and not math.isfinite(val):
                raise ValueError("round3_quarter_infinite_financial_fact")
            values.append(val)
            masks.append(present)
        if (sum(masks) != int(r["observed_selected_feature_count"])
            or int(r["selected_feature_count"]) != 24):
            raise ValueError("round3_quarter_feature_observation_count_conflict")
        coverage[r["source_status"]] += 1
        if r["source_status"] != "OFFICIAL_QUARTER_SAME_GRAIN_CANDIDATE_VINTAGE_UNKNOWN":
            if any(masks):
                raise ValueError("round3_quarter_values_without_valid_source")
            continue
        if part in splits and sum(masks)>=4:
            splits[part].append((ticker,period,np.asarray(values,dtype=float),
                                 np.asarray(masks,dtype=float)))
    counts = {part:len(v) for part,v in splits.items()}
    for part, minimum in (("fit",12),("validation",2),("test",2)):
        if counts[part] < minimum:
            raise ValueError("round3_strict_joint_quarter_split_too_sparse:"+part)
    a = np.stack([r[2] for r in splits["fit"]])
    medians = np.nanmedian(a, axis=0)
    if not np.isfinite(medians).all():
        raise ValueError("round3_fit_only_feature_median_unavailable")
    scaler = RobustScaler().fit(np.sign(np.where(np.isfinite(a),a,medians)) *
                                 np.log1p(np.abs(np.where(np.isfinite(a),a,medians))))
    fit_x = None
    prepared = {}
    for part,rows in splits.items():
        x = np.stack([r[2] for r in rows])
        present = np.stack([r[3] for r in rows])
        filled = np.where(np.isfinite(x),x,medians)
        transformed = np.sign(filled)*np.log1p(np.abs(filled))
        z = np.concatenate([np.clip(scaler.transform(transformed),-25,25),present],axis=1)
        if not np.isfinite(z).all():
            raise ValueError("round3_quarter_nonfinite_preprocessed_matrix")
        prepared[part] = z
    fit_x = prepared["fit"]
    schemes = {
        "isolation_forest":IsolationForest(n_estimators=220,contamination="auto",
                                          random_state=seed,n_jobs=1),
        "lof_novelty":LocalOutlierFactor(n_neighbors=min(20,len(fit_x)-1),novelty=True),
        "one_class_svm":OneClassSVM(nu=0.1,kernel="rbf",gamma="scale"),
        "pca_reconstruction":PCA(n_components=min(7,len(fit_x)-1,fit_x.shape[1]),
                                 random_state=seed),
    }
    comparisons, scores = [], []
    for name, learner in schemes.items():
        learner.fit(fit_x)
        def score(x):
            if name == "pca_reconstruction":
                return np.mean((x-learner.inverse_transform(learner.transform(x)))**2,axis=1)
            return -learner.score_samples(x)
        fit_s = score(fit_x)
        val_s, test_s = score(prepared["validation"]),score(prepared["test"])
        if not all(np.isfinite(x).all() for x in (fit_s,val_s,test_s)):
            raise ValueError("round3_nonfinite_anomaly_scores")
        threshold = float(np.quantile(fit_s,.95))
        comparisons.append({
            "model":name,"fit_quarters":len(fit_s),
            "validation_quarters":len(val_s),"test_quarters":len(test_s),
            "fit_issuers":len({r[0] for r in splits["fit"]}),
            "validation_issuers":len({r[0] for r in splits["validation"]}),
            "test_issuers":len({r[0] for r in splits["test"]}),
            "training_score_p95":threshold,
            "validation_anomaly_fraction_above_fit_p95":float(np.mean(val_s>threshold)),
            "test_anomaly_fraction_above_fit_p95":float(np.mean(test_s>threshold)),
            "validation_score_median":float(np.median(val_s)),
            "test_score_median":float(np.median(test_s)),
            "validation_score_ks_from_fit":ks_distance(fit_s,val_s),
            "test_score_ks_from_fit":ks_distance(fit_s,test_s),
            "validation_score_jsd_from_fit":js_divergence_fit_bins(fit_s,val_s),
            "test_score_jsd_from_fit":js_divergence_fit_bins(fit_s,test_s),
            "independent_verified_labels":0,
        })
        for part, vals in (("validation",val_s),("test",test_s)):
            for row, v in zip(splits[part],vals):
                scores.append({
                    "model":name,"ticker":row[0],"reporting_period":row[1],
                    "joint_strict_split":part,
                    "observed_selected_feature_count":int(sum(row[3])),
                    "anomaly_proxy_score":float(v),
                    "above_fit_score_p95":str(v>threshold).lower(),
                    "verified_fraud_label":"UNKNOWN",
                    "interpretation":"unlabeled_distribution_novelty_NOT_verified_financial_fraud",
                })
    dump(out / "quarter_unlabeled_model_comparison.csv",QUARTER_MODEL_FIELDS,comparisons)
    dump(out / "quarter_unlabeled_validation_test_scores.csv",
         QUARTER_SCORE_FIELDS,scores)
    return {"status":"OFFICIAL_RETROSPECTIVE_QUARTER_UNLABELED_NOVELTY_ONLY",
            "raw_company_quarters":len(matrix),"quarter_source_statuses":dict(coverage),
            "training_selected_exact_fields":fids,
            "feature_count":len(fids),"training_only_median_and_robust_scaler":True,
            "strict_issuer_and_time_sample_counts":counts,
            "models":comparisons,"fraud_classification_metrics":None,
            "source_not_first_publication_version":True}


def run(data_root,bridge_root,output,*,models=ANNUAL_MODELS,
        epochs=40,seed=20261020):
    if not models or len(models)!=len(set(models)) or any(
            n not in ANNUAL_MODELS for n in models):
        raise ValueError("round3_invalid_model_families")
    if not 5<=epochs<=150:
        raise ValueError("round3_epochs_out_of_bounds")
    frozen,closeout,release,hashes=contract(data_root,bridge_root)
    out = Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("round3_previous_experiment_must_remain_immutable")
    out.mkdir(parents=True,exist_ok=True)
    annually = regression(frozen,out,models=models,epochs=epochs,seed=seed)
    quarter = quarters(frozen,out,seed=seed)
    report = {
        "status":"ROUND3_NUMERIC_REGRESSION_AND_UNLABELED_ANOMALY_RESEARCH_ONLY",
        "experiment_seed":seed,"epochs_requested":epochs,
        "source_gate_sha256":hashes,
        "annual_numeric_study":annually,
        "quarter_unlabeled_study":quarter,
        "fraud_supervised_training_allowed":False,
        "fraud_precision":None,"fraud_recall":None,"fraud_f1":None,
        "fraud_pr_auc":None,"fraud_roc_auc":None,
        "fraud_confusion_matrix":None,
        "known_positive_labels":0,"reviewed_normal_labels":0,
        "financial_accounting_amount_mse_is_not_fraud_accuracy":True,
        "model_selection_validation_only":True,
        "models_not_claimed_as_historical_asof":True,
        "reserved_final_case_1785_used":False,
        "production_db_writes":0,"network_requests":0,
        "warnings":[
            "Annual predictive regressions are provisional FinMind financial amounts, not reviewed anomalies.",
            "Annual train/validation/test are time-disjoint but repeat issuers; NOT issuer-independent external evidence.",
            "Quarter technical novelty fits only issuer/time joint fit rows, and scores UNKNOWN labels.",
            "2026-accessible official retrospective financials do not authenticate original historical publication.",
            "Fraud F1/Precision/Recall/PR-AUC require genuine independently verified positive and negative labels."],
    }
    (out / "round3_real_data_model_report.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n",
        encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="Round3 source-gated research ML numbers; no fake fraud labels")
    p.add_argument("--data-root",required=True)
    p.add_argument("--round2-bridge-root",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--models",nargs="+",default=list(ANNUAL_MODELS))
    p.add_argument("--epochs",type=int,default=40)
    p.add_argument("--seed",type=int,default=20261020)
    opts=p.parse_args(argv)
    r=run(opts.data_root,opts.round2_bridge_root,opts.output,
          models=tuple(opts.models),epochs=opts.epochs,seed=opts.seed)
    print(json.dumps({"status":r["status"],
                      "annual_models":r["annual_numeric_study"]["comparisons"],
                      "quarter_models":r["quarter_unlabeled_study"]["models"],
                      "fraud_f1":r["fraud_f1"],
                      "fraud_pr_auc":r["fraud_pr_auc"]},
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
