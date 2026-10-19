"""Round4 evidence-based explainability, robustness and audit-manager handoff.

Do not classify misstatements or touch 1785. Explain *numeric prediction* and
*unlabeled novelty*, using frozen Round3 true run output and training-only
model checkpoints; never relabel unknown cases, never fit on held-out 2023-25.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .round3_research_models import (
    contract, annual_windows, signed_exp, signed_log, metrics,
)
from .provisional_sequence_experiment import time_partition, prepare_scaled
from .annual_panel_readiness import METRICS
from .round2_evidence_review import read_csv

ANNUAL_METRICS = ("validation_signed_log_mae", "holdout_signed_log_mae",
                  "validation_scaled_rmse", "holdout_scaled_rmse",
                  "validation_scaled_r2", "holdout_scaled_r2",
                  "validation_smape", "holdout_smape")
RANK_COLS = ("model", "trained", "validation_signed_log_mae",
             "holdout_signed_log_mae", "holdout_scaled_rmse",
             "holdout_scaled_r2", "holdout_smape",
             "validation_minus_persistence", "selected_on_validation",
             "model_use_status")
PERM_COLS = ("model", "financial_field", "n_validation_windows",
             "history_steps_permuted", "repeats", "baseline_validation_signed_log_mae",
             "mean_increase_validation_signed_log_mae",
             "std_increase_validation_signed_log_mae",
             "interpretation")
CONSENSUS_COLS = ("ticker","reporting_period","model_count",
                  "models_above_fit_p95", "model_votes",
                  "uncertainty_or_fraud_label", "meaning")
PAIR_COLS = ("model_a","model_b","n_test_quarters","both_flagged",
             "either_flagged","jaccard_on_unlabeled_quarters")
HEALTH_FIELDS = ("measure","value","basis","significance","risk_for_early_warning")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def csv_dump(path, keys, rows):
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        w=csv.DictWriter(f,fieldnames=keys,extrasaction="raise")
        w.writeheader()
        w.writerows(rows)


def read_round3(source, frozen, bridge):
    d=json.loads(Path(source).read_text(encoding="utf-8"))
    _,round2,gate,hashes = contract(frozen,bridge)
    if (d.get("status") !=
        "ROUND3_NUMERIC_REGRESSION_AND_UNLABELED_ANOMALY_RESEARCH_ONLY"
        or d.get("source_gate_sha256") != hashes
        or d.get("fraud_supervised_training_allowed") is not False
        or d.get("reserved_final_case_1785_used") is not False
        or d.get("known_positive_labels") != 0
        or d.get("reviewed_normal_labels") != 0
        or any(d.get(k) is not None for k in (
            "fraud_precision","fraud_recall","fraud_f1","fraud_pr_auc",
            "fraud_roc_auc","fraud_confusion_matrix"))
        or d.get("model_selection_validation_only") is not True):
        raise ValueError("round4_frozen_round3_label_source_or_policy_changed")
    annual=d["annual_numeric_study"]
    strict=d["annual_strict_issuer_and_time_study"]
    quarter=d["quarter_unlabeled_study"]
    if (annual.get("sample_count") != 399
        or annual.get("time_partition_counts") != {
            "fit":192,"validation":82,"holdout":125}
        or annual.get("selected_model_by_validation_only") != "persistence"
        or strict.get("counts") != {"fit":147,"validation":18,"holdout":6}
        or strict.get("unique_issuer_counts") != {
            "fit":30,"validation":9,"holdout":2}
        or quarter.get("strict_issuer_and_time_sample_counts") != {
            "fit":20,"validation":9,"test":6}
        or quarter.get("feature_count") != 24
        or quarter.get("quarter_source_statuses") != {
            "OFFICIAL_QUARTER_SAME_GRAIN_CANDIDATE_VINTAGE_UNKNOWN":132,
            "filing_not_found":9,"source_invalid_content":3}
        or quarter.get("source_not_first_publication_version") is not True):
        raise ValueError("round4_round3_actual_sample_topology_mismatch")
    models=annual["comparisons"]
    if len(models)!=9 or len({x["model"] for x in models})!=9:
        raise ValueError("round4_annual_nine_models_required")
    scores={x["model"]:x for x in models}
    if not scores["persistence"]["status"]=="FIT_NUMERIC_PROXY_ONLY":
        raise ValueError("round4_missing_annual_baseline")
    for name,record in scores.items():
        if record["status"]=="FIT_NUMERIC_PROXY_ONLY":
            for m in ANNUAL_METRICS:
                v=record[m]
                if not isinstance(v,(int,float)) or not math.isfinite(v):
                    raise ValueError("round4_nonfinite_or_missing_numeric_metrics")
        elif name=="catboost" and record["status"]=="DEPENDENCY_NOT_INSTALLED":
            pass
        else:
            raise ValueError("round4_unexpected_untrained_model_or_status")
    winner=min(
        (x for x in models if x["status"]=="FIT_NUMERIC_PROXY_ONLY"),
        key=lambda x:x["validation_signed_log_mae"])["model"]
    if winner != annual["selected_model_by_validation_only"]:
        raise ValueError("round4_champion_not_selected_from_validation")
    return d


def ranking_table(d):
    models=d["annual_numeric_study"]["comparisons"]
    base=next(r for r in models if r["model"]=="persistence")
    selected=d["annual_numeric_study"]["selected_model_by_validation_only"]
    rows=[]
    for r in models:
        ok=r["status"]=="FIT_NUMERIC_PROXY_ONLY"
        rows.append({
            "model":r["model"],"trained":str(ok).lower(),
            "validation_signed_log_mae":r["validation_signed_log_mae"] if ok else "",
            "holdout_signed_log_mae":r["holdout_signed_log_mae"] if ok else "",
            "holdout_scaled_rmse":r["holdout_scaled_rmse"] if ok else "",
            "holdout_scaled_r2":r["holdout_scaled_r2"] if ok else "",
            "holdout_smape":r["holdout_smape"] if ok else "",
            "validation_minus_persistence": (
                float(r["validation_signed_log_mae"]) -
                float(base["validation_signed_log_mae"])) if ok else "",
            "selected_on_validation":str(r["model"]==selected).lower(),
            "model_use_status":"NUMERIC_PROXY_ONLY" if ok
                               else "DEPENDENCY_NOT_INSTALLED",
        })
    return rows


def permutation_validation(report_root, data_root, *, seed=20261020, repeats=5):
    """Validation-only grouped permutation of every field's complete history.

    This tests input reliance for already fitted Ridge/RF predictors, NOT SHAP,
    causal importance, abnormality evidence or a retrained model. Never scores
    1785 and never uses the test set for model selection/explainability.
    """
    import numpy as np
    import joblib
    root=Path(report_root)
    frozen=Path(data_root)/"final_round1_integrated_ml_dataset"
    windows=annual_windows(frozen/"annual_12_amount_candidate_index.csv")
    partitions=time_partition(windows)
    scaled, derived_scaler=prepare_scaled(partitions)
    manifest=root/"annual_checkpoints"/"fit_only_preprocessor.joblib"
    if not manifest.is_file():
        raise ValueError("round4_training_preprocessor_artifact_missing")
    bundle=joblib.load(manifest)  # ONLY own locally produced trusted checkpoint
    scaler=bundle.get("scaler")
    if (bundle.get("study_only") is not True
        or tuple(bundle.get("features",[])) != tuple(METRICS)
        or scaler is None
        or not np.allclose(scaler.center_,derived_scaler.center_)
        or not np.allclose(scaler.scale_,derived_scaler.scale_)):
        raise ValueError("round4_preprocessor_checkpoint_disagrees_with_frozen_training_data")
    X,Y=scaled["validation"]
    if len(X)!=len(partitions["validation"]) or len(METRICS)!=12 or repeats<2:
        raise ValueError("round4_wrong_validation_or_repeats")
    rows=[]
    for name in ("ridge","random_forest"):
        path=root/"annual_checkpoints"/(name+"_experimental.joblib")
        if not path.is_file():
            raise ValueError("round4_trained_model_checkpoint_missing:"+name)
        model=joblib.load(path)  # own outputs ONLY, not untrusted serialized files
        pred=model.predict(X.reshape(len(X),-1))
        if pred.shape!=Y.shape:
            raise ValueError("round4_permutation_prediction_shape")
        baseline=float(np.mean(np.abs(
            scaler.inverse_transform(pred)-scaler.inverse_transform(Y))))
        for idx,financial in enumerate(METRICS):
            loss_changes=[]
            for repetition in range(repeats):
                rng=np.random.default_rng(seed+101*idx+17*repetition)
                Xp=X.copy()
                shuffle=rng.permutation(len(X))
                # Whole three-year history is moved together by financial field
                Xp[:,:,idx]=X[shuffle,:,idx]
                pp=model.predict(Xp.reshape(len(Xp),-1))
                loss=float(np.mean(np.abs(
                    scaler.inverse_transform(pp)-scaler.inverse_transform(Y))))
                loss_changes.append(loss-baseline)
            rows.append({
                "model":name,"financial_field":financial,
                "n_validation_windows":len(X),
                "history_steps_permuted":3,"repeats":repeats,
                "baseline_validation_signed_log_mae":baseline,
                "mean_increase_validation_signed_log_mae":float(np.mean(loss_changes)),
                "std_increase_validation_signed_log_mae":float(np.std(loss_changes,ddof=1)),
                "interpretation":"VALIDATION_NUMERIC_PREDICTION_SENSITIVITY_NOT_FRAUD_NOT_CAUSAL",
            })
    return rows


def consensus_table(round3_root, d):
    f=Path(round3_root)/"quarter_unlabeled_validation_test_scores.csv"
    rows=read_csv(f,("ticker","reporting_period","joint_strict_split",
                     "model","above_fit_score_p95","verified_fraud_label"))
    groups=defaultdict(dict)
    for item in rows:
        if item["verified_fraud_label"]!="UNKNOWN" or item["ticker"]=="1785":
            raise ValueError("round4_quarter_fraud_label_or_holdout_violation")
        key=(item["ticker"],item["reporting_period"],item["joint_strict_split"])
        if item["model"] in groups[key]:
            raise ValueError("round4_quarter_duplicate_model_score")
        val=item["above_fit_score_p95"]
        if val not in ("true","false"):
            raise ValueError("round4_not_boolean_model_flag")
        groups[key][item["model"]]=val=="true"
    models={r["model"] for r in d["quarter_unlabeled_study"]["models"]}
    if len(groups)!=15 or len(models)!=4:
        raise ValueError("round4_quarter_15_validation_test_groups_expected")
    summarized=[]
    sets=defaultdict(set)
    for (ticker,period,partition),flags in sorted(groups.items()):
        if set(flags)!=models:
            raise ValueError("round4_incomplete_quarter_method_votes")
        votes=sum(flags.values())
        summarized.append({
            "ticker":ticker,"reporting_period":period,
            "model_count":len(models),"models_above_fit_p95":votes,
            "model_votes":"|".join(sorted(k for k,v in flags.items() if v)),
            "uncertainty_or_fraud_label":"UNKNOWN",
            "meaning":"NOVELTY_ENSEMBLE_DISAGREEMENT_NO_CONFIRMED_FRAUD",
        })
        if partition=="test":
            for name,is_high in flags.items():
                if is_high:sets[name].add((ticker,period))
    ntest=sum(key[2]=="test" for key in groups)
    if ntest!=6:
        raise ValueError("round4_test_six_quarters_required")
    pairs=[]
    for a in sorted(models):
        for b in sorted(models):
            if a>=b:continue
            both=len(sets[a]&sets[b])
            either=len(sets[a]|sets[b])
            pairs.append({"model_a":a,"model_b":b,"n_test_quarters":ntest,
                          "both_flagged":both,"either_flagged":either,
                          "jaccard_on_unlabeled_quarters":both/either if either else None})
    return summarized,pairs


def health(d):
    annual=d["annual_numeric_study"]
    strict=d["annual_strict_issuer_and_time_study"]
    quarter=d["quarter_unlabeled_study"]
    report=[]
    def add(name,value,basis,significance,risk):
        report.append({"measure":name,"value":value,"basis":basis,
                       "significance":significance,"risk_for_early_warning":risk})
    add("validation_champion",annual["selected_model_by_validation_only"],
        "validation_signed_log_mae","Simpler previous-year benchmark beats neural models on selected metric","HIGH")
    add("strict_joint_test_independent_issuers",
        strict["unique_issuer_counts"]["holdout"],
        "2023–2025 and issuer-disjoint", "Only two test issuers; generalization claim severely limited","HIGH")
    add("strict_joint_test_sample_count",strict["counts"]["holdout"],
        "real financial amounts","Only six target windows; R2 is unstable","HIGH")
    add("quarter_fit_valid_test",json.dumps(
        quarter["strict_issuer_and_time_sample_counts"],sort_keys=True),
        "official retrospective quarter source","Only 20/9/6 eligible joint samples","HIGH")
    for r in quarter["models"]:
        add("test_above_fit_p95_"+r["model"],
            r["test_anomaly_fraction_above_fit_p95"],
            "six unlabeled holdout quarters","Different algorithms flag 0–100%; NO accuracy evidence","HIGH")
    add("historical_original_filing_vintages",0,
        "Round2 source certification","As-of detection claims cannot be validated","CRITICAL")
    add("reviewed_positive_negative_labels","0/0",
        "Round2 independent outcomes","Fraud F1/Precision/Recall/PR-AUC undefined","CRITICAL")
    add("last_event_holdout","1785 reserved",
        "prior research contract","No 1785 fit, test or demonstration-as-of replay","CRITICAL")
    return report


def build(data_root, bridge_root, round3_root, output, *, seed=20261020,
          repeats=5, report_sha=None):
    root=Path(round3_root);out=Path(output)
    source=root/"round3_real_data_model_report.json"
    if report_sha and sha(source)!=report_sha:
        raise ValueError("round4_user_uploaded_round3_report_sha_mismatch")
    d=read_round3(source,data_root,bridge_root)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("round4_previous_results_immutable")
    ranks=ranking_table(d)
    votes,pairs=consensus_table(root,d)
    permutation=permutation_validation(root,data_root,seed=seed,repeats=repeats)
    risk=health(d)
    out.mkdir(parents=True,exist_ok=True)
    csv_dump(out/"round4_validation_model_comparison.csv",RANK_COLS,ranks)
    csv_dump(out/"round4_validation_permutation_importance.csv",PERM_COLS,permutation)
    csv_dump(out/"round4_quarter_unlabeled_consensus.csv",CONSENSUS_COLS,votes)
    csv_dump(out/"round4_quarter_model_agreement.csv",PAIR_COLS,pairs)
    csv_dump(out/"round4_audit_manager_research_risks.csv",HEALTH_FIELDS,risk)
    round3=Path(round3_root)
    result={
        "status":"ROUND4_EXPLAINABILITY_ROBUSTNESS_RESEARCH_HANDOFF",
        "source_round3_sha256":sha(source),
        "validation_chosen_numeric_model":d["annual_numeric_study"]["selected_model_by_validation_only"],
        "annual_numeric_models_attempted":len(ranks),
        "annual_numeric_models_with_metrics":sum(x["trained"]=="true" for x in ranks),
        "catboost_fitted":False,
        "model_ranking_selection_only_validation":True,
        "diagnostic_permutation_trained_regression_models":2,
        "diagnostic_permutation_features_per_model":12,
        "permutation_importance_validation_only_not_fraud":True,
        "unlabeled_quarter_scores_compared":len(votes),
        "unlabeled_quarter_method_pairs_compared":len(pairs),
        "strict_joint_test_company_count":d["annual_strict_issuer_and_time_study"]["unique_issuer_counts"]["holdout"],
        "strict_joint_test_target_count":d["annual_strict_issuer_and_time_study"]["counts"]["holdout"],
        "reviewed_case_outcomes":0,"normal_controls_certified":0,
        "supervised_fraud_F1":None,"supervised_fraud_pr_auc":None,
        "original_asof_1785_replay_status":"BLOCKED_ORIGINAL_VINTAGE_AND_OUTCOME_REVIEW",
        "reserved_1785_excluded":True,
        "source_tiers_not_fused":True,
        "no_retrained_holdout_models":True,
        "network_requests":0,"production_db_writes":0,
        "files":{
            "ranking":"round4_validation_model_comparison.csv",
            "model_input_sensitivity":"round4_validation_permutation_importance.csv",
            "quarter_consensus":"round4_quarter_unlabeled_consensus.csv",
            "quarter_agreement":"round4_quarter_model_agreement.csv",
            "audit_manager_risks":"round4_audit_manager_research_risks.csv",
        },
        "key_explanations":[
            "Persistence best by chosen validation signed-log MAE. Best holdout RMSE is not used to change the selection.",
            "Annual temporal experiment repeats some issuers; strict dual split only 2 unseen test issuers and 6 windows.",
            "Quarter novelty scores and p95 thresholds are distribution diagnostics, not fraud likelihoods.",
            "Permutation scores quantify validation input sensitivity of Ridge/RandomForest for 12 future financial amounts, not SHAP or causality.",
            "A source SHA protects archived bytes but does not authenticate original release, outcome labels or true first disclosure.",
        ],
    }
    (out/"round4_research_handoff_report.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n",
        encoding="utf-8")
    return result


def main(argv=None):
    ap=argparse.ArgumentParser(description="Offline Round4 explainability and research handoff")
    ap.add_argument("--data-root",required=True)
    ap.add_argument("--round2-bridge-root",required=True)
    ap.add_argument("--round3-root",required=True)
    ap.add_argument("--output",required=True)
    ap.add_argument("--round3-sha256",default="")
    ap.add_argument("--repeats",type=int,default=5)
    args=ap.parse_args(argv)
    print(json.dumps(build(args.data_root,args.round2_bridge_root,
                            args.round3_root,args.output,
                            report_sha=args.round3_sha256 or None,
                            repeats=args.repeats),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
