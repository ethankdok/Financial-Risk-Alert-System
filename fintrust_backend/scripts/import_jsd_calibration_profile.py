"""Convert a teammate calibration result JSON into a validated JSD calibration profile.

The report is produced by the teammate research method
(scripts/calibrate_tsmc_shift.py on the research branch). Scope that the report
does not state is never inferred: preprocessing version, extraction method,
source family and research commit must be given explicitly. document_type and
language must be explicit and identical across the report's source documents.

Dry-run by default. --write-json writes <calibration_id>.json into --output-dir;
--write-firestore writes the profile to the shift_calibrations collection. A
profile id that already exists with different content is a conflict (exit 2);
nothing is overwritten.

Run from fintrust_backend:
  python -m scripts.import_jsd_calibration_profile --report calibration_result.json \\
      --source-family investor_tsmc_com_earnings_call_transcript \\
      --extraction-method "pypdf_layout_mode (build_tsmc_corpus.extract_pdf)" \\
      --preprocessing-version "tsmc-corpus-extract_pdf@5b91493" \\
      --source-research-commit <40-hex> --method-module ../data_shift.py [--write-json] [--write-firestore]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.services.jsd_calibration import (
    DEFAULT_PROFILE_DIR,
    FIRESTORE_COLLECTION,
    JsdCalibrationProfile,
    ProfileCalibration,
    ProfileMethod,
    ProfileScope,
    calibration_id_for,
    profile_to_firestore,
)
from app.services.jsd_method import normalized_sha256

RULE_OUTCOMES = {"dual": "雙指標顯著文字漂移（需人工確認）", "single": "單一指標異常（待觀察）",
                 "neither": "未達雙指標歷史漂移門檻"}
DEFAULT_RULE = "JSD >= historical P90 AND Cosine <= historical P10"


class ImportRejected(ValueError):
    pass


def _required(report: dict, path: str):
    value = report
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ImportRejected(f"calibration report is missing '{path}'")
        value = value[key]
    return value


def _unanimous(documents: list[dict], key: str) -> str:
    values = {str(doc.get(key) or "").strip() for doc in documents}
    if len(values) != 1 or "" in values:
        raise ImportRejected(f"source_documents must state one explicit {key}; found {sorted(values)}")
    return values.pop()


def build_profile(report: dict, *, source_family: str, extraction_method: str, preprocessing_version: str,
                  source_research_commit: str, module_sha256: str) -> JsdCalibrationProfile:
    documents = _required(report, "source_documents")
    if not isinstance(documents, list) or len(documents) < 2:
        raise ImportRejected("source_documents must list the calibrated target pair")
    method = _required(report, "method")
    calibration = _required(report, "calibration")
    history = list(calibration.get("history_pairs") or [])
    history_latest = max((pair["period_2"] for pair in history),
                         key=lambda p: int(p[:4]) * 4 + int(p[-1]), default=None)
    scope = ProfileScope(
        ticker=str(_required(report, "ticker")), company=str(report.get("company") or ""),
        industry=str(_required(report, "industry")),
        document_type=_unanimous(documents, "document_type"), language=_unanimous(documents, "language"),
        source_family=source_family,
    )
    profile_method = ProfileMethod(
        method_version=str(_required(report, "method.version")), calculator_module_sha256=module_sha256,
        extraction_method=extraction_method, preprocessing_version=preprocessing_version,
        tokenizer=str(_required(report, "method.tokenizer")), tfidf=str(_required(report, "method.tfidf")),
        jsd_log_base=int(_required(report, "method.jsd_log_base")), comparison=str(_required(report, "method.comparison")),
        minimum_history_pairs=int(_required(report, "method.min_history_pairs")),
    )
    thresholds = calibration.get("thresholds")
    profile_calibration = ProfileCalibration(
        history_pair_count=int(_required(report, "calibration.history_pair_count")),
        history_pairs=history, history_latest_period=history_latest, thresholds=thresholds,
        calibrated_for_target={"period_1": str(_required(report, "period_1")), "period_2": str(_required(report, "period_2"))},
    )
    rule = (report.get("combined_rule") or {}).get("rule") or DEFAULT_RULE
    return JsdCalibrationProfile(
        calibration_id=calibration_id_for(scope, profile_method, history_latest),
        scope=scope, method=profile_method, calibration=profile_calibration,
        decision_rule={"rule": rule, **RULE_OUTCOMES},
        source_document_hashes=[str(doc["sha256"]) for doc in documents],
        source_research_commit=source_research_commit,
        created_at=str(_required(report, "created_at")),
        imported_at=datetime.now(timezone.utc).isoformat(),
        status="active" if thresholds else "insufficient_history",
        warnings=[*map(str, report.get("warnings") or []),
                  "History pair document hashes are not part of the research report; only the target pair hashes are stored."],
    )


def _comparable(data: dict) -> dict:
    return {key: value for key, value in data.items() if key != "imported_at"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--source-family", required=True)
    parser.add_argument("--extraction-method", required=True)
    parser.add_argument("--preprocessing-version", required=True)
    parser.add_argument("--source-research-commit", required=True)
    parser.add_argument("--method-module", type=Path, required=True, help="data_shift.py used for the calibration")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PROFILE_DIR)
    parser.add_argument("--write-json", action="store_true")
    parser.add_argument("--write-firestore", action="store_true")
    parser.add_argument("--project", default=None)
    args = parser.parse_args()
    try:
        profile = build_profile(
            json.loads(args.report.read_text(encoding="utf-8")), source_family=args.source_family,
            extraction_method=args.extraction_method, preprocessing_version=args.preprocessing_version,
            source_research_commit=args.source_research_commit, module_sha256=normalized_sha256(args.method_module),
        )
    except (ImportRejected, ValueError) as exc:
        print(json.dumps({"status": "rejected", "error": str(exc)}, ensure_ascii=False))
        return 1
    data = profile.model_dump(mode="json")
    summary = {"status": "dry_run", "calibration_id": profile.calibration_id, "profile_status": profile.status,
               "scope": data["scope"], "history_pair_count": profile.calibration.history_pair_count,
               "history_latest_period": profile.calibration.history_latest_period,
               "thresholds": data["calibration"]["thresholds"], "preprocessing_version": profile.method.preprocessing_version}
    if args.write_json:
        target = args.output_dir / f"{profile.calibration_id}.json"
        if target.is_file():
            existing = json.loads(target.read_text(encoding="utf-8"))
            if _comparable(existing) != _comparable(data):
                summary.update(status="conflict", conflict=str(target.name))
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                return 2
            summary["json"] = "unchanged"
        else:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            summary["json"] = f"written {target.name}"
        summary["status"] = "written"
    if args.write_firestore:
        from google.cloud import firestore

        db = firestore.Client(project=args.project) if args.project else firestore.Client()
        reference = db.collection(FIRESTORE_COLLECTION).document(profile.calibration_id)
        snapshot = reference.get()
        document = profile_to_firestore(profile)
        if snapshot.exists:
            if _comparable(snapshot.to_dict()) != _comparable(document):
                summary.update(status="conflict", conflict=f"{FIRESTORE_COLLECTION}/{profile.calibration_id}")
                print(json.dumps(summary, ensure_ascii=False, indent=2))
                return 2
            summary["firestore"] = "unchanged"
        else:
            reference.create(document)
            summary["firestore"] = f"created {FIRESTORE_COLLECTION}/{profile.calibration_id}"
        summary["status"] = "written"
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
