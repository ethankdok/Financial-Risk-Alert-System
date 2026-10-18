"""Read-only FinMind vs archived MOPS annual-value reconciliation.

This is a candidate *measurement study*, not permission to train a model.
Q4 flow vs four-quarter sum are separately compared; balance sheets use Q4
instant only. A match does not verify original filing, release time, or
FinMind-to-COMPUSTAT literature mapping.
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

DATASETS = {
    "income": "TaiwanStockFinancialStatements",
    "balance": "TaiwanStockBalanceSheet",
    "cashflow": "TaiwanStockCashFlowsStatement",
}
# Conservative *candidate* pairs; source values must still match.
PAIRS = (
    ("income", "Revenue", "revenue"),
    ("income", "CostOfGoodsSold", "cost_of_goods_sold"),
    ("income", "GrossProfit", "gross_profit"),
    ("income", "OperatingIncome", "operating_income"),
    ("income", "IncomeAfterTaxes", "net_income"),
    ("balance", "TotalAssets", "total_assets"),
    ("balance", "CurrentAssets", "current_assets"),
    ("balance", "CurrentLiabilities", "current_liabilities"),
    ("balance", "Liabilities", "total_liabilities"),
    ("balance", "Inventories", "inventory"),
    ("balance", "CashAndCashEquivalents", "cash_and_cash_equivalents"),
    ("cashflow", "CashFlowsFromOperatingActivities", "operating_cash_flow"),
)
HEADERS = (
    "ticker", "year", "statement", "finmind_type", "mops_metric",
    "finmind_quarters_found", "finmind_q4_value", "finmind_four_quarter_sum",
    "mops_annual_value", "q4_relative_difference", "sum_relative_difference",
    "q4_within_tolerance", "sum_within_tolerance", "candidate_preference",
    "evidence_status", "provider_archive_sha256", "mops_raw_sha256",
)


def value_of(number):
    if isinstance(number, bool) or number is None:
        raise ValueError("not_a_numeric_value")
    try:
        number = Decimal(str(number))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid_decimal") from None
    if not number.is_finite():
        raise ValueError("nonfinite_decimal")
    return number


def _quantities(folder, ticker):
    """Read locally cached provider data. Never fetch, fill, or accept *_per."""
    output = {}
    hashes = {}
    for family, dataset in DATASETS.items():
        path = Path(folder) / ticker / (dataset + ".json")
        if not path.is_file():
            output[family] = {}
            hashes[family] = ""
            continue
        contents = path.read_bytes()
        obj = json.loads(contents)
        if obj.get("ticker") != ticker or obj.get("dataset") != dataset:
            raise ValueError("finmind_archive_identity_mismatch")
        if not isinstance(obj.get("records"), list):
            raise ValueError("finmind_archive_missing_records")
        grouped = defaultdict(set)
        for line in obj["records"]:
            if str(line.get("stock_id")) != ticker:
                raise ValueError("finmind_record_wrong_issuer")
            kind = str(line.get("type") or "").strip()
            if kind.endswith("_per"):
                continue  # Percentage; never equivalent to monetary statement amount.
            raw_day = str(line.get("date") or "")
            try:
                report_day = date.fromisoformat(raw_day)
            except ValueError:
                raise ValueError("finmind_invalid_statement_date") from None
            if not kind:
                raise ValueError("finmind_missing_type")
            grouped[(kind, report_day.isoformat())].add(value_of(line.get("value")))
        # Ambiguous numerical duplicates are not selected in response order.
        if any(len(values) > 1 for values in grouped.values()):
            raise ValueError("finmind_conflicting_type_period_values")
        output[family] = {key: next(iter(values)) for key, values in grouped.items()}
        hashes[family] = hashlib.sha256(contents).hexdigest()
    return output, hashes


def _official(manifest, ticker, year):
    entry = manifest.get("outcomes", {}).get(f"{ticker}:{year}")
    if not entry or entry.get("status") != "validated":
        return {}, ""
    if entry.get("statement_scope") != "consolidated" or entry.get("accounting_framework") != "TIFRS":
        return {}, ""
    facts = {}
    for fact in entry.get("facts", []):
        if fact.get("unit") != "TWD":
            continue
        metric = str(fact.get("metric_code") or "")
        val = value_of(fact.get("value"))
        if metric in facts and facts[metric] != val:
            raise ValueError("mops_ambiguous_metric")
        facts[metric] = val
    return facts, entry.get("content_hash") or ""


def _deviation(observed, target):
    if observed is None or target is None:
        return None
    scale = max(abs(target), Decimal("1"))
    return abs(observed - target) / scale


def _show(x):
    return "" if x is None else format(x, "f")


def compare(provider_root, mops_manifest, output, *, tickers=("2330",),
            start_year=2013, end_year=2015, tolerance="0.001"):
    """Report both interpretations, with *no* approval of a period policy."""
    if not 2013 <= start_year <= end_year <= 2025:
        raise ValueError("invalid_retrospective_years")
    tol = value_of(tolerance)
    if not Decimal(0) <= tol <= Decimal("0.01"):
        raise ValueError("tolerance_out_of_bounds")
    if not tickers or "1785" in tickers or len(set(tickers)) != len(tickers):
        raise ValueError("reserved_case_or_duplicate_ticker")
    manifest = json.loads(Path(mops_manifest).read_text(encoding="utf-8"))
    rows = []
    source_count = Counter()
    for ticker in tickers:
        inputs, hashes = _quantities(provider_root, ticker)
        for year in range(start_year, end_year + 1):
            facts, mops_hash = _official(manifest, ticker, year)
            for family, provider_type, official_metric in PAIRS:
                x = inputs[family]
                qs = [x.get((provider_type, f"{year}-{month:02d}-{day:02d}"))
                      for month, day in ((3, 31), (6, 30), (9, 30), (12, 31))]
                q4 = qs[3]
                qsum = (sum(qs, Decimal(0)) if family != "balance" and
                        all(value is not None for value in qs) else None)
                target = facts.get(official_metric)
                dq = _deviation(q4, target)
                ds = _deviation(qsum, target)
                mq = dq is not None and dq <= tol
                ms = ds is not None and ds <= tol
                if target is None:
                    result = "no_eligible_mops_annual_fact"
                elif q4 is None:
                    result = "provider_q4_not_available"
                elif family != "balance" and qsum is None:
                    result = "provider_full_quarter_set_missing"
                else:
                    result = "comparable_candidates_not_period_certification"
                if family == "balance":
                    method = "Q4_INSTANT_CANDIDATE" if mq else "NO_MATCH"
                elif mq and ms:
                    method = "BOTH_AGREE_AMBIGUOUS"
                elif mq:
                    method = "Q4_ONLY_CANDIDATE"
                elif ms:
                    method = "FOUR_QUARTER_SUM_CANDIDATE"
                else:
                    method = "NO_MATCH"
                source_count[method] += 1
                rows.append({
                    "ticker": ticker, "year": year,
                    "statement": family, "finmind_type": provider_type,
                    "mops_metric": official_metric,
                    "finmind_quarters_found": sum(a is not None for a in qs),
                    "finmind_q4_value": _show(q4),
                    "finmind_four_quarter_sum": _show(qsum),
                    "mops_annual_value": _show(target),
                    "q4_relative_difference": _show(dq),
                    "sum_relative_difference": _show(ds),
                    "q4_within_tolerance": mq, "sum_within_tolerance": ms,
                    "candidate_preference": method,
                    "evidence_status": result,
                    "provider_archive_sha256": hashes.get(family) or "",
                    "mops_raw_sha256": mops_hash,
                })
    folder = Path(output)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "finmind_mops_annual_crosscheck.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    report = {
        "status": "FINMIND_MOPS_ANNUAL_PERIOD_CANDIDATE_CROSSCHECK",
        "ticker_count": len(tickers), "company_years_requested": len(tickers) * (end_year - start_year + 1),
        "comparison_rows": len(rows), "candidate_method_counts": dict(sorted(source_count.items())),
        "tolerance_relative": str(tol),
        "provider_raw_version_and_fiscal_period": "UNVERIFIED",
        "mops_original_version_and_publication_time": "UNVERIFIED",
        "candidate_mapping_is_approved": False,
        "annual_dataset_built": False,
        "literature_features_built": False,
        "models_trained": False,
        "production_database_writes": 0, "network_requests": 0,
        "warning": ("A numerical match is only reconciliation evidence for these "
                    "issuer-years; it does not certify annual flow semantics "
                    "for every account/year or original/publication vintage.")
    }
    (folder / "finmind_mops_crosscheck_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description="Offline FinMind/MOPS annual crosscheck, no training or fetch")
    p.add_argument("--provider-root", required=True)
    p.add_argument("--mops-manifest", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--ticker", action="append", default=[])
    p.add_argument("--start-year", type=int, default=2013)
    p.add_argument("--end-year", type=int, default=2015)
    p.add_argument("--tolerance", default="0.001")
    args = p.parse_args(argv)
    print(json.dumps(compare(args.provider_root, args.mops_manifest, args.output,
                             tickers=tuple(args.ticker) if args.ticker else ("2330",),
                             start_year=args.start_year, end_year=args.end_year,
                             tolerance=args.tolerance), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
