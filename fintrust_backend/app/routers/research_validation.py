"""Read-only API for precomputed, exploratory transcript experiments.

This route does not recompute metrics, modify existing analysis results, or
persist to Firestore/SQLite. It checks provenance before exposing results.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(
    prefix="/api/v1/financial/research-validation",
    tags=["research-validation"],
)

# fintrust_backend/app/routers/research_validation.py -> fintrust_backend
DEFAULT_RESULTS_DIR = Path(__file__).resolve().parents[2] / "data" / "research-results"
COMPANIES = {
    "2330": ("TSMC", "tsmc_history.json", "tsmc_cleaned_tfidf.json"),
    "2454": ("MediaTek", "mediatek_history.json", "mediatek_tfidf_validation.json"),
}


def _results_dir() -> Path:
    return Path(os.environ.get("RESEARCH_RESULTS_DIR", str(DEFAULT_RESULTS_DIR)))


def _read(name: str) -> dict[str, Any]:
    path = _results_dir() / name
    if not path.is_file():
        raise HTTPException(503, detail=f"Missing research artifact: {name}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(503, detail=f"Unreadable research artifact: {name}") from exc
    if not isinstance(data, dict):
        raise HTTPException(503, detail=f"Invalid research artifact: {name}")
    return data


def _row_periods(row: dict[str, Any]) -> tuple[str, str]:
    return (row.get("before") or row.get("previous_period") or "",
            row.get("after") or row.get("current_period") or "")


def _document_hashes(history: dict[str, Any], ticker: str) -> dict[str, str]:
    documents = history.get("documents")
    result: dict[str, str] = {}
    if not isinstance(documents, list):
        raise ValueError("History must contain its document provenance list")
    for doc in documents:
        if not isinstance(doc, dict):
            raise ValueError("Malformed document record")
        period = doc.get("period")
        sha = doc.get("sha256")
        if not isinstance(period, str) or not isinstance(sha, str) or len(sha) != 64:
            raise ValueError("Missing period or SHA-256 in history")
        if period in result and result[period] != sha:
            raise ValueError("Conflicting hashes for a period")
        result[period] = sha
    return result


def _metrics(row: dict[str, Any]) -> dict[str, float]:
    fields = ("raw_pairwise", "clean_pairwise", "raw_fixed", "clean_fixed")
    values: dict[str, float] = {}
    for field in fields:
        value = row.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"Invalid {field}")
        if not 0 <= value <= 1:
            raise ValueError(f"Out-of-range {field}")
        values[field] = float(value)
    return values


def _load_company(ticker: str) -> dict[str, Any]:
    if ticker not in COMPANIES:
        raise HTTPException(404, detail="No precomputed research data for this ticker")
    company, history_name, fixed_name = COMPANIES[ticker]
    history = _read(history_name)
    fixed = _read(fixed_name)
    try:
        baseline = history["comparisons"]
        rows = fixed["comparisons"]
        hashes = _document_hashes(history, ticker)
        fixed_hashes = fixed["documents"]
        if not isinstance(baseline, list) or not isinstance(rows, list):
            raise ValueError("Comparisons must be lists")
        if len(baseline) != 7 or len(rows) != 7 or len(hashes) != 8:
            raise ValueError("Expected eight documents and seven comparisons")
        if not isinstance(fixed_hashes, dict) or hashes != fixed_hashes:
            raise ValueError("History and fixed-TFIDF document hashes disagree")
        expected_periods = [f"{year}Q{q}" for year in (2024, 2025) for q in range(1, 5)]
        if list(hashes) != expected_periods:
            raise ValueError("Unexpected period ordering")
        normalized = []
        for index, (original, fixed_row) in enumerate(zip(baseline, rows)):
            pair = (expected_periods[index], expected_periods[index + 1])
            if _row_periods(original) != pair or _row_periods(fixed_row) != pair:
                raise ValueError("History and TF-IDF period alignment differs")
            for value_name in ("jsd", "cosine"):
                value = original.get(value_name)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f"Invalid historical {value_name}")
            metrics = _metrics(fixed_row)
            if abs(float(original["cosine"]) - metrics["raw_pairwise"]) > 0.0001:
                raise ValueError("Historical cosine and raw pairwise cosine disagree")
            normalized.append({
                "previous_period": pair[0],
                "current_period": pair[1],
                "dataset": "calibration" if index < 5 else "holdout",
                "historical_jsd": float(original["jsd"]),
                "historical_cosine": float(original["cosine"]),
                **metrics,
                "raw_fixed_to_clean_fixed_change": round(metrics["clean_fixed"] - metrics["raw_fixed"], 6),
            })
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail=f"Research artifacts failed validation: {exc}") from exc
    return {
        "ticker": ticker,
        "company": company,
        "method_version": "read-only-precomputed-research-v1",
        "status": "EXPLORATORY_ONLY",
        "documents": hashes,
        "comparisons": normalized,
        "calibration_size": 5,
        "holdout_size": 2,
        "thresholds": history.get("thresholds"),
        "source_files": [history_name, fixed_name],
        "limitations": [
            "Precomputed results, not live document analysis.",
            "Each company's fixed TF-IDF model was fitted separately.",
            "Document publication dates and complete PDF content still require review.",
            "Text drift is not fraud probability or evidence of wrongdoing.",
            "Exploratory thresholds must not be applied to production risk scoring.",
        ],
    }


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "read_only": True, "supported_tickers": sorted(COMPANIES)}


@router.get("/companies/{ticker}/history")
def company_history(ticker: str) -> dict[str, Any]:
    return _load_company(ticker)


@router.get("/comparison")
def comparison() -> dict[str, Any]:
    return {
        "status": "EXPLORATORY_ONLY",
        "companies": [_load_company(ticker) for ticker in COMPANIES],
        "note": "Method consistency comparison; company scores are not a risk ranking.",
    }
