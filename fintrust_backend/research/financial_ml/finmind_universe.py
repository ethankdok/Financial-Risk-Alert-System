"""FinMind TaiwanStockInfo -> current TWSE/TPEx nonfinancial issuer candidates.

This is a *current listing* candidate frame, not a historically complete listing
or evidence of normal financial behavior. No records are mislabeled as normal.
Fetch is explicit. Tokens stay in FINMIND_API_TOKEN (never logged).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ENDPOINT = "https://api.finmindtrade.com/api/v4/data"
MARKETS = frozenset({"twse", "tpex"})
FINANCIAL = re.compile(r"金融|保險|銀行|證券|票券|金控|financial|insurance|banking", re.IGNORECASE)
NON_EQUITY = re.compile(r"ETF|ETN|指數|受益證券|存託憑證|特別股|存託|TDR|基金", re.IGNORECASE)
CODE = re.compile(r"^[1-9][0-9]{3}$")
FIELDS = ("ticker", "company_name", "industry_category", "market",
          "source_snapshot_date", "historical_eligibility", "normal_label_status")


def current_nonfinancial_candidates(rows, *, include_conflicts=False):
    """Use the latest *dated* TaiwanStockInfo row per ticker, then filter.

    FinMind intentionally retains earlier board records (e.g. emerging -> TWSE).
    Never prefer response ordering. Multiple distinct records at the SAME newest
    date, or any undated row for an otherwise valid ticker, are quarantined
    instead of being silently chosen or crashing the entire universe.
    """
    histories = defaultdict(list)
    invalid_dates = defaultdict(list)
    counters = Counter()
    for record in rows:
        if not isinstance(record, dict):
            counters["invalid_row"] += 1
            continue
        ticker = str(record.get("stock_id") or "").strip()
        if ticker == "1785":
            counters["reserved_case"] += 1
            continue
        if not CODE.fullmatch(ticker):
            counters["not_four_digit_common_equity_candidate"] += 1
            continue
        raw_day = str(record.get("date") or "").strip()
        try:
            # FinMind's stock overview uses ISO dates; do not compare dates as
            # unverified strings or treat a missing date as an older observation.
            day = date.fromisoformat(raw_day)
        except ValueError:
            counters["invalid_or_missing_date_rows"] += 1
            invalid_dates[ticker].append({
                "ticker": ticker, "date": raw_day,
                "market": str(record.get("type") or "").strip().lower(),
                "company_name": str(record.get("stock_name") or "").strip(),
                "industry_category": str(record.get("industry_category") or "").strip(),
                "reason": "invalid_or_missing_date",
            })
            continue
        histories[ticker].append({
            "ticker": ticker, "date": day.isoformat(),
            "market": str(record.get("type") or "").strip().lower(),
            "company_name": str(record.get("stock_name") or "").strip(),
            "industry_category": str(record.get("industry_category") or "").strip(),
        })
    out = {}
    quarantined = []
    for ticker in sorted(set(histories) | set(invalid_dates)):
        entries = histories.get(ticker, [])
        if ticker in invalid_dates:
            # An undated row might be newer than the latest dated row.
            counters["tickers_quarantined_invalid_date"] += 1
            quarantined.extend(invalid_dates[ticker])
            quarantined.extend({**item, "reason": "ticker_contains_undated_row"} for item in entries)
            continue
        newest = max(item["date"] for item in entries)
        latest = [item for item in entries if item["date"] == newest]
        counters["superseded_historical_rows"] += len(entries) - len(latest)
        values = {(item["market"], item["company_name"], item["industry_category"]) for item in latest}
        if len(values) != 1:
            counters["tickers_quarantined_latest_date_conflict"] += 1
            quarantined.extend({**item, "reason": "same_date_conflicting_company_identity"} for item in latest)
            continue
        counters["identical_duplicate_latest_rows"] += len(latest) - 1
        selected = latest[0]  # All same-date candidate identity values agree.
        market, industry, name = (selected[x] for x in ("market", "industry_category", "company_name"))
        if market not in MARKETS:
            counters["not_twse_or_tpex"] += 1
        elif not industry or not name:
            counters["missing_company_or_industry"] += 1
        elif FINANCIAL.search(industry):
            counters["financial_excluded"] += 1
        elif NON_EQUITY.search(industry) or NON_EQUITY.search(name):
            counters["fund_or_non_equity_excluded"] += 1
        else:
            out[ticker] = {
                "ticker": ticker, "company_name": name,
                "industry_category": industry, "market": market,
                "source_snapshot_date": newest,
                "historical_eligibility": "UNVERIFIED",
                "normal_label_status": "UNREVIEWED",
            }
    ordered = [out[ticker] for ticker in sorted(out)]
    if include_conflicts:
        return ordered, dict(sorted(counters.items())), quarantined
    return ordered, dict(sorted(counters.items()))


def fetch_snapshot(*, token=None, timeout=35):
    url = ENDPOINT + "?" + urllib.parse.urlencode({"dataset": "TaiwanStockInfo"})
    headers = {"Accept": "application/json", "User-Agent": "Academic Financial-ML Dataset Research"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError("FinMind non-200 HTTP response")
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("status") not in (None, 200, "200") or not isinstance(payload.get("data"), list):
        raise ValueError("FinMind TaiwanStockInfo response not valid or quota limited")
    return payload


def build(source, output):
    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise ValueError("Expected archived FinMind TaiwanStockInfo JSON data list")
    if payload.get("status") not in (None, 200, "200"):
        raise ValueError("FinMind source status invalid")
    rows, rejections, quarantined = current_nonfinancial_candidates(payload["data"], include_conflicts=True)
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "taiwan_nonfinancial_current_candidates.csv").open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    # Keep an inspectable quarantine report; never leak authentication tokens.
    quarantine_path = folder / "taiwan_stock_info_quarantined.csv"
    with quarantine_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=(
            "ticker", "date", "market", "company_name", "industry_category", "reason"
        ))
        writer.writeheader()
        writer.writerows(sorted(quarantined, key=lambda x: (x["ticker"], x["date"], x["reason"])))
    report = {
        "status": "CURRENT_UNIVERSE_CANDIDATES_NOT_HISTORICAL_TRAINING_ELIGIBILITY",
        "source": "FinMind TaiwanStockInfo",
        "source_sha256": hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        "source_snapshot": str(source), "source_company_rows": len(payload["data"]),
        "nonfinancial_candidate_tickers": len(rows), "markets": ["twse", "tpex"],
        "quarantined_tickers": len({record["ticker"] for record in quarantined}),
        "quarantined_rows": len(quarantined),
        "quarantine_file": str(quarantine_path),
        "quarantined_ticker_examples": sorted({record["ticker"] for record in quarantined})[:20],
        "rejections": rejections, "reserved_1785_excluded": True,
        "historical_listing_and_industry_verified": False,
        "normal_labels_created": 0,
        "warning": "Current stocks exclude some historical/delisted issuers; latest-date selection does not verify historical membership. Any unresolved latest-date or undated conflicts are quarantined and not in the candidate CSV."
    }
    (folder / "taiwan_nonfinancial_universe_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Current Taiwan listed nonfinancial candidate universe; no labels")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source-json", help="Already archived official FinMind TaiwanStockInfo response")
    mode.add_argument("--fetch", action="store_true", help="Explicitly fetch one current stock-info snapshot")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    source = args.source_json
    if args.fetch:
        folder = Path(args.output)
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / "TaiwanStockInfo_snapshot.json"
        payload = fetch_snapshot(token=os.environ.get("FINMIND_API_TOKEN", "").strip() or None)
        payload["research_retrieved_at"] = datetime.now(timezone.utc).isoformat()
        temp = source.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp.replace(source)
    print(json.dumps(build(source, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
