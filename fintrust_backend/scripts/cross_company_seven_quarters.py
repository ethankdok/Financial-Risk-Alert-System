import csv
import hashlib
import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.test_provider_impact import (
    calculate_jsd,
    calculate_cosine_similarity,
)
from scripts.build_tsmc_history import existing_transcript
from scripts.build_mediatek_history import load_documents
from scripts.test_provider_impact import (
    basic_clean,
    remove_provider,
    evaluate,
)

PERIODS = [
    "2024Q1", "2024Q2", "2024Q3", "2024Q4",
    "2025Q1", "2025Q2", "2025Q3", "2025Q4"
]

OUTPUT = Path("data/research-results")
PATTERN = re.compile(
    r"\b(?:refinitiv|lseg)\b",
    re.IGNORECASE
)


def get_text(value):
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ("text", "raw_text", "content"):
            if isinstance(value.get(key), str):
                return value[key]

    raise ValueError("無法確認原始文字格式")


def sha256(text):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def prepare_documents():
    mediatek = load_documents()

    if not isinstance(mediatek, dict):
        raise ValueError("聯發科文件結構不正確")

    result = {"TSMC": {}, "MediaTek": {}}

    for period in PERIODS:
        result["TSMC"][period] = get_text(
            existing_transcript(period)
        )

        if period not in mediatek:
            raise ValueError(
                f"聯發科缺少 {period} 文件"
            )

        result["MediaTek"][period] = get_text(
            mediatek[period]
        )

    return result


def calculate_company(company, documents):
    prepared = {}
    rows = []

    for period, original in documents.items():
        if len(original.strip()) < 5000:
            raise ValueError(
                f"{company} {period} 原文過短"
            )

        cleaned = basic_clean(original)
        modified = remove_provider(cleaned)

        if not isinstance(cleaned, str):
            raise TypeError("清理函式未回傳文字")

        if not isinstance(modified, str):
            raise TypeError("移除函式未回傳文字")

        prepared[period] = {
            "original_sha256": sha256(original),
            "original_length": len(original),
            "before": cleaned,
            "after": modified,
            "before_count": len(
                PATTERN.findall(cleaned)
            ),
            "after_count": len(
                PATTERN.findall(modified)
            )
        }

    for previous, current in zip(
        PERIODS[:-1], PERIODS[1:]
    ):
        left = prepared[previous]
        right = prepared[current]

        baseline = evaluate(
            left["before"], right["before"]
        )

        modified = evaluate(
            left["after"], right["after"]
        )

        removed_count = (
            left["before_count"]
            + right["before_count"]
            - left["after_count"]
            - right["after_count"]
        )

        row = {
            "company": company,
            "previous_period": previous,
            "current_period": current,
            "previous_sha256":
                left["original_sha256"],
            "current_sha256":
                right["original_sha256"],
            "previous_length":
                left["original_length"],
            "current_length":
                right["original_length"],
            "provider_terms_removed":
                removed_count,
            "baseline_jsd": baseline["jsd"],
            "removed_jsd": modified["jsd"],
            "jsd_change": round(
                modified["jsd"]
                - baseline["jsd"], 6
            ),
            "baseline_cosine":
                baseline["cosine"],
            "removed_cosine":
                modified["cosine"],
            "cosine_change": round(
                modified["cosine"]
                - baseline["cosine"], 6
            ),
            "status": (
                "EXPLORATORY_ONLY"
                if removed_count > 0
                else "NO_PROVIDER_TERMS_REMOVED"
            )
        }

        rows.append(row)

        print(
            company,
            previous, "→", current,
            "移除詞數:", removed_count,
            "JSD變化:", row["jsd_change"],
            "Cosine變化:", row["cosine_change"]
        )

    return rows


def main():
    documents = prepare_documents()
    rows = []

    for company, texts in documents.items():
        print("\n公司：", company)
        rows.extend(
            calculate_company(company, texts)
        )

    assert len(rows) == 14

    # 保存底層方法，方便之後查核
    methods = {}

    for name in (
        "calculate_jsd",
        "calculate_cosine_similarity"
    ):
        fn = globals()[name]
        methods[name] = inspect.getsource(fn)

    report = {
        "experiment":
            "Seven-quarter provider ablation",
        "generated_at":
            datetime.now(timezone.utc).isoformat(),
        "periods": PERIODS,
        "removed_terms": [
            "Refinitiv", "LSEG"
        ],
        "research_status": "EXPLORATORY_ONLY",
        "limitations": [
            "Fixed TF-IDF configuration "
            "has not yet been independently verified.",
            "No fraud classification.",
            "Provider-name removal does not "
            "eliminate all source-format effects.",
            "SHA-256 identifies extracted text, "
            "not the original PDF file."
        ],
        "methods": methods,
        "results": rows
    }

    OUTPUT.mkdir(
        parents=True, exist_ok=True
    )

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S_%f")

    json_path = OUTPUT / (
        f"cross_company_seven_{stamp}.json"
    )

    csv_path = OUTPUT / (
        f"cross_company_seven_{stamp}.csv"
    )

    json_path.write_text(
        json.dumps(
            report, ensure_ascii=False, indent=2
        ),
        encoding="utf-8"
    )

    with csv_path.open(
        "x",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0])
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n完成：", len(rows), "組比較")
    print("JSON：", json_path)
    print("CSV：", csv_path)


if __name__ == "__main__":
    main()
