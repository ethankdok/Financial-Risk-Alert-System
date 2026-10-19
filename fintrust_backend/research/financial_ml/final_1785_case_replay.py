"""1785 光洋科: independent, frozen final-case evidence/replay.

Two distinct outputs:
(1) real published-formula historical scores already calculated from filed
    evidence by the audited literature engine (never fraud probabilities);
(2) strictly input-eligible Round3 12-amount inference ONLY if all twelve
    identical-scope, same-version official rows are available before the
    declared cutoff. No fit, retrain, holdout recalibration or new labels.

Raw historical ZIP is verified with the project's independent semantic
verifier; 2016 restatement notices cannot be used as 2016-05-13 inputs.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.services.historical_audit.package_verify import verify_package
from .annual_panel_readiness import METRICS
from .round4_research_handoff import read_round3
from .round3_research_models import signed_exp

STRICT_SHA = "304934a4a2e05dc16439155b267554a99a731ff6c07fa95e1cd05f25504f2bcf"
ROUND3_SHA = "766fa54e83763c39634605e983a3928e0fd8055e7fa06b72fc767bfa037ce380"
ROUND4_SHA = "786f1e5598ca287b4896710742617da7863054c469d1ca30f3bbd44aa1bb6cc6"
EVENT_PRE_DISCLOSURE = "2016-05-13T00:00:00+08:00"
VALID_CASE_YEARS = tuple(range(2011, 2017))
ROOT = Path(__file__).resolve().parents[3]
LITERATURE_DOC = ROOT / "docs/research/LITERATURE_COMPARATIVE_CASE_STUDY_1785.md"

CASE_COLS = (
    "fiscal_year","version","beneish_m_score","dechow_f_score",
    "basis","forecast_2016_may13_eligible","interpretation"
)
FACT_COLS = ("fiscal_year","metric_code","value","unit",
             "statement_scope","accounting_framework",
             "filing_version_type","point_in_time_eligible",
             "effective_available_at")
GAP_COLS = ("target_year","prior_year","metric",
            "observation_status","eligible_historical_input","reason")
PRED_COLS = ("target_year","model","metric","predicted_twd",
             "actual_twd","absolute_error_twd","evidence_mode")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_sections(text):
    if "## 2. Current-filing series" not in text or "## 3. Original-filing series" not in text:
        raise ValueError("1785_literature_source_sections_missing")
    current = text.split("## 2. Current-filing series",1)[1].split(
        "## 3. Original-filing series",1)[0]
    originals = text.split("## 3. Original-filing series",1)[1].split(
        "## 4.",1)[0]
    return originals,current


def clean_score(raw):
    raw=raw.strip().replace("**","").replace("−","-")
    if raw.startswith(("null","—","–","-:")) or raw in ("","-"):
        return None
    match=re.fullmatch(r"-?\d+(?:\.\d+)?",raw)
    if not match:
        raise ValueError("1785_unknown_literature_score:" + raw[:85])
    result=float(raw)
    if not math.isfinite(result):
        raise ValueError("1785_nonfinite_literature_score")
    return result


def literature_scores(text):
    originals,current=source_sections(text)
    results=[]
    for year in range(2011,2016):
        selection=originals if year<=2012 else current
        candidates=[x.split("|")[1:-1] for x in selection.splitlines()
                    if re.match(r"^\|\s*"+str(year)+r"\s*\|",x)]
        if len(candidates)!=1:
            raise ValueError(f"1785_literature_year_missing_or_duplicate:{year}")
        cells=[x.strip() for x in candidates[0]]
        if len(cells)!=6:
            raise ValueError("1785_unexpected_literature_table_shape:"+str(year))
        version=cells[1]
        if (year<=2012 and "original" not in version) or (
            year>=2013 and "restated" not in version):
            raise ValueError("1785_wrong_historical_version:"+str(year))
        beneish=clean_score(cells[2])
        dechow=clean_score(cells[4])
        if beneish is None:
            raise ValueError("1785_literature_beneish_missing:"+str(year))
        if year==2011 and dechow is not None or year==2015 and dechow is not None:
            raise ValueError("1785_invalid_incomplete_dechow_score")
        results.append({
            "fiscal_year":year, "version":version,
            "beneish_m_score":beneish,
            "dechow_f_score":dechow,
            "basis":"archived_original_accounting_records" if year<=2012
                    else "2016_restatement_latest_available",
            "forecast_2016_may13_eligible":False,
            "interpretation":"RETROSPECTIVE_PUBLISHED_FORMULA_UNCALIBRATED",
        })
    return results


def package_data(path):
    """Use audited historical ZIP. This does not extract executable content."""
    if digest(path)!=STRICT_SHA:
        raise ValueError("1785_strict_archive_sha256_not_accepted")
    check=verify_package(path)
    if check.get("status")!="verified" or check.get("mode")!="strict_point_in_time":
        raise ValueError("1785_official_archive_not_semantically_verified")
    with zipfile.ZipFile(path) as z:
        root="fintrust_historical_research_dataset/"
        manifest=json.loads(z.read(root+"manifest.json").decode("utf-8"))
        if (manifest.get("mode")!="strict_point_in_time"
            or manifest.get("case",{}).get("ticker") not in ("1785",1785)
            or manifest.get("parameters",{}).get("as_of")!="2016-11-14"):
            raise ValueError("1785_case_archive_identity_or_cutoff_mismatch")
        records=list(csv.DictReader(io.StringIO(z.read(
            root+"data/financial_facts.csv").decode("utf-8-sig"))))
    # Strict package has 27 retrospectively public 2016-Nov rows, NOT
    # twelve same-version 2016-May original filing features.
    if len(records)!=27:
        raise ValueError("1785_frozen_27_fact_strict_archive_changed")
    cleaned=[]
    identities=set()
    for r in records:
        if not set(FACT_COLS).issubset(r):
            raise ValueError("1785_facts_contract_changed")
        year=int(r["fiscal_year"])
        metric=r["metric_code"]
        if (r.get("ticker") not in ("1785","")
            or year not in VALID_CASE_YEARS
            or not metric
            or r["unit"] not in ("TWD","TWD/share")
            or r["statement_scope"]!="consolidated"
            or r["accounting_framework"]!="TIFRS"
            or r["filing_version_type"]!="restated"
            or r["point_in_time_eligible"].lower()!="true"):
            raise ValueError("1785_strict_facts_unexpected_identity")
        if not r["value"] or not math.isfinite(float(r["value"])):
            raise ValueError("1785_nonfinite_official_financial_value")
        effective = r["effective_available_at"]
        if not effective:
            raise ValueError("1785_missing_2016_restatement_disclosure_availability")
        ts=datetime.fromisoformat(effective.replace("Z","+00:00"))
        if ts.tzinfo is None:
            raise ValueError("1785_financial_publication_time_lacks_zone")
        if ts.astimezone(timezone.utc) < datetime.fromisoformat(
                EVENT_PRE_DISCLOSURE).astimezone(timezone.utc):
            raise ValueError("1785_2016_restatement_observation_appears_pre_event")
        key=(year,metric)
        if key in identities:
            raise ValueError("1785_duplicate_historical_fact")
        identities.add(key)
        cleaned.append(r)
    return check,manifest,cleaned


def gate_features_for_event(facts,*, asof=EVENT_PRE_DISCLOSURE):
    """Each value must itself have been public before prediction day, and
    come from an original SAME-scope SAME-accounting period source."""
    deadline=datetime.fromisoformat(asof)
    if deadline.tzinfo is None:
        raise ValueError("1785_cutoff_missing_timezone")
    history=(2013,2014,2015)
    by_key={(int(r["fiscal_year"]),r["metric_code"]):r for r in facts}
    matrix=[]
    blockers=[]
    for year in history:
        arr=[]
        for feature in METRICS:
            r=by_key.get((year,feature))
            if r is None:
                blockers.append({"target_year":2016,"prior_year":year,
                    "metric":feature,"observation_status":"MISSING",
                    "eligible_historical_input":False,
                    "reason":"not_a_verified_original_annual_account_observation"})
                arr.append(None)
                continue
            at=datetime.fromisoformat(r["effective_available_at"].replace("Z","+00:00"))
            eligible=(at<=deadline and r["filing_version_type"]=="original"
                      and r["statement_scope"]=="consolidated"
                      and r["accounting_framework"]=="TIFRS"
                      and r["unit"]=="TWD")
            if not eligible:
                blockers.append({"target_year":2016,"prior_year":year,
                    "metric":feature,"observation_status":"PRESENT_BUT_NOT_PRE_EVENT_ORIGINAL",
                    "eligible_historical_input":False,
                    "reason":"restatement_or_late_disclosure_or_nonoriginal"})
            arr.append(float(r["value"]) if eligible else None)
        matrix.append(arr)
    return (matrix if not blockers else None),blockers


def predict_2016_frozen_numeric(history, model_root, report):
    """This can run only if 36 independently verified original full-TWD
    historical facts survived all evidence gates; no fitting is possible here."""
    import numpy as np
    import joblib
    study=Path(model_root)/"annual_checkpoints"
    bundle=joblib.load(study/"fit_only_preprocessor.joblib")
    if (bundle.get("study_only") is not True
        or tuple(bundle.get("features",()))!=tuple(METRICS)
        or bundle.get("seed")!=report["experiment_seed"]):
        raise ValueError("1785_training_frozen_scaler_mismatch")
    scaler=bundle["scaler"]
    values=np.asarray(history,dtype=float)
    if values.shape!=(3,12) or not np.isfinite(values).all():
        raise ValueError("1785_case_bad_original_full_amounts")
    with np.errstate(invalid="raise",over="raise"):
        scaled=scaler.transform((np.sign(values)*np.log1p(np.abs(values))))
    scores={}
    champion=report["annual_numeric_study"]["selected_model_by_validation_only"]
    # Strictly evaluate the validation-selected model, NEVER tune with 1785.
    if champion=="persistence":
        pred=scaled[-1:].copy()
    elif champion in ("ridge","random_forest","mlp","catboost"):
        learner=joblib.load(study/(champion+"_experimental.joblib"))
        pred=np.asarray(learner.predict(scaled.reshape(1,-1)),dtype=float)
    elif champion in ("gru","lstm","tcn","transformer"):
        import torch
        from .provisional_sequence_experiment import build_neural
        torch.set_num_threads(min(torch.get_num_threads(),4))
        payload=torch.load(study/(champion+"_experimental.pt"),
                           map_location="cpu",weights_only=True)
        if payload.get("architecture")!=champion or payload.get("window")!=3:
            raise ValueError("1785_frozen_neural_architecture_mismatch")
        network=build_neural(champion,3,seed=report["experiment_seed"])
        network.load_state_dict(payload["model"])
        network.eval()
        with torch.no_grad():
            pred=network(torch.tensor(scaled.reshape(1,3,12),
                                       dtype=torch.float32)).numpy()
    else:
        raise ValueError("1785_unknown_locked_champion")
    if pred.shape!=(1,12) or not np.isfinite(pred).all():
        raise ValueError("1785_inference_nonfinite_or_wrong_shape")
    amounts=signed_exp(scaler.inverse_transform(pred))[0]
    if not np.isfinite(amounts).all():
        raise ValueError("1785_forecast_infinite_amount")
    for name,value in zip(METRICS,amounts):
        scores[name]=float(value)
    return {"status":"FROZEN_INFERENCE_ORIGINAL_FIRST_PUBLISHED_PRE_EVENT",
            "model":champion,"target_year":2016,"predicted_twd":scores,
            "fraud_probability":None,"retained_case_not_train_fit":True}


def audit_and_report(*, data_root,bridge_root,round3_root,round4_report,
                     strict_zip,output,literature_doc=LITERATURE_DOC):
    droot=Path(data_root);out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("1785_final_case_output_is_immutable")
    if digest(round3_root/"round3_real_data_model_report.json")!=ROUND3_SHA:
        raise ValueError("1785_round3_accepted_model_report_sha256_disagrees")
    if digest(round4_report)!=ROUND4_SHA:
        raise ValueError("1785_round4_accepted_explainability_report_sha256_disagrees")
    model_report=read_round3(
        Path(round3_root)/"round3_real_data_model_report.json",
        droot,bridge_root)
    if model_report["annual_numeric_study"]["selected_model_by_validation_only"]!="persistence":
        raise ValueError("1785_research_champion_reselection_forbidden")
    method_text=Path(literature_doc).read_text(encoding="utf-8")
    historical=literature_scores(method_text)
    check,manifest,facts=package_data(strict_zip)
    original,missing=gate_features_for_event(facts)
    forecast=(predict_2016_frozen_numeric(original,round3_root,model_report)
              if original is not None else {
                  "status":"PRE_EVENT_FROZEN_INFERENCE_NOT_INPUT_ELIGIBLE",
                  "model":"persistence","target_year":2016,
                  "predicted_twd":None,"fraud_probability":None,
                  "blocked_feature_slots":len(missing),
                  "reason":"2013-15 original/first-public 36-feature input not available before 2016-05-13",
              })
    report={
        "case":"光洋科","ticker":"1785",
        "status":"FINAL_1785_REAL_LITERATURE_SCORES_AND_STRICT_REPLAY_AUDITED",
        "strict_package_sha256":digest(strict_zip),
        "strict_archive_verification":check,
        "strict_package_as_of":"2016-11-14",
        "2016_first_misstatement_public_disclosure":"2016-05-13 (official quote; day-level)",
        "pre_disclosure_safe_cutoff":EVENT_PRE_DISCLOSURE,
        "strict_package_financial_fact_count":len(facts),
        "strict_package_financial_metrics_by_year":{
            str(y):sorted({r["metric_code"] for r in facts if int(r["fiscal_year"])==y})
            for y in (2013,2014,2015)},
        "historical_literature_score_source":{
            "relative_path":"docs/research/LITERATURE_COMPARATIVE_CASE_STUDY_1785.md",
            "source_sha256":hashlib.sha256(method_text.encode("utf-8")).hexdigest(),
            "engines":"Beneish (1999) full8 / Dechow et al. (2011) Model1",
            "interpretation":"RETROSPECTIVE_FILING_VERSION_DEPENDENT_UNCALIBRATED",
        },
        "historical_score_rows":historical,
        "frozen_round3_case_numeric_inference":forecast,
        "frozen_round3_training_test_1785_excluded":True,
        "case_used_to_select_features_models_thresholds":False,
        "historical_first_public_filing_model_probability":None,
        "classifier_accuracy_precision_recall_f1_auc":None,
        "no_production_db_writes":True,
        "no_network_requests":True,
        "presentation":{
            "heading":"光洋科 1785｜歷史財報模型回放",
            "primary_result":"2011 原始財報 Beneish M-Score -1.730106；2012 -2.286269",
            "contrast":"2013–2015 重編後 M-Score 為 -2.942811、-2.300361、-2.240182",
            "round3_model_status":forecast["status"],
            "note":"Beneish/Dechow 為事後財報版本研究分數；2016-05-13 以前的 Round3 事前模型推論需原始財報時點證據。",
        },
    }
    out.mkdir(parents=True,exist_ok=True)
    (out/"1785_case_final_report.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n",
        encoding="utf-8")
    with (out/"1785_historical_model_scores.csv").open(
            "w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=CASE_COLS);w.writeheader()
        w.writerows(historical)
    with (out/"1785_pre_event_input_gaps.csv").open(
            "w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=GAP_COLS);w.writeheader()
        w.writerows(missing)
    (out/"1785_presentation_text_zh.txt").write_text(
        report["presentation"]["heading"]+"\n"+
        report["presentation"]["primary_result"]+"\n"+
        report["presentation"]["contrast"]+"\n"+
        report["presentation"]["note"]+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description="1785 historical final case; verify source before scoring")
    for arg in ("data-root","round2-bridge-root","round3-root",
                "round4-report","strict-zip","output"):
        p.add_argument("--"+arg,required=True)
    a=p.parse_args(argv)
    r=audit_and_report(data_root=a.data_root,bridge_root=a.round2_bridge_root,
                       round3_root=Path(a.round3_root),
                       round4_report=a.round4_report,
                       strict_zip=a.strict_zip,output=a.output)
    print(json.dumps({
        "status":r["status"],"literature_scores":r["historical_score_rows"],
        "frozen_round3_numeric":r["frozen_round3_case_numeric_inference"],
        "observed_original_pre_event_input_gaps":
            r["frozen_round3_case_numeric_inference"].get("blocked_feature_slots",0)
    },ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
