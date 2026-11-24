"""Read-only official TWSE/TPEx company directory for the standalone Cloud Run frontend.

The browser only receives the fields needed for ticker autocomplete.
This module never performs filings ingestion, model inference or private data access.
"""
from __future__ import annotations

import json
import re
import threading
import time
from urllib.request import Request, urlopen

from flask import Blueprint, jsonify

_DIRECTORY_URLS = {
    "listed": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "otc": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
}
_MARKET_LABEL = {"listed": "上市", "otc": "上櫃"}
_TTL_SECONDS = 6 * 60 * 60
_MAX_BYTES = 5_000_000
_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()


def _download(url: str) -> list[dict]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "FinTrust/1.0"})
    with urlopen(request, timeout=12) as response:
        body = response.read(_MAX_BYTES + 1)
    if len(body) > _MAX_BYTES:
        raise ValueError("Directory response exceeds size limit")
    result = json.loads(body.decode("utf-8-sig"))
    if not isinstance(result, list):
        raise ValueError("Directory response is not a list")
    return result


def _public_rows(market: str, rows: list[dict]) -> list[dict]:
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        ticker = str(row.get("公司代號") or row.get("SecuritiesCompanyCode") or "").strip()
        name = str(row.get("公司簡稱") or row.get("CompanyAbbreviation") or "").strip()
        if not re.fullmatch(r"\d{4,6}", ticker) or not name or len(name) > 100:
            continue
        result[ticker] = {
            "ticker": ticker,
            "name": name,
            "fullName": str(row.get("公司名稱") or row.get("CompanyName") or name).strip()[:140],
            "industry": str(row.get("產業別") or row.get("SecuritiesIndustryCode") or "").strip()[:40],
            "market": _MARKET_LABEL[market],
        }
    return list(result.values())


def _get_directory(market: str) -> tuple[list[dict], bool]:
    now = time.monotonic()
    with _lock:
        cached = _cache.get(market)
        if cached and now < cached[0]:
            return cached[1], False
    try:
        rows = _public_rows(market, _download(_DIRECTORY_URLS[market]))
        if len(rows) < 100:
            raise ValueError("Official directory has unexpectedly few companies")
        with _lock:
            _cache[market] = (time.monotonic() + _TTL_SECONDS, rows)
        return rows, False
    except (OSError, ValueError, json.JSONDecodeError):
        with _lock:
            cached = _cache.get(market)
        if cached:
            return cached[1], True
        raise


def create_company_directory_blueprint() -> Blueprint:
    bp = Blueprint("public_company_directory", __name__)

    @bp.get("/data/companies/<market>")
    def list_companies(market: str):
        if market not in _DIRECTORY_URLS:
            return jsonify({"error": "not found"}), 404
        try:
            companies, stale = _get_directory(market)
        except (OSError, ValueError, json.JSONDecodeError):
            return jsonify({"error": "official directory temporarily unavailable"}), 503
        resp = jsonify(companies)
        resp.headers["Cache-Control"] = "public, max-age=3600"
        if stale:
            resp.headers["Warning"] = '110 - "Stale official directory"'
        return resp

    return bp
