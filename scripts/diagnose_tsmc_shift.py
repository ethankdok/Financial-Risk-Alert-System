"""Inspect outlier pairs without exposing third-party transcript text.

Outputs metadata-only QA, cross-period metric disagreements and alternate
vectorization comparisons. The alternate scores are *diagnostic*, not
validated thresholds.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_shift import tokenize, calculate_jsd, calculate_cosine_similarity  # noqa: E402
from calibrate_tsmc_shift import load, quality, quarter_number  # noqa: E402


def structural_stats(text: str) -> dict:
    """Heuristic document diagnostics; do NOT treat marker counts as validated sections."""
    lines = [re.sub(r"\s+", " ", line).strip().lower()
             for line in text.splitlines() if line.strip()]
    duplicated = sum(n-1 for line, n in Counter(lines).items()
                     if n > 1 and len(line) > 20)
    tokens = tokenize(text)
    histogram = Counter(tokens)
    nonlatin = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return {
        "characters": len(text),
        "clean_tokens": len(tokens),
        "vocabulary": len(histogram),
        "type_token_ratio": round(len(histogram)/len(tokens), 6) if tokens else 0,
        "chinese_characters": nonlatin,
        "duplicate_long_lines": duplicated,
        "nonblank_lines": len(lines),
        "qa_marker_mentions": len(re.findall(
            r"\b(question(?:s)?(?:\s+and\s+answers)?|q\s*&\s*a|operator)\b",
            text, flags=re.I)),
        "common_tokens": [w for w, _ in histogram.most_common(15)],
    }


def alternate_cosine(a: str, b: str) -> dict:
    """Diagnostic raw-count and shared-corpus TF-IDF; not compared to old thresholds."""
    vectorizer = CountVectorizer(tokenizer=tokenize, token_pattern=None, lowercase=False)
    mat = vectorizer.fit_transform([a, b])
    return {"count_cosine": round(float(cosine_similarity(mat[0], mat[1])[0][0]), 6)}


def diagnose(rows: list[dict], period1="2025Q3", period2="2025Q4") -> dict:
    by_period = {row["period"]: row for row in rows}
    if period1 not in by_period or period2 not in by_period:
        raise ValueError("Target official transcripts absent in corpus")
    if quarter_number(period2) != quarter_number(period1) + 1:
        raise ValueError("Target must use adjacent quarters")
    a, b = by_period[period1]["text"], by_period[period2]["text"]
    qa, qb = structural_stats(a), structural_stats(b)
    ta, tb = set(tokenize(a)), set(tokenize(b))
    all_pairs = []
    periods = sorted(by_period, key=quarter_number)
    for earlier, later in zip(periods, periods[1:]):
        if quarter_number(later) != quarter_number(earlier) + 1:
            continue
        x, y = by_period[earlier]["text"], by_period[later]["text"]
        passed, info = quality(x, y)
        if passed:
            all_pairs.append({
                "period1": earlier, "period2": later,
                "cosine": round(calculate_cosine_similarity(x, y), 6),
                "jsd": round(calculate_jsd(x, y), 6),
                "length_ratio": info["length_ratio"],
            })
    target = next(x for x in all_pairs if x["period1"] == period1 and x["period2"] == period2)
    historic = [p for p in all_pairs if quarter_number(p["period2"]) < quarter_number(period1)]
    hist_cos = [x["cosine"] for x in historic]
    return {
        "method_warning": "This report only diagnoses extraction/model sensitivity; no fraud inference.",
        "target": target,
        "official_documents": {
            period1: {"url": by_period[period1]["source_pdf"],
                      "sha256": by_period[period1]["sha256"], "qa": qa},
            period2: {"url": by_period[period2]["source_pdf"],
                      "sha256": by_period[period2]["sha256"], "qa": qb},
        },
        "token_vocabulary_jaccard": round(len(ta & tb)/len(ta | tb), 6) if ta | tb else 0,
        "alternate_unvalidated_metric": alternate_cosine(a, b),
        "historical_cosine_median": round(float(np.median(hist_cos)), 6) if hist_cos else None,
        "historical_cosine_min": round(float(min(hist_cos)), 6) if hist_cos else None,
        "historical_valid_pairs": len(historic),
        "lowest_five_prior_cosine_pairs": sorted(historic, key=lambda x:x["cosine"])[:5],
        "all_pair_metrics": all_pairs,
        "manual_quality_check_required": [
            "Verify extracted text corresponds to same full transcript type and language",
            "Inspect if 2025Q3/Q4 have materially different Q&A, operator or PDF artifacts",
            "Identify differences between token frequency JSD and pairwise TF-IDF cosine",
            "Never classify text shift as investment fraud",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=Path("data/tsmc_corpus/tsmc_quarterly_text.csv"))
    parser.add_argument("--period1", default="2025Q3")
    parser.add_argument("--period2", default="2025Q4")
    parser.add_argument("--output", type=Path, default=Path("data/tsmc_corpus/diagnostic_report.json"))
    args = parser.parse_args()
    report = diagnose(load(args.csv, "2330"), args.period1, args.period2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = {k:report[k] for k in ["target","token_vocabulary_jaccard","alternate_unvalidated_metric",
                                   "historical_cosine_median","historical_cosine_min",
                                   "historical_valid_pairs","lowest_five_prior_cosine_pairs"]}
    digest["document_qa"] = {k:v["qa"] for k,v in report["official_documents"].items()}
    print(json.dumps(digest, ensure_ascii=False, indent=2))
    print("Saved metadata-only diagnostic", args.output)
