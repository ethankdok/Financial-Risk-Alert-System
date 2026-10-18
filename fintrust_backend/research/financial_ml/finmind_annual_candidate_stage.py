"""Phase 5B: bounded local FinMind quarterly -> annual *candidate* line staging.

Rules are source-/family-specific candidates supported by only three TSMC
MOPS comparisons, NOT broadly approved literature inputs or historical PIT.
No API, model fitting, normal label, or production DB writes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .finmind_bulk_stage import DATASETS, URL
from .finmind_annual_crosscheck import PAIRS

POLICY_VERSION = "finmind_family_semantics_candidate_tsmc_2013_2015_v1"
FAMILY_DATASET = dict(zip(("income", "balance", "cashflow"), DATASETS))
FAMILY_METHOD = {"income": "FOUR_QUARTER_SUM_CANDIDATE",
                 "balance": "DEC31_INSTANT_CANDIDATE",
                 "cashflow": "Q4_CUMULATIVE_CANDIDATE"}
PERIODS = ((3, 31), (6, 30), (9, 30), (12, 31))
COLUMNS = ("ticker", "fiscal_year", "source_family", "source_type",
           "candidate_mops_metric", "candidate_annual_value", "source_quarters_found",
           "status", "method_candidate", "method_version", "source_sha256",
           "training_admitted", "publication_asof_verified", "label_status")
VALID_LABEL = "UNREVIEWED"


def decimal_value(v):
    if isinstance(v, bool) or v is None:
        raise ValueError("invalid_financial_decimal")
    try:
        val = Decimal(str(v))
    except (ValueError, InvalidOperation):
        raise ValueError("invalid_financial_decimal") from None
    if not val.is_finite():
        raise ValueError("nonfinite_financial_decimal")
    return val


def issuer_ids(candidate_csv):
    with Path(candidate_csv).open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        needed = {"ticker", "normal_label_status"}
        if not needed.issubset(reader.fieldnames or []):
            raise ValueError("candidate_csv_missing_required_columns")
        tickers = []
        for row in reader:
            ticker = str(row["ticker"]).strip()
            if ticker == "1785" or not ticker.isascii() or len(ticker) != 4 or not ticker.isdecimal():
                raise ValueError("reserved_or_invalid_company_ticker")
            if row["normal_label_status"] != VALID_LABEL:
                raise ValueError("unexpected_prelabelled_company")
            tickers.append(ticker)
    if len(set(tickers)) != len(tickers) or not tickers:
        raise ValueError("duplicate_or_empty_issuer_cohort")
    return tickers


def load_source(root, ticker, family):
    dataset = FAMILY_DATASET[family]
    path = Path(root) / ticker / (dataset + ".json")
    if not path.is_file():
        return {}, "", "archive_missing"
    raw = path.read_bytes()
    archive = json.loads(raw)
    if (archive.get("ticker") != ticker or archive.get("dataset") != dataset
            or archive.get("source") != URL or not isinstance(archive.get("records"), list)):
        raise ValueError("provider_archive_contract_invalid")
    if archive.get("period_semantics") not in (None, "QUARTERLY_UNVERIFIED_ANNUAL_AGGREGATION"):
        raise ValueError("provider_archive_semantics_conflict")
    results = defaultdict(set)
    for row in archive["records"]:
        if str(row.get("stock_id")) != ticker:
            raise ValueError("provider_issuer_mismatch")
        day = date.fromisoformat(str(row["date"]))
        if not row.get("type"):
            raise ValueError("provider_line_type_missing")
        key = (str(row["type"]), day.isoformat())
        results[key].add(decimal_value(row["value"]))
    if any(len(v) > 1 for v in results.values()):
        raise ValueError("provider_duplicate_period_value_conflict")
    if not archive["records"]:
        return {}, hashlib.sha256(raw).hexdigest(), "empty_provider_response"
    return {k: next(iter(v)) for k, v in results.items()}, hashlib.sha256(raw).hexdigest(), "raw_present"


def stage(candidate_csv, raw_root, output, *, start_year=2013, end_year=2025):
    if not (2013 <= start_year <= end_year <= 2025):
        raise ValueError("invalid_year_bounds")
    tickers = issuer_ids(candidate_csv)
    records = []
    counts = Counter()
    for ticker in tickers:
        sources = {name: load_source(raw_root, ticker, name) for name in FAMILY_DATASET}
        for year in range(start_year, end_year + 1):
            for family, provider_type, metric in PAIRS:
                observations, source_hash, source_status = sources[family]
                quarter = [observations.get((provider_type, f"{year}-{m:02d}-{d:02d}"))
                           for m, d in PERIODS]
                present = sum(v is not None for v in quarter)
                value = None
                if source_status != "raw_present":
                    status = source_status
                elif family == "income":
                    if present == 4:
                        value, status = sum(quarter, Decimal(0)), "candidate_annual_value"
                    else:
                        status = "missing_income_quarter"
                elif quarter[3] is not None:
                    value, status = quarter[3], "candidate_annual_value"
                else:
                    status = "missing_december_value"
                counts[status] += 1
                records.append({
                    "ticker": ticker, "fiscal_year": year,
                    "source_family": family, "source_type": provider_type,
                    "candidate_mops_metric": metric,
                    "candidate_annual_value": "" if value is None else format(value, "f"),
                    "source_quarters_found": present, "status": status,
                    "method_candidate": FAMILY_METHOD[family],
                    "method_version": POLICY_VERSION, "source_sha256": source_hash,
                    "training_admitted": "false",
                    "publication_asof_verified": "false",
                    "label_status": VALID_LABEL
                })
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "finmind_annual_candidate_lines.csv"
    with target.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    report = {
        "status": "ANNUAL_CANDIDATE_LINES_ONLY_NOT_APPROVED_FOR_ML",
        "method_version": POLICY_VERSION, "source_company_count": len(tickers),
        "fiscal_years": [start_year, end_year],
        "rows": len(records), "counts": dict(sorted(counts.items())),
        "candidate_semantics": FAMILY_METHOD,
        "calibration_evidence": "2330 MOPS FY2013-2015, limited 12-field comparisons; "
                                "2014 total liabilities discrepancy remains unresolved",
        "training_dataset_ready": False, "literature_15_features_built": False,
        "anomaly_labels_created": 0, "reserved_1785_excluded": True,
        "network_requests": 0, "production_database_writes": 0,
        "warning": "Candidate annual values are for numerical reconciliation only. "
                   "The source quarter semantics, units, and statement scope need "
                   "per-issuer verification before using them as model inputs. "
                   "A source not presenting a line is NOT financial zero."
    }
    (folder / "finmind_annual_candidate_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Offline annual candidate lines; no model or authoritative labels")
    p.add_argument("--candidate-csv", required=True)
    p.add_argument("--raw-root", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--start-year", type=int, default=2013)
    p.add_argument("--end-year", type=int, default=2025)
    options = p.parse_args(argv)
    print(json.dumps(stage(options.candidate_csv, options.raw_root, options.output,
                           start_year=options.start_year, end_year=options.end_year),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
