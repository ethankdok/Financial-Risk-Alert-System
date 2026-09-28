
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(ROOT))

from data_shift import (
    calculate_jsd,
    calculate_cosine_similarity,
    check_data_quality,
)

DATA_DIR = BACKEND / "data/official-ir-pdfs/2454"
OUT = BACKEND / "data/research-results"

PERIODS = [
    f"{year}Q{q}"
    for year in (2024, 2025)
    for q in range(1, 5)
]


def clean_text(text):
    text = re.sub(
        r"(?m)^\[page \d+\]\s*$",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def load_documents():
    found = {period: {} for period in PERIODS}

    for path in DATA_DIR.glob("acquisition-*.json"):
        manifest = json.loads(
            path.read_text(encoding="utf-8")
        )

        url = unquote(
            manifest.get("source_page", "")
        ).lower()

        # 僅接受逐字稿，不混入財報或簡報
        if not any(
            word in url
            for word in ("transcript", "逐字稿")
        ):
            continue

        for period in PERIODS:
            if period.lower() not in url:
                continue

            for doc in manifest.get("documents", []):
                if doc.get("status") != "text_extracted":
                    continue

                sha = doc.get("sha256")
                text_path = doc.get("text_path")

                if not sha or not text_path:
                    continue

                text_file = BACKEND / text_path

                if not text_file.is_file():
                    continue

                found[period][sha] = {
                    "period": period,
                    "sha256": sha,
                    "source_url": doc.get(
                        "resolved_document_url"
                    ),
                    "page_count": doc.get("page_count"),
                    "low_text_page_count": doc.get(
                        "low_text_page_count", 0
                    ),
                    "text": clean_text(
                        text_file.read_text(
                            encoding="utf-8"
                        )
                    ),
                }

    documents = {}

    for period in PERIODS:
        versions = found[period]

        if len(versions) != 1:
            raise RuntimeError(
                f"{period} 找到 {len(versions)} "
                "個文件版本，請先檢查下載紀錄。"
            )

        documents[period] = next(
            iter(versions.values())
        )

    return documents


def main():
    documents = load_documents()
    rows = []

    for i in range(1, len(PERIODS)):
        before = documents[PERIODS[i - 1]]
        after = documents[PERIODS[i]]

        quality = check_data_quality(
            before["text"],
            after["text"],
        )

        if not quality["passed"]:
            raise RuntimeError(
                f"{before['period']} → "
                f"{after['period']} 品質檢查失敗："
                f"{quality['reasons']}"
            )

        row = {
            "before": before["period"],
            "after": after["period"],
            "jsd": calculate_jsd(
                before["text"], after["text"]
            ),
            "cosine": calculate_cosine_similarity(
                before["text"], after["text"]
            ),
            "before_sha256": before["sha256"],
            "after_sha256": after["sha256"],
            "before_characters": len(before["text"]),
            "after_characters": len(after["text"]),
        }

        rows.append(row)

        print(
            f"{row['before']} → {row['after']} | "
            f"JSD: {row['jsd']:.6f} | "
            f"Cosine: {row['cosine']:.6f}",
            flush=True,
        )

    # 前五組作探索性校準
    # 後兩組保留測試
    calibration = rows[:5]
    holdout = rows[5:]

    thresholds = {
        "sample_size": len(calibration),
        "jsd_p90": float(np.percentile(
            [x["jsd"] for x in calibration], 90
        )),
        "jsd_p95": float(np.percentile(
            [x["jsd"] for x in calibration], 95
        )),
        "cosine_p05": float(np.percentile(
            [x["cosine"] for x in calibration], 5
        )),
        "status": "EXPLORATORY_ONLY",
    }

    report = {
        "experiment": "MediaTek historical transcript comparison",
        "ticker": "2454",
        "periods": PERIODS,
        "method": {
            "preprocessing": (
                "Remove page markers and "
                "normalize whitespace"
            ),
            "comparison": "Adjacent quarters",
            "vectorization": "Original pairwise method",
        },
        "documents": [
            {
                k: v for k, v in doc.items()
                if k != "text"
            }
            for doc in documents.values()
        ],
        "comparisons": rows,
        "thresholds": thresholds,
        "holdout": holdout,
        "limitations": [
            "Only five calibration comparisons.",
            "Thresholds are exploratory.",
            "Full document review is incomplete.",
            "Results do not indicate fraud.",
        ],
    }

    OUT.mkdir(parents=True, exist_ok=True)

    json_path = OUT / "mediatek_history.json"
    csv_path = OUT / "mediatek_history.csv"

    json_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    with csv_path.open(
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

    print("\n=== 聯發科歷史實驗摘要 ===")
    print("成功取得季度:", PERIODS)
    print("比較組數:", len(rows))
    print("探索性門檻:", thresholds)
    print("保留測試組數:", len(holdout))
    print("JSON:", json_path)
    print("CSV:", csv_path)


if __name__ == "__main__":
    main()
