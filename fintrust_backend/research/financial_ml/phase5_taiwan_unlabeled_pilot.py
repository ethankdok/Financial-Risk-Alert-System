"""Phase 5 Taiwan literature-feature anomaly-learning pilot, strictly unlabeled.

Models are trained ONLY on preliminary unapproved FinMind candidate-feature
evidence; they are not predictors of confirmed false financial statements.
Only Phase4 issuer AND fiscal-year independent study splits are used.
No outcome labels/1785/case candidates, no official-vendor merging, no external
network or database mutations. Train-only imputer/scaler and fixed thresholds.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

from .literature_dataset import FEATURES

SOURCE="FINMIND_PROVISIONAL"
TRAINING_CONTRACT="UNLABELED_UNVERIFIED_FINMIND_TECHNICAL_SMOKE"
MIN_REQUIRED_INPUTS=4
MIN_FEATURE_FIT_COUNT=12
MIN_FIT=30
MIN_VAL=5
MIN_TEST=5
MODEL_NAMES=("isolation_forest","lof_novelty","one_class_svm","pca_reconstruction")


def read_audited_data(register,phase4_report):
    import numpy as np
    report=json.loads(Path(phase4_report).read_text(encoding="utf-8"))
    if (report.get("eligible_for_supervised_financial_fraud_training") is not False
            or report.get("labels_approved_positive") != 0
            or report.get("labels_approved_negative") != 0
            or report.get("final_holdout_excluded") is not True
            or report.get("source_tiers_not_fused") is not True):
        raise ValueError("phase4_provenance_or_label_gate_not_satisfied")
    needed={"ticker","fiscal_year","evidence_tier","issuer_split","temporal_split",
            "joint_strict_split","development_event_candidate","outcome_label",
            "approved_supervised_training","approved_supervised_validation",
            "approved_supervised_test","first_filing_publication_verified",
            "original_vintage_verified","feature_vector_json"}
    with Path(register).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if needed-set(reader.fieldnames or []):
            raise ValueError("phase4_split_register_schema_mismatch")
        incoming=list(reader)
    case_ids=set(report.get("case_development_candidate_ids") or [])
    if not case_ids or "1785" in case_ids:
        raise ValueError("missing_or_corrupted_development_case_registry")
    seen=set()
    values={"fit":[],"validation":[],"test":[]}
    excluded=Counter()
    firms={"fit":set(),"validation":set(),"test":set()}
    for r in incoming:
        ticker=r["ticker"].strip()
        if (ticker=="1785" or not ticker.isdecimal() or len(ticker)!=4):
            raise ValueError("reserved_case_or_invalid_issuer")
        year=int(r["fiscal_year"])
        if not 2013 <= year <= 2025:
            raise ValueError("out_of_sample_year")
        key=(r["evidence_tier"],ticker,year)
        if key in seen:
            raise ValueError("duplicate_evidence_source_issuer_year")
        seen.add(key)
        if (r["outcome_label"]!="UNKNOWN"
                or any(r[flag].lower()!="false" for flag in (
                    "approved_supervised_training","approved_supervised_validation",
                    "approved_supervised_test"))
                or r["first_filing_publication_verified"].lower()!="false"
                or r["original_vintage_verified"].lower()!="false"):
            raise ValueError("unapproved_label_or_asof_promotion")
        if (r["development_event_candidate"].lower()=="true")!=(ticker in case_ids):
            raise ValueError("development_candidate_flag_conflicts_with_locked_case_registry")
        if r["evidence_tier"]!=SOURCE:
            excluded["separate_official_retrospective_tier"]+=1
            continue
        if r["development_event_candidate"].lower()=="true":
            excluded["potential_case_company_excluded"]+=1
            continue
        split=r["joint_strict_split"]
        if split not in values:
            excluded["outside_joint_company_time_evaluation"]+=1
            continue
        if split!=r["issuer_split"] or split!=r["temporal_split"]:
            raise ValueError("inconsistent_joint_study_split")
        vector=json.loads(r["feature_vector_json"])
        if set(vector)!=set(FEATURES):
            raise ValueError("inconsistent_original_paper_feature_schema")
        if vector["d_issue"]:
            raise ValueError("finmind_unverified_issue_not_permitted")
        result=[]
        for name in FEATURES:
            val=vector[name]
            if val=="":
                result.append(float("nan"))
            else:
                num=float(val)
                if not math.isfinite(num):
                    raise ValueError("nonfinite_paper_candidate_feature")
                result.append(num)
        if np.isfinite(result).sum()<MIN_REQUIRED_INPUTS:
            excluded["fewer_than_4_observed_paper_features"]+=1
            continue
        values[split].append((ticker,year,np.asarray(result,dtype="float64")))
        firms[split].add(ticker)
    if any(firms[a]&firms[b] for a,b in (("fit","validation"),("fit","test"),
                                        ("validation","test"))):
        raise ValueError("cross_split_company_leak")
    if (any(len(values[p])<n for p,n in
            (("fit",MIN_FIT),("validation",MIN_VAL),("test",MIN_TEST)))
            or len(firms["fit"])<8):
        return None,{
            "status":"UNLABELED_PROXY_BLOCKED_INSUFFICIENT_STRICT_SPLIT_COVERAGE",
            "rows_by_split":{k:len(v) for k,v in values.items()},
            "issuer_counts":{k:len(v) for k,v in firms.items()},
            "excluded":dict(excluded),
            "approved_fraud_evaluation_possible":False}
    return values,{"status":"PROVISIONAL_SOURCE_SPLIT_READY_FOR_UNLABELED_PROXY_ONLY",
                   "rows_by_split":{k:len(v) for k,v in values.items()},
                   "issuer_counts":{k:len(v) for k,v in firms.items()},
                   "excluded":dict(excluded),
                   "approved_fraud_evaluation_possible":False}


def transform_only_training_fit(splits):
    import numpy as np
    from sklearn.preprocessing import RobustScaler
    matrix={part:np.stack([v for _,_,v in batch]) for part,batch in splits.items()}
    fit=matrix["fit"]
    usable=[]
    dropped={}
    for idx,feature in enumerate(FEATURES):
        numbers=fit[np.isfinite(fit[:,idx]),idx]
        if feature=="d_issue":
            dropped[feature]="no_verified_issuance_evidence"
        elif len(numbers)<MIN_FEATURE_FIT_COUNT or len(numbers)/len(fit)<0.15:
            dropped[feature]="insufficient_fit_coverage"
        elif float(np.std(numbers))<1e-10:
            dropped[feature]="constant_in_fit"
        else:
            usable.append(idx)
    if len(usable)<3:
        raise ValueError("too_few_available_original_paper_features")
    # Signed log1p handles wide-tailed ratio/absolute accounting features,
    # but is fitted to TRAIN only; track missingness explicitly.
    medians=np.nanmedian(fit[:,usable],axis=0)
    if not np.isfinite(medians).all():
        raise ValueError("unresolved_training_median")
    def encode(values):
        a=values[:,usable]
        present=np.isfinite(a)
        filled=np.where(present,a,medians)
        transformed=np.sign(filled)*np.log1p(np.abs(filled))
        return transformed,present
    train,_=encode(fit)
    scaler=RobustScaler(quantile_range=(25,75))
    scaler.fit(train)
    encoded={}
    for part,values in matrix.items():
        num,mask=encode(values)
        scaled=scaler.transform(num)
        # A visible indicator of unobserved finance concepts, not zero financial amounts.
        x=np.concatenate([np.clip(scaled,-25,25),mask.astype(float)],axis=1)
        if not np.isfinite(x).all():
            raise ValueError("invalid_model_matrix")
        encoded[part]=x
    return encoded,{
        "trained_feature_names":[FEATURES[i] for i in usable],
        "excluded_features":dropped,
        "fit_only_medians":medians.tolist(),
        "preprocessing":"fit_only_median_plus_binary_observation_mask_signed_log1p_robust_scaled",
        "model_columns":len(usable)*2,
        "imputation_is_model_input_only_not_financial_source_zero":True
    }


def models(seed,n_train,xtrain):
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.svm import OneClassSVM
    from sklearn.decomposition import PCA
    return {
        "isolation_forest":IsolationForest(
            n_estimators=250,max_samples=min(256,n_train),
            random_state=seed,n_jobs=1),
        "lof_novelty":LocalOutlierFactor(
            n_neighbors=min(20,n_train-1),novelty=True),
        "one_class_svm":OneClassSVM(kernel="rbf",nu=0.1,gamma="scale"),
        "pca_reconstruction":PCA(n_components=min(5,xtrain.shape[1],n_train-1),
                                 random_state=seed),
    }


def fit_score(name,est,fit_x,x):
    import numpy as np
    if name=="pca_reconstruction":
        return np.mean((est.inverse_transform(est.transform(x))-x)**2,axis=1)
    return -est.score_samples(x)


def run(register,report_path,output,*,seed=20261019,
        experimental_allow_unverified_data=False):
    import numpy as np
    if not experimental_allow_unverified_data:
        raise ValueError("experimental_unverified_financial_data_opt_in_required")
    root=Path(output)
    root.mkdir(parents=True,exist_ok=True)
    splits,entry=read_audited_data(register,report_path)
    result={
        "study":"UNLABELED_TAIWAN_15_PAPER_CANDIDATE_COMPONENT_ANOMALY_TECHNICAL_PILOT",
        "status":entry["status"],"source_tier":SOURCE,
        "cohort_is_unreviewed":True,"labels_approved":0,
        "evaluation_metrics_for_misstatement":None,
        "accuracy_recall_pr_auc_f1_reported":False,
        "mops_responding_to_correction_data_used":False,
        "uses_frozen_1785":False,"network_requests":0,"production_db_writes":0,
        "audit":entry,
        "input_sha256":hashlib.sha256(Path(register).read_bytes()).hexdigest(),
        "split_report_sha256":hashlib.sha256(Path(report_path).read_bytes()).hexdigest()
    }
    if splits is None:
        (root/"phase5_exploratory_report.json").write_text(
            json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return result
    try:
        xy,prep=transform_only_training_fit(splits)
    except ValueError as exc:
        result["status"]="UNLABELED_PROXY_BLOCKED_INSUFFICIENT_PAPER_FEATURE_COVERAGE"
        result["blocking_reason"]=str(exc)
        (root/"phase5_exploratory_report.json").write_text(
            json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        return result
    scores=[]
    comparisons=[]
    for name,model in models(seed,len(xy["fit"]),xy["fit"]).items():
        model.fit(xy["fit"])
        fit_scores=fit_score(name,model,xy["fit"],xy["fit"])
        validation=fit_score(name,model,xy["fit"],xy["validation"])
        holdout=fit_score(name,model,xy["fit"],xy["test"])
        if not (np.isfinite(fit_scores).all()
                and np.isfinite(validation).all()
                and np.isfinite(holdout).all()):
            raise ValueError("model_scores_nonfinite")
        # The threshold depends ONLY on the unsupervised fitting set.
        threshold=float(np.quantile(fit_scores,0.95))
        comparisons.append({
            "model":name,"fit_companies":entry["issuer_counts"]["fit"],
            "fit_rows":len(fit_scores),"validation_rows":len(validation),
            "holdout_rows":len(holdout),
            "fit_score_p95":round(threshold,8),
            "validation_fraction_above_training_p95":round(float(np.mean(validation>threshold)),6),
            "holdout_fraction_above_training_p95":round(float(np.mean(holdout>threshold)),6),
            "holdout_score_median":round(float(np.median(holdout)),8),
            "interpretation":"distribution_shift_proxy_NOT_fraud_detection_accuracy"
        })
        for (ticker,yr,_),score in zip(splits["test"],holdout):
            scores.append({
                "model":name,"ticker":ticker,"fiscal_year":yr,
                "anomaly_proxy_score":round(float(score),8),
                "flagged_at_training_p95":str(score>threshold).lower(),
                "verified_financial_misstatement_label":"UNKNOWN",
                "can_assert_historical_early_warning":"false"
            })
        print(f"[Phase5 model] {name}: {len(xy['fit'])} fit, {len(validation)} val, "
              f"{len(holdout)} holdout rows (NO LABELS)",flush=True)
    def out_csv(name,items):
        with (root/name).open("w",encoding="utf-8",newline="") as stream:
            w=csv.DictWriter(stream,fieldnames=list(items[0]))
            w.writeheader();w.writerows(items)
    out_csv("unlabeled_method_comparison.csv",comparisons)
    out_csv("unknown_label_holdout_proxy_scores.csv",scores)
    result.update({
        "status":"PROXY_MODEL_FAMILIES_FIT_NOT_FINANCIAL_MISSTATEMENT_DETECTION",
        "model_families":[x["model"] for x in comparisons],
        "preprocessing":prep,
        "model_comparison":comparisons,
        "unsupervised_fit_only_technical_models_trained":len(comparisons),
        "validation_heldout_used_for_model_choice":False,
        "holdout_used_for_hyperparameter_tuning":False,
        "score_percentiles_are_not_probabilities":True,
        "limitation":"No official original filing vintage, no confirmed Taiwan labels, "
                     "FinMind aliases unapproved; exploratory anomaly proxy only."
    })
    (root/"phase5_exploratory_report.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description="Unlabeled source-gated 15 paper-feature Taiwan anomaly proxy")
    parser.add_argument("--register",required=True)
    parser.add_argument("--phase4-report",required=True)
    parser.add_argument("--output",required=True)
    parser.add_argument("--seed",type=int,default=20261019)
    parser.add_argument("--experimental-allow-unverified-data",action="store_true",required=True)
    opt=parser.parse_args(argv)
    print(json.dumps(run(opt.register,opt.phase4_report,opt.output,seed=opt.seed,
                         experimental_allow_unverified_data=opt.experimental_allow_unverified_data),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
