"""Read-only FinTrust adapter for actual external AAER 0/1 supervised results.

No production Taiwan risk scores or predictions are changed. The published
U.S. research baseline is displayed separately, with source jurisdiction
and limitations mandatory in every response.
"""
from __future__ import annotations
import json
from pathlib import Path

def published_aaer_benchmark_summary(path):
    file=Path(path)
    if not file.exists():
        raise FileNotFoundError("AAER real supervised benchmark report unavailable")
    result=json.loads(file.read_text(encoding="utf-8"))
    if (result.get("status")!="REAL_PUBLISHED_AAER_LABELLED_SUPERVISED_TRAIN_AND_HOLDOUT_COMPLETE"
        or result.get("NOT_TAIWAN_MODEL") is not True
        or result.get("NOT_USER_MANUALLY_VERIFIED_EVERY_LABEL") is not True
        or result.get("non_AAER_0_is_not_a_guarantee_of_clean_reporting") is not True
        or result.get("historical_asfiled_input_version_not_independently_verified") is not True):
        raise ValueError("AAER benchmark source/scope or quality disclaimer missing")
    if (result["total_0"]+result["total_1"]!=result["total_records"]
        or result["feature_count"]!=42
        or result["total_1"]<=0 or result["total_0"]<=0
        or set(result["split_counts"])!={"train","validation","test"}
        or any(x in result["features"] for x in ("misstate","p_aaer","gvkey","fyear"))):
        raise ValueError("AAER report dataset authenticity structure invalid")
    outcome=result["untouched_holdout_metrics"]
    if (sum(outcome[k] for k in
            ("true_negative","false_positive","false_negative","true_positive"))
        !=outcome["samples"]):
        raise ValueError("AAER holdout confusion matrix inconsistent")
    return {
        "status":result["status"],
        "purpose":"PUBLIC_EXTERNAL_RESEARCH_ONLY_NOT_TAIWAN_PRODUCTION",
        "training_years":[result["source_fy_min"],result["source_fy_max"]],
        "company_count":result["total_unique_companies"],
        "label_0":result["total_0"],"label_1":result["total_1"],
        "labeled_company_year_count":result["total_records"],
        "target":"U.S. SEC AAER identified reporting misstatement",
        "labels_compiled_by":"Bao et al. (2020) published research",
        "selected_algorithm":result["selected_model"],
        "holdout_issuer_disjoint":True,
        "holdout":outcome,
        "dummy_all_negative_holdout":result["dummy_holdout_metrics"],
        "dataset_sha256":result["source_dataset_sha256"],
        "not_a_Taiwan_1785_prediction":True,
        "not_proof_of_clean_controls":True,
        "not_verified_individual_SEC_filings_as_of_each_date":True,
    }
