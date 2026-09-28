import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from scripts.build_tsmc_history import existing_transcript
from scripts.build_mediatek_history import load_documents
from scripts.test_provider_impact import (
    basic_clean,
    remove_provider,
    evaluate,
)

OUTPUT = Path("data/research-results")
PERIODS = ("2025Q3", "2025Q4")


def digest(text):
    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def extract_text(value):
    """只接受能明確確認為原文的資料。"""
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        for key in ("text", "raw_text", "content"):
            text = value.get(key)
            if isinstance(text, str):
                return text

    raise ValueError(
        "無法確定原始文字欄位，停止實驗"
    )


def load_company_documents():
    result = {}

    # 台積電：沿用既有官方逐字稿選取邏輯
    tsmc = {}
    for period in PERIODS:
        tsmc[period] = extract_text(
            existing_transcript(period)
        )

    result["TSMC"] = tsmc

    # 聯發科：沿用既有文件載入邏輯
    mediatek_data = load_documents()

    if not isinstance(mediatek_data, dict):
        raise ValueError(
            "聯發科資料不是預期的季度字典"
        )

    mediatek = {}
    for period in PERIODS:
        if period not in mediatek_data:
            raise ValueError(
                f"聯發科缺少 {period} 原始資料"
            )

        mediatek[period] = extract_text(
            mediatek_data[period]
        )

    result["MediaTek"] = mediatek

    # 資料完整性驗證
    for company, documents in result.items():
        for period, text in documents.items():
            if len(text.strip()) < 5000:
                raise ValueError(
                    f"{company} {period} 原文過短"
                )

    return result


def count_provider_words(text):
    return {
        word: len(
            re.findall(
                rf"\b{word}\b",
                text,
                flags=re.IGNORECASE
            )
        )
        for word in ("refinitiv", "lseg")
    }


def experiment(company, documents):
    before_texts = {}
    after_texts = {}
    source_info = {}

    for period in PERIODS:
        original = documents[period]
        cleaned = basic_clean(original)
        removed = remove_provider(cleaned)

        if not isinstance(cleaned, str):
            raise TypeError("文字清理結果不是字串")

        if not isinstance(removed, str):
            raise TypeError("名稱移除結果不是字串")

        before_texts[period] = cleaned
        after_texts[period] = removed

        source_info[period] = {
            "original_text_sha256": digest(original),
            "original_length": len(original),
            "cleaned_length": len(cleaned),
            "removed_length": len(removed),
            "original_provider_counts":
                count_provider_words(original),
            "cleaned_provider_counts":
                count_provider_words(cleaned),
            "remaining_provider_counts":
                count_provider_words(removed),
        }

    q3_before = before_texts["2025Q3"]
    q4_before = before_texts["2025Q4"]

    q3_after = after_texts["2025Q3"]
    q4_after = after_texts["2025Q4"]

    baseline = evaluate(q3_before, q4_before)
    modified = evaluate(q3_after, q4_after)

    if not all(
        key in result
        for result in (baseline, modified)
        for key in ("jsd", "cosine")
    ):
        raise ValueError("計算結果缺少必要指標")

    changed = any(
        before_texts[p] != after_texts[p]
        for p in PERIODS
    )

    return {
        "company": company,
        "previous_period": PERIODS[0],
        "current_period": PERIODS[1],
        "method": "existing_research_functions",
        "removed_terms": ["Refinitiv", "LSEG"],
        "text_changed": changed,
        "baseline": baseline,
        "provider_removed": modified,
        "jsd_change": round(
            modified["jsd"] - baseline["jsd"], 6
        ),
        "cosine_change": round(
            modified["cosine"] - baseline["cosine"], 6
        ),
        "documents": source_info,
        "status": (
            "EXPLORATORY_ONLY"
            if changed
            else "NO_PROVIDER_TERMS_REMOVED"
        ),
    }


def main():
    print("=== 跨公司實驗開始 ===")

    documents = load_company_documents()

    results = [
        experiment(company, texts)
        for company, texts in documents.items()
    ]

    # 全部成功後才輸出，避免不完整結果
    report = {
        "experiment":
            "Cross-company provider name ablation",
        "generated_at":
            datetime.now(timezone.utc).isoformat(),
        "periods": list(PERIODS),
        "removed_terms": ["Refinitiv", "LSEG"],
        "limitations": [
            "Exploratory study only.",
            "No fraud classification is performed.",
            "Provider-name removal is not equivalent "
            "to removing all document-source effects.",
            "Existing evaluation functions are reused; "
            "fixed TF-IDF vocabulary is not independently "
            "verified by this experiment.",
            "Original PDF source identifiers require "
            "separate provenance verification."
        ],
        "results": results,
    }

    rows = []

    for result in results:
        rows.append({
            "company": result["company"],
            "previous_period": result["previous_period"],
            "current_period": result["current_period"],
            "baseline_jsd":
                result["baseline"]["jsd"],
            "baseline_cosine":
                result["baseline"]["cosine"],
            "removed_jsd":
                result["provider_removed"]["jsd"],
            "removed_cosine":
                result["provider_removed"]["cosine"],
            "jsd_change": result["jsd_change"],
            "cosine_change": result["cosine_change"],
            "text_changed": result["text_changed"],
            "status": result["status"],
        })

    OUTPUT.mkdir(parents=True, exist_ok=True)

    json_path = (
        OUTPUT / "cross_company_provider_experiment.json"
    )
    csv_path = (
        OUTPUT / "cross_company_provider_experiment.csv"
    )

    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    with csv_path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=list(rows[0])
        )
        writer.writeheader()
        writer.writerows(rows)

    print("\n=== 實驗結果 ===")

    for row in rows:
        print(json.dumps(
            row, ensure_ascii=False, indent=2
        ))

    print("\nJSON：", json_path)
    print("CSV：", csv_path)
    print("實驗完成")


if __name__ == "__main__":
    main()
