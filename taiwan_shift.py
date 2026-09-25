"""臺灣繁中金融／防詐文本跨期漂移。與英文 STRUX 模組隔離，不共用門檻。"""
from __future__ import annotations

import math
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pandas as pd
from flask import Blueprint, jsonify, request
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

taiwan_shift_bp = Blueprint("taiwan_shift", __name__)

# 中文以字元二／三元組為基礎；不依賴未校驗的英文停用字或英文切詞。
# 中英混用資料必須沿用同一版 tokenizer 重新計算歷史門檻。
def tokenize_zh(text: str) -> list[str]:
    text = str(text or "").lower()
    output = []
    for han in re.findall(r"[\u4e00-\u9fff]+", text):
        for n in (2, 3):
            output.extend(han[i:i+n] for i in range(max(0, len(han)-n+1)))
    output.extend(w for w in re.findall(r"[a-z]{2,}", text) if len(w) >= 3)
    return output


def average_distribution(texts: list[str]) -> dict[str, float]:
    """每篇文件先正規化，再對篇數取平均，避免長篇文章獨占權重。"""
    summed = Counter()
    used = 0
    for text in texts:
        counts = Counter(tokenize_zh(text))
        total = sum(counts.values())
        if total:
            used += 1
            summed.update({word: cnt/total for word, cnt in counts.items()})
    return {word: value/used for word, value in summed.items()} if used else {}


def js_divergence(p: dict[str, float], q: dict[str, float]) -> float:
    if not p or not q:
        raise ValueError("資料無可分析的文字，無法計算 JSD")
    midpoint = {k: (p.get(k, 0.0)+q.get(k, 0.0))/2 for k in p.keys() | q.keys()}
    kl_p = sum(v*math.log2(v/midpoint[k]) for k, v in p.items() if v)
    kl_q = sum(v*math.log2(v/midpoint[k]) for k, v in q.items() if v)
    return float((kl_p+kl_q)/2)


def compare_groups(texts_a: list[str], texts_b: list[str]) -> dict:
    p = average_distribution(texts_a)
    q = average_distribution(texts_b)
    jsd = js_divergence(p, q)
    # 每篇文件共享詞彙表與 IDF，再平均 TF-IDF 向量，避免長篇文章獨占。
    # 任何斷詞／IDF 定義變更，都必須重算歷史門檻。
    documents = [" ".join(tokenize_zh(t)) for t in (texts_a + texts_b)]
    tfidf = TfidfVectorizer(token_pattern=r"(?u)\b\w+\b").fit_transform(documents)
    mean_a = tfidf[:len(texts_a)].mean(axis=0)
    mean_b = tfidf[len(texts_a):].mean(axis=0)
    cosine = float(cosine_similarity(mean_a, mean_b)[0][0])
    changes = [(word, round(q.get(word,0)-p.get(word,0),6)) for word in p.keys() | q.keys()]
    return {
        "jsd": round(jsd, 6),
        "cosine_similarity": round(cosine, 6),
        "emerging_terms": [{"term":w,"delta":v} for w,v in sorted(changes,key=lambda x:x[1],reverse=True) if v>0][:10],
        "disappearing_terms": [{"term":w,"delta":v} for w,v in sorted(changes,key=lambda x:x[1]) if v<0][:10],
    }


@lru_cache(maxsize=2)
def _read_csv_cached(path: str, mtime: float) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig").fillna("")
    required = {"date", "text", "sector", "source"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError("CSV 缺少必要欄位：" + ", ".join(sorted(missing)))
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.loc[df["date"].notna() & df["text"].str.strip().ne("")].copy()
    df["month"] = df["date"].dt.to_period("M")
    return df


def load_dataset() -> tuple[pd.DataFrame, str]:
    path_str = os.environ.get("TAIWAN_SHIFT_DATASET", "").strip()
    if not path_str:
        raise FileNotFoundError("未設定 TAIWAN_SHIFT_DATASET；請先準備有來源的 CSV")
    path = Path(path_str).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError("找不到臺灣文本資料集：" + str(path))
    return _read_csv_cached(str(path), path.stat().st_mtime), path.name


def group_texts(df: pd.DataFrame, period: pd.Period) -> list[str]:
    return df.loc[df["month"] == period, "text"].astype(str).tolist()


def calibrate(df: pd.DataFrame, before: pd.Period, min_documents: int) -> dict:
    """只採目標區間開始前，同產業／同來源、連續月份的相鄰組合。"""
    historical = sorted(p for p in df["month"].unique() if p < before)
    observations = []
    for old, new in zip(historical, historical[1:]):
        if new != old + 1:
            continue
        a, b = group_texts(df, old), group_texts(df, new)
        if len(a) >= min_documents and len(b) >= min_documents:
            metrics = compare_groups(a, b)
            observations.append((metrics["jsd"], metrics["cosine_similarity"]))
    # 30 對只是初步可估門檻的工程下限；後續仍需穩健性／留出集驗證。
    if len(observations) < 30:
        return {
            "status": "insufficient_history",
            "historical_pairs": len(observations),
            "minimum_pairs": 30,
            "thresholds": None,
            "note": "歷史相鄰月份不足 30 對：只顯示量測值，不判定高低或詐騙。",
        }
    jsd_vals = pd.Series([v[0] for v in observations])
    cosine_vals = pd.Series([v[1] for v in observations])
    return {
        "status": "calibrated",
        "historical_pairs": len(observations),
        "minimum_pairs": 30,
        "thresholds": {
            "jsd_p90": round(float(jsd_vals.quantile(.90)), 6),
            "jsd_p95": round(float(jsd_vals.quantile(.95)), 6),
            "cosine_p10": round(float(cosine_vals.quantile(.10)), 6),
            "cosine_p05": round(float(cosine_vals.quantile(.05)), 6),
        },
        "note": "同來源／同產業歷史相鄰月份經驗百分位；不是通用詐騙判定標準。",
    }


def analyze_taiwan_shift(*, df: pd.DataFrame, sector: str, source: str,
                         period_1: str, period_2: str, min_documents: int = 5) -> dict:
    try:
        q1, q2 = pd.Period(period_1, freq="M"), pd.Period(period_2, freq="M")
    except (ValueError, TypeError) as exc:
        raise ValueError("period_1／period_2 請填 YYYY-MM 等月份格式") from exc
    if q2 != q1 + 1:
        raise ValueError("請選連續兩月，避免時間跨度使指標不可比")
    subset = df.loc[(df["sector"] == sector) & (df["source"] == source)].copy()
    a, b = group_texts(subset, q1), group_texts(subset, q2)
    if len(a) < min_documents or len(b) < min_documents:
        raise ValueError(f"每期至少 {min_documents} 篇；目前 {len(a)}／{len(b)} 篇，請補資料")
    values = compare_groups(a, b)
    calibration = calibrate(subset, q1, min_documents)
    classification = "未校準：不判定漂移等級"
    decision = None
    if calibration["thresholds"]:
        t = calibration["thresholds"]
        jsd_high = values["jsd"] >= t["jsd_p90"]
        cosine_low = values["cosine_similarity"] <= t["cosine_p10"]
        decision = {"jsd_high": jsd_high, "cosine_low": cosine_low,
                    "rule": "JSD >= historical P90 AND Cosine <= historical P10"}
        if jsd_high and cosine_low:
            classification = "顯著文字分布漂移（需人工查證原因）"
        elif jsd_high or cosine_low:
            classification = "單一指標異常（待觀察）"
        else:
            classification = "未達本資料集的雙指標漂移門檻"
    return {
        "sector": sector, "source": source,
        "period_1": str(q1), "period_2": str(q2),
        "sample_counts": {"period_1": len(a), "period_2": len(b)},
        "metrics": values, "calibration": calibration,
        "combined_rule": decision, "drift_result": classification,
        "warning": "JSD/Cosine 只衡量文字分布差異，不是文章真偽、犯罪認定或詐騙機率。",
        "method_version": "taiwan-zh-char23-equal-doc-weight-v1",
    }


@taiwan_shift_bp.post("/api/taiwan-shift/analyze")
def taiwan_shift_api():
    data = request.get_json(silent=True) or {}
    sector = str(data.get("sector", "")).strip()
    source = str(data.get("source", "")).strip()
    if not sector or not source:
        return jsonify({"success": False, "error": "必須指定 sector 及 source；不同語料來源不可混用"}), 400
    try:
        df, dataset_name = load_dataset()
        result = analyze_taiwan_shift(
            df=df, sector=sector, source=source,
            period_1=data.get("period_1"), period_2=data.get("period_2"),
        )
        result["dataset_file"] = dataset_name
        return jsonify({"success": True, "data": result})
    except (ValueError, FileNotFoundError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
