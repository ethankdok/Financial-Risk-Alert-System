
from pathlib import Path
import sys
import json
import re
import csv
from collections import Counter

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

sys.path.insert(0, str(ROOT))

from data_shift import tokenize
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

DATA_DIR = BACKEND / "data/official-ir-pdfs/2330"
OUTPUT_DIR = BACKEND / "data/research-results"

PERIODS = [
    f"{year}Q{quarter}"
    for year in [2024, 2025]
    for quarter in range(1, 5)
]


def load_documents():
    documents = {}

    for path in DATA_DIR.glob("acquisition-*.json"):
        manifest = json.loads(
            path.read_text(encoding="utf-8")
        )

        source = manifest.get("source_page", "").lower()

        for period in PERIODS:
            year = period[:4]
            quarter = period[-1]

            if f"/{year}/q{quarter}" not in source:
                continue

            for doc in manifest.get("documents", []):
                if "transcript" not in doc.get("title", "").lower():
                    continue

                if doc.get("status") != "text_extracted":
                    continue

                text_path = doc.get("text_path")

                if not text_path:
                    continue

                file = BACKEND / text_path

                if not file.exists():
                    continue

                text = file.read_text(encoding="utf-8")
                text = re.sub(
                    r"(?m)^\[page \d+\]\s*$",
                    " ",
                    text,
                )
                text = re.sub(r"\s+", " ", text).strip()

                record = {
                    "text": text,
                    "sha256": doc.get("sha256"),
                }

                if period in documents:
                    if documents[period]["sha256"] != record["sha256"]:
                        raise RuntimeError(
                            f"{period}: 發現不同版本，請人工確認"
                        )

                documents[period] = record

    missing = set(PERIODS) - set(documents)

    if missing:
        raise RuntimeError(f"缺少文件: {sorted(missing)}")

    return documents


def main():
    documents = load_documents()
    texts = [documents[p]["text"] for p in PERIODS]

    # 僅使用最早六期建立固定的詞彙與 IDF
    # 2025Q3、2025Q4 不參與模型訓練
    vectorizer = TfidfVectorizer(
        tokenizer=tokenize,
        token_pattern=None,
        lowercase=False,
        norm="l2",
    )

    vectorizer.fit(texts[:6])
    vectors = vectorizer.transform(texts)

    # 不使用 IDF 的詞頻向量，作為另一組檢查
    counters = [Counter(tokenize(t)) for t in texts]

    def count_cosine(a, b):
        common = set(a) & set(b)

        dot = sum(a[t] * b[t] for t in common)
        norm_a = sum(v*v for v in a.values()) ** 0.5
        norm_b = sum(v*v for v in b.values()) ** 0.5

        if not norm_a or not norm_b:
            raise RuntimeError("文件沒有有效詞彙")

        return dot / (norm_a * norm_b)

    rows = []

    print("\n=== 固定模型 Cosine 驗證 ===")

    for i in range(1, len(PERIODS)):
        before = PERIODS[i-1]
        after = PERIODS[i]

        fixed = float(
            cosine_similarity(
                vectors[i-1],
                vectors[i],
            )[0, 0]
        )

        count = count_cosine(
            counters[i-1],
            counters[i],
        )

        row = {
            "previous": before,
            "current": after,
            "fixed_tfidf_cosine": round(fixed, 6),
            "count_cosine": round(count, 6),
        }

        rows.append(row)
        print(row)

    # 檢查後兩期有多少詞彙不在訓練字典中
    vocabulary = set(vectorizer.vocabulary_)

    print("\n=== 未知詞彙檢查 ===")

    for period in ["2025Q3", "2025Q4"]:
        tokens = tokenize(documents[period]["text"])

        unknown = sum(
            token not in vocabulary
            for token in tokens
        )

        ratio = unknown / len(tokens) if tokens else 0

        print(
            period,
            "未知詞比例:",
            round(ratio, 4),
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "tsmc_cosine_validation.csv"

    with output.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0]),
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n結果儲存:", output)


if __name__ == "__main__":
    main()
