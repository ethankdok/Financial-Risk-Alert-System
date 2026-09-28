
import csv
import json
import sys
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

sys.path.insert(0, str(BACKEND))
sys.path.append(str(ROOT))

from data_shift import (
    calculate_cosine_similarity,
    calculate_jsd,
    tokenize,
)
from scripts.build_mediatek_history import (
    load_documents,
)
from scripts.test_provider_impact import (
    remove_provider,
)

PERIODS = [
    f"{year}Q{quarter}"
    for year in (2024, 2025)
    for quarter in range(1, 5)
]

OUTPUT = BACKEND / "data/research-results"


def vectorizer():
    return TfidfVectorizer(
        tokenizer=tokenize,
        token_pattern=None,
        lowercase=False,
        norm="l2",
    )


def main():
    docs = load_documents()

    original = [
        docs[period]["text"]
        for period in PERIODS
    ]

    cleaned = [
        remove_provider(text)
        for text in original
    ]

    # 只使用前六期訓練固定模型。
    # 最後兩期不參與詞彙庫及 IDF 訓練。
    raw_model = vectorizer()
    clean_model = vectorizer()

    raw_model.fit(original[:6])
    clean_model.fit(cleaned[:6])

    raw_vectors = raw_model.transform(original)
    clean_vectors = clean_model.transform(cleaned)

    rows = []

    print("\n=== 聯發科固定 TF-IDF 驗證 ===")

    for i in range(1, len(PERIODS)):
        row = {
            "before": PERIODS[i - 1],
            "after": PERIODS[i],
            "raw_jsd": calculate_jsd(
                original[i - 1],
                original[i],
            ),
            "clean_jsd": calculate_jsd(
                cleaned[i - 1],
                cleaned[i],
            ),
            "raw_pairwise": calculate_cosine_similarity(
                original[i - 1],
                original[i],
            ),
            "clean_pairwise": calculate_cosine_similarity(
                cleaned[i - 1],
                cleaned[i],
            ),
            "raw_fixed": float(
                cosine_similarity(
                    raw_vectors[i - 1],
                    raw_vectors[i],
                )[0, 0]
            ),
            "clean_fixed": float(
                cosine_similarity(
                    clean_vectors[i - 1],
                    clean_vectors[i],
                )[0, 0]
            ),
        }

        row["fixed_change"] = (
            row["clean_fixed"] - row["raw_fixed"]
        )

        rows.append(row)

        print(
            f"{row['before']} -> {row['after']} | "
            f"固定模型原始: {row['raw_fixed']:.6f} | "
            f"清理後: {row['clean_fixed']:.6f}"
        )

    report = {
        "company": "MediaTek",
        "ticker": "2454",
        "training_periods": PERIODS[:6],
        "holdout_periods": PERIODS[6:],
        "method": {
            "raw": "Basic cleaning",
            "cleaned": "Remove Refinitiv and LSEG",
            "fixed_model": (
                "Company-specific vocabulary "
                "trained on first six quarters"
            ),
            "warning": (
                "Company models are fitted separately. "
                "Scores are not fraud probabilities."
            ),
        },
        "documents": {
            period: docs[period]["sha256"]
            for period in PERIODS
        },
        "comparisons": rows,
        "calibration": rows[:5],
        "holdout": rows[5:],
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT / "mediatek_tfidf_validation.csv"
    json_path = OUTPUT / "mediatek_tfidf_validation.json"

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0])
        )
        writer.writeheader()
        writer.writerows(rows)

    json_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n=== 後期測試 ===")

    for row in rows[5:]:
        print(
            row["before"],
            "->",
            row["after"],
            "原始:",
            round(row["raw_fixed"], 6),
            "清理後:",
            round(row["clean_fixed"], 6),
        )

    print("\nCSV:", csv_path)
    print("JSON:", json_path)


if __name__ == "__main__":
    main()
