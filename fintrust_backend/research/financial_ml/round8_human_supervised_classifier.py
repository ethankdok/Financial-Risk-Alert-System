"""Round8 — audited human labels -> supervised fiscal-year misstatement research.

Unreviewed issuer != healthy control. The official 1785 final case stays
outside training/validation/testing. Every approved 0/1 observation must cite
its original financial-report bytes, original publication notice and its
independently reviewed outcome / negative follow-up evidence. The model fits
only after enough positive AND negative samples in issuer+time disjoint sets.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

from .annual_panel_readiness import METRICS
from .round3_research_models import ANNUAL_COLUMNS

REVIEW_FIELDS=(
    "sample_key","ticker","fiscal_year","sample_grain",
    "candidate_financial_source_tier","proposed_outcome",
    "outcome_reason","positive_regulator_or_court_document",
    "negative_followup_review_document",
    "first_published_original_pdf_evidence",
    "first_publication_notice_evidence",
    "reviewer_a","reviewer_b","method_owner",
    "review_status","comments",
)
PANEL_FIELDS=(
    "ticker","fiscal_year","sample_grain","label","approval_status",
    "reviewer_a","reviewer_b","method_owner_approval",
    "outcome_definition","outcome_document_path","outcome_document_sha256",
    "outcome_publication_at","negative_followup_end_at",
    "original_report_path","original_report_sha256",
    "original_filing_publication_at","first_publication_notice_path",
    "first_publication_notice_sha256","original_vintage_verified",
    "finance_double_review_status",*METRICS
)
REPORT_KEYS=("accuracy","precision","recall","f1_score","balanced_accuracy",
             "roc_auc","pr_auc","tn","fp","fn","tp")
EXPECTED_SCHEMA="SUPERVISED_APPROVED_ORIGINAL_VINTAGE_V1"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows_from_csv(path,columns):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        rd=csv.DictReader(f)
        if not set(columns).issubset(rd.fieldnames or ()):
            raise ValueError("round8_csv_source_schema_changed:"+Path(path).name)
        return list(rd)


def csv_write(path,fields,rows):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="raise")
        w.writeheader();w.writerows(rows)


def prepare_labels(annual_index,output):
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("round8_review_packet_output_immutable")
    source=rows_from_csv(annual_index,ANNUAL_COLUMNS)
    if not source:
        raise ValueError("round8_empty_round1_issuer_panel")
    seen=set();pack=[]
    for r in source:
        ticker=r["ticker"]
        year=int(r["fiscal_year"])
        key=(ticker,year)
        if key in seen:raise ValueError("round8_duplicate_issuer_year")
        seen.add(key)
        if ticker=="1785":raise ValueError("round8_reserved_1785_in_original_round1")
        if not re.fullmatch(r"[0-9]{4}",ticker) or not 2013<=year<=2025:
            raise ValueError("round8_bad_issuer_year")
        if r["label_status"]!="UNKNOWN" or r["training_admitted"].lower()!="false":
            raise ValueError("round8_provisional_label_promotion_forbidden")
        if r["complete_candidate_vector"].lower()!="true":
            continue
        pack.append({
            "sample_key":f"{ticker}:{year}FY","ticker":ticker,
            "fiscal_year":year,"sample_grain":"issuer_fiscal_year",
            "candidate_financial_source_tier":"FINMIND_PROVISIONAL_NOT_CERTIFIED_ORIGINAL",
            "proposed_outcome":"UNKNOWN","outcome_reason":"",
            "positive_regulator_or_court_document":"",
            "negative_followup_review_document":"",
            "first_published_original_pdf_evidence":"",
            "first_publication_notice_evidence":"",
            "reviewer_a":"","reviewer_b":"","method_owner":"",
            "review_status":"PENDING_EVIDENCE_AND_APPROVAL","comments":"",
        })
    output.mkdir(parents=True,exist_ok=True)
    csv_write(output/"round8_human_label_review_queue.csv",REVIEW_FIELDS,pack)
    csv_write(output/"round8_approved_original_supervised_panel_TEMPLATE.csv",PANEL_FIELDS,[])
    manifest={
        "status":"ROUND8_LABEL_REVIEW_PACKET_PENDING_HUMAN_APPROVAL",
        "source_sha256":sha(annual_index),
        "original_provisional_rows":len(source),
        "reviewable_full_numeric_candidate_years":len(pack),
        "default_candidate_outcome":"UNKNOWN",
        "unreviewed_is_not_label_zero":True,
        "approved_training_records":0,
        "no_1785_training_rows":True,
        "source_tier":"FINMIND_PROVISIONAL_NOT_TREATED_AS_VERIFIED_FIRST_FILING",
        "approved_panel_is_separate_and_never_auto_filled_from_provisional":True,
    }
    (output/"round8_label_review_packet_report.json").write_text(
        json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return manifest


def verify_file(root,relative,hash_expected):
    if not re.fullmatch(r"[0-9a-f]{64}",hash_expected):
        raise ValueError("round8_evidence_sha256_unapproved")
    rel=Path(relative)
    if (not relative or rel.is_absolute() or ".." in rel.parts or
        "\\" in relative or any(p in (".","") for p in rel.parts)):
        raise ValueError("round8_evidence_path_unsafe_or_blank")
    candidate=(root/rel).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file() or candidate.is_symlink():
        raise ValueError("round8_evidence_file_missing_or_unsafe")
    if candidate.stat().st_size<12 or candidate.stat().st_size>65_000_000:
        raise ValueError("round8_evidence_file_size_incompatible")
    if sha(candidate)!=hash_expected:
        raise ValueError("round8_evidence_hash_changed")
    return candidate


def timestamp(v):
    dt=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("round8_historical_date_without_timezone")
    return dt.astimezone(timezone.utc)


def approved_rows(path,evidence_dir):
    root=Path(evidence_dir)
    source=rows_from_csv(path,PANEL_FIELDS)
    accepted=[]
    counts=Counter()
    keys=set()
    for r in source:
        t=str(r["ticker"]).strip();year=int(r["fiscal_year"])
        key=(t,year)
        if key in keys:
            raise ValueError("round8_duplicate_issuer_fiscal_year")
        keys.add(key)
        if t=="1785":
            # 1785 is the blinded FINAL CASE and must not become a model fit
            raise ValueError("round8_never_train_on_final_case_1785")
        if not re.fullmatch(r"[1-9][0-9]{3}",t) or not 2013<=year<=2025:
            raise ValueError("round8_invalid_issuer_or_annual_period")
        if r["label"] not in ("0","1"):
            counts["UNKNOWN_OR_DRAFT"]+=1;continue
        if (r["sample_grain"]!="issuer_fiscal_year"
            or r["approval_status"]!="APPROVED"
            or r["method_owner_approval"]!="APPROVED"
            or r["reviewer_a"]==r["reviewer_b"]
            or not r["reviewer_a"] or not r["reviewer_b"]
            or r["finance_double_review_status"] not in (
                "DOUBLE_REVIEWED_ORIGINAL_PDF","DOUBLE_REVIEWED_OFFICIAL_XBRL")
            or r["original_vintage_verified"]!="true"):
            counts["UNAPPROVED_OR_UNCERTIFIED"]+=1;continue
        original=verify_file(root,r["original_report_path"],r["original_report_sha256"])
        if original.suffix.lower() not in (".pdf",".xml",".zip",".xhtml",".html"):
            raise ValueError("round8_original_filing_evidence_not_financial_filing")
        notice=verify_file(root,r["first_publication_notice_path"],
                           r["first_publication_notice_sha256"])
        outcome=verify_file(root,r["outcome_document_path"],
                            r["outcome_document_sha256"])
        first=timestamp(r["original_filing_publication_at"])
        outcome_at=timestamp(r["outcome_publication_at"])
        if not (datetime(year,12,31,tzinfo=timezone.utc)<first
                and first<outcome_at
                and outcome_at<=datetime.now(timezone.utc)):
            raise ValueError("round8_future_or_backfilled_case_evidence")
        if r["label"]=="1":
            if r["outcome_definition"]!="REGULATOR_OR_COURT_CONFIRMED_MISSTATEMENT_AFFECTED_YEAR":
                raise ValueError("round8_positive_year_not_independently_adjudicated")
        else:
            if r["outcome_definition"]!="OFFICIAL_FOLLOWUP_NO_IDENTIFIED_MISSTATEMENT":
                raise ValueError("round8_negative_cannot_mean_merely_no_known_issue")
            if not r["negative_followup_end_at"]:
                raise ValueError("round8_negative_unchecked_followup")
            follow=timestamp(r["negative_followup_end_at"])
            if follow < datetime(year+3,1,1,tzinfo=timezone.utc):
                raise ValueError("round8_negative_less_than_two_year_followup")
            if follow>datetime.now(timezone.utc):
                raise ValueError("round8_future_negative_assumed_clean")
        values=[]
        for name in METRICS:
            raw=r[name].strip()
            try: v=float(raw)
            except (ValueError,TypeError):
                raise ValueError("round8_missing_original_numeric_amount:"+name)
            if not math.isfinite(v) or abs(v)>1e16:
                raise ValueError("round8_nonfinite_original_numeric_amount")
            values.append(v)
        accepted.append({
            "ticker":t,"fiscal_year":year,"label":int(r["label"]),
            "features":values,"original_sha256":r["original_report_sha256"],
            "outcome_sha256":r["outcome_document_sha256"],
            "timestamp_original":first.isoformat(),
        })
        counts["APPROVED_POSITIVE" if r["label"]=="1" else "APPROVED_NEGATIVE"]+=1
    return accepted,dict(counts)


def feature_matrix(cases):
    import numpy as np
    result=[]
    for case in cases:
        x=case["features"]
        by={k:float(v) for k,v in zip(METRICS,x)}
        def frac(n,d):
            return n/d if d!=0 else 0.
        liab=by["total_liabilities"];asset=by["total_assets"]
        revenue=by["revenue"];current=by["current_liabilities"]
        ratios=[
            frac(by["gross_profit"],revenue),
            frac(by["net_income"],revenue),
            frac(liab,asset),
            frac(by["inventory"],asset),
            frac(by["current_assets"],current),
            frac(by["operating_cash_flow"],asset),
        ]
        v=[math.copysign(math.log1p(abs(float(i))),i) for i in x]+ratios
        if not np.isfinite(v).all() or max(abs(y) for y in ratios)>1e8:
            raise ValueError("round8_derived_ratio_invalid")
        result.append(v)
    return np.array(result,dtype=float)


def score(y,prob,threshold):
    import numpy as np
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score, f1_score,
        balanced_accuracy_score, roc_auc_score, average_precision_score,
        confusion_matrix,
    )
    predicted=(np.asarray(prob)>=threshold).astype(int)
    tn,fp,fn,tp=confusion_matrix(y,predicted,labels=[0,1]).ravel()
    return {
        "accuracy":float(accuracy_score(y,predicted)),
        "precision":float(precision_score(y,predicted,zero_division=0)),
        "recall":float(recall_score(y,predicted,zero_division=0)),
        "f1_score":float(f1_score(y,predicted,zero_division=0)),
        "balanced_accuracy":float(balanced_accuracy_score(y,predicted)),
        "roc_auc":float(roc_auc_score(y,prob)) if len(set(y))==2 else None,
        "pr_auc":float(average_precision_score(y,prob)) if len(set(y))==2 else None,
        "tn":int(tn),"fp":int(fp),"fn":int(fn),"tp":int(tp),
    }


def study(approved,output,*,persist=False):
    import numpy as np
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import RobustScaler
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("round8_supervised_output_immutable")
    partitions={"fit":[],"validation":[],"test":[]}
    for row in approved:
        p=("fit" if row["fiscal_year"]<=2019 else
           "validation" if row["fiscal_year"]<=2022 else "test")
        partitions[p].append(row)
    counts={k:dict(Counter(str(r["label"]) for r in values))
            for k,values in partitions.items()}
    issuer={k:{r["ticker"] for r in rows} for k,rows in partitions.items()}
    disjoint=(not issuer["fit"]&issuer["validation"] and
              not issuer["fit"]&issuer["test"] and
              not issuer["validation"]&issuer["test"])
    eligible=(disjoint and
              all(sum(x["label"]==1 for x in samples)>=min_pos
                  and sum(x["label"]==0 for x in samples)>=min_neg
                  for samples,min_pos,min_neg in (
                      (partitions["fit"],5,10),
                      (partitions["validation"],2,2),
                      (partitions["test"],2,2))))
    summary={
        "status":"ROUND8_SUPERVISED_LABELS_PENDING_SUFFICIENT_APPROVAL",
        "accepted_label_counts_by_split":counts,
        "issuer_disjoint_and_time_ordered":disjoint,
        "training_issuer_count":len(issuer["fit"]),
        "validation_issuer_count":len(issuer["validation"]),
        "test_issuer_count":len(issuer["test"]),
        "final_holdout_1785_excluded":True,
        "target":"REVIEWED_OFFICIAL_MISSTATEMENT_CASE_YEAR_VS_FOLLOWUP_SCREENED_CONTROL",
        "outcome_is_not_absolute_fraud_certainty":True,
        "features":"12 ORIGINAL annual financial amounts signed-log + 6 intra-filing ratios",
        "feature_importance_method":"LogisticRegression coefficients / RandomForest impurity (diagnostic)",
        "real_supervised_f1":None,"real_supervised_accuracy":None,
        "real_supervised_precision":None,"real_supervised_recall":None,
        "real_supervised_pr_auc":None,
        "selected_model":None,
        "selection_metric":"validation_pr_auc_only",
        "trained_on_case_1785":False,
    }
    if eligible:
        from sklearn.metrics import f1_score
        def arr(p):
            arr=partitions[p]
            return feature_matrix(arr), np.array([r["label"] for r in arr],dtype=int)
        fitx,fity=arr("fit");valx,valy=arr("validation");testx,testy=arr("test")
        models={
            "logistic_regression":Pipeline([
                ("scaler",RobustScaler()),
                ("classifier",LogisticRegression(max_iter=1600,
                    class_weight="balanced",random_state=20261020))
            ]),
            "random_forest":Pipeline([
                ("scaler",RobustScaler()),
                ("classifier",RandomForestClassifier(
                    n_estimators=180,max_depth=5,min_samples_leaf=2,
                    class_weight="balanced",random_state=20261020,n_jobs=2))
            ]),
        }
        comparisons=[]
        for name,learner in models.items():
            learner.fit(fitx,fity)
            pv=learner.predict_proba(valx)[:,1]
            # Threshold is chosen from validation only, not case 1785/test.
            thresholds=np.arange(.10,.91,.05)
            threshold=float(max(thresholds,key=lambda t:(
                f1_score(valy,pv>=t,zero_division=0),-abs(t-.5))))
            val=score(valy,pv,threshold)
            pt=learner.predict_proba(testx)[:,1]
            test=score(testy,pt,threshold)
            comparisons.append({
                "model":name,"decision_threshold_validation_selected":threshold,
                "validation":val,"test_holdout":test,
                "fit_sample_count":len(fitx),"validation_sample_count":len(valx),
                "test_sample_count":len(testx),
            })
            if persist:
                import joblib
                out.mkdir(parents=True,exist_ok=True)
                joblib.dump(learner,out/(name+"_officially_reviewed_experiment.joblib"))
        win=max(comparisons,key=lambda d:(
            d["validation"]["pr_auc"],d["validation"]["f1_score"]))
        summary.update(
            status="ROUND8_SUPERVISED_APPROVED_ORIGINAL_LABELLED_EXPERIMENT",
            real_supervised_f1=win["test_holdout"]["f1_score"],
            real_supervised_accuracy=win["test_holdout"]["accuracy"],
            real_supervised_precision=win["test_holdout"]["precision"],
            real_supervised_recall=win["test_holdout"]["recall"],
            real_supervised_pr_auc=win["test_holdout"]["pr_auc"],
            selected_model=win["model"],comparisons=comparisons,
            feature_count=fitx.shape[1],
            labels_are_human_reviewed_still_require_external_audit=True,
        )
    out.mkdir(parents=True,exist_ok=True)
    (out/"round8_supervised_classification_report.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
        encoding="utf-8")
    return summary


def run(panel,evidence_dir,out):
    p=Path(panel)
    if p.exists():
        records,adjudication=approved_rows(p,evidence_dir)
    else:
        records,adjudication=[],{"NO_APPROVED_PANEL":1}
    report=study(records,out,persist=True)
    report["human_label_acceptance_counts"]=adjudication
    (Path(out)/"round8_supervised_classification_report.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="mode",required=True)
    a=sub.add_parser("prepare")
    a.add_argument("--annual-index",required=True)
    a.add_argument("--out",required=True)
    b=sub.add_parser("train")
    b.add_argument("--approved-panel",required=True)
    b.add_argument("--evidence-root",required=True)
    b.add_argument("--out",required=True)
    args=p.parse_args(argv)
    result=(prepare_labels(args.annual_index,args.out) if args.mode=="prepare"
            else run(args.approved_panel,args.evidence_root,args.out))
    print(json.dumps(result,indent=2,ensure_ascii=False))
if __name__=="__main__":
    main()
