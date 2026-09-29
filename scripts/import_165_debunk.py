"""將 data.gov.tw 38262 的 165 闢謠 CSV 正規化（非詐騙貼文原文）。
用法：python3 scripts/import_165_debunk.py 原始資料.csv data/taiwan_165_debunk.csv
"""
import re
import sys
from pathlib import Path

import pandas as pd

INVESTMENT_TERMS = re.compile(
    r"假投資|投資|股票|飆股|股市|投顧|虛擬貨幣|虛擬通貨|比特幣|期貨|外匯|基金|財經"
)


def first_col(df, candidates):
    normalized = {str(c).replace(" ", "").replace("\ufeff", ""): c for c in df.columns}
    for wanted in candidates:
        key = wanted.replace(" ", "")
        if key in normalized:
            return normalized[key]
    raise ValueError("CSV 找不到欄位 " + " / ".join(candidates) + "；實際：" + ", ".join(df.columns))


def parse_date(s):
    value = str(s or "").strip()
    m = re.match(r"^(\d{2,3})[/-](\d{1,2})[/-](\d{1,2})", value)
    if m and int(m.group(1)) < 1911:
        return f"{int(m.group(1)) + 1911:04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else str(parsed.date())


def convert(src, dst):
    frame = pd.read_csv(src, dtype=str, encoding="utf-8-sig").fillna("")
    title_col = first_col(frame, ["標題", "新聞標題"])
    time_col = first_col(frame, ["發佈時間", "發布時間", "發佈日期", "發布日期"])
    body_col = first_col(frame, ["發佈內容", "發布內容", "內容"])
    output = pd.DataFrame({
        "date": frame[time_col].map(parse_date),
        "text": (frame[title_col].str.strip() + "\n" + frame[body_col].str.strip()),
        "sector": "假投資",
        "source": "165_debunk",
        "ticker": "",
        "url": "https://data.gov.tw/dataset/38262",
        # 僅代表「官方闢謠脈絡」，不代表整篇是「詐騙文案」。
        "label": "official_debunk_context",
    })
    output = output.loc[
        output["date"].ne("") &
        output["text"].str.contains(INVESTMENT_TERMS, na=False)
    ].drop_duplicates(subset=["date","text"]).copy()
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(dst, index=False, encoding="utf-8-sig")
    print(f"已轉換 {len(output)} 篇相關 165 公開闢謠文本 → {dst}")
    print("提醒：這不是已驗證的詐騙貼文原文，也不能用來計算準確率。")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("用法：python3 scripts/import_165_debunk.py 165.csv data/taiwan_165_debunk.csv")
    convert(sys.argv[1], sys.argv[2])
