"""Audit provisional company-year financial panels and temporal window coverage.

No network, no model fitting. Candidate FinMind annual lines are NOT original
Beneish/Dechow features or verified training inputs; missing is never zero.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

METRICS = (
    "revenue", "cost_of_goods_sold", "gross_profit", "operating_income", "net_income",
    "total_assets", "current_assets", "current_liabilities", "total_liabilities",
    "inventory", "cash_and_cash_equivalents", "operating_cash_flow",
)
FIELDNAMES = (
    "ticker", "fiscal_year", "source_family", "candidate_mops_metric", "status",
    "candidate_annual_value", "source_sha256", "training_admitted",
    "publication_asof_verified", "label_status", "source_quarters_found",
)
STATUSES = {"candidate_annual_value", "empty_provider_response",
            "missing_december_value", "missing_income_quarter", "archive_missing"}


def write_csv(path, records, columns):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)


def prepare(dataset, output, *, window_lengths=(3, 5)):
    source = Path(dataset)
    if not window_lengths or any(not 2 <= w <= 15 for w in window_lengths):
        raise ValueError("unsupported_window_lengths")
    with source.open(encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        if not set(FIELDNAMES).issubset(reader.fieldnames or []):
            raise ValueError("incompatible_annual_candidate_schema")
        rows = list(reader)
    if not rows:
        raise ValueError("empty_annual_candidates")
    records = {}
    identities = defaultdict(set)
    hashes = defaultdict(set)
    status_counts = Counter()
    for row in rows:
        ticker = row["ticker"].strip()
        if ticker == "1785" or not re.fullmatch(r"[1-9][0-9]{3}", ticker):
            raise ValueError("invalid_or_reserved_ticker")
        year = int(row["fiscal_year"])
        if not 2013 <= year <= 2035:
            raise ValueError("invalid_fiscal_year")
        metric = row["candidate_mops_metric"].strip()
        if metric not in METRICS:
            raise ValueError("unknown_candidate_metric:" + metric)
        key = (ticker, year, metric)
        if key in records:
            raise ValueError("duplicate_ticker_year_metric")
        if (row["training_admitted"].strip().lower() != "false" or
                row["publication_asof_verified"].strip().lower() != "false"):
            raise ValueError("unauthorized_model_admission_or_point_in_time_claim")
        if row["label_status"] != "UNREVIEWED":
            raise ValueError("unapproved_outcome_label")
        status = row["status"]
        if status not in STATUSES:
            raise ValueError("unknown_candidate_status")
        amount = row["candidate_annual_value"].strip()
        if status == "candidate_annual_value":
            try:
                value = float(amount)
            except ValueError:
                raise ValueError("invalid_candidate_number") from None
            if not math.isfinite(value):
                raise ValueError("nonfinite_candidate_number")
        elif amount:
            raise ValueError("missing_status_contains_fabricated_value")
        sha = row["source_sha256"].strip()
        if sha and not re.fullmatch(r"[a-fA-F0-9]{64}", sha):
            raise ValueError("invalid_source_sha256")
        if status == "candidate_annual_value" and not sha:
            raise ValueError("candidate_value_without_source_hash")
        family = row["source_family"]
        if family not in ("income", "balance", "cashflow"):
            raise ValueError("unexpected_statement_family")
        hashes[(ticker, family)].add(sha)
        identities[(ticker, year)].add(metric)
        records[key] = (amount, status)
        status_counts[status] += 1
    if any(len(values) != 1 for values in hashes.values()):
        raise ValueError("inconsistent_source_hash_for_statement")
    if any(items != set(METRICS) for items in identities.values()):
        raise ValueError("incomplete_company_year_metric_grain")
    panel = defaultdict(dict)
    panel_rows = []
    for ticker, year in sorted(identities):
        values = {metric: records[(ticker, year, metric)][0] for metric in METRICS}
        observed = sum(bool(value) for value in values.values())
        panel[ticker][year] = observed
        panel_rows.append({
            "ticker": ticker, "fiscal_year": year, "candidate_observed": observed,
            "candidate_total": len(METRICS), "complete_12_candidate_metrics": observed == len(METRICS),
            "training_admitted": "false", "original_asof_verified": "false", **values
        })
    window_rows = []
    window_stats = {}
    for span in sorted(set(window_lengths)):
        all_windows = 0
        complete_windows = 0
        available_issuers = set()
        for ticker, year_counts in sorted(panel.items()):
            for end in range(min(year_counts)+span-1, max(year_counts)+1):
                start = end-span+1
                count = sum(year_counts.get(y, 0) for y in range(start, end+1))
                total = span*len(METRICS)
                complete = (count == total and all(y in year_counts for y in range(start, end+1)))
                window_rows.append({
                    "ticker": ticker, "window_years": span, "start_year": start,
                    "end_year": end, "candidate_observed_cells": count,
                    "candidate_required_cells": total,
                    "candidate_complete_window": "true" if complete else "false",
                    "missing_cells": total-count, "training_admitted": "false"
                })
                all_windows += 1
                if complete:
                    complete_windows += 1
                    available_issuers.add(ticker)
        window_stats[str(span)] = {
            "all_windows": all_windows,
            "candidate_complete_windows": complete_windows,
            "distinct_companies_with_complete_windows": len(available_issuers)
        }
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    write_csv(folder/"company_year_candidate_panel.csv", panel_rows, [
        "ticker", "fiscal_year", "candidate_observed", "candidate_total",
        "complete_12_candidate_metrics", "training_admitted", "original_asof_verified", *METRICS])
    write_csv(folder/"candidate_sequence_window_index.csv", window_rows, [
        "ticker", "window_years", "start_year", "end_year",
        "candidate_observed_cells", "candidate_required_cells",
        "candidate_complete_window", "missing_cells", "training_admitted"])
    report = {
        "status": "PROVISIONAL_12_METRIC_PANEL_NOT_MODEL_TRAINING_READY",
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_company_years": len(identities), "source_companies": len(panel),
        "candidate_metric_cells": len(rows),
        "candidate_available_cells": status_counts.get("candidate_annual_value", 0),
        "complete_12_metric_company_years": sum(
            bool(row["complete_12_candidate_metrics"]) for row in panel_rows),
        "source_status_counts": dict(sorted(status_counts.items())),
        "per_company": {ticker: {
            "years": len(years),
            "complete_12_metric_years": sum(n == len(METRICS) for n in years.values()),
            "candidate_observed_cells": sum(years.values())
        } for ticker, years in sorted(panel.items())},
        "window_stats": window_stats,
        "literal_model_features": "12 provisional annual amounts, NOT Beneish 8 + Dechow 7",
        "independent_company_year_samples": "sliding windows overlap within issuers",
        "financial_model_admitted": False, "official_filing_and_historical_asof_verified": False,
        "labels_created": 0, "reserved_1785_excluded": True,
        "network_requests": 0, "production_db_writes": 0,
        "warning": ("Input measures are unapproved candidate values; window "
                    "completeness does not prove training readiness. "
                    "No 15-variable literature features or models are produced.")
    }
    (folder/"candidate_panel_readiness.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline annual panel and sequence-window readiness")
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--window-years", type=int, action="append")
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.dataset, args.output,
          window_lengths=args.window_years or (3, 5)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
