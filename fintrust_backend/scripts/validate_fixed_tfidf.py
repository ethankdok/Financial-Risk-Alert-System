import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from scripts.cross_company_seven_quarters import (
    PERIODS,
    prepare_documents,
    basic_clean,
    remove_provider,
)
from scripts.test_provider_impact import (
    calculate_cosine_similarity,
)

OUTPUT = Path("data/research-results")

# 直接取得原本研究程式使用的 tokenizer
original_globals = calculate_cosine_similarity.__globals__
tokenize = original_globals.get("tokenize")

if not callable(tokenize):
    raise RuntimeError(
        "找不到原始 tokenizer，停止實驗"
    )


def sha256(text):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def main():
    documents = prepare_documents()

    prepared = {}
    training_texts = []

    # 1. 統一進行原本的文字清理
    for company, company_docs in documents.items():
        prepared[company] = {}

        for period in PERIODS:
            original = company_docs[period]
            before = basic_clean(original)
            after = remove_provider(before)

            if not before.strip() or not after.strip():
                raise ValueError(
                    f"{company} {period} 文字為空"
                )

            prepared[company][period] = {
                "before": before,
                "after": after,
                "sha256": sha256(original),
                "changed": before != after,
                "removed_tokens": (
                    len(tokenize(before))
                    - len(tokenize(after))
                )
            }

            training_texts.append(before)

    # 2. 所有原始清理文字只建立一次模型
    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        tokenizer=tokenize,
        token_pattern=None,
    )

    vectorizer.fit(training_texts)

    print(
        "固定詞彙數量：",
        len(vectorizer.vocabulary_)
    )

    # 3. 以同一模型轉換所有文件
    for company, company_docs in prepared.items():
        for period, doc in company_docs.items():
            doc["before_vector"] = (
                vectorizer.transform([doc["before"]])
            )
            doc["after_vector"] = (
                vectorizer.transform([doc["after"]])
            )

    # 4. 計算清理前後的 Cosine
    rows = []

    for company, company_docs in prepared.items():
        for previous, current in zip(
            PERIODS[:-1],
            PERIODS[1:]
        ):
            a = company_docs[previous]
            b = company_docs[current]

            baseline = float(
                cosine_similarity(
                    a["before_vector"],
                    b["before_vector"]
                )[0][0]
            )

            modified = float(
                cosine_similarity(
                    a["after_vector"],
                    b["after_vector"]
                )[0][0]
            )

            old_result = calculate_cosine_similarity(
                a["before"],
                b["before"]
            )

            removed_count = (
                len(re.findall(
                    r"\b(?:refinitiv|lseg)\b",
                    a["before"],
                    flags=re.I
                ))
                +
                len(re.findall(
                    r"\b(?:refinitiv|lseg)\b",
                    b["before"],
                    flags=re.I
                ))
            )

            row = {
                "company": company,
                "previous_period": previous,
                "current_period": current,
                "previous_text_sha256": a["sha256"],
                "current_text_sha256": b["sha256"],
                "provider_terms_before":
                    removed_count,
                "text_changed": (
                    a["changed"] or b["changed"]
                ),
                "old_cosine": round(
                    old_result, 6
                ),
                "fixed_before": round(
                    baseline, 6
                ),
                "fixed_after": round(
                    modified, 6
                ),
                "fixed_change": round(
                    modified - baseline, 6
                )
            }

            rows.append(row)

            print(
                company,
                previous, "->", current,
                "原方法:", row["old_cosine"],
                "固定清理前:", row["fixed_before"],
                "固定清理後:", row["fixed_after"],
                "變化:", row["fixed_change"]
            )

    assert len(rows) == 14

    # 沒有修改文字的實驗，變化必須為零
    for row in rows:
        if not row["text_changed"]:
            assert abs(row["fixed_change"]) < 1e-10

    # 5. 保存模型與研究資訊
    timestamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S_%f")

    report = {
        "experiment": "Fixed TF-IDF ablation",
        "generated_at": timestamp,
        "training": (
            "Pooled baseline corpus: "
            "both companies, all eight quarters"
        ),
        "vocabulary_size": len(
            vectorizer.vocabulary_
        ),
        "status": "EXPLORATORY_ONLY",
        "limitations": [
            "All periods are used to fit the model.",
            "This is not a chronological holdout.",
            "Original extracted text SHA-256 "
            "is not the PDF file hash.",
            "JSD is not recalculated here.",
            "Provider-token removal does not "
            "remove every source-format effect."
        ],
        "results": rows
    }

    OUTPUT.mkdir(
        parents=True,
        exist_ok=True
    )

    json_path = OUTPUT / (
        f"fixed_tfidf_{timestamp}.json"
    )

    csv_path = OUTPUT / (
        f"fixed_tfidf_{timestamp}.csv"
    )

    json_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    with csv_path.open(
        "x",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys())
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n=== 實驗完成 ===")
    print("比較組數：", len(rows))
    print("JSON：", json_path)
    print("CSV：", csv_path)


if __name__ == "__main__":
    main()
