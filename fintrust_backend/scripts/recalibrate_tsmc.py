
import csv
import json
import sys
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.append(str(ROOT))

from data_shift import (
    calculate_jsd,
    calculate_cosine_similarity,
    check_data_quality,
)
from scripts.build_tsmc_history import (
    existing_transcript,
    clean_text,
)
from scripts.test_provider_impact import remove_provider

PERIODS = [
    f"{year}Q{quarter}"
    for year in (2024, 2025)
    for quarter in range(1, 5)
]

OUTPUT = BACKEND / "data" / "research-results"


def calculate(a, b):
    return {
        "jsd": calculate_jsd(a, b),
        "cosine": calculate_cosine_similarity(a, b),
    }


def main():
    documents = {}

    for period in PERIODS:
        doc = existing_transcript(period)

        if doc is None:
            raise RuntimeError(
                f"缺少 {period} 逐字稿，停止實驗"
            )

        original = clean_text(doc["text"])
        documents[period] = {
            "sha256": doc["sha256"],
            "original": original,
            "cleaned": remove_provider(original),
        }

    rows = []

    for i in range(1, len(PERIODS)):
        before = PERIODS[i - 1]
        after = PERIODS[i]

        a = documents[before]
        b = documents[after]

        quality = check_data_quality(
            a["cleaned"], b["cleaned"]
        )

        if not quality["passed"]:
            raise RuntimeError(
                f"{before} → {after}: "
                f"品質檢查未通過：{quality['reasons']}"
            )

        old = calculate(
            a["original"], b["original"]
        )
        new = calculate(
            a["cleaned"], b["cleaned"]
        )

        row = {
            "before": before,
            "after": after,
            "original_jsd": old["jsd"],
            "cleaned_jsd": new["jsd"],
            "original_cosine": old["cosine"],
            "cleaned_cosine": new["cosine"],
            "jsd_change": new["jsd"] - old["jsd"],
            "cosine_change": (
                new["cosine"] - old["cosine"]
            ),
        }
        rows.append(row)
        print(
            f"{before} → {after}: "
            f"JSD {new['jsd']:.6f}, "
            f"Cosine {new['cosine']:.6f}"
        )

    calibration = rows[:5]
    holdout = rows[5:]

    thresholds = {
        "sample_size": len(calibration),
        "jsd_p90": float(np.percentile(
            [r["cleaned_jsd"] for r in calibration],
            90
        )),
        "jsd_p95": float(np.percentile(
            [r["cleaned_jsd"] for r in calibration],
            95
        )),
        "cosine_p05": float(np.percentile(
            [r["cleaned_cosine"] for r in calibration],
            5
        )),
        "status": "EXPLORATORY_ONLY",
    }

    report = {
        "experiment": "TSMC provider normalization",
        "method": "Pairwise TF-IDF and JSD",
        "preprocessing": (
            "Basic cleaning and provider-brand "
            "token removal"
        ),
        "documents": {
            period: documents[period]["sha256"]
            for period in PERIODS
        },
        "comparisons": rows,
        "thresholds": thresholds,
        "holdout": holdout,
    }

    OUTPUT.mkdir(parents=True, exist_ok=True)

    csv_path = OUTPUT / "tsmc_recalibrated.csv"
    with csv_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(rows[0])
        )
        writer.writeheader()
        writer.writerows(rows)

    json_path = OUTPUT / "tsmc_recalibrated.json"
    json_path.write_text(
        json.dumps(
            report, ensure_ascii=False, indent=2
        ),
        encoding="utf-8"
    )

    print("\n=== 新探索性門檻 ===")
    print(json.dumps(
        thresholds, indent=2, ensure_ascii=False
    ))
    print("\n=== 保留測試資料 ===")
    for row in holdout:
        print(row)

    print("\nCSV:", csv_path)
    print("JSON:", json_path)


if __name__ == "__main__":
    main()
