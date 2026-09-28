
from __future__ import annotations

import csv
import json
import re
from urllib.parse import unquote
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(ROOT))

from data_shift import (
    calculate_jsd,
    calculate_cosine_similarity,
    check_data_quality,
    tokenize,
)

DATA_DIR = BACKEND / "data/official-ir-pdfs/2454"
OUTPUT_DIR = BACKEND / "data/research-results"


def load_transcript(period):
    matches = {}
    
    for path in DATA_DIR.glob("acquisition-*.json"):
        manifest = json.loads(
            path.read_text(encoding="utf-8")
        )
        
        source = manifest.get("source_page", "")
        if period.lower() not in source.lower():
            continue

        for doc in manifest.get("documents", []):
            if doc.get("status") != "text_extracted":
                continue

            url = doc.get("resolved_document_url", "")
            if "逐" not in unquote(source) and "transcript" not in unquote(url).lower():
                continue

            text_path = doc.get("text_path")
            if not text_path:
                continue

            file = BACKEND / text_path
            if not file.exists():
                continue

            matches[doc["sha256"]] = {
                "period": period,
                "text": file.read_text(encoding="utf-8"),
                "sha256": doc["sha256"],
                "source_url": url,
                "pages": doc.get("page_count"),
                "low_text_pages": doc.get(
                    "low_text_page_count", 0
                ),
            }

    if len(matches) != 1:
        raise RuntimeError(
            f"{period}: 找到 {len(matches)} 個文件版本，"
            "請確認下載紀錄。"
        )

    return next(iter(matches.values()))


def split_pages(text):
    parts = re.split(
        r"(?m)^\[page (\d+)\]\s*$",
        text
    )

    return {
        int(parts[i]): parts[i + 1].strip()
        for i in range(1, len(parts) - 1, 2)
    }


def clean_text(text):
    text = re.sub(
        r"(?m)^\[page \d+\]\s*$",
        " ",
        text
    )
    return re.sub(r"\s+", " ", text).strip()


def calculate(a, b):
    quality = check_data_quality(a, b)

    if not tokenize(a) or not tokenize(b):
        raise RuntimeError("缺少有效詞彙")

    return {
        "jsd": round(calculate_jsd(a, b), 6),
        "cosine": round(
            calculate_cosine_similarity(a, b),
            6
        ),
        "quality": quality,
    }


def main():
    q3 = load_transcript("2025Q3")
    q4 = load_transcript("2025Q4")

    for doc in (q3, q4):
        print("\n季度:", doc["period"])
        print("文件頁數:", doc["pages"])
        print("SHA-256:", doc["sha256"])

        pages = split_pages(doc["text"])

        print("可擷取文字頁數:", len(pages))

        low_pages = [
            (number, len(content))
            for number, content in pages.items()
            if len(content) < 100
        ]

        print("文字不足頁面:", low_pages)

        for number, length in low_pages:
            print(
                f"第 {number} 頁預覽:",
                pages[number][:200]
            )

    original = calculate(
        q3["text"],
        q4["text"]
    )

    cleaned3 = clean_text(q3["text"])
    cleaned4 = clean_text(q4["text"])

    cleaned = calculate(cleaned3, cleaned4)

    needs_review = (
        q3["low_text_pages"] > 0
        or q4["low_text_pages"] > 0
        or not original["quality"]["passed"]
        or not cleaned["quality"]["passed"]
    )

    results = {
        "experiment": "MediaTek 2025 Q3-Q4",
        "status": (
            "NEEDS_MANUAL_REVIEW"
            if needs_review
            else "PRELIMINARY"
        ),
        "documents": [
            {
                key: value
                for key, value in doc.items()
                if key != "text"
            }
            for doc in (q3, q4)
        ],
        "original": original,
        "cleaned": cleaned,
        "limitations": [
            "Document publication dates require verification.",
            "Low-text pages require manual review.",
            "Results do not indicate fraud risk.",
            "No historical threshold has been calibrated.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output = OUTPUT_DIR / "mediatek_q3_q4.json"
    output.write_text(
        json.dumps(
            results,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    csv_path = OUTPUT_DIR / "mediatek_q3_q4.csv"

    with csv_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.writer(file)
        writer.writerow(["version", "jsd", "cosine"])

        for name in ("original", "cleaned"):
            writer.writerow([
                name,
                results[name]["jsd"],
                results[name]["cosine"],
            ])

    print("\n=== 聯發科比較結果 ===")

    for name in ("original", "cleaned"):
        print(name, results[name])

    print("\n實驗狀態:", results["status"])
    print("JSON:", output)
    print("CSV:", csv_path)


if __name__ == "__main__":
    main()
