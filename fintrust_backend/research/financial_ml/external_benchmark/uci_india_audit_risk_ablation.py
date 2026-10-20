"""Independent UCI Audit Data risk-prediction demonstration.

The 2015-16 Indian Auditor Office data are NOT SEC/TAIWAN fraud cases.
'Risk' is an auditor-derived composite score target, NOT an independent
financial statement fraud adjudication. Results must always say so.

A naive model includes Audit_Risk/Inherent_Risk/CONTROL_RISK/Risk_A-F etc,
which leaks the risk formula into the model. Two honest ablations run:
  A. Raw observed factors only (no weights, computed sums, risk scores)
  B. Raw factors + individual auditor probability/weight inputs (still
     derived risk target, therefore a risk-assessment reproduction).
Input-identical rows cannot cross fit/validation/test via group splitting.
Test untouched; 0/1 prevalences reported; no fabricated observations.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesClassifier,RandomForestClassifier,HistGradientBoostingClassifier)
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,balanced_accuracy_score,confusion_matrix,
    f1_score,precision_score,recall_score,roc_auc_score,
    average_precision_score)
from sklearn.model_selection import GroupShuffleSplit
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler
from sklearn.svm import SVC

RAW=(
    "Sector_score","PARA_A","PARA_B","numbers",
    "Money_Value","District_Loss","History",
)
WEIGHTED=RAW+("Score_A","Score_B","Score_B.1","Score_MV","PROB","Prob")
LABEL="Risk"
LEAKY=(
    "Audit_Risk","Inherent_Risk","CONTROL_RISK","Detection_Risk",
    "Risk_A","Risk_B","Risk_C","Risk_D","RiSk_E","Risk_F",
    "TOTAL","Score",
)
SEED=20261020

def read(csv):
    path=Path(csv)
    raw=path.read_bytes()
    data=pd.read_csv(path,low_memory=False)
    if len(data)<700 or len(data)>800:
        raise ValueError("Unexpected UCI Audit Data row count")
    missing=sorted(set(WEIGHTED+(LABEL,))-set(data.columns))
    if missing:
        raise ValueError("Unexpected UCI Audit Data schema "+repr(missing))
    y=pd.to_numeric(data[LABEL],errors="raise").astype(int)
    if set(y.unique())!={0,1}:
        raise ValueError("UCI risk label must contain real 0 and 1")
    for feature in WEIGHTED:
        data[feature]=pd.to_numeric(data[feature].replace("?",np.nan),errors="coerce")
    # Unlike issuer-based SEC sets, this data does not provide a stable
    # company identifier. Prevent exact same raw observation duplicates from
    # appearing across any partitions using a group digest.
    key=data.loc[:,WEIGHTED].fillna(-9.87654321e19).round(8)
    grouping=pd.util.hash_pandas_object(key,index=False).astype("uint64").astype(str)
    return data,y,grouping,hashlib.sha256(raw).hexdigest()

def freeze_splits(data,y,groups):
    groups=np.asarray(groups,dtype=str)
    indices=np.arange(len(y))
    for seed in range(SEED,SEED+10):
        splitter=GroupShuffleSplit(n_splits=1,test_size=.20,random_state=seed)
        left,test=next(splitter.split(indices,y,groups))
        splitter2=GroupShuffleSplit(n_splits=1,test_size=.25,random_state=seed+100)
        xvalidx,yvalidx=next(splitter2.split(left,y.iloc[left],groups[left]))
        train,valid=left[xvalidx],left[yvalidx]
        blocks={"train":train,"validation":valid,"test":test}
        counts={k:{"0":int(sum(y.iloc[v]==0)),"1":int(sum(y.iloc[v]==1))}
                for k,v in blocks.items()}
        if all(counts[k]["0"]>=12 and counts[k]["1"]>=12 for k in counts):
            uniques={k:set(groups[v]) for k,v in blocks.items()}
            if any(uniques[a]&uniques[b] for a,b in (
                ("train","validation"),("train","test"),("validation","test"))):
                raise AssertionError("duplicate observation crossed partitions")
            return blocks,counts,seed
    raise ValueError("Cannot create valid group-disjoint UCI split")

def make_model(kind):
    if kind=="extra_trees":
        clf=ExtraTreesClassifier(n_estimators=380,max_features=.85,
            min_samples_leaf=2,n_jobs=2,random_state=SEED,class_weight="balanced")
        return Pipeline([("impute",SimpleImputer(strategy="median")),
                         ("clf",clf)])
    if kind=="random_forest":
        clf=RandomForestClassifier(n_estimators=360,min_samples_leaf=2,
            max_features="sqrt",class_weight="balanced_subsample",
            random_state=SEED,n_jobs=2)
        return Pipeline([("impute",SimpleImputer(strategy="median")),
                         ("clf",clf)])
    if kind=="hist_gradient":
        clf=HistGradientBoostingClassifier(max_iter=250,max_leaf_nodes=9,
            learning_rate=.045,l2_regularization=4,
            random_state=SEED)
        return Pipeline([("impute",SimpleImputer(strategy="median")),
                         ("clf",clf)])
    if kind=="logistic":
        return Pipeline([("impute",SimpleImputer(strategy="median")),
            ("scale",RobustScaler()),
            ("clf",LogisticRegression(max_iter=1000,
                      class_weight="balanced",random_state=SEED))])
    if kind=="svm":
        return Pipeline([("impute",SimpleImputer(strategy="median")),
            ("scale",RobustScaler()),
            ("clf",SVC(C=2,gamma="scale",probability=True,
                       class_weight="balanced",random_state=SEED))])
    raise ValueError(kind)

def measures(y,p,t):
    y=np.asarray(y,dtype=int);p=np.asarray(p,dtype=float)
    hard=np.asarray(p>=t,dtype=int)
    tn,fp,fn,tp=map(int,confusion_matrix(y,hard,labels=[0,1]).ravel())
    return dict(n=int(len(y)),positive=int(y.sum()),
        negative=int((y==0).sum()),
        accuracy=float(accuracy_score(y,hard)),
        balanced_accuracy=float(balanced_accuracy_score(y,hard)),
        precision=float(precision_score(y,hard,zero_division=0)),
        recall=float(recall_score(y,hard,zero_division=0)),
        f1=float(f1_score(y,hard,zero_division=0)),
        roc_auc=float(roc_auc_score(y,p)),
        pr_auc=float(average_precision_score(y,p)),
        threshold=float(t),
        confusion={"TN":tn,"FP":fp,"FN":fn,"TP":tp})

def best_threshold(y,p):
    grid=np.unique(np.r_[np.linspace(.15,.85,71),
              np.quantile(p,np.linspace(.05,.95,41))])
    return float(max(grid,key=lambda t:(
       f1_score(y,np.asarray(p)>=t,zero_division=0),
       -abs(float(t)-.5))))

def run(path,out):
    df,y,groups,sha=read(path)
    partitions,counts,seed=freeze_splits(df,y,groups)
    experiments=[]
    score_rows=[]
    for tier,features in (("raw_factors_no_risk_weights",RAW),
                          ("raw_plus_auditor_weights",WEIGHTED)):
        for name in ("extra_trees","random_forest","hist_gradient",
                     "logistic","svm"):
            model=make_model(name)
            xtrain=df.iloc[partitions["train"]].loc[:,features]
            xval=df.iloc[partitions["validation"]].loc[:,features]
            yy=y.iloc[partitions["train"]]
            vv=y.iloc[partitions["validation"]]
            model.fit(xtrain,yy)
            prob=np.asarray(model.predict_proba(xval)[:,1])
            t=best_threshold(vv,prob)
            v=measures(vv,prob,t)
            experiments.append(dict(tier=tier,model=name,validation=v))
            score_rows.append((v["f1"],v["pr_auc"],v["roc_auc"],
                               tier,name,t,model,features))
            print("VALIDATION",tier,name,round(v["f1"],4),
                  round(v["roc_auc"],4),flush=True)
    # predeclared single champion: prefer raw-only when identical scores.
    champ=max(score_rows,key=lambda x:(x[0],x[1],x[2],
             x[3]=="raw_factors_no_risk_weights"))
    f1,ap,roc,tier,name,t,model,features=champ
    test=partitions["test"]
    p=np.asarray(model.predict_proba(df.iloc[test].loc[:,features])[:,1])
    final=measures(y.iloc[test],p,t)
    reference=None
    if "Audit_Risk" in df.columns:
        score=pd.to_numeric(df["Audit_Risk"],errors="coerce")
        for candidate in (1.0,0.99):
            prob=(score>candidate).astype(float)
            reference={
                "candidate_risk_threshold":candidate,
                "full_data_fraction_equal_to_label":float(
                    (prob.astype(int)==y).mean()),
            }
            if reference["full_data_fraction_equal_to_label"]>.99:break
    output=Path(out);output.mkdir(parents=True,exist_ok=True)
    import joblib
    joblib.dump(model,output/"uci_audit_risk_no_aggregate_score_model.joblib")
    predictions=pd.DataFrame({
        "row_number":test,
        "risk_label_0_1":y.iloc[test].to_numpy(),
        "model_prediction_score":p,
        "classification_at_validation_threshold":(p>=t).astype(int)})
    predictions.to_csv(output/"uci_audit_risk_untouched_holdout.csv",index=False)
    result={
        "dataset":"UCI Audit Data 2015-2016 India firms",
        "official_source":"https://archive.ics.uci.edu/dataset/475/audit+data",
        "uci_dataset_sha256":sha,
        "sample_count":int(len(df)),
        "class_0_count":int(sum(y==0)),
        "class_1_count":int(sum(y==1)),
        "target":"UCI-derived audit RISK score classification, NOT independently adjudicated financial fraud",
        "independent_misstatement_labels_exist":False,
        "training_validation_test_duplicate_groups_disjoint":True,
        "company_isolation_verified":False,
        "group_split_seed":seed,
        "split_counts":counts,
        "intentionally_forbidden_features":list(LEAKY),
        "critical_target_construction_caveat":
          "Even raw inspection risk inputs mathematically influence target Risk, so 90% classifying it cannot validate future financial misstatements.",
        "aggregate_audit_risk_threshold_matches_target":reference,
        "all_models_validation_only":experiments,
        "winner_selection":"MAX_VALIDATION_F1_THEN_PR_AUC_THEN_ROC_AUC",
        "winner_tier":tier,"winner_model":name,
        "selected_input_features":list(features),
        "selected_threshold_validation_only":t,
        "untouched_test":final,
        "goals_90pct":{"accuracy":final["accuracy"]>=.9,
                       "precision":final["precision"]>=.9,
                       "recall":final["recall"]>=.9,
                       "f1":final["f1"]>=.9,
                       "roc_auc":final["roc_auc"]>=.9,
                       "pr_auc":final["pr_auc"]>=.9},
        "not_Taiwan_fraud_detection":True,
        "not_compatible_as_direct_MOPS_original_report_fraud_model":True,
    }
    (output/"uci_audit_risk_nonleaky_model_report.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n",
        encoding="utf-8")
    print("FINAL",json.dumps({"winner":name,"tier":tier,"test":final,
                              "score_formula_match":reference}),flush=True)
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source-csv",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    run(a.source_csv,a.out)
if __name__=="__main__":
    main()
