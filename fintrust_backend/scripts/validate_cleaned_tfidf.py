
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

sys.path.insert(0, str(BACKEND))
sys.path.append(str(ROOT))

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from data_shift import calculate_cosine_similarity, tokenize
from scripts.build_tsmc_history import (
    existing_transcript,
    clean_text,
)
from scripts.test_provider_impact import remove_provider

PERIODS = [
    f"{year}Q{q}"
    for year in (2024, 2025)
    for q in range(1, 5)
]

OUT = BACKEND / "data" / "research-results"


def make_vectorizer():
    return TfidfVectorizer(
        tokenizer=tokenize,
        token_pattern=None,
        lowercase=False,
        norm="l2",
    )


def main():
    originals = []
    cleaned = []
    hashes = {}

    for period in PERIODS:
        document = existing_transcript(period)

        if document is None:
            raise RuntimeError(f"缺少 {period} 逐字稿")

        original = clean_text(document["text"])
        normalized = remove_provider(original)

        originals.append(original)
        cleaned.append(normalized)
        hashes[period] = document["sha256"]

    # 前六期為訓練資料
    # 最後兩期保留作後期測試
    raw_model = make_vectorizer()
    clean_model = make_vectorizer()

    raw_model.fit(originals[:6])
    clean_model.fit(cleaned[:6])

    raw_vectors = raw_model.transform(originals)
    clean_vectors = clean_model.transform(cleaned)

    rows = []

    for i in range(1, len(PERIODS)):
        before = PERIODS[i - 1]
        after = PERIODS[i]

        result = {
            "before": before,
            "after": after,
            "raw_pairwise": calculate_cosine_similarity(
                originals[i - 1], originals[i]
            ),
            "clean_pairwise": calculate_cosine_similarity(
                cleaned[i - 1], cleaned[i]
            ),
            "raw_fixed": float(
                cosine_similarity(
                    raw_vectors[i - 1],
                    raw_vectors[i]
                )[0, 0]
            ),
            "clean_fixed": float(
                cosine_similarity(
                    clean_vectors[i - 1],
                    clean_vectors[i]
                )[0, 0]
            ),
        }

        result["pairwise_change"] = (
            result["clean_pairwise"]
            - result["raw_pairwise"]
        )

        result["fixed_change"] = (
            result["clean_fixed"]
            - result["raw_fixed"]
        )

        rows.append(result)

        print(f"\n{before} -> {after}")

        for key, value in result.items():
            if key not in ("before", "after"):
                print(f"{key}: {value:.6f}")

    # 不用後期資料建立門檻
    calibration = rows[:5]
    holdout = rows[5:]

    report = {
        "experiment": "TSMC cleaned fixed TF-IDF",
        "training_periods": PERIODS[:6],
        "holdout_periods": PERIODS[6:],
        "documents": hashes,
        "method": {
            "raw": "Basic text cleaning",
            "cleaned": "Remove Refinitiv and LSEG tokens",
            "pairwise": "Fit separately for each pair",
            "fixed": "Fit only on first six quarters",
            "note": (
                "Raw and cleaned models have different "
                "vocabularies and IDF weights."
            ),
        },
        "calibration": calibration,
        "holdout": holdout,
        "comparisons": rows,
        "warning": (
            "Cosine is not a fraud probability. "
            "Publication dates and PDF extraction "
            "still require manual verification."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)

    json_path = OUT / "tsmc_cleaned_tfidf.json"
    csv_path = OUT / "tsmc_cleaned_tfidf.csv"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0].keys()),
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n=== 後期測試結果 ===")

    for row in holdout:
        print(
            row["before"],
            "->",
            row["after"],
            "固定模型清理前:",
            round(row["raw_fixed"], 6),
            "清理後:",
            round(row["clean_fixed"], 6),
        )

    print("\nCSV:", csv_path)
    print("JSON:", json_path)


if __name__ == "__main__":
    main()
