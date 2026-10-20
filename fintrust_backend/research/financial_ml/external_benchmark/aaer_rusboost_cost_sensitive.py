"""Second independent real AAER trial: RUSBoost / balanced bagging / cost grids.

Why: reproduce approaches from Bao et al. JAR 2020 and test whether class
imbalance remedies improve genuine precision, recall and PR-AUC.
No balanced/undersampled TEST data. No 90% guarantee. No look-ahead features.
This new issuer holdout uses a different, predeclared seed from all prior
experimental holdouts and is not used to select thresholds.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer
from sklearn.metrics import roc_auc_score,average_precision_score

from .published_aaer_real_supervised import read_original,SOURCE_URL,signed_log
from .enhanced_real_aaer_training import (
    engineer,ALL_FEATURES,COMMON_FEATURES,metric,validation_threshold,
    triage,model_setup)
from sklearn.model_selection import train_test_split

NEW_HOLDOUT_SEED=20261028
SOURCE_SHA="ed4cefd9db2a23d0a13911d9f482fc755d3dcf6c9be0bc051af95ddcae5b286f"

def fresh_issuer_holdout(df):
    tags=df.groupby("gvkey",sort=True)["misstate"].max()
    companies=tags.index.astype(str).to_numpy()
    ever=tags.to_numpy().astype(int)
    train,other=train_test_split(companies,test_size=.30,random_state=NEW_HOLDOUT_SEED,
                                 stratify=ever)
    rank=dict(zip(companies,ever))
    val,test=train_test_split(other,test_size=.5,random_state=NEW_HOLDOUT_SEED+1,
                              stratify=[rank[x] for x in other])
    groups={"fit":set(train),"validation":set(val),"test":set(test)}
    assert len(set.union(*groups.values()))==len(companies)
    assert all(not (groups[a]&groups[b]) for a,b in
               (("fit","validation"),("fit","test"),("validation","test")))
    result={}
    for name,keys in groups.items():
        subset=df[df["gvkey"].isin(keys)].copy()
        if subset.misstate.sum()<35:raise ValueError("rare_positive_holdout_inadequate:"+name)
        result[name]=subset
    return result

def learning_candidates():
    from imblearn.ensemble import RUSBoostClassifier,BalancedRandomForestClassifier,EasyEnsembleClassifier
    from lightgbm import LGBMClassifier
    # RUSBoost is the method implemented by the original published authors.
    # Every resampling step takes place on FIT only, never validation or test.
    return [
        ("rusboost_120_stumps","all",
          lambda:RUSBoostClassifier(
            estimator=DecisionTreeClassifier(max_depth=2,min_samples_leaf=12,
                  random_state=NEW_HOLDOUT_SEED),
            n_estimators=120,learning_rate=.10,sampling_strategy="auto",
            random_state=NEW_HOLDOUT_SEED)),
        ("rusboost_250_tree3","all",
          lambda:RUSBoostClassifier(
            estimator=DecisionTreeClassifier(max_depth=3,min_samples_leaf=15,
                  random_state=NEW_HOLDOUT_SEED),
            n_estimators=250,learning_rate=.07,sampling_strategy="auto",
            random_state=NEW_HOLDOUT_SEED)),
        ("balanced_rf_180","all",
          lambda:BalancedRandomForestClassifier(n_estimators=180,max_depth=9,
            min_samples_leaf=5,n_jobs=2,sampling_strategy="all",
            replacement=True,random_state=NEW_HOLDOUT_SEED)),
        ("easy_ensemble_12","all",
          lambda:EasyEnsembleClassifier(n_estimators=12,n_jobs=2,
             sampling_strategy="auto",random_state=NEW_HOLDOUT_SEED)),
        ("lgbm_no_reweight","all",
          lambda:LGBMClassifier(n_estimators=550,learning_rate=.025,
            num_leaves=13,min_child_samples=140,
            reg_alpha=2,reg_lambda=15,
            colsample_bytree=.85,subsample=.9,subsample_freq=1,
            random_state=NEW_HOLDOUT_SEED,n_jobs=2,verbosity=-1)),
        ("lgbm_weight3","all",
          lambda:LGBMClassifier(n_estimators=550,learning_rate=.025,
            num_leaves=13,min_child_samples=140,scale_pos_weight=3,
            reg_alpha=2,reg_lambda=15,colsample_bytree=.85,
            random_state=NEW_HOLDOUT_SEED,n_jobs=2,verbosity=-1)),
        ("lgbm_weight12","all",
          lambda:LGBMClassifier(n_estimators=550,learning_rate=.025,
            num_leaves=13,min_child_samples=140,scale_pos_weight=12,
            reg_alpha=2,reg_lambda=15,colsample_bytree=.85,
            random_state=NEW_HOLDOUT_SEED,n_jobs=2,verbosity=-1)),
        ("lgbm_weight25","all",
          lambda:LGBMClassifier(n_estimators=550,learning_rate=.025,
            num_leaves=13,min_child_samples=140,scale_pos_weight=25,
            reg_alpha=2,reg_lambda=15,colsample_bytree=.85,
            random_state=NEW_HOLDOUT_SEED,n_jobs=2,verbosity=-1)),
        ("lgbm_common9_weight3","common",
          lambda:LGBMClassifier(n_estimators=500,learning_rate=.025,
            num_leaves=13,min_child_samples=120,scale_pos_weight=3,
            reg_alpha=2,reg_lambda=15,colsample_bytree=.85,
            random_state=NEW_HOLDOUT_SEED,n_jobs=2,verbosity=-1)),
    ]

def run(source,output):
    begin=time.monotonic()
    df,digest=read_original(source)
    if digest!=SOURCE_SHA:
        raise ValueError("AAER original human-labeled source changed")
    df=engineer(df)
    partitions=fresh_issuer_holdout(df)
    fit=partitions["fit"];val=partitions["validation"];test=partitions["test"]
    yfit=fit.misstate.to_numpy(dtype=int)
    yval=val.misstate.to_numpy(dtype=int)
    ytest=test.misstate.to_numpy(dtype=int)
    trials=[]
    champions=[]
    preds={}
    train_models={}
    for name,fs,make_model in learning_candidates():
        features=ALL_FEATURES if fs=="all" else COMMON_FEATURES
        xt=fit.loc[:,features].to_numpy(dtype=float)
        xv=val.loc[:,features].to_numpy(dtype=float)
        try:
            model=Pipeline([
                ("impute",SimpleImputer(strategy="median",
                                       keep_empty_features=True)),
                ("learner",make_model()),
            ])
            model.fit(xt,yfit)
            v=np.asarray(model.predict_proba(xv)[:,1],dtype=float)
            if len(v)!=len(yval) or not np.all(np.isfinite(v)):
                raise ValueError("RUSBoost / BRF candidate emitted invalid probabilities")
            t=validation_threshold(yval,v)
            score=metric(yval,v,t)
            row={"candidate":name,"status":"FITTED_VALIDATED",
                 "input_columns":len(features),"threshold_from_validation":t,
                 "validation":score}
            preds[name]=v
            train_models[name]=(model,tuple(features),t)
            champions.append((score["pr_auc_average_precision"],score["roc_auc"],name))
            print("VALIDATION",name,score["pr_auc_average_precision"],
                  score["roc_auc"],score["f1"],flush=True)
        except Exception as exc:
            row={"candidate":name,"status":"ERROR_DURING_FIT",
                 "error_type":type(exc).__name__,"error_message":str(exc)[:350]}
            print("ERROR",name,repr(exc),flush=True)
        trials.append(row)
    # Only VALIDATION metrics select a champion and threshold.
    if not champions:
        raise RuntimeError("All RUSBoost and cost-sensitive training candidates failed")
    champs=sorted(champions,reverse=True)
    chosen=champs[0][2]
    model,features,threshold=train_models[chosen]
    hold_pred=np.asarray(model.predict_proba(
        test.loc[:,features].to_numpy(dtype=float))[:,1])
    hold=metric(ytest,hold_pred,threshold)
    outcome={
       "status":"REAL_AAER_RUSBOOST_COST_SENSITIVE_VALIDATION_DONE",
       "source":SOURCE_URL,"source_sha256":digest,
       "fixed_new_holdout_seed":NEW_HOLDOUT_SEED,
       "not_prior_test_selected":True,
       "dataset_AAER_labels_0":int((df.misstate==0).sum()),
       "dataset_AAER_labels_1":int((df.misstate==1).sum()),
       "issuer_count":int(df.gvkey.nunique()),
       "split":{key:{"issuer_count":int(z.gvkey.nunique()),
                     "company_year_count":len(z),
                     "positive":int(z.misstate.sum()),
                     "negative":int((z.misstate==0).sum())}
                for key,z in partitions.items()},
       "positive_negative_test_natural_prevalence_unchanged":True,
       "all_trials_validation_only":trials,
       "selected_model":chosen,
       "selection_rule":"MAX_VALIDATION_PR_AUC_THEN_ROC",
       "selected_validation_threshold":threshold,
       "fresh_unseen_test":hold,
       "top_k_review_utility":triage(ytest,hold_pred),
       "targets90":{x:hold[x]>=.9 for x in
                    ("accuracy","roc_auc","precision","recall","f1")},
       "no_test_tuning":True,"not_Taiwan_financial_model":True,
       "not_as_filed_certified":True,
       "duration_seconds":round(time.monotonic()-begin,2),
    }
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    import joblib
    joblib.dump(model,out/"new_heldout_rusboost_best.joblib",compress=3)
    pd.DataFrame({
        "gvkey":test.gvkey.astype(str).to_numpy(),
        "fyear":test.fyear.to_numpy(dtype=int),
        "misstate":ytest,
        "score":hold_pred,
        "prediction":(hold_pred>=threshold).astype(int)
    }).to_csv(out/"new_heldout_rusboost_predictions.csv.gz",
              index=False,compression="gzip")
    (out/"real_rusboost_cost_sensitive_results.json").write_text(
        json.dumps(outcome,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
        encoding="utf-8")
    print("TEST_RESULTS",json.dumps({
        "name":chosen,"holdout":hold,"duration":outcome["duration_seconds"],
    }),flush=True)
    return outcome

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-csv",required=True)
    p.add_argument("--output-dir",required=True)
    x=p.parse_args()
    run(x.source_csv,x.output_dir)
if __name__=="__main__":
    main()
