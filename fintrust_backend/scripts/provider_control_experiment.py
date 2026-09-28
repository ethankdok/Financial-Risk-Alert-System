import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from scripts.cross_company_seven_quarters import (
    prepare_documents,
    basic_clean,
    remove_provider,
)
from scripts.test_provider_impact import (
    calculate_cosine_similarity,
)

OUTPUT = Path("data/research-results")
PATTERN = re.compile(
    r"\b(?:refinitiv|lseg)\b",
    flags=re.IGNORECASE
)

tokenize = calculate_cosine_similarity.__globals__["tokenize"]


def normalize_provider(text):
    return PATTERN.sub("providerbrand", text)


def similarity(vectorizer, left, right):
    vectors = vectorizer.transform([left, right])
    return float(
        cosine_similarity(
            vectors[0],
            vectors[1]
        )[0][0]
    )


def main():
    documents = prepare_documents()

    prepared = {}
    training_texts = []

    # 所有公司、所有季度使用相同規則
    for company, periods in documents.items():
        prepared[company] = {}

        for period, original in periods.items():
            baseline = basic_clean(original)
            removed = remove_provider(baseline)
            normalized = normalize_provider(baseline)

            if not all((
                baseline.strip(),
                removed.strip(),
                normalized.strip()
            )):
                raise ValueError(
                    f"{company} {period} 存在空白文件"
                )

            prepared[company][period] = {
                "original": baseline,
                "removed": removed,
                "normalized": normalized,
                "provider_count": len(
                    PATTERN.findall(baseline)
                ),
            }

            # 加入統一名稱版本，讓佔位詞進入詞彙表
            training_texts.extend([
                baseline,
                normalized
            ])

    # 三種條件共用同一套模型
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        tokenizer=tokenize,
        token_pattern=None,
    )

    vectorizer.fit(training_texts)

    results = []

    for company in prepared:
        left = prepared[company]["2025Q3"]
        right = prepared[company]["2025Q4"]

        original = similarity(
            vectorizer,
            left["original"],
            right["original"]
        )

        removed = similarity(
            vectorizer,
            left["removed"],
            right["removed"]
        )

        normalized = similarity(
            vectorizer,
            left["normalized"],
            right["normalized"]
        )

        row = {
            "company": company,
            "period": "2025Q3_to_2025Q4",
            "q3_provider_count":
                left["provider_count"],
            "q4_provider_count":
                right["provider_count"],
            "original_cosine":
                round(original, 6),
            "removed_cosine":
                round(removed, 6),
            "normalized_cosine":
                round(normalized, 6),
            "removal_change":
                round(removed - original, 6),
            "normalization_change":
                round(normalized - original, 6),
        }

        results.append(row)

        print("\n公司：", company)
        print("原始：", row["original_cosine"])
        print("刪除：", row["removed_cosine"])
        print("統一：", row["normalized_cosine"])
        print("刪除變化：", row["removal_change"])
        print("統一變化：", row["normalization_change"])

    report = {
        "experiment": "Provider name control",
        "method": "Shared TF-IDF model",
        "model_training":
            "Pooled baseline and normalized texts",
        "vocabulary_size":
            len(vectorizer.vocabulary_),
        "status": "EXPLORATORY_ONLY",
        "limitations": [
            "Uses all periods for model fitting.",
            "Not a chronological holdout.",
            "Provider normalization is not "
            "equivalent to removing all formatting.",
            "This experiment does not measure "
            "fraud detection performance.",
            "The TF-IDF fitting corpus differs "
            "from the previous fixed-model test."
        ],
        "results": results,
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    path = OUTPUT / (
        f"provider_control_{stamp}.json"
    )

    path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n實驗完成")
    print("結果檔案：", path)


if __name__ == "__main__":
    main()
