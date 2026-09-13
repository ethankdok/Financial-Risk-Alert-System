import math
import os
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from flask import Blueprint, jsonify, request

from sklearn.feature_extraction.text import (
    ENGLISH_STOP_WORDS,
    TfidfVectorizer,
)
from sklearn.metrics.pairwise import cosine_similarity


# ============================================================
# Flask Blueprint
# ============================================================

data_shift_bp = Blueprint(
    "data_shift",
    __name__,
)


# ============================================================
# 目前版本的校準門檻
#
# 來源：
# 使用 STRUX 真實 earnings-call transcripts，
# 經 Data Quality Filter 後建立的 empirical distribution。
#
# 注意：
# 這些不是「全世界通用 JSD 標準」，
# 而是目前本研究資料集校準出的 operational thresholds。
# ============================================================

JSD_P90 = 0.366397
JSD_P95 = 0.389590
JSD_P99 = 0.436144

COSINE_P05 = 0.618645
COSINE_P10 = 0.664451


# ============================================================
# Data Quality Rule
# ============================================================

MIN_TEXT_LENGTH = 5000
MIN_LENGTH_RATIO = 0.50


# ============================================================
# Stopwords
# ============================================================

STOPWORDS = set(ENGLISH_STOP_WORDS)

EXTRA_STOPWORDS = {
    "quarter",
    "year",
    "company",
    "conference",
    "call",
    "operator",
    "today",
    "thank",
    "thanks",
    "morning",
    "afternoon",
    "evening",
    "welcome",
    "please",
    "good",
    "first",
    "second",
    "third",
    "fourth",
}

STOPWORDS.update(EXTRA_STOPWORDS)


# ============================================================
# Tokenizer
#
# 目前英文 earnings call 可以直接用。
# 中文財報/法說會之後建議再改成 Jieba 或 CKIP。
# ============================================================

def tokenize(text):
    if not text:
        return []

    text = str(text)

    tokens = []

    english_words = re.findall(
        r"[A-Za-z][A-Za-z'-]+",
        text.lower(),
    )

    for word in english_words:
        if (
            len(word) > 2
            and word not in STOPWORDS
        ):
            tokens.append(word)

    chinese_words = re.findall(
        r"[\u4e00-\u9fff]{2,}",
        text,
    )

    tokens.extend(chinese_words)

    percentages = re.findall(
        r"\d+(?:\.\d+)?%",
        text,
    )

    tokens.extend(percentages)

    return tokens


# ============================================================
# Term Frequency Distribution
# ============================================================

def build_distribution(text):
    tokens = tokenize(text)

    counter = Counter(tokens)

    total = sum(counter.values())

    if total == 0:
        return {}, counter

    distribution = {
        token: count / total
        for token, count in counter.items()
    }

    return distribution, counter


# ============================================================
# KL Divergence
# ============================================================

def kl_divergence(p, m):
    value = 0.0

    for token, p_value in p.items():
        if p_value <= 0:
            continue

        m_value = m.get(token, 0.0)

        if m_value <= 0:
            continue

        value += (
            p_value
            * math.log2(
                p_value / m_value
            )
        )

    return value


# ============================================================
# Jensen-Shannon Divergence
#
# 使用 log2，因此理論範圍為 0 ~ 1。
# ============================================================

def calculate_jsd(text_1, text_2):
    p, _ = build_distribution(text_1)
    q, _ = build_distribution(text_2)

    vocabulary = set(p) | set(q)

    if not vocabulary:
        return 0.0

    p_full = {
        token: p.get(token, 0.0)
        for token in vocabulary
    }

    q_full = {
        token: q.get(token, 0.0)
        for token in vocabulary
    }

    m = {
        token: (
            p_full[token]
            + q_full[token]
        ) / 2
        for token in vocabulary
    }

    jsd = (
        0.5 * kl_divergence(
            p_full,
            m,
        )
        +
        0.5 * kl_divergence(
            q_full,
            m,
        )
    )

    return float(jsd)


# ============================================================
# TF-IDF Cosine Similarity
# ============================================================

def calculate_cosine_similarity(
    text_1,
    text_2,
):
    if not text_1 or not text_2:
        return 0.0

    try:
        vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            tokenizer=tokenize,
            token_pattern=None,
        )

        vectors = vectorizer.fit_transform(
            [
                text_1,
                text_2,
            ]
        )

        similarity = cosine_similarity(
            vectors[0],
            vectors[1],
        )[0][0]

        return float(similarity)

    except ValueError:
        return 0.0


# ============================================================
# Data Quality Check
# ============================================================

def check_data_quality(
    text_1,
    text_2,
):
    text_1 = text_1 or ""
    text_2 = text_2 or ""

    length_1 = len(text_1)
    length_2 = len(text_2)

    if max(length_1, length_2) == 0:
        length_ratio = 0.0
    else:
        length_ratio = (
            min(length_1, length_2)
            /
            max(length_1, length_2)
        )

    reasons = []

    if length_1 < MIN_TEXT_LENGTH:
        reasons.append(
            "第一期文字長度過短"
        )

    if length_2 < MIN_TEXT_LENGTH:
        reasons.append(
            "第二期文字長度過短"
        )

    if length_ratio < MIN_LENGTH_RATIO:
        reasons.append(
            "兩期文字長度差異過大"
        )

    passed = len(reasons) == 0

    return {
        "passed": passed,
        "text_length_1": length_1,
        "text_length_2": length_2,
        "length_ratio": round(
            length_ratio,
            4,
        ),
        "min_text_length": (
            MIN_TEXT_LENGTH
        ),
        "min_length_ratio": (
            MIN_LENGTH_RATIO
        ),
        "reasons": reasons,
    }


# ============================================================
# Emerging / Disappearing Terms
# ============================================================

def compare_terms(
    text_1,
    text_2,
    top_n=10,
):
    dist_1, count_1 = (
        build_distribution(text_1)
    )

    dist_2, count_2 = (
        build_distribution(text_2)
    )

    vocabulary = (
        set(dist_1)
        |
        set(dist_2)
    )

    changes = []

    for token in vocabulary:
        rate_1 = dist_1.get(
            token,
            0.0,
        )

        rate_2 = dist_2.get(
            token,
            0.0,
        )

        change = rate_2 - rate_1

        changes.append({
            "term": token,
            "period_1_rate": rate_1,
            "period_2_rate": rate_2,
            "change": change,
            "period_1_count": (
                count_1.get(
                    token,
                    0,
                )
            ),
            "period_2_count": (
                count_2.get(
                    token,
                    0,
                )
            ),
        })

    emerging = sorted(
        changes,
        key=lambda x: x["change"],
        reverse=True,
    )

    disappearing = sorted(
        changes,
        key=lambda x: x["change"],
    )

    emerging = [
        item
        for item in emerging
        if item["change"] > 0
    ][:top_n]

    disappearing = [
        item
        for item in disappearing
        if item["change"] < 0
    ][:top_n]

    return (
        emerging,
        disappearing,
    )


# ============================================================
# Drift Level
# ============================================================

def determine_drift_level(
    jsd,
    cosine,
):
    if jsd >= JSD_P99:
        level = "高度異常漂移"

    elif jsd >= JSD_P95:
        level = "明顯漂移"

    elif jsd >= JSD_P90:
        level = "值得注意"

    else:
        level = "一般變化"

    cosine_warning = None

    if cosine < COSINE_P05:
        cosine_warning = (
            "文字相似度明顯偏低"
        )

    elif cosine < COSINE_P10:
        cosine_warning = (
            "文字相似度偏低"
        )

    return (
        level,
        cosine_warning,
    )


# ============================================================
# Main Analysis Function
# ============================================================

def analyze_data_shift(
    text_1,
    text_2,
    ticker=None,
    source_type=None,
    period_1=None,
    period_2=None,
):
    text_1 = str(
        text_1 or ""
    )

    text_2 = str(
        text_2 or ""
    )

    quality = check_data_quality(
        text_1,
        text_2,
    )

    jsd = calculate_jsd(
        text_1,
        text_2,
    )

    cosine = (
        calculate_cosine_similarity(
            text_1,
            text_2,
        )
    )

    emerging_terms, disappearing_terms = (
        compare_terms(
            text_1,
            text_2,
            top_n=10,
        )
    )

    drift_level, cosine_warning = (
        determine_drift_level(
            jsd,
            cosine,
        )
    )

    warnings = []

    if not quality["passed"]:
        warnings.append(
            "資料品質未通過，本次漂移結果可能受到文字缺失或長度差異影響。"
        )

    if cosine_warning:
        warnings.append(
            cosine_warning
        )

    result = {
        "ticker": ticker,
        "source_type": source_type,
        "period_1": period_1,
        "period_2": period_2,

        "metrics": {
            "jsd": round(
                jsd,
                6,
            ),
            "cosine_similarity": round(
                cosine,
                6,
            ),
        },

        "drift": {
            "level": drift_level,

            "jsd_percentile_thresholds": {
                "p90": JSD_P90,
                "p95": JSD_P95,
                "p99": JSD_P99,
            },

            "cosine_thresholds": {
                "p05": COSINE_P05,
                "p10": COSINE_P10,
            },
        },

        "data_quality": quality,

        "emerging_terms": (
            emerging_terms
        ),

        "disappearing_terms": (
            disappearing_terms
        ),

        "warnings": warnings,

        "method": {
            "distribution_metric": (
                "Jensen-Shannon Divergence"
            ),
            "similarity_metric": (
                "TF-IDF Cosine Similarity"
            ),
            "jsd_log_base": 2,
            "threshold_type": (
                "Empirical historical percentile calibration"
            ),
        },
    }

    return result



# ============================================================
# STRUX Dataset Auto Loader
#
# 可用環境變數 DATA_SHIFT_PARQUET 指定 parquet 路徑。
# 若未指定，會依序搜尋常見位置。
# ============================================================

_STRUX_DF_CACHE = None
_STRUX_PATH_CACHE = None


def resolve_strux_path():
    candidates = []

    env_path = os.environ.get("DATA_SHIFT_PARQUET")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    here = Path(__file__).resolve().parent

    candidates.extend([
        here / "data" / "train-00000-of-00001.parquet",
        here.parent / "02_Data_Shift資料" / "train-00000-of-00001.parquet",
        Path.home()
        / "Downloads"
        / "畢業專題"
        / "02_Data_Shift資料"
        / "train-00000-of-00001.parquet",
    ])

    for path in candidates:
        if path.exists():
            return path

    raise FileNotFoundError(
        "找不到 STRUX parquet。請設定 DATA_SHIFT_PARQUET，"
        "或將 train-00000-of-00001.parquet 放到專案 data/ 資料夾。"
    )


def flatten_prepared_remarks(items):
    if items is None:
        return ""

    if hasattr(items, "tolist") and not isinstance(items, (str, bytes, dict)):
        try:
            items = items.tolist()
        except Exception:
            pass

    if isinstance(items, dict):
        items = [items]

    if not isinstance(items, (list, tuple)):
        return ""

    texts = []

    for item in items:
        if not isinstance(item, dict):
            continue

        speech = item.get("speech", [])

        if speech is None:
            continue

        if hasattr(speech, "tolist") and not isinstance(
            speech,
            (str, bytes, dict),
        ):
            try:
                speech = speech.tolist()
            except Exception:
                pass

        if isinstance(speech, (list, tuple)):
            for part in speech:
                if part is None:
                    continue

                part = str(part).strip()

                if part:
                    texts.append(part)

        elif isinstance(speech, str):
            speech = speech.strip()

            if speech:
                texts.append(speech)

    return " ".join(texts)


def load_strux_dataset():
    global _STRUX_DF_CACHE
    global _STRUX_PATH_CACHE

    path = resolve_strux_path()

    if (
        _STRUX_DF_CACHE is not None
        and _STRUX_PATH_CACHE == str(path)
    ):
        return _STRUX_DF_CACHE, path

    df = pd.read_parquet(path)

    required_columns = {
        "ticker",
        "date",
        "prepared_remarks",
    }

    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            "STRUX 資料缺少必要欄位："
            + ", ".join(sorted(missing))
        )

    df = df.copy()

    df["ticker"] = (
        df["ticker"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    df["date"] = pd.to_datetime(
        df["date"],
        errors="coerce",
    )

    df["prepared_text"] = (
        df["prepared_remarks"]
        .apply(flatten_prepared_remarks)
    )

    df = df[
        df["date"].notna()
        & df["prepared_text"].str.len().gt(0)
    ].copy()

    _STRUX_DF_CACHE = df
    _STRUX_PATH_CACHE = str(path)

    return df, path


def get_latest_two_strux_transcripts(ticker):
    ticker = str(ticker or "").upper().strip()

    if not ticker:
        raise ValueError("ticker 為必填")

    df, path = load_strux_dataset()

    company = (
        df[df["ticker"] == ticker]
        .sort_values("date")
        .reset_index(drop=True)
    )

    if len(company) < 2:
        raise ValueError(
            f"STRUX 中找不到 {ticker} 至少兩期可比較的法說會資料"
        )

    row_1 = company.iloc[-2]
    row_2 = company.iloc[-1]

    return {
        "ticker": ticker,
        "period_1": str(row_1["date"].date()),
        "period_2": str(row_2["date"].date()),
        "text_1": row_1["prepared_text"],
        "text_2": row_2["prepared_text"],
        "dataset": "STRUX Transcripts Dataset (train split)",
        "dataset_path": str(path),
        "available_periods": int(len(company)),
    }


# ============================================================
# Auto Data Shift API
#
# POST /api/data-shift/auto
# Body:
# {
#   "ticker": "AMT"
# }
#
# 後端會直接從 STRUX 抓取該公司最新兩期法說會。
# ============================================================

@data_shift_bp.route(
    "/api/data-shift/auto",
    methods=["POST"],
)
def data_shift_auto_api():
    payload = request.get_json(silent=True) or {}

    ticker = str(
        payload.get("ticker", "")
    ).upper().strip()

    if not ticker:
        return jsonify({
            "success": False,
            "error": "ticker 為必填欄位",
        }), 400

    try:
        source = get_latest_two_strux_transcripts(
            ticker
        )

        result = analyze_data_shift(
            text_1=source["text_1"],
            text_2=source["text_2"],
            ticker=source["ticker"],
            source_type="earnings_call",
            period_1=source["period_1"],
            period_2=source["period_2"],
        )

        result["dataset"] = source["dataset"]
        result["available_periods"] = source[
            "available_periods"
        ]

        return jsonify({
            "success": True,
            "data": result,
        })

    except FileNotFoundError as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 500

    except ValueError as exc:
        return jsonify({
            "success": False,
            "error": str(exc),
        }), 404

    except Exception as exc:
        return jsonify({
            "success": False,
            "error": f"自動跨期分析失敗：{exc}",
        }), 500



# ============================================================
# Flask API
#
# POST /api/data-shift
# ============================================================

@data_shift_bp.route(
    "/api/data-shift",
    methods=["POST"],
)
def data_shift_api():
    payload = (
        request.get_json(
            silent=True
        )
        or {}
    )

    text_1 = payload.get(
        "text_1",
        "",
    )

    text_2 = payload.get(
        "text_2",
        "",
    )

    if not text_1 or not text_2:
        return jsonify({
            "success": False,
            "error": (
                "text_1 與 text_2 皆為必填欄位"
            ),
        }), 400

    result = analyze_data_shift(
        text_1=text_1,
        text_2=text_2,

        ticker=payload.get(
            "ticker"
        ),

        source_type=payload.get(
            "source_type"
        ),

        period_1=payload.get(
            "period_1"
        ),

        period_2=payload.get(
            "period_2"
        ),
    )

    return jsonify({
        "success": True,
        "data": result,
    })
