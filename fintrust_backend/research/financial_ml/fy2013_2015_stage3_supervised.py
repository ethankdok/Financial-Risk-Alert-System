"""FY2013-2015 Stage 3 — actual supervised evaluation ONLY with audited 0/1.

Target = retrospectively verified material ORIGINAL annual restatement within
a fixed five-year horizon; this is NOT a demonstrated fraud probability.
ALL input features come from original FY2013–15 reports, never later years.
Issuer-disjoint fit/validation/test, per-FY outcome pairing in each partition,
validation-only model/threshold selection and untouched one-shot holdout.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter,defaultdict
from pathlib import Path
from .annual_panel_readiness import METRICS
from .fy2013_2015_stage1_freeze import YEARS
from .fy2013_2015_stage2_labels import ACCEPTED_FIELDS,TARGET
from .round8_human_supervised_classifier import feature_matrix,score
from .round10_disclosure_event_label_gate import cohort

MIN_TOTAL={0:24,1:12}

def load_approved(path):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        rd=csv.DictReader(f)
        if not set(ACCEPTED_FIELDS).issubset(rd.fieldnames or []):
            raise ValueError("fy1315_supervised_requires_stage2_audited_csv")
        rows=list(rd)
    seen=set();records=[]
    approved_issuer_universe=set(cohort())
    for r in rows:
        k=(r["ticker"],int(r["fiscal_year"]))
        if (k in seen or k[1] not in YEARS or k[0]=="1785"
            or k[0] not in approved_issuer_universe
            or r["label_target"]!=TARGET
            or r["label"] not in ("0","1")
            or not r["original_sha256"]):
            raise ValueError("fy1315_not_approved_original_fiscal_sample")
        seen.add(k)
        values=[]
        for m in METRICS:
            try: v=float(r[m])
            except (TypeError,ValueError):
                raise ValueError("fy1315_missing_financial_amount:"+m)
            if not __import__("math").isfinite(v):
                raise ValueError("fy1315_nonfinite_original_financial_amount")
            values.append(v)
        records.append({"ticker":k[0],"fiscal_year":k[1],
                        "label":int(r["label"]),"features":values})
    return records

def same_fy_pairs(cases):
    by=defaultdict(Counter)
    for x in cases:by[x["fiscal_year"]][x["label"]]+=1
    return len(by)==3 and all(by[year][0]>=1 and by[year][1]>=1
                              for year in YEARS)

def choose_company_disjoint(cases,*,random_state=20261020):
    """Independent company groups, deterministic first eligible split.

    StratifiedGroupKFold uses labels only for group assignment; it never
    trains the model or uses holdout performance for selection. The first
    deterministic admissible set is locked, not the highest-performing set.
    """
    import numpy as np
    from sklearn.model_selection import StratifiedGroupKFold
    y=np.array([x["label"] for x in cases],dtype=int)
    company=np.array([x["ticker"] for x in cases])
    ids=np.arange(len(cases))
    for seed in range(random_state,random_state+20):
        outer=StratifiedGroupKFold(n_splits=4,shuffle=True,random_state=seed)
        for remain_idx,test_idx in outer.split(ids,y,company):
            # Holdout has approximately 25% of issuers.
            remaining=ids[remain_idx]
            valgen=StratifiedGroupKFold(n_splits=3,shuffle=True,
                                        random_state=seed+1000)
            for fit_part,val_part in valgen.split(
                    remaining,y[remaining],company[remaining]):
                fit_idx=remaining[fit_part]
                val_idx=remaining[val_part]
                parts={
                    "fit":[cases[i] for i in fit_idx],
                    "validation":[cases[i] for i in val_idx],
                    "test":[cases[i] for i in test_idx],
                }
                if not all(same_fy_pairs(v) for v in parts.values()):
                    continue
                n={
                    part:Counter(x["label"] for x in subset)
                    for part,subset in parts.items()
                }
                if not (
                    n["fit"][1]>=6 and n["fit"][0]>=12 and
                    n["validation"][1]>=3 and n["validation"][0]>=6 and
                    n["test"][1]>=3 and n["test"][0]>=6):
                    continue
                issuers={part:{x["ticker"] for x in subset}
                         for part,subset in parts.items()}
                if (issuers["fit"]&issuers["validation"] or
                    issuers["fit"]&issuers["test"] or
                    issuers["validation"]&issuers["test"]):
                    raise AssertionError("fy1315_bug_issuer_disjoint")
                return parts,{
                    "split_seed":seed,
                    "split_procedure":"FIRST_ELIGIBLE_STRATIFIED_GROUP_FOLD_NOT_SCORE_SELECTED",
                    "fit_issuers":len(issuers["fit"]),
                    "validation_issuers":len(issuers["validation"]),
                    "test_issuers":len(issuers["test"]),
                }
    return None,{"reason":"NO_YEAR_MATCHED_COMPANY_DISJOINT_0_1_SPLIT_WITH_MIN_COUNTS"}

def train(approved_csv,label_gate_json,output):
    import numpy as np
    from sklearn.dummy import DummyClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import RobustScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score,f1_score
    out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("fy1315_supervised_output_immutable")
    panel_hash=hashlib.sha256(Path(approved_csv).read_bytes()).hexdigest()
    info=json.loads(Path(label_gate_json).read_text(encoding="utf-8"))
    if (info.get("status")!="FY1315_HUMAN_REVIEW_GATE_COMPLETE"
        or info.get("approved_panel_sha256")!=panel_hash):
        raise ValueError("fy1315_approved_label_file_not_cryptographically_bound_to_gate")
    rows=load_approved(approved_csv)
    counts=Counter(x["label"] for x in rows)
    manifest={
        "research_scope":"FY2013_FY2014_FY2015_ONLY",
        "model_input_years":list(YEARS),
        "sample_unit":"issuer_fiscal_year",
        "supervised_target":TARGET,
        "not_a_fraud_verdict":True,
        "approved_source_panel_sha256":panel_hash,
        "approved_0":counts[0],"approved_1":counts[1],
        "original_1785_final_case_excluded":True,
        "status":"STOPPED_NOT_ENOUGH_CERTIFIED_YEAR_MATCHED_0_1",
        "classifier_evaluation":None,
        "test_precision":None,"test_recall":None,"test_f1":None,
        "test_pr_auc":None,"test_confusion_matrix":None,
        "fit_issuers_repeat_in_test":False,
        "no_future_financial_amount_features":True,
    }
    split=None;splitmeta={}
    if (counts[0]>=MIN_TOTAL[0] and counts[1]>=MIN_TOTAL[1]
        and same_fy_pairs(rows)):
        split,splitmeta=choose_company_disjoint(rows)
    if split is not None:
        def arrays(part):
            obs=split[part]
            return (feature_matrix(obs),
                    np.array([x["label"] for x in obs],dtype=int))
        xfit,yfit=arrays("fit")
        xval,yval=arrays("validation")
        xtest,ytest=arrays("test")
        candidates={
            "dummy_prior":DummyClassifier(strategy="prior"),
            "logistic_balanced":Pipeline([
                ("scale",RobustScaler()),
                ("model",LogisticRegression(max_iter=1600,
                    class_weight="balanced",random_state=20261020))
            ]),
            "random_forest_balanced":RandomForestClassifier(
                n_estimators=250,max_depth=5,min_samples_leaf=2,
                class_weight="balanced",random_state=20261020,n_jobs=2),
        }
        comparisons=[]
        winners=[]
        for name,model in candidates.items():
            model.fit(xfit,yfit)
            vprob=model.predict_proba(xval)[:,1]
            # This decision threshold is selected from VALIDATION only;
            # the test set is NEVER used in this process.
            grid=[round(t/20,2) for t in range(2,19)]
            threshold=max(grid,key=lambda t:(
                f1_score(yval,vprob>=t,zero_division=0),-abs(t-.5)))
            metrics=score(yval,vprob,threshold)
            comparisons.append({
                "model":name,"validation_pr_auc":metrics["pr_auc"],
                "validation_f1":metrics["f1_score"],
                "threshold_from_validation":threshold,
            })
            if name!="dummy_prior":
                winners.append((metrics["pr_auc"],metrics["f1_score"],name,threshold,model))
        _,_,chosen,t,model=max(winners,key=lambda x:(x[0],x[1]))
        pred=model.predict_proba(xtest)[:,1]
        hold=score(ytest,pred,t)
        per_year={}
        for year in YEARS:
            indices=[i for i,r in enumerate(split["test"])
                     if r["fiscal_year"]==year]
            per_year[str(year)]=score(ytest[indices],pred[indices],t)
        import joblib
        out.mkdir(parents=True,exist_ok=True)
        joblib.dump(model,out/"fy2013_15_approved_supervised_model.joblib")
        manifest.update({
            "status":"FY1315_APPROVED_0_1_SUPERVISED_MODEL_EVALUATED",
            "classifier_evaluation":{
                "selected_model":chosen,
                "selected_threshold_validation_only":t,
                "validation_model_comparison":comparisons,
                "holdout_test_metrics":hold,
                "holdout_metrics_by_fiscal_year":per_year,
                "training_rows":len(split["fit"]),
                "validation_rows":len(split["validation"]),
                "holdout_rows":len(split["test"]),
                "split_properties":splitmeta,
                "feature_count":int(xfit.shape[1]),
                "feature_definitions":"12 signed-log original amounts + 6 ratios",
                "holdout_once_no_retraining":True,
            },
            "test_precision":hold["precision"],"test_recall":hold["recall"],
            "test_f1":hold["f1_score"],"test_pr_auc":hold["pr_auc"],
            "test_confusion_matrix":{
                k:hold[k] for k in ("tn","fp","fn","tp")},
        })
    else:
        manifest["eligibility_blockers"]={
            "minimum_required":MIN_TOTAL,
            "same_fiscal_year_has_0_and_1_for_all_three":same_fy_pairs(rows),
            "split_gate":splitmeta,
            "valid_original_first_filing_cases":len(rows),
        }
        out.mkdir(parents=True,exist_ok=True)
    (out/"fy2013_15_supervised_study_report.json").write_text(
        json.dumps(manifest,indent=2,ensure_ascii=False,allow_nan=False)+"\n",
        encoding="utf-8")
    return manifest

def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--approved-csv",required=True)
    p.add_argument("--label-gate",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args(argv)
    x=train(a.approved_csv,a.label_gate,a.out)
    print(json.dumps(x,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
