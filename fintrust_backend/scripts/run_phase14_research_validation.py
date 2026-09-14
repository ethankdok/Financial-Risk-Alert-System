from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.text_experiments import (
    FORMAL_METRICS_PENDING,
    WEAK_SUPERVISION_LABEL_SOURCE,
    ablation_summary,
    balanced_group_aware_split,
    build_phase12_official_corpus,
    calculate_drift_metric_rows,
    corpus_rows_to_train_ready,
    error_analysis_from_predictions,
    evaluate_relevance_model_family,
    evaluate_topic_keyword_baseline,
    experiment_manifest,
    keyword_baseline_predict,
    load_annotation_csv,
    model_selection_rows,
    rank_active_learning_candidates,
    stratified_annotation_sample,
    summarize_annotation_quality,
    to_annotation_package_rows,
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: object) -> object:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "UNKNOWN"


def _weak_probabilities(rows: list[dict[str, object]]) -> list[dict[str, float]]:
    probabilities: list[dict[str, float]] = []
    for row in rows:
        score = float(row.get("weak_relevance_score") or 0.5)
        probabilities.append({"1": max(0.0, min(1.0, score)), "0": max(0.0, min(1.0, 1 - score))})
    return probabilities


def _load_human_annotation_summary(path: str | None) -> dict[str, object]:
    if not path:
        return {
            "status": FORMAL_METRICS_PENDING,
            "annotation_file": None,
            "note": "No completed human annotation CSV was provided or discovered.",
        }
    rows = load_annotation_csv(path)
    return {
        "status": "HUMAN_GT_AVAILABLE",
        "annotation_file": path,
        "quality": summarize_annotation_quality(rows),
    }


def _research_report(summary: dict[str, object]) -> str:
    corpus = summary["corpus"]
    artifacts = summary["artifacts"]
    return "\n".join(
        [
            "# Phase 14 Research Validation Report",
            "",
            "## Formal Human-Ground-Truth Results",
            "",
            f"Status: `{summary['formal_human_ground_truth_status']}`.",
            "No formal accuracy, Spearman, threshold calibration, or model-selection claim is made without completed human labels.",
            "",
            "## Preliminary / Weak-Supervision Results",
            "",
            f"Corpus sentences: `{corpus['sentence_count']}` from `{corpus['document_count']}` official-text documents.",
            f"Companies represented: `{', '.join(corpus['companies']) if corpus['companies'] else 'none'}`.",
            f"Weak label source: `{WEAK_SUPERVISION_LABEL_SOURCE}`.",
            f"Model comparison CSV: `{artifacts['model_comparison_csv']}`.",
            f"Drift metrics CSV: `{artifacts['drift_metrics_csv']}`.",
            "These results are engineering smoke/exploration only; they are not human Ground Truth performance.",
            "",
            "## Engineering Capabilities Ready but Waiting for Human Labels",
            "",
            "- Real official corpus extraction with provenance.",
            "- Practical annotation CSV with blank human-label fields and suggestion-only model columns.",
            "- Group-aware split manifest to prevent document leakage.",
            "- Keyword, TF-IDF Naive Bayes, TF-IDF Logistic Regression, and Linear SVM adapters.",
            "- Multi-label topic metric harness.",
            "- Drift metric, ablation, active-learning, and error-analysis artifacts.",
            "",
            "## Scientifically Supported Claims",
            "",
            "- The pipeline can build a reproducible official-evidence research dataset from locally available Phase 12 output.",
            "- The current corpus can be sampled and split without putting the same document in both train and test.",
            "- STRUX external benchmark remains pending because the exact parquet artifact is unavailable.",
            "",
            "## Claims NOT Yet Supported",
            "",
            "- ML relevance detection does not yet have validated superiority over the keyword baseline.",
            "- No final model family is selected.",
            "- Topic classification reliability is not established.",
            "- Drift metrics are not yet validated against human drift judgments.",
            "",
            "## Remaining External Blockers",
            "",
            "- Completed human sentence annotations.",
            "- Completed human drift-pair annotations.",
            "- Exact STRUX parquet artifact for external benchmark.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Phase 14 real official-text research validation without production writes.")
    parser.add_argument("--phase12-report", default=str(REPO_ROOT / "reports" / "phase12-official-smoke-report.json"))
    parser.add_argument("--output-dir", default=str(REPO_ROOT / "reports" / "phase14"))
    parser.add_argument("--target-annotation-size", type=int, default=500)
    parser.add_argument("--test-ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--human-annotations", help="Optional completed human annotation CSV.")
    args = parser.parse_args()

    report_path = Path(args.phase12_report)
    output_dir = Path(args.output_dir)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    corpus_build = build_phase12_official_corpus(payload)
    corpus_rows = corpus_build.rows
    annotation_sample = stratified_annotation_sample(corpus_rows, target_size=args.target_annotation_size, seed=args.seed)
    annotation_package = to_annotation_package_rows(annotation_sample)

    train_ready = corpus_rows_to_train_ready(corpus_rows)
    split = balanced_group_aware_split(train_ready, test_ratio=args.test_ratio, seed=args.seed)
    split_manifest = {
        "seed": split["seed"],
        "test_ratio": split["test_ratio"],
        "grouping_rule": "document_id",
        "train_groups": split["train_groups"],
        "test_groups": split["test_groups"],
        "document_leakage_prevented": split["document_leakage_prevented"],
        "train_count": len(split["train"]),
        "test_count": len(split["test"]),
    }
    manifest = experiment_manifest(
        experiment_id="phase14-real-official-weak-validation",
        git_commit=_git_commit(),
        dataset_manifest=corpus_build.manifest,
        split_manifest=split_manifest,
        random_seed=args.seed,
    )

    relevance_results = evaluate_relevance_model_family(
        split["train"],
        split["test"],
        label_status=WEAK_SUPERVISION_LABEL_SOURCE,
    )
    topic_result = evaluate_topic_keyword_baseline(split["test"], label_status=WEAK_SUPERVISION_LABEL_SOURCE)
    keyword_predictions = [
        int(keyword_baseline_predict(str(row.get("text") or ""))["predicted_relevant"])
        for row in split["test"]
    ]
    error_analysis = error_analysis_from_predictions(split["test"], keyword_predictions)
    drift_metrics = calculate_drift_metric_rows(corpus_rows)
    ablations = ablation_summary(corpus_rows)
    active_learning = rank_active_learning_candidates(train_ready, _weak_probabilities(corpus_rows), limit=50)
    human_annotation_summary = _load_human_annotation_summary(args.human_annotations)
    selection_rows = model_selection_rows(relevance_results, topic_result)

    artifacts = {
        "dataset_manifest_json": str(output_dir / "dataset_manifest.json"),
        "official_text_corpus_jsonl": str(output_dir / "official_text_corpus.jsonl"),
        "annotation_candidates_csv": str(output_dir / "annotation_candidates.csv"),
        "split_manifest_json": str(output_dir / "split_manifest.json"),
        "experiment_manifest_json": str(output_dir / "experiment_manifest.json"),
        "relevance_metrics_csv": str(output_dir / "relevance_metrics.csv"),
        "topic_metrics_json": str(output_dir / "topic_metrics.json"),
        "model_comparison_csv": str(output_dir / "model_comparison.csv"),
        "drift_metrics_csv": str(output_dir / "drift_metrics.csv"),
        "ablation_results_csv": str(output_dir / "ablation_results.csv"),
        "error_analysis_json": str(output_dir / "error_analysis.json"),
        "active_learning_batch_csv": str(output_dir / "active_learning_batch.csv"),
        "experiment_summary_json": str(output_dir / "experiment_summary.json"),
        "research_report_md": str(output_dir / "research_report.md"),
    }
    summary = {
        "schema_version": "phase14-experiment-summary-v1.0",
        "formal_human_ground_truth_status": human_annotation_summary["status"],
        "drift_ground_truth_status": FORMAL_METRICS_PENDING,
        "threshold_calibration_status": FORMAL_METRICS_PENDING,
        "selected_final_model": "NOT_SELECTED_PENDING_HUMAN_GROUND_TRUTH",
        "model_artifact_status": "NOT_CREATED_PENDING_HUMAN_GROUND_TRUTH",
        "strux_status": "STRUX_EXTERNAL_BENCHMARK_PENDING",
        "corpus": corpus_build.manifest,
        "annotation_dataset_size": len(annotation_package),
        "human_annotation_summary": human_annotation_summary,
        "split": split_manifest,
        "models_evaluated": [row.get("model") for row in relevance_results],
        "topic_metric_status": topic_result["status"],
        "keyword_free_subset_count": sum(1 for row in split["test"] if not keyword_baseline_predict(str(row.get("text") or ""))["keyword_hits"]),
        "company_held_out_status": "PENDING_MORE_DIVERSE_TEXT_CORPUS",
        "temporal_holdout_status": "PENDING_HUMAN_GROUND_TRUTH",
        "multilingual_subset_status": "PENDING_HUMAN_GROUND_TRUTH",
        "external_api_calls": [],
        "artifacts": artifacts,
    }

    _write_json(output_dir / "dataset_manifest.json", corpus_build.manifest)
    _write_jsonl(output_dir / "official_text_corpus.jsonl", corpus_rows)
    _write_csv(output_dir / "annotation_candidates.csv", annotation_package)
    _write_json(output_dir / "split_manifest.json", split_manifest)
    _write_json(output_dir / "experiment_manifest.json", manifest)
    _write_csv(output_dir / "relevance_metrics.csv", relevance_results)
    _write_json(output_dir / "topic_metrics.json", topic_result)
    _write_csv(output_dir / "model_comparison.csv", selection_rows)
    _write_csv(output_dir / "drift_metrics.csv", drift_metrics)
    _write_csv(output_dir / "ablation_results.csv", ablations)
    _write_json(output_dir / "error_analysis.json", error_analysis)
    _write_csv(output_dir / "active_learning_batch.csv", active_learning)
    _write_json(output_dir / "experiment_summary.json", summary)
    (output_dir / "research_report.md").write_text(_research_report(summary), encoding="utf-8")

    print(json.dumps({"status": "PHASE14_ENGINEERING_COMPLETE_HUMAN_GT_PENDING", "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
