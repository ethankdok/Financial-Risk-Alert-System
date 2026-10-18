"""Bounded research-only FinMind 3-statement raw acquisition for a company cohort.

Use the current nonfinancial candidate CSV from finmind_universe.py. Original
historical availability and annual-period semantics are UNVERIFIED. Raw data
cannot be fed directly to Beneish/Dechow without audited item/period mapping.
No production DB writes or labels. Dry-run by default. Token via environment.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

DATASETS = ("TaiwanStockFinancialStatements", "TaiwanStockBalanceSheet",
            "TaiwanStockCashFlowsStatement")
URL = "https://api.finmindtrade.com/api/v4/data"
MAX_TICKERS_PER_RUN = 40
DEFAULT_PAUSE_SECONDS = 15.0


class QuotaOrAccessError(RuntimeError):
    pass


def tickers_from_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        if "ticker" not in set(reader.fieldnames or []):
            raise ValueError("Expected ticker column")
        universe = set()
        for row in reader:
            ticker = str(row["ticker"]).strip()
            if ticker == "1785":
                continue
            if not (ticker.isdecimal() and len(ticker) == 4):
                raise ValueError("Invalid listed-company ticker")
            if str(row.get("normal_label_status") or "").lower() == "reviewed_normal":
                raise ValueError("This downloader must never infer or consume normal labels")
            universe.add(ticker)
    return sorted(universe)


def fetch_dataset(dataset, ticker, start, end, *, token=None, timeout=60):
    query = urllib.parse.urlencode({
        "dataset": dataset, "data_id": ticker,
        "start_date": start, "end_date": end
    })
    headers = {"Accept": "application/json", "User-Agent": "Academic-Financial-Research"}
    if token:
        headers["Authorization"] = "Bearer " + token
    try:
        with urllib.request.urlopen(urllib.request.Request(URL + "?" + query, headers=headers), timeout=timeout) as response:
            if response.status != 200:
                raise QuotaOrAccessError("Non-success HTTP status")
            content = response.read(40_000_001)
            if len(content) > 40_000_000:
                raise ValueError("Response above 40MB limit")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 402, 403, 429):
            raise QuotaOrAccessError(f"FinMind access/quota HTTP {exc.code}") from None
        raise RuntimeError(f"FinMind HTTP {exc.code}") from None
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("FinMind response not JSON object")
    if payload.get("status") not in (None, 200, "200") or not isinstance(payload.get("data"), list):
        raise QuotaOrAccessError("FinMind status/data error; verify API access and quota")
    rows = payload["data"]
    for item in rows:
        if not isinstance(item, dict) or str(item.get("stock_id")) != ticker:
            raise ValueError("Wrong issuer returned")
        if not all(k in item for k in ("date", "stock_id", "type", "value")):
            raise ValueError("Missing FinMind finance row fields")
        if not (start <= str(item["date"]) <= end):
            raise ValueError("Out-of-range record")
    return rows


def run(source_csv, output, *, start="2013-01-01", end="2025-12-31",
        offset=0, max_tickers=8, execute=False, pause_seconds=DEFAULT_PAUSE_SECONDS,
        getter=fetch_dataset):
    if not (0 <= offset and 1 <= max_tickers <= MAX_TICKERS_PER_RUN):
        raise ValueError(f"offset must be >=0 and max_tickers 1..{MAX_TICKERS_PER_RUN}")
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("start_date exceeds end_date")
    if pause_seconds < 0:
        raise ValueError("pause_seconds must be nonnegative")
    universe = tickers_from_csv(source_csv)
    selected = universe[offset:offset + max_tickers]
    jobs = [(ticker, dataset) for ticker in selected for dataset in DATASETS]
    result = {
        "status": "dry_run_plan_only" if not execute else "raw_staging_completed_or_partial",
        "ticker_total": len(universe), "offset": offset,
        "tickers_selected": selected, "period": [start, end],
        "datasets": list(DATASETS), "jobs": len(jobs),
        "requests_sent": 0, "reused_cached": 0, "network_performed": False,
        "db_writes": 0, "normal_labels_created": 0,
        "historical_original_filing_verified": False,
        "annual_period_mapping_verified": False,
        "warning": "Raw quarterly provider data, not annual MOPS filings or paper-variable features; no model training."
    }
    if not execute:
        return result
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    token = os.getenv("FINMIND_API_TOKEN", "").strip() or None
    results, halted = [], False
    for ticker, dataset in jobs:
        path = folder / ticker / (dataset + ".json")
        log = {"ticker": ticker, "dataset": dataset}
        if path.is_file():
            try:
                saved = json.loads(path.read_text(encoding="utf-8"))
                if (saved.get("source") != URL or saved.get("ticker") != ticker or
                    saved.get("dataset") != dataset or saved.get("period") != [start, end] or
                    not isinstance(saved.get("records"), list)):
                    raise ValueError("existing_source_contract_mismatch")
                log.update(status="reused", records=len(saved["records"]),
                           sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                result["reused_cached"] += 1
            except (ValueError, OSError):
                log.update(status="blocked_existing_unverified_archive")
                halted = True
            results.append(log)
            print(f"[FinMind {len(results)}/{len(jobs)}] {ticker} {dataset}: "
                  f"{log['status']}", flush=True)
            if halted:
                break
            continue
        try:
            result["requests_sent"] += 1
            result["network_performed"] = getter is fetch_dataset
            rows = getter(dataset, ticker, start, end, token=token)
            data = {
                "source": URL, "dataset": dataset, "ticker": ticker,
                "period": [start, end], "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "period_semantics": "QUARTERLY_UNVERIFIED_ANNUAL_AGGREGATION",
                "original_filing_vintage": "UNKNOWN", "records": rows
            }
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            tmp.replace(path)
            log.update(status="downloaded", records=len(rows),
                       sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        except QuotaOrAccessError:
            log.update(status="halted_quota_or_access")
            halted = True
        except (OSError, ValueError, RuntimeError, urllib.error.URLError):
            log.update(status="failed_to_download_or_verify")
        results.append(log)
        print(f"[FinMind {len(results)}/{len(jobs)}] {ticker} {dataset}: "
              f"{log['status']} (rows={log.get('records', 0)})", flush=True)
        if halted:
            break
        if getter is fetch_dataset:
            time.sleep(pause_seconds)
    result["request_results"] = results
    result["outcome_counts"] = dict(Counter(x["status"] for x in results))
    result["halted"] = halted
    report_path = folder / "finmind_raw_acquisition_report.json"
    report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bounded raw FinMind historical 3-statement download; dry-run default")
    parser.add_argument("--candidate-csv", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--start-date", default="2013-01-01")
    parser.add_argument("--end-date", default="2025-12-31")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-tickers", type=int, default=8)
    parser.add_argument("--pause-seconds", type=float, default=DEFAULT_PAUSE_SECONDS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    report = run(args.candidate_csv, args.output, start=args.start_date,
                 end=args.end_date, offset=args.offset, max_tickers=args.max_tickers,
                 execute=args.execute, pause_seconds=args.pause_seconds)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
