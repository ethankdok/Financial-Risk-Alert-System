"""Run reproducible company-quarter earnings-transcript JSD / Cosine calibration.

Prerequisite:
 python3 scripts/build_tsmc_corpus.py --start 2017 --end 2025

Run:
 python3 scripts/calibrate_tsmc_shift.py --ticker 2330 --period1 2025Q3 --period2 2025Q4

Requires >=30 clean *historical* adjacent-quarter pairs BEFORE period1
for provisional P90/P95 and Cosine P10/P05; otherwise report raw metrics only.
Optional: --upload-firestore (requires GOOGLE_APPLICATION_CREDENTIALS or workload identity).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_shift import calculate_jsd, calculate_cosine_similarity  # noqa: E402

METHOD = "earnings-en-full-pairwise-tfidf-v1"
MIN_CHARS = 5000
MIN_RATIO = 0.50
MIN_HISTORY_PAIRS = 30
COLUMN_SET = {"ticker", "industry", "period", "document_type", "language",
              "text", "source_page", "source_pdf", "sha256"}


def quarter_number(value: str) -> int:
    match = re.fullmatch(r"(20\d{2})Q([1-4])", str(value))
    if not match:
        raise ValueError(f"Invalid quarter {value}; expected YYYYQ1..YYYYQ4")
    return int(match.group(1)) * 4 + int(match.group(2)) - 1


def quality(a: str, b: str) -> tuple[bool, dict]:
    la, lb = len(a.strip()), len(b.strip())
    ratio = min(la, lb) / max(la, lb) if max(la, lb) else 0
    return la >= MIN_CHARS and lb >= MIN_CHARS and ratio >= MIN_RATIO, {
        "length_a": la, "length_b": lb, "length_ratio": round(ratio, 4),
        "min_chars": MIN_CHARS, "min_length_ratio": MIN_RATIO,
    }


def pair(a: dict, b: dict) -> dict:
    qa, qb = a["period"], b["period"]
    if quarter_number(qb) != quarter_number(qa) + 1:
        raise ValueError("Both transcripts must be from adjacent fiscal quarters")
    ok, q = quality(a["text"], b["text"])
    result = {
        "period_1": qa, "period_2": qb,
        "source_doc_hashes": [a["sha256"], b["sha256"]],
        "data_quality": q, "passed": bool(ok),
    }
    if ok:
        result["metrics"] = {
            "jsd": round(calculate_jsd(a["text"], b["text"]), 6),
            "cosine_similarity": round(calculate_cosine_similarity(a["text"], b["text"]), 6),
        }
    return result


def load(path: Path, ticker: str) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"Missing corpus {path}; run build_tsmc_corpus.py first")
    df = pd.read_csv(path, dtype=str).fillna("")
    missing = COLUMN_SET - set(df.columns)
    if missing:
        raise ValueError(f"Dataset missing fields: {sorted(missing)}")
    df = df.loc[(df["ticker"] == ticker) &
                (df["document_type"] == "full_earnings_transcript")].copy()
    if df.empty:
        raise ValueError(f"No full earnings transcripts for ticker {ticker}")
    if df["period"].duplicated().any():
        raise ValueError("Multiple documents for one ticker and fiscal period. Resolve manually.")
    if df["sha256"].duplicated().any():
        raise ValueError("Identical PDF reused across quarters. Resolve manually.")
    values = df.to_dict("records")
    values.sort(key=lambda r: quarter_number(r["period"]))
    return values


def analyze(rows: list[dict], start: str, end: str, min_pairs: int = MIN_HISTORY_PAIRS) -> dict:
    p1, p2 = quarter_number(start), quarter_number(end)
    if p2 != p1 + 1:
        raise ValueError("Choose adjacent quarters; e.g. 2025Q3 and 2025Q4")
    by_period = {quarter_number(x["period"]): x for x in rows}
    if p1 not in by_period or p2 not in by_period:
        raise ValueError(f"Missing official full transcript for {start} or {end}")
    target = pair(by_period[p1], by_period[p2])
    if not target["passed"]:
        raise ValueError(f"Target failed quality checks: {target['data_quality']}")

    history = []
    for current in sorted(k for k in by_period if k < p1):
        nxt = current + 1
        if nxt < p1 and nxt in by_period:
            obs = pair(by_period[current], by_period[nxt])
            if obs["passed"]:
                history.append(obs)
    if len(history) < min_pairs:
        thresholds = None
        drift = "歷史資料不足：不可判定漂移等級"
        decision = None
    else:
        jsd = pd.Series([x["metrics"]["jsd"] for x in history])
        cosine = pd.Series([x["metrics"]["cosine_similarity"] for x in history])
        thresholds = {
            "jsd_p90": round(float(jsd.quantile(.90)), 6),
            "jsd_p95": round(float(jsd.quantile(.95)), 6),
            "cosine_p10": round(float(cosine.quantile(.10)), 6),
            "cosine_p05": round(float(cosine.quantile(.05)), 6),
        }
        high = target["metrics"]["jsd"] >= thresholds["jsd_p90"]
        low = target["metrics"]["cosine_similarity"] <= thresholds["cosine_p10"]
        decision = {"jsd_high": bool(high), "cosine_low": bool(low),
                    "rule": "JSD >= historical P90 AND Cosine <= historical P10"}
        drift = ("雙指標顯著文字漂移（需人工確認）" if high and low else
                 "單一指標異常（待觀察）" if high or low else
                 "未達雙指標歷史漂移門檻")

    first = by_period[p1]
    source_documents = [
        {k: row[k] for k in ("ticker", "industry", "period", "document_type",
                             "language", "source_page", "source_pdf", "sha256")}
        for row in (first, by_period[p2])
    ]
    return {
        "ticker": first["ticker"], "company": first.get("company", ""),
        "industry": first["industry"], "period_1": start, "period_2": end,
        "method": {"version": METHOD, "jsd_log_base": 2,
                   "tokenizer": "Original STRUX English tokenizer",
                   "tfidf": "TF-IDF fit independently on each paired English transcripts",
                   "comparison": "Same-company adjacent-quarter full earnings transcripts",
                   "min_history_pairs": min_pairs,
                   "calibration": "Earlier pairs only, target quarters excluded"},
        "target": target,
        "calibration": {
            "history_pair_count": len(history),
            "history_pairs": [{"period_1": x["period_1"], "period_2": x["period_2"],
                               "metrics": x["metrics"]} for x in history],
            "thresholds": thresholds,
        },
        "combined_rule": decision, "drift_result": drift,
        "source_documents": source_documents,
        "warnings": [
            "This is textual change, NOT a fraud/legality verdict.",
            "TSMC is an ordinary public-company corpus demo, not the company named in a scam case.",
            "Pilot thresholds are corpus and method-specific; validate on held-out companies/periods.",
            "Manually review PDF extraction quality, language and Q&A boundaries before treating as research evidence.",
        ],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def write_firestore(report: dict, project: str | None) -> None:
    """Metadata and numerical evidence only; raw copyrighted PDF/text remains local."""
    from google.cloud import firestore
    db = firestore.Client(project=project) if project else firestore.Client()
    method_id = hashlib.sha256(
        f"{report['industry']}:{report['ticker']}:{METHOD}:{report['period_1']}".encode()
    ).hexdigest()[:24]
    run_id = hashlib.sha256(
        f"{report['ticker']}:{report['period_1']}:{report['period_2']}:{METHOD}".encode()
    ).hexdigest()[:24]
    for doc in report["source_documents"]:
        db.collection("document_sources").document(doc["sha256"]).set(doc, merge=True)
    db.collection("shift_calibrations").document(method_id).set({
        "ticker": report["ticker"], "industry": report["industry"],
        "method": report["method"], "calibration": report["calibration"],
        "created_at": report["created_at"],
    })
    db.collection("shift_runs").document(run_id).set({
        "ticker": report["ticker"], "company": report["company"],
        "industry": report["industry"], "period_1": report["period_1"],
        "period_2": report["period_2"], "calibration_id": method_id,
        "target": report["target"], "combined_rule": report["combined_rule"],
        "drift_result": report["drift_result"], "warnings": report["warnings"],
        "source_documents": [x["sha256"] for x in report["source_documents"]],
        "method_version": METHOD, "created_at": report["created_at"],
    })
    print(f"Uploaded Firestore metadata: shift_runs/{run_id} calibration/{method_id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=Path, default=Path("data/tsmc_corpus/tsmc_quarterly_text.csv"))
    parser.add_argument("--ticker", default="2330")
    parser.add_argument("--period1", default="2025Q3")
    parser.add_argument("--period2", default="2025Q4")
    parser.add_argument("--output", type=Path, default=Path("data/tsmc_corpus/calibration_result.json"))
    parser.add_argument("--upload-firestore", action="store_true")
    parser.add_argument("--gcp-project", default=None)
    args = parser.parse_args()
    data = analyze(load(args.csv, args.ticker), args.period1, args.period2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": data["target"]["metrics"],
                      "history_pairs": data["calibration"]["history_pair_count"],
                      "thresholds": data["calibration"]["thresholds"],
                      "drift": data["drift_result"]}, ensure_ascii=False, indent=2))
    print(f"Saved {args.output}")
    if args.upload_firestore:
        if data["calibration"]["thresholds"] is None:
            raise SystemExit("Blocked Firestore upload: not enough history for calibration")
        write_firestore(data, args.gcp_project)
