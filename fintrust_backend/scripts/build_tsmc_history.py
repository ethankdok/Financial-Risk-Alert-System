
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

sys.path.insert(0, str(BACKEND))
sys.path.append(str(ROOT))

from app.services.official_ir_pdf_archive import acquire_page
from data_shift import (
    calculate_jsd,
    calculate_cosine_similarity,
    check_data_quality,
)

DATA_DIR = BACKEND / "data" / "official-ir-pdfs"
RESULT_DIR = BACKEND / "data" / "research-results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

PERIODS = [
    f"{year}Q{quarter}"
    for year in (2024, 2025)
    for quarter in (1, 2, 3, 4)
]


def official_url(period):
    year = period[:4]
    quarter = period[-1]

    return (
        "https://investor.tsmc.com/english/"
        f"quarterly-results/{year}/q{quarter}"
    )


def existing_transcript(period):
    folder = DATA_DIR / "2330"
    source = official_url(period)

    if not folder.exists():
        return None

    for manifest_path in folder.glob("acquisition-*.json"):
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )

        if manifest.get("source_page") != source:
            continue

        for doc in manifest.get("documents", []):
            if "transcript" not in doc.get("title", "").lower():
                continue

            if doc.get("status") != "text_extracted":
                continue

            text_path = doc.get("text_path")
            if not text_path:
                continue

            path = BACKEND / text_path

            if not path.exists():
                continue

            return {
                "period": period,
                "text": path.read_text(encoding="utf-8"),
                "sha256": doc.get("sha256"),
                "source_url": doc.get("resolved_document_url"),
                "page_count": doc.get("page_count"),
            }

    return None


def acquire_transcript(period):
    cached = existing_transcript(period)

    if cached:
        print(f"{period}: 使用既有逐字稿")
        return cached

    print(f"{period}: 嘗試下載官方 PDF")

    try:
        result = acquire_page(
            ticker="2330",
            company_name="TSMC",
            page_url=official_url(period),
            output_dir=DATA_DIR,
            max_documents=8,
        )

        transcripts = [
            doc for doc in result.get("documents", [])
            if "transcript" in doc.get("title", "").lower()
            and doc.get("status") == "text_extracted"
        ]

        if len(transcripts) != 1:
            print(
                f"{period}: 取得 {len(transcripts)} "
                "份可用逐字稿，跳過"
            )
            return None

        return existing_transcript(period)

    except Exception as exc:
        print(
            f"{period}: 下載失敗 "
            f"({type(exc).__name__}: {exc})"
        )
        return None


def clean_text(text):
    import re

    text = re.sub(
        r"(?m)^\[page \d+\]\s*$",
        " ",
        text,
    )
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def compare(previous, current):
    text1 = clean_text(previous["text"])
    text2 = clean_text(current["text"])

    quality = check_data_quality(text1, text2)

    row = {
        "previous_period": previous["period"],
        "current_period": current["period"],
        "previous_sha256": previous["sha256"],
        "current_sha256": current["sha256"],
        "previous_characters": len(text1),
        "current_characters": len(text2),
        "quality_passed": quality["passed"],
        "quality_reasons": "; ".join(quality["reasons"]),
        "jsd": None,
        "cosine": None,
    }

    if not quality["passed"]:
        return row

    row["jsd"] = calculate_jsd(text1, text2)
    row["cosine"] = calculate_cosine_similarity(
        text1, text2
    )

    return row


def main():
    documents = {}
    missing = []

    for period in PERIODS:
        doc = acquire_transcript(period)

        if doc:
            documents[period] = doc
        else:
            missing.append(period)

    rows = []

    # 只比較真正相鄰的季度，絕不跳過缺漏季度配對
    for i in range(1, len(PERIODS)):
        before = PERIODS[i - 1]
        after = PERIODS[i]

        if before not in documents or after not in documents:
            continue

        row = compare(documents[before], documents[after])
        rows.append(row)

        print(
            f"{before} -> {after}: "
            f"JSD={row['jsd']}, "
            f"Cosine={row['cosine']}"
        )

    # 以較早的期間建立探索性基準
    # 最後兩組相鄰季度留作後期觀察
    calibration = [
        row for row in rows
        if row["current_period"] <= "2025Q2"
        and row["quality_passed"]
    ]

    holdout = [
        row for row in rows
        if row["current_period"] > "2025Q2"
        and row["quality_passed"]
    ]

    thresholds = None

    if len(calibration) >= 4:
        jsd_values = [
            row["jsd"] for row in calibration
        ]
        cosine_values = [
            row["cosine"] for row in calibration
        ]

        thresholds = {
            "sample_size": len(calibration),
            "jsd_p90": float(
                np.percentile(jsd_values, 90)
            ),
            "jsd_p95": float(
                np.percentile(jsd_values, 95)
            ),
            "cosine_p05": float(
                np.percentile(cosine_values, 5)
            ),
            "status": "EXPLORATORY_ONLY",
        }

    report = {
        "experiment": "TSMC multi-quarter transcript history",
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "periods_requested": PERIODS,
        "periods_available": sorted(documents),
        "periods_missing": missing,
        "method": {
            "comparison": "Adjacent quarters only",
            "preprocessing": "Remove page markers and normalize whitespace",
            "publication_dates": "Require independent verification",
            "threshold_status": "Exploratory, not production",
        },
        "documents": [
            {
                k: v
                for k, v in doc.items()
                if k != "text"
            }
            for doc in documents.values()
        ],
        "comparisons": rows,
        "thresholds": thresholds,
        "holdout_comparisons": holdout,
    }

    json_path = RESULT_DIR / "tsmc_history.json"
    csv_path = RESULT_DIR / "tsmc_history.csv"

    json_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    fields = [
        "previous_period",
        "current_period",
        "previous_sha256",
        "current_sha256",
        "previous_characters",
        "current_characters",
        "quality_passed",
        "quality_reasons",
        "jsd",
        "cosine",
    ]

    with csv_path.open(
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n=== 歷史實驗摘要 ===")
    print("成功取得季度:", sorted(documents))
    print("缺漏季度:", missing)
    print("跨期比較數量:", len(rows))
    print("探索性門檻:", thresholds)
    print("後期測試組數:", len(holdout))
    print("CSV:", csv_path)
    print("JSON:", json_path)

    print(
        "\n注意：須人工核對逐字稿期別、"
        "首次發布日期及文字擷取內容。"
    )


if __name__ == "__main__":
    main()
