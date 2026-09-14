from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ClassificationReport:
    precision: float
    recall: float
    f1: float
    macro_f1: float
    confusion_matrix: dict[str, dict[str, int]]


def safe_divide(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def confusion_matrix(y_true: Iterable[str], y_pred: Iterable[str]) -> dict[str, dict[str, int]]:
    true_values = list(y_true)
    pred_values = list(y_pred)
    labels = sorted(set(true_values) | set(pred_values))
    matrix = {label: {inner: 0 for inner in labels} for label in labels}
    for truth, prediction in zip(true_values, pred_values):
        matrix[truth][prediction] += 1
    return matrix


def binary_classification_report(y_true: Iterable[int], y_pred: Iterable[int], *, positive_label: int = 1) -> ClassificationReport:
    true_values = [str(value) for value in y_true]
    pred_values = [str(value) for value in y_pred]
    matrix = confusion_matrix(true_values, pred_values)
    pos = str(positive_label)
    tp = matrix.get(pos, {}).get(pos, 0)
    fp = sum(row.get(pos, 0) for label, row in matrix.items() if label != pos)
    fn = sum(value for label, value in matrix.get(pos, {}).items() if label != pos)
    precision = safe_divide(tp, tp + fp)
    recall = safe_divide(tp, tp + fn)
    f1 = safe_divide(2 * precision * recall, precision + recall)
    macro_scores = []
    for label in matrix:
        label_tp = matrix[label].get(label, 0)
        label_fp = sum(row.get(label, 0) for other, row in matrix.items() if other != label)
        label_fn = sum(value for other, value in matrix[label].items() if other != label)
        p = safe_divide(label_tp, label_tp + label_fp)
        r = safe_divide(label_tp, label_tp + label_fn)
        macro_scores.append(safe_divide(2 * p * r, p + r))
    return ClassificationReport(
        precision=round(precision, 6),
        recall=round(recall, 6),
        f1=round(f1, 6),
        macro_f1=round(sum(macro_scores) / len(macro_scores), 6) if macro_scores else 0.0,
        confusion_matrix=matrix,
    )


def multilabel_report(true_labels: list[set[str]], pred_labels: list[set[str]]) -> dict[str, object]:
    labels = sorted(set().union(*true_labels, *pred_labels)) if true_labels or pred_labels else []
    per_topic: dict[str, dict[str, float]] = {}
    micro_tp = micro_fp = micro_fn = 0
    f1_values = []
    for label in labels:
        tp = sum(1 for truth, pred in zip(true_labels, pred_labels) if label in truth and label in pred)
        fp = sum(1 for truth, pred in zip(true_labels, pred_labels) if label not in truth and label in pred)
        fn = sum(1 for truth, pred in zip(true_labels, pred_labels) if label in truth and label not in pred)
        micro_tp += tp
        micro_fp += fp
        micro_fn += fn
        precision = safe_divide(tp, tp + fp)
        recall = safe_divide(tp, tp + fn)
        f1 = safe_divide(2 * precision * recall, precision + recall)
        f1_values.append(f1)
        per_topic[label] = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(f1, 6),
            "support": sum(1 for truth in true_labels if label in truth),
        }
    micro_precision = safe_divide(micro_tp, micro_tp + micro_fp)
    micro_recall = safe_divide(micro_tp, micro_tp + micro_fn)
    micro_f1 = safe_divide(2 * micro_precision * micro_recall, micro_precision + micro_recall)
    return {
        "macro_f1": round(sum(f1_values) / len(f1_values), 6) if f1_values else 0.0,
        "micro_f1": round(micro_f1, 6),
        "per_topic": per_topic,
    }


def cohens_kappa(labels_a: Iterable[str], labels_b: Iterable[str]) -> float:
    left = list(labels_a)
    right = list(labels_b)
    if len(left) != len(right):
        raise ValueError("Cohen's Kappa requires paired label lists of equal length.")
    if not left:
        return 0.0
    observed = sum(1 for a, b in zip(left, right) if a == b) / len(left)
    left_counts = Counter(left)
    right_counts = Counter(right)
    expected = sum((left_counts[label] / len(left)) * (right_counts[label] / len(right)) for label in set(left) | set(right))
    return round(safe_divide(observed - expected, 1 - expected), 6)


def spearman_correlation(xs: Iterable[float], ys: Iterable[float]) -> float:
    x_values = list(xs)
    y_values = list(ys)
    if len(x_values) != len(y_values):
        raise ValueError("Spearman correlation requires equal-length inputs.")
    if len(x_values) < 2:
        return 0.0
    x_ranks = rank_values(x_values)
    y_ranks = rank_values(y_values)
    x_mean = sum(x_ranks) / len(x_ranks)
    y_mean = sum(y_ranks) / len(y_ranks)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_ranks, y_ranks))
    denominator = math.sqrt(sum((x - x_mean) ** 2 for x in x_ranks) * sum((y - y_mean) ** 2 for y in y_ranks))
    return round(safe_divide(numerator, denominator), 6)


def rank_values(values: list[float]) -> list[float]:
    sorted_pairs = sorted((value, index) for index, value in enumerate(values))
    ranks = [0.0] * len(values)
    index = 0
    while index < len(sorted_pairs):
        end = index
        while end + 1 < len(sorted_pairs) and sorted_pairs[end + 1][0] == sorted_pairs[index][0]:
            end += 1
        rank = (index + end + 2) / 2
        for _, original_index in sorted_pairs[index : end + 1]:
            ranks[original_index] = rank
        index = end + 1
    return ranks


def load_annotation_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def summarize_annotation_quality(rows: list[dict[str, str]]) -> dict[str, object]:
    by_sample: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        by_sample.setdefault(row.get("sample_id", ""), []).append(row)
    paired = [items for items in by_sample.values() if len(items) >= 2]
    if not paired:
        return {
            "sample_count": len(by_sample),
            "paired_sample_count": 0,
            "cohens_kappa_relevance": None,
            "note": "At least two annotations per sample are required for Cohen's Kappa.",
        }
    first = [items[0].get("relevant_label", "") for items in paired]
    second = [items[1].get("relevant_label", "") for items in paired]
    return {
        "sample_count": len(by_sample),
        "paired_sample_count": len(paired),
        "cohens_kappa_relevance": cohens_kappa(first, second),
    }

