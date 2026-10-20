"""Enhanced real AAER supervised benchmark, precommitted new holdouts.

True published dataset, no invented Taiwan labels, no threshold tuning on test.
Two TEST protocols:
  fresh COMPANY-heldout split seeded differently from baseline;
  strict company-disjoint + out-of-time FY2008-2012 test (train <=2004,
  validation FY2005-07), avoiding the FY2013-14 right-censored shortage
  of AAER positive labels. Lagged features are from prior year only.
Neither protocol uses the old baseline test for hyperparameter selection.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    roc_auc_score,average_precision_score,precision_score,recall_score,
    f1_score,confusion_matrix,accuracy_score)
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler,FunctionTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.dummy import DummyClassifier

from .published_aaer_real_supervised import (
    read_original,FEATURES,RAW_FEATURES,RATIOS,signed_log,SOURCE_URL)

SEED=20261023
LAGS=("sale","at","ni","rect","invt","che","cogs","lt","lct","ib")
COMMON=("sale","at","ni","act","lct","lt","invt","che","cogs")
SAFE_RATIOS=("total_debt_to_assets","cash_to_assets","inventory_to_assets",
    "net_profit_margin","gross_margin","asset_turnover","working_capital_to_assets",
    "current_ratio","cogs_to_sales")
EXPERIMENTS=(
    ("logistic_full","logit","full",0),
    ("lgbm_full","lgbm","full",0),
    ("lgbm_full_conservative","lgbm","full",1),
    ("lgbm_under10","lgbm","full",2),
    ("lgbm_common9","lgbm","common",0),
    ("xgb_full","xgb","full",0),
    ("catboost_full","catboost","full",0),
)

def safe_ratio(n,d):
    x=pd.to_numeric(n,errors="coerce")
    y=pd.to_numeric(d,errors="coerce")
    v=x/y.replace(0,np.nan)
    return v.replace([np.inf,-np.inf],np.nan).clip(-100,100)

def engineer(df):
    # All engineered features are computed from the currently reported FY or
    # PREVIOUS fiscal year ONLY; no target labels nor later-year reports enter.
    df=df.sort_values(["gvkey","fyear"]).copy()
    prev_year=df.groupby("gvkey",sort=False)["fyear"].shift(1)
    matched=prev_year.eq(df["fyear"]-1)
    for key in LAGS:
        prior=df.groupby("gvkey",sort=False)[key].shift(1).where(matched)
        df[key+"_lag1"]=prior
        df[key+"_delta_1yr"]=safe_ratio(df[key]-prior,prior.abs()+1)
    df["total_debt_to_assets"]=safe_ratio(df["lt"],df["at"])
    df["cash_to_assets"]=safe_ratio(df["che"],df["at"])
    df["inventory_to_assets"]=safe_ratio(df["invt"],df["at"])
    df["net_profit_margin"]=safe_ratio(df["ni"],df["sale"])
    df["gross_margin"]=safe_ratio(df["sale"]-df["cogs"],df["sale"])
    df["asset_turnover"]=safe_ratio(df["sale"],df["at"])
    df["working_capital_to_assets"]=safe_ratio(df["act"]-df["lct"],df["at"])
    df["current_ratio"]=safe_ratio(df["act"],df["lct"])
    df["cogs_to_sales"]=safe_ratio(df["cogs"],df["sale"])
    return df

ALL_FEATURES=tuple(FEATURES)+tuple(k+"_lag1" for k in LAGS)+tuple(k+"_delta_1yr" for k in LAGS)+SAFE_RATIOS
COMMON_FEATURES=COMMON+SAFE_RATIOS

def select_split(df,mode):
    companies=df.groupby("gvkey")["misstate"].max()
    issuer=companies.index.astype(str).to_numpy()
    labels=companies.to_numpy().astype(int)
    trainco,otherco=train_test_split(
        issuer,train_size=.70,random_state=SEED,stratify=labels)
    lookup=dict(zip(issuer,labels))
    otherlabels=np.array([lookup[g] for g in otherco])
    valco,testco=train_test_split(
        otherco,train_size=.5,random_state=SEED+1,stratify=otherlabels)
    allowed={"train":set(trainco),"validation":set(valco),"test":set(testco)}
    if len(set.union(*allowed.values()))!=len(companies) or any(
        allowed[x]&allowed[y] for x,y in
        (("train","validation"),("train","test"),("validation","test"))):
        raise AssertionError("company overlap in split")
    out={}
    for split,ids in allowed.items():
        part=df[df["gvkey"].isin(ids)]
        if mode=="forward_year_and_issuer":
            date_lim={
                "train":lambda x:x<=2004,
                "validation":lambda x:(x>=2005)&(x<=2007),
                "test":lambda x:(x>=2008)&(x<=2012)}
            part=part.loc[date_lim[split](part["fyear"])]
        out[split]=part.copy()
        positives=int((part["misstate"]==1).sum())
        negatives=int((part["misstate"]==0).sum())
        if positives<12 or negatives<100:
            raise ValueError(f"Insufficient true AAER events for {mode}:{split}: {positives}/{negatives}")
    return out

def model_setup(kind,variant,negative_ratio):
    if kind=="logit":
        return Pipeline([
            ("impute",SimpleImputer(strategy="median",add_indicator=True,
                                   keep_empty_features=True)),
            ("signedlog",FunctionTransformer(signed_log)),
            ("scale",RobustScaler()),
            ("model",LogisticRegression(solver="liblinear",max_iter=700,
                  C=.15,class_weight="balanced",random_state=SEED))
        ])
    if kind=="lgbm":
        from lightgbm import LGBMClassifier
        kwargs=dict(
            n_estimators=420 if variant!=1 else 650,
            learning_rate=.035 if variant!=1 else .022,
            num_leaves=15 if variant!=1 else 9,
            max_depth=-1 if variant!=1 else 5,
            min_child_samples=125 if variant!=1 else 225,
            reg_alpha=1.0 if variant!=1 else 4.0,
            reg_lambda=10.0 if variant!=1 else 25.0,
            colsample_bytree=.82,subsample=.85,subsample_freq=1,
            n_jobs=2,verbosity=-1,random_state=SEED,
            scale_pos_weight=6 if variant!=2 else 1,
        )
        return LGBMClassifier(**kwargs)
    if kind=="xgb":
        from xgboost import XGBClassifier
        return XGBClassifier(
            n_estimators=420,max_depth=3,learning_rate=.045,
            min_child_weight=16,colsample_bytree=.8,subsample=.8,
            reg_alpha=2,reg_lambda=15,gamma=1.0,
            scale_pos_weight=7,tree_method="hist",n_jobs=2,
            eval_metric="logloss",random_state=SEED)
    if kind=="catboost":
        from catboost import CatBoostClassifier
        return CatBoostClassifier(
            iterations=500,depth=5,learning_rate=.045,
            l2_leaf_reg=12,auto_class_weights=None,
            class_weights=[1,6],loss_function="Logloss",
            thread_count=2,verbose=False,random_seed=SEED)
    raise ValueError(kind)

def metric(y,p,t):
    y=np.asarray(y,dtype=int);p=np.asarray(p,dtype=float)
    hard=(p>=t).astype(int)
    tn,fp,fn,tp=(int(z) for z in confusion_matrix(y,hard,labels=[0,1]).ravel())
    return {
        "threshold":float(t),"records":len(y),"positive_count":int(y.sum()),
        "positive_prevalence":float(y.mean()),
        "precision":float(precision_score(y,hard,zero_division=0)),
        "recall":float(recall_score(y,hard,zero_division=0)),
        "f1":float(f1_score(y,hard,zero_division=0)),
        "accuracy":float(accuracy_score(y,hard)),
        "roc_auc":float(roc_auc_score(y,p)),
        "pr_auc_average_precision":float(average_precision_score(y,p)),
        "confusion":{"TN":tn,"FP":fp,"FN":fn,"TP":tp},
    }

def validation_threshold(y,prob):
    thresholds=np.unique(np.r_[np.linspace(.01,.99,80),
                  np.quantile(prob,np.linspace(.5,.999,80))])
    best=max(thresholds,key=lambda t:(
        f1_score(y,prob>=t,zero_division=0),-abs(float(t)-.5)))
    return float(best)

def triage(y,p,top_sizes=(50,100,250,500,1000)):
    positions=np.argsort(-np.asarray(p))
    out={}
    for n in top_sizes:
        if n>len(y):continue
        labels=np.asarray(y)[positions[:n]]
        out[f"top_{n}"]={
            "alerts":n,"true_positives":int(labels.sum()),
            "precision_at_k":float(labels.mean()),
            "recall_at_k":float(labels.sum()/max(1,sum(y)))}
    return out

def run(source,output):
    begin=time.monotonic()
    df,digest=read_original(source)
    if digest!="ed4cefd9db2a23d0a13911d9f482fc755d3dcf6c9be0bc051af95ddcae5b286f":
        raise ValueError("Unexpected change to frozen published source SHA-256")
    # Use published source's full 1991-2014 panel. Any later years are barred.
    if int(df.fyear.max())!=2014:
        raise ValueError("Unexpected source fiscal-year horizon")
    df=engineer(df)
    output=Path(output)
    output.mkdir(parents=True,exist_ok=True)
    experiments={}
    for mode in ("new_company_holdout","forward_year_and_issuer"):
        spl=select_split(df,mode)
        val=spl["validation"];fit=spl["train"];test=spl["test"]
        vf=val["misstate"].to_numpy(dtype=int)
        yf=fit["misstate"].to_numpy(dtype=int)
        yt=test["misstate"].to_numpy(dtype=int)
        diagnostics={part:{
            "companies":int(z["gvkey"].nunique()),
            "rows":int(len(z)),"positive":int(z["misstate"].sum()),
            "negative":int((z["misstate"]==0).sum()),
            "fiscal_year_min":int(z.fyear.min()),
            "fiscal_year_max":int(z.fyear.max()),
            } for part,z in spl.items()}
        candidate_rows=[]
        selected=None
        for name,kind,feature_set,variant in EXPERIMENTS:
            features=ALL_FEATURES if feature_set=="full" else COMMON_FEATURES
            x_train=fit.loc[:,features].to_numpy(dtype=float)
            x_val=val.loc[:,features].to_numpy(dtype=float)
            fit_y=yf
            if variant==2:
                # Downsample negatives ONLY inside training. Never rebalance
                # validation or test; they retain real fraud prevalence.
                rng=np.random.default_rng(SEED)
                pos=np.flatnonzero(fit_y==1)
                neg=np.flatnonzero(fit_y==0)
                keep=np.sort(np.r_[pos,rng.choice(
                    neg,size=min(len(neg),10*len(pos)),replace=False)])
                x_train=x_train[keep];fit_y=fit_y[keep]
            try:
                model=model_setup(kind,variant,feature_set)
                model.fit(x_train,fit_y)
                pv=np.asarray(model.predict_proba(x_val)[:,1],dtype=float)
                if not np.all(np.isfinite(pv)):
                    raise ValueError("non-finite predictions")
                t=validation_threshold(vf,pv)
                measures=metric(vf,pv,t)
                candidate_rows.append({
                    "name":name,
                    "input_feature_count":len(features),
                    "training_rows_seen":len(fit_y),
                    "validation":measures})
                print("VAL",mode,name,"PR-AUC",round(measures["pr_auc_average_precision"],5),
                      "ROC-AUC",round(measures["roc_auc"],5),"F1",round(measures["f1"],5),
                      flush=True)
                if selected is None or (
                    measures["pr_auc_average_precision"],measures["roc_auc"]) > (
                    selected["val_pr"],selected["val_roc"]):
                    selected={
                        "model":model,"name":name,"features":features,
                        "threshold":t,
                        "val_pr":measures["pr_auc_average_precision"],
                        "val_roc":measures["roc_auc"],
                    }
            except Exception as exc:
                # Do NOT quietly drop model failures without recording them.
                candidate_rows.append({"name":name,"status":"MODEL_FAILED",
                    "error":str(exc)[:350]})
                print("MODEL_FAILED",mode,name,repr(exc),flush=True)
        if selected is None:
            raise RuntimeError("All precommitted AAER candidate models failed")
        xt=test.loc[:,selected["features"]].to_numpy(dtype=float)
        predicted=np.asarray(selected["model"].predict_proba(xt)[:,1],dtype=float)
        hold=metric(yt,predicted,selected["threshold"])
        # No additional model selections, threshold adjustments or tuning
        # based on TEST outcome. These metrics are observational only.
        test_top=triage(yt,predicted)
        result={
            "status":"COMPLETED_REAL_LABELED_EXTERNAL_AAER_SUPERVISION",
            "mode":mode,"splits":diagnostics,
            "selection":"PRECOMMITTED_HIGHEST_VALIDATION_PR_AUC_THEN_ROC_AUC",
            "selected_model":selected["name"],
            "selected_features":list(selected["features"]),
            "selected_threshold_from_validation_only":selected["threshold"],
            "all_candidates_validation_only":candidate_rows,
            "unchanged_test_prevalence":float(yt.mean()),
            "test":hold,"top_k_without_test_tuning":test_top,
            "target_90_roc_auc_achieved":hold["roc_auc"]>=.9,
            "target_90_precision_achieved":hold["precision"]>=.9,
            "target_90_recall_achieved":hold["recall"]>=.9,
            "target_90_f1_achieved":hold["f1"]>=.9,
            "NO_90_PERCENT_GUARANTEE":True,
        }
        experiments[mode]=result
        output_name=output/(mode+"_holdout_scores.csv.gz")
        pd.DataFrame({
            "gvkey":test["gvkey"].astype(str).to_numpy(),
            "fyear":test["fyear"].astype(int).to_numpy(),
            "AAER_label":yt,"probability":predicted,
            "classification_at_validation_threshold":
                (predicted>=selected["threshold"]).astype(int)
        }).to_csv(output_name,index=False,compression="gzip")
        import joblib
        joblib.dump(selected["model"],output/(mode+"_best_model.joblib"),compress=3)
        # Model group/year split descriptions, no sample memorization.
        print("TEST",mode,json.dumps(hold,allow_nan=False),flush=True)
    report={
        "status":"REAL_AAER_ENHANCED_VALIDATED_MULTIMODEL_TRAINING",
        "publication":"Bao et al. 2020 Journal of Accounting Research",
        "source_url":SOURCE_URL,"source_sha256":digest,
        "label_0":int((df.misstate==0).sum()),
        "label_1":int((df.misstate==1).sum()),
        "labeled_issuer_year_count":int(len(df)),
        "unique_issuers":int(df.gvkey.nunique()),
        "input_source_years":[int(df.fyear.min()),int(df.fyear.max())],
        "year_t_for_features_never_exceeds_filing_year":True,
        "lagged_input_only_if_prior_year_is_consecutive":True,
        "NOT_TAIWAN_VALIDATED":True,
        "not_time_stamped_first_original_filing_certified":True,
        "negative_AAER_controls_not_verified_clean":True,
        "right_censored_source_FY2013_14_excluded_from_forward_year_evaluation":True,
        "no_test_based_model_or_threshold_selection":True,
        "top_level_outcome_can_be_below_90":True,
        "duration_seconds":round(time.monotonic()-begin,2),
        "experiments":experiments,
    }
    (output/"enhanced_real_aaer_multimodel_results.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
        encoding="utf-8")
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-csv",required=True)
    p.add_argument("--output-dir",required=True)
    args=p.parse_args()
    result=run(args.source_csv,args.output_dir)
    print("FINAL",json.dumps({
        "status":result["status"],
        "results":{k:{
            "selected_model":v["selected_model"],
            "ROC-AUC":v["test"]["roc_auc"],
            "PR-AUC":v["test"]["pr_auc_average_precision"],
            "Precision":v["test"]["precision"],
            "Recall":v["test"]["recall"],
            "F1":v["test"]["f1"],
        } for k,v in result["experiments"].items()},
    },allow_nan=False),flush=True)

if __name__=="__main__":
    main()
