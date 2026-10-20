"""FinTrust reproducible real AAER-labeled supervised experiment.

PUBLIC AUTHOR-CURATED SOURCE (not synthetic, not Taiwan, not manually verified here):
Bao et al. (2020) JAR, github.com/JarFraud/FraudDetection
File: data_FraudDetection_JAR2020.csv
Label: misstate = AAER-identified reporting misstatement, 0 = comparison.
Features: 28 accounting amounts + 14 accounting ratios, explicitly exclude
misstate, p_aaer and any identifiers/timestamps from the predictors.

Evaluation: entire companies held out from each other (no gvkey crossover).
Validation selects threshold/model; untouched test scored once. Class imbalance
shown, no made-up fraud accuracy; non-AAER 0 does not prove absence of fraud.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd

from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier,HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (average_precision_score,roc_auc_score,
    precision_score,recall_score,f1_score,accuracy_score,balanced_accuracy_score,
    confusion_matrix)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import FunctionTransformer,RobustScaler

SOURCE_URL="https://raw.githubusercontent.com/JarFraud/FraudDetection/master/data_FraudDetection_JAR2020.csv"
AAER_FIRM_YEAR_URL="https://github.com/JarFraud/FraudDetection/blob/master/AAER_firm_year.csv"
RAW_FEATURES=("act","ap","at","ceq","che","cogs","csho","dlc","dltis","dltt","dp","ib",
              "invt","ivao","ivst","lct","lt","ni","ppegt","pstk","re","rect",
              "sale","sstk","txp","txt","xint","prcc_f")
RATIOS=("dch_wc","ch_rsst","dch_rec","dch_inv","soft_assets","ch_cs",
        "ch_cm","ch_roa","issue","bm","dpi","reoa","EBIT","ch_fcf")
FEATURES=RAW_FEATURES+RATIOS
LEAKAGE={"misstate","p_aaer","gvkey","fyear","cik","AAER","misstatement","fraud"}
SEED=20261020

def signed_log(x):
    x=np.asarray(x,dtype=np.float64)
    return np.sign(x)*np.log1p(np.abs(x))

def read_original(source):
    path=Path(source)
    if not path.exists() or path.stat().st_size<4_000_000:
        raise ValueError("JAR2020 real published source file missing or suspiciously small")
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    df=pd.read_csv(path,low_memory=False)
    missing=sorted(set(FEATURES)|{"misstate","gvkey","fyear"}-set(df.columns))
    missing=sorted((set(FEATURES)|{"misstate","gvkey","fyear"})-set(df.columns))
    if missing:
        raise ValueError("Source was not JAR2020 fraud dataset; missing "+str(missing))
    df=df.loc[:,["misstate","gvkey","fyear",*FEATURES]].copy()
    df["misstate"]=pd.to_numeric(df["misstate"],errors="raise")
    df["fyear"]=pd.to_numeric(df["fyear"],errors="raise")
    df["gvkey"]=df["gvkey"].astype("string").str.strip()
    df=df[df["fyear"].between(1991,2024)].copy()
    if len(df)<30_000 or not set(df["misstate"].unique())<={0,1}:
        raise ValueError("JAR2020 fraud dataset failed real year/sample/label checks")
    if df["gvkey"].isna().any() or (df["gvkey"]=="").any():
        raise ValueError("JAR2020 source has missing company identifier")
    if df.duplicated(["gvkey","fyear"]).any():
        raise ValueError("JAR2020 contains duplicate firm-year; do not silently delete")
    for col in FEATURES:
        df[col]=pd.to_numeric(df[col],errors="coerce").replace([np.inf,-np.inf],np.nan)
    return df,digest

def firm_split(df):
    issuer=df.groupby("gvkey",sort=True)["misstate"].max().reset_index()
    companies=issuer["gvkey"].astype(str).to_numpy()
    is_case=issuer["misstate"].to_numpy().astype(int)
    if sum(is_case)<25:
        raise ValueError("Not enough positive companies for issuer-disjoint test")
    trainco,remainco=train_test_split(companies,test_size=.30,random_state=SEED,
                                    stratify=is_case)
    case_by_firm=dict(zip(companies,is_case))
    case_remaining=np.array([case_by_firm[z] for z in remainco])
    valco,testco=train_test_split(remainco,test_size=.5,random_state=SEED+1,
                                 stratify=case_remaining)
    split={"train":set(trainco),"validation":set(valco),"test":set(testco)}
    assert not (split["train"]&split["validation"] or
                split["train"]&split["test"] or split["validation"]&split["test"])
    assigned=np.select(
        [df["gvkey"].isin(split["train"]),df["gvkey"].isin(split["validation"]),
         df["gvkey"].isin(split["test"])],
        ["train","validation","test"],default="UNASSIGNED")
    if "UNASSIGNED" in assigned:
        raise ValueError("Unassigned original company split")
    df=df.copy()
    df["split"]=assigned
    counts={}
    for name,part in df.groupby("split"):
        counts[name]={"rows":int(len(part)),
                      "issuers":int(part["gvkey"].nunique()),
                      "positives":int(part["misstate"].sum()),
                      "negatives":int((part["misstate"]==0).sum()),
                      "base_rate":float(part["misstate"].mean())}
        if min(counts[name]["positives"],counts[name]["negatives"])<10:
            raise ValueError("Unexpected severe split imbalance "+str(counts))
    return df,counts

def metric(y,prob,t):
    y=np.asarray(y,dtype=int)
    prob=np.asarray(prob,dtype=float)
    chosen=(prob>=t).astype(int)
    a,b,c,d=map(int,confusion_matrix(y,chosen,labels=[0,1]).ravel())
    return {"threshold":round(float(t),6),"samples":int(len(y)),
            "prevalence":float(y.mean()),"true_negative":a,
            "false_positive":b,"false_negative":c,"true_positive":d,
            "precision":float(precision_score(y,chosen,zero_division=0)),
            "recall":float(recall_score(y,chosen,zero_division=0)),
            "f1":float(f1_score(y,chosen,zero_division=0)),
            "pr_auc_average_precision":float(average_precision_score(y,prob)),
            "roc_auc":float(roc_auc_score(y,prob)),
            "accuracy":float(accuracy_score(y,chosen)),
            "balanced_accuracy":float(balanced_accuracy_score(y,chosen))}

def pipeline(name,fit_prevalence):
    pre=[("impute",SimpleImputer(strategy="median",keep_empty_features=True)),
         ("signed_log",FunctionTransformer(signed_log)),
         ("scale",RobustScaler())]
    if name=="dummy_prior":
        return Pipeline(pre+[("model",DummyClassifier(strategy="prior"))])
    if name=="logistic_balanced":
        return Pipeline(pre+[("model",LogisticRegression(
            solver="liblinear",class_weight="balanced",max_iter=500,
            random_state=SEED))])
    if name=="random_forest_balanced":
        return Pipeline(pre+[("model",RandomForestClassifier(
            n_estimators=110,max_depth=12,min_samples_leaf=12,
            class_weight="balanced_subsample",n_jobs=2,random_state=SEED))])
    raise ValueError("Unknown predeclared algorithm")

def run(source,output,limit=None):
    df,source_sha=read_original(source)
    raw_size=int(len(df));time_start=int(df["fyear"].min());time_end=int(df["fyear"].max())
    # Exclusion list is diagnostic only; fixed actual financial predictors.
    missing_rate={col:round(float(df[col].isna().mean()),4) for col in FEATURES}
    empty=[c for c in FEATURES if df[c].notna().sum()==0]
    if empty:raise ValueError("Published financial features all missing: "+str(empty))
    ds,counts=firm_split(df)
    partitions={p:ds.loc[ds["split"]==p] for p in ("train","validation","test")}
    arrays={p:(data.loc[:,FEATURES].to_numpy(dtype=float),
                data["misstate"].to_numpy(dtype=int))
            for p,data in partitions.items()}
    xfit,yfit=arrays["train"]
    xval,yval=arrays["validation"]
    xtest,ytest=arrays["test"]
    results=[]
    fitted={}
    # ONLY original JAR misstate label, no retrospective p_aaer as feature
    for model_name in ("dummy_prior","logistic_balanced","random_forest_balanced"):
        model=pipeline(model_name,float(yfit.mean()))
        model.fit(xfit,yfit)
        vp=model.predict_proba(xval)[:,1]
        if model_name=="dummy_prior":
            threshold=.5
        else:
            grid=np.linspace(.01,.80,80)
            f1s=[f1_score(yval,vp>=t,zero_division=0) for t in grid]
            best=max(range(len(grid)),key=lambda i:(f1s[i],-abs(grid[i]-.5)))
            threshold=float(grid[best])
        report=metric(yval,vp,threshold)
        fitted[model_name]=(model,threshold)
        results.append({"model":model_name,"validation":report})
        print("VALIDATION",model_name,report["pr_auc_average_precision"],
              report["f1"],flush=True)
    candidates=[r for r in results if r["model"]!="dummy_prior"]
    champion=max(candidates,key=lambda r:(
        r["validation"]["pr_auc_average_precision"],r["validation"]["f1"]))
    name=champion["model"]
    m,t=fitted[name]
    testprob=m.predict_proba(xtest)[:,1]
    hold=metric(ytest,testprob,t)
    baseline,baseline_threshold=fitted["dummy_prior"]
    baseprob=baseline.predict_proba(xtest)[:,1]
    base_score=metric(ytest,baseprob,.5)
    print("TEST_RESULT",name,json.dumps(hold),flush=True)
    print("BASELINE_TEST",json.dumps(base_score),flush=True)
    top=[]
    estimator=m.named_steps["model"]
    if hasattr(estimator,"feature_importances_"):
        coeff=estimator.feature_importances_
    else:coeff=np.abs(estimator.coef_[0])
    top=sorted([{"name":key,"importance":float(val)} for key,val in zip(FEATURES,coeff)],
               key=lambda x:x["importance"],reverse=True)[:12]
    out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    labels=ds.loc[:,["gvkey","fyear","misstate","split"]].copy()
    labels=labels.sort_values(["split","gvkey","fyear"])
    labels.to_csv(out/"full_published_research_0_1_label_audit.csv.gz",
                  index=False,compression="gzip")
    holdout=partitions["test"].loc[:,["gvkey","fyear","misstate"]].copy()
    holdout["predicted_misstatement_score"]=testprob
    holdout["predicted_label_at_validation_threshold"]=(testprob>=t).astype(int)
    holdout.to_csv(out/"independent_holdout_predictions.csv.gz",
                   index=False,compression="gzip")
    import joblib
    joblib.dump(m,out/"frozen_published_AAER_supervised_model.joblib",compress=3)
    yr=ds.groupby("fyear")["misstate"].agg(["count","sum"]).reset_index()
    year_rows=[{"fyear":int(row["fyear"]),"observations":int(row["count"]),
                "aaer_positive":int(row["sum"])}
               for _,row in yr.iterrows()]
    report={
      "status":"REAL_PUBLISHED_AAER_LABELLED_SUPERVISED_TRAIN_AND_HOLDOUT_COMPLETE",
      "source_author_citation":"Bao, Ke, Li, Yu, Zhang (2020) Journal of Accounting Research 58(1):199-235",
      "source_url":SOURCE_URL,"source_dataset_sha256":source_sha,
      "population":"U.S. public Compustat firm-years 1991-2014, SEC AAER identified events",
      "NOT_TAIWAN_MODEL":True,"NOT_USER_MANUALLY_VERIFIED_EVERY_LABEL":True,
      "non_AAER_0_is_not_a_guarantee_of_clean_reporting":True,
      "historical_asfiled_input_version_not_independently_verified":True,
      "source_fy_min":time_start,"source_fy_max":time_end,
      "total_records":raw_size,"total_0":int((df["misstate"]==0).sum()),
      "total_1":int((df["misstate"]==1).sum()),
      "total_unique_companies":int(df["gvkey"].nunique()),
      "feature_count":len(FEATURES),
      "features":list(FEATURES),
      "explicitly_excluded_lookahead":["p_aaer","misstate","gvkey","fyear"],
      "split_method":"stratified by firm-ever-AAER, issuer-disjoint fixed 70/15/15",
      "split_counts":counts,
      "validation_model_comparison":results,
      "selected_model":name,
      "selected_threshold_validation_only":t,
      "untouched_holdout_metrics":hold,
      "dummy_holdout_metrics":base_score,
      "selected_model_top_12_feature_importances":top,
      "feature_missing_fraction":missing_rate,
      "labeled_distribution_by_fiscal_year":year_rows,
      "label_audit_file":"full_published_research_0_1_label_audit.csv.gz",
      "holdout_predictions_file":"independent_holdout_predictions.csv.gz",
      "frozen_model_file":"frozen_published_AAER_supervised_model.joblib",
      "caveat":"Externally curated AAER detection benchmark, not audited Taiwan original-as-of fraud alerts."
    }
    (out/"real_aaer_supervised_holdout_report.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
        encoding="utf-8")
    print("FINAL_SUMMARY",json.dumps({
        k:report[k] for k in ("status","total_records","total_0","total_1",
             "total_unique_companies","selected_model","untouched_holdout_metrics")}),
          flush=True)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-csv",required=True)
    p.add_argument("--output-dir",required=True)
    args=p.parse_args()
    run(args.source_csv,args.output_dir)

if __name__=="__main__":
    main()
