
from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# 允許 scripts 裡的程式引用專案根目錄的 data_shift.py
ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data_shift import (
    calculate_jsd,
    calculate_cosine_similarity,
    check_data_quality,
    tokenize,
)

DATA_DIR = BACKEND / "data" / "official-ir-pdfs" / "2330"
OUTPUT_DIR = BACKEND / "data" / "research-results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PERIODS = {
    "2025Q3": "/2025/q3",
    "2025Q4": "/2025/q4",
}


def load_transcript(period, url_fragment):
    matches = []

    for manifest in DATA_DIR.glob("acquisition-*.json"):
        data = json.loads(manifest.read_text(encoding="utf-8"))

        if url_fragment not in data.get("source_page", "").lower():
            continue

        for doc in data.get("documents", []):
            title = doc.get("title", "").lower()

            if "transcript" not in title:
                continue

            if doc.get("status") != "text_extracted":
                continue

            text_path = doc.get("text_path")
            if not text_path:
                continue

            path = BACKEND / text_path
            if not path.exists():
                continue

            text = path.read_text(encoding="utf-8")

            matches.append({
                "period": period,
                "text": text,
                "sha256": doc.get("sha256"),
                "source_url": doc.get("resolved_document_url"),
                "pages": doc.get("page_count"),
                "length": len(text),
            })

    if len(matches) != 1:
        raise RuntimeError(
            f"{period}: 找到 {len(matches)} 份逐字稿，"
            "預期恰好一份。請檢查 manifest。"
        )

    return matches[0]


def clean_text(text):
    # 第一階段採用保守清理：
    # 1. 移除下載程式自行加入的頁碼標記
    # 2. 統一空白字元
    # 不刪除財務數字、公司名稱或實質發言
    text = re.sub(
        r"(?m)^\[page \d+\]\s*$",
        " ",
        text,
    )

    text = re.sub(r"\s+", " ", text)

    return text.strip()


def mask_company_terms(text):
    # 敏感度測試，不是主要清理版本。
    patterns = [
        r"\bTSMC\b",
        r"\bTaiwan Semiconductor Manufacturing Company\b",
    ]

    for pattern in patterns:
        text = re.sub(
            pattern,
            "COMPANY",
            text,
            flags=re.IGNORECASE,
        )

    return text


def calculate(text1, text2):
    quality = check_data_quality(text1, text2)

    tokens1 = tokenize(text1)
    tokens2 = tokenize(text2)

    if not tokens1 or not tokens2:
        raise RuntimeError("文字沒有有效 token，停止計算。")

    return {
        "q3_characters": len(text1),
        "q4_characters": len(text2),
        "q3_tokens": len(tokens1),
        "q4_tokens": len(tokens2),
        "jsd": round(calculate_jsd(text1, text2), 6),
        "cosine": round(
            calculate_cosine_similarity(text1, text2),
            6,
        ),
        "quality_check": quality,
    }


def main():
    q3 = load_transcript(
        "2025Q3",
        PERIODS["2025Q3"],
    )

    q4 = load_transcript(
        "2025Q4",
        PERIODS["2025Q4"],
    )

    original = calculate(
        q3["text"],
        q4["text"],
    )

    cleaned_q3 = clean_text(q3["text"])
    cleaned_q4 = clean_text(q4["text"])

    cleaned = calculate(
        cleaned_q3,
        cleaned_q4,
    )

    masked = calculate(
        mask_company_terms(cleaned_q3),
        mask_company_terms(cleaned_q4),
    )

    results = {
        "experiment": "TSMC transcript comparison",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "company": "2330",
        "documents": [
            {k: v for k, v in doc.items() if k != "text"}
            for doc in (q3, q4)
        ],
        "method": {
            "jsd": "Existing data_shift.py JSD",
            "cosine": "Existing data_shift.py TF-IDF Cosine",
            "baseline": "Extracted text with page markers",
            "cleaned": "Remove page markers; normalize whitespace",
            "sensitivity": "Mask specified company names",
            "threshold": "Not calibrated for official PDFs",
        },
        "results": {
            "original": original,
            "cleaned": cleaned,
            "company_masked": masked,
        },
    }

    json_path = OUTPUT_DIR / "tsmc_q3_q4_results.json"
    csv_path = OUTPUT_DIR / "tsmc_q3_q4_comparison.csv"

    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:
        writer = csv.writer(f)

        writer.writerow([
            "Experiment",
            "Q3 characters",
            "Q4 characters",
            "Q3 tokens",
            "Q4 tokens",
            "JSD",
            "Cosine",
            "Quality passed",
        ])

        for name, result in results["results"].items():
            writer.writerow([
                name,
                result["q3_characters"],
                result["q4_characters"],
                result["q3_tokens"],
                result["q4_tokens"],
                result["jsd"],
                result["cosine"],
                result["quality_check"]["passed"],
            ])

    print("\n=== TSMC Q3 vs Q4 ===")

    for name, result in results["results"].items():
        print(f"\n{name}")
        print("JSD:", result["jsd"])
        print("Cosine:", result["cosine"])
        print("Q3 tokens:", result["q3_tokens"])
        print("Q4 tokens:", result["q4_tokens"])
        print(
            "Quality:",
            result["quality_check"]["passed"],
        )

    print("\nCSV:", csv_path)
    print("JSON:", json_path)
    print(
        "\n注意：此實驗不直接使用 STRUX 歷史門檻，"
        "也不將文字漂移視為詐騙證據。"
    )


if __name__ == "__main__":
    main()
