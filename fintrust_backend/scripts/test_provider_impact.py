
from pathlib import Path
import sys
import re
import json

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(ROOT))

from data_shift import calculate_jsd, calculate_cosine_similarity

DATA_DIR = BACKEND / "data/official-ir-pdfs/2330"
OUTPUT_DIR = BACKEND / "data/research-results"

PERIODS = ["2025Q3", "2025Q4"]


def load_text(period):
    year = period[:4]
    quarter = period[-1]
    matches = {}

    for path in DATA_DIR.glob("acquisition-*.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        source = manifest.get("source_page", "").lower()

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
            if file.exists():
                matches[doc["sha256"]] = file.read_text(
                    encoding="utf-8"
                )

    if len(matches) != 1:
        raise RuntimeError(
            f"{period}: 找到 {len(matches)} 個文件版本，"
            "請先人工確認。"
        )

    return next(iter(matches.values()))


def basic_clean(text):
    text = re.sub(
        r"(?m)^\[page \d+\]\s*$",
        " ",
        text
    )
    return re.sub(r"\s+", " ", text).strip()


def remove_provider(text):
    # 只移除已確認的供應商品牌詞
    # 不移除財務、技術詞彙或一般發言者標籤
    pattern = (
        r"(?i)(?<![A-Za-z])"
        r"(?:refinitiv|lseg)(?:['’]s?)?"
        r"(?![A-Za-z])"
    )

    return re.sub(r"\s+", " ", re.sub(pattern, " ", text)).strip()


def evaluate(text1, text2):
    return {
        "jsd": round(calculate_jsd(text1, text2), 6),
        "cosine": round(
            calculate_cosine_similarity(text1, text2),
            6
        ),
    }


def main():
    q3 = basic_clean(load_text("2025Q3"))
    q4 = basic_clean(load_text("2025Q4"))

    q3_clean = remove_provider(q3)
    q4_clean = remove_provider(q4)

    baseline = evaluate(q3, q4)
    filtered = evaluate(q3_clean, q4_clean)

    results = {
        "experiment": "Provider name ablation",
        "removed_terms": ["Refinitiv", "LSEG"],
        "baseline": baseline,
        "provider_removed": filtered,
        "cosine_change": round(
            filtered["cosine"] - baseline["cosine"], 6
        ),
        "jsd_change": round(
            filtered["jsd"] - baseline["jsd"], 6
        ),
        "note": (
            "Brand-token removal only. "
            "This is not a fraud-detection result."
        ),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "tsmc_provider_impact.json"

    output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print("\n=== 原始基礎清理 ===")
    print(baseline)

    print("\n=== 移除供應商品牌詞 ===")
    print(filtered)

    print("\n=== 指標變化 ===")
    print("Cosine:", results["cosine_change"])
    print("JSD:", results["jsd_change"])
    print("\n結果檔案:", output)


if __name__ == "__main__":
    main()
