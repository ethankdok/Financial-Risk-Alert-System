
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

sys.path.append(str(ROOT))

from data_shift import tokenize

DATA_DIR = BACKEND / "data" / "official-ir-pdfs" / "2330"
OUT = BACKEND / "data" / "research-results"

PERIODS = [
    f"{year}Q{quarter}"
    for year in (2024, 2025)
    for quarter in (1, 2, 3, 4)
]


def clean_text(text):
    text = re.sub(
        r"(?m)^\[page \d+\]\s*$",
        " ",
        text
    )
    return re.sub(r"\s+", " ", text).strip()


def load_documents():
    documents = {}

    for file in sorted(DATA_DIR.glob("acquisition-*.json")):
        manifest = json.loads(
            file.read_text(encoding="utf-8")
        )

        source = manifest.get("source_page", "").lower()

        for period in PERIODS:
            year = period[:4]
            quarter = period[-1]

            if f"/{year}/q{quarter}" not in source:
                continue

            for doc in manifest.get("documents", []):
                if "transcript" not in doc.get(
                    "title", ""
                ).lower():
                    continue

                if doc.get("status") != "text_extracted":
                    continue

                text_path = doc.get("text_path")
                if not text_path:
                    continue

                path = BACKEND / text_path

                if not path.exists():
                    continue

                record = {
                    "text": clean_text(
                        path.read_text(encoding="utf-8")
                    ),
                    "sha256": doc.get("sha256"),
                    "source_url": doc.get(
                        "resolved_document_url"
                    ),
                }

                if period in documents:
                    old = documents[period]

                    if old["sha256"] != record["sha256"]:
                        raise RuntimeError(
                            f"{period} 存在不同文件版本，"
                            "請先人工確認。"
                        )

                documents[period] = record

    missing = set(PERIODS) - set(documents)

    if missing:
        raise RuntimeError(
            f"缺少季度文件: {sorted(missing)}"
        )

    return documents


def save_csv(filename, rows, fields):
    path = OUT / filename

    with path.open(
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields
        )
        writer.writeheader()
        writer.writerows(rows)

    return str(path)


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    docs = load_documents()

    tokens = {
        period: tokenize(docs[period]["text"])
        for period in PERIODS
    }

    counts = {
        period: Counter(tokens[period])
        for period in PERIODS
    }

    # 前六期建立歷史詞彙庫
    historical_vocabulary = set()

    for period in PERIODS[:6]:
        historical_vocabulary.update(tokens[period])

    q3 = counts["2025Q3"]
    q4 = counts["2025Q4"]

    total3 = sum(q3.values())
    total4 = sum(q4.values())

    # 實驗 A：分析 Q4 未知詞
    unknown = []

    for word, count in q4.items():
        if word in historical_vocabulary:
            continue

        unknown.append({
            "word": word,
            "q4_count": count,
            "q3_count": q3.get(word, 0),
            "q4_per_1000": round(
                count / total4 * 1000, 4
            ),
        })

    unknown.sort(
        key=lambda row: row["q4_count"],
        reverse=True
    )

    # 實驗 B：比較 Q3、Q4 詞彙變化
    changes = []

    for word in set(q3) | set(q4):
        count3 = q3[word]
        count4 = q4[word]

        if count3 + count4 < 3:
            continue

        rate3 = count3 / total3 * 1000
        rate4 = count4 / total4 * 1000

        changes.append({
            "word": word,
            "q3_count": count3,
            "q4_count": count4,
            "q3_per_1000": round(rate3, 4),
            "q4_per_1000": round(rate4, 4),
            "change_per_1000": round(
                rate4 - rate3, 4
            ),
        })

    emerging = sorted(
        changes,
        key=lambda row: row["change_per_1000"],
        reverse=True
    )

    disappearing = sorted(
        changes,
        key=lambda row: row["change_per_1000"]
    )

    # 實驗 C：量化未知詞比例
    unknown_ratios = {}

    for period in ["2025Q3", "2025Q4"]:
        values = tokens[period]

        unknown_count = sum(
            word not in historical_vocabulary
            for word in values
        )

        unknown_ratios[period] = {
            "token_count": len(values),
            "unknown_count": unknown_count,
            "unknown_ratio": (
                unknown_count / len(values)
                if values else None
            ),
        }

    files = {}

    files["unknown"] = save_csv(
        "tsmc_q4_unknown_words.csv",
        unknown,
        [
            "word",
            "q4_count",
            "q3_count",
            "q4_per_1000"
        ]
    )

    files["emerging"] = save_csv(
        "tsmc_q4_emerging_words.csv",
        emerging,
        [
            "word",
            "q3_count",
            "q4_count",
            "q3_per_1000",
            "q4_per_1000",
            "change_per_1000"
        ]
    )

    files["disappearing"] = save_csv(
        "tsmc_q4_disappearing_words.csv",
        disappearing,
        [
            "word",
            "q3_count",
            "q4_count",
            "q3_per_1000",
            "q4_per_1000",
            "change_per_1000"
        ]
    )

    report = {
        "experiment": "TSMC vocabulary analysis",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "training_periods": PERIODS[:6],
        "evaluation_periods": [
            "2025Q3",
            "2025Q4"
        ],
        "documents": {
            period: {
                "sha256": docs[period]["sha256"],
                "source_url": docs[period]["source_url"]
            }
            for period in PERIODS
        },
        "unknown_ratios": unknown_ratios,
        "top_unknown": unknown[:30],
        "top_emerging": emerging[:30],
        "top_disappearing": disappearing[:30],
        "output_files": files,
        "limitations": [
            "Unknown terms are not risk labels.",
            "Names and formatting may affect results.",
            "Document sections are not separated.",
            "Publication dates require verification."
        ]
    }

    report_path = OUT / "tsmc_vocabulary_analysis.json"

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    print("\n=== 未知詞比例 ===")

    for period, result in unknown_ratios.items():
        print(
            period,
            round(result["unknown_ratio"] * 100, 2),
            "%"
        )

    print("\n=== Q4 高頻未知詞 TOP 20 ===")

    for row in unknown[:20]:
        print(row["word"], row["q4_count"])

    print("\n=== Q4 相對增加詞彙 TOP 20 ===")

    for row in emerging[:20]:
        print(
            row["word"],
            row["change_per_1000"]
        )

    print("\n=== Q4 相對減少詞彙 TOP 20 ===")

    for row in disappearing[:20]:
        print(
            row["word"],
            row["change_per_1000"]
        )

    print("\n結果檔案：")
    for path in files.values():
        print(path)

    print(report_path)


if __name__ == "__main__":
    main()
