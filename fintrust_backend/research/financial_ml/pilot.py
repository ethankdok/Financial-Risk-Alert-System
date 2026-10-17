"""Auditable XBRL-export -> company-year ML feature pilot.

Consumes ONLY the historical_audit_case export contract (not the live DB).
It never creates fraud labels or regards restated data as ex-ante evidence.
Only the 11 descriptive ratios matching feature_registry are calculated here;
Beneish and Dechow use richer, separate literature line mappings and are NOT
silently approximated from canonical financial facts.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

REQUIRED = {"ticker", "fiscal_year", "period", "metric_code", "value", "unit",
            "statement_scope", "filing_version_id", "filing_version_type",
            "quality_status", "validation_status", "point_in_time_eligible",
            "effective_available_at", "source_kind", "accounting_framework"}
CORE = {"revenue", "cost_of_goods_sold", "gross_profit", "operating_income",
        "net_income", "accounts_receivable", "inventory", "current_assets",
        "total_assets", "current_liabilities", "total_liabilities", "equity",
        "operating_cash_flow", "investing_cash_flow", "capital_expenditure",
        "eps", "cash_and_cash_equivalents"}
FEATURES = ("gross_margin", "cogs_sales_ratio", "operating_margin", "net_margin",
            "inventory_to_assets", "receivables_sales_ratio", "debt_asset_ratio",
            "inventory_turnover", "inventory_growth_assets", "receivables_growth_assets",
            "earnings_cashflow_gap_proxy", "revenue_yoy", "inventory_yoy",
            "receivables_yoy", "cashflow_assets_ratio")


def _date(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.utcoffset() is None:
        raise ValueError(f"Timestamp must contain timezone: {s!r}")
    return dt


def _number(s: str) -> Decimal | None:
    try:
        v = Decimal(s)
        return v if v.is_finite() else None
    except (InvalidOperation, TypeError):
        return None


def _ratio(n: Decimal | None, d: Decimal | None, *, positive=True) -> float | None:
    if n is None or d is None or (d <= 0 if positive else d == 0):
        return None
    try:
        result = float(n / d)
    except (OverflowError, InvalidOperation):
        return None
    return result if math.isfinite(result) else None


def _avg(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return (a + b) / 2 if a is not None and b is not None else None


def _diff(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    return a - b if a is not None and b is not None else None


def _read_csv(paths):
    for source in paths:
        with Path(source).open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            missing = REQUIRED - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"{source}: missing historical export columns: {sorted(missing)}")
            for lineno, row in enumerate(reader, 2):
                row["_file"] = str(source)
                row["_line"] = lineno
                yield row


def _read_cutoffs(path):
    if path is None:
        return {}
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        rdr = csv.DictReader(fh)
        if not {"ticker", "fiscal_year", "cutoff_at"}.issubset(rdr.fieldnames or []):
            raise ValueError("cutoffs CSV needs ticker,fiscal_year,cutoff_at")
        return {(r["ticker"].strip(), int(r["fiscal_year"])): _date(r["cutoff_at"]) for r in rdr}


def _read_labels(path):
    if not path:
        return {}
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        rdr = csv.DictReader(fh)
        required = {"ticker", "fiscal_year", "label", "label_source", "outcome_known_at"}
        if not required.issubset(rdr.fieldnames or []):
            raise ValueError(f"labels CSV needs {sorted(required)}")
        labels = {}
        for r in rdr:
            key = (r["ticker"].strip(), int(r["fiscal_year"]))
            if key in labels:
                raise ValueError(f"duplicate label {key}")
            if r["label"] not in {"0", "1"} or not r["label_source"].strip():
                raise ValueError(f"label must be 0/1 and label_source nonempty: {key}")
            _date(r["outcome_known_at"])
            labels[key] = r
        return labels


def build(paths, *, mode="retrospective", cutoffs_path=None, labels_path=None):
    if mode not in {"retrospective", "strict"}:
        raise ValueError("mode must be retrospective or strict")
    if mode == "strict" and not cutoffs_path:
        raise ValueError("strict mode requires --cutoffs containing independently verified cutoff times")
    cutoffs = _read_cutoffs(cutoffs_path)
    labels = _read_labels(labels_path)
    reasons = Counter()
    source_rows = 0
    # Each (company, year, immutable filing version) is independently assembled.
    versions: dict[tuple[str, int, str], dict] = {}
    for r in _read_csv(paths):
        source_rows += 1
        try:
            ticker, fy = r["ticker"].strip(), int(r["fiscal_year"])
        except (ValueError, TypeError):
            reasons["invalid_company_year"] += 1
            continue
        if r["period"] != f"{fy}FY":
            reasons["not_annual_fy_observation"] += 1
            continue
        if r["metric_code"] not in CORE:
            reasons["non_core_metric"] += 1
            continue
        if r["source_kind"] == "test_fixture":
            reasons["test_fixture"] += 1
            continue
        if r["statement_scope"] != "consolidated":
            reasons["not_consolidated"] += 1
            continue
        if r["unit"] != "TWD":
            reasons["not_twd"] += 1
            continue
        if r["validation_status"] not in {"validated", "validated_with_warnings"} or r["quality_status"] not in {"accepted", "warning"}:
            reasons["failed_source_validation"] += 1
            continue
        if r["accounting_framework"] not in {"TIFRS", "TW_GAAP"}:
            reasons["unknown_accounting_framework"] += 1
            continue
        if mode == "strict":
            cutoff = cutoffs.get((ticker, fy))
            if cutoff is None:
                reasons["cutoff_missing"] += 1
                continue
            if r["filing_version_type"] != "original":
                reasons["not_original"] += 1
                continue
            if str(r["point_in_time_eligible"]).lower() != "true" or not r["effective_available_at"]:
                reasons["not_point_in_time_eligible"] += 1
                continue
            try:
                if not _date(r["effective_available_at"]) < cutoff:
                    reasons["published_after_cutoff"] += 1
                    continue
            except ValueError:
                reasons["invalid_availability_timestamp"] += 1
                continue
        val = _number(r["value"])
        if val is None:
            reasons["invalid_number"] += 1
            continue
        key = (ticker, fy, r["filing_version_id"])
        block = versions.setdefault(key, {"facts": {}, "framework": r["accounting_framework"],
                                           "version_type": r["filing_version_type"], "conflict": False})
        if block["framework"] != r["accounting_framework"] or block["version_type"] != r["filing_version_type"]:
            block["conflict"] = True
        field = r["metric_code"]
        if field in block["facts"] and block["facts"][field] != val:
            block["conflict"] = True
        block["facts"][field] = val
    groups = defaultdict(list)
    for (ticker, year, version), block in versions.items():
        groups[(ticker, year)].append((version, block))
    selected = {}
    ambiguous = []
    for key, vs in sorted(groups.items()):
        if len(vs) != 1 or vs[0][1]["conflict"]:
            ambiguous.append({"ticker": key[0], "fiscal_year": key[1],
                              "versions": len(vs), "reason": "ambiguous_or_conflicting_versions"})
            continue
        selected[key] = (vs[0][0], vs[0][1])
    records = []
    missing_counts = Counter()
    for (ticker, year), (version, blk) in sorted(selected.items()):
        curr = blk["facts"]
        prev_entry = selected.get((ticker, year - 1))
        prev = prev_entry[1]["facts"] if prev_entry and prev_entry[1]["framework"] == blk["framework"] else {}
        a, p = lambda field: curr.get(field), lambda field: prev.get(field)
        avg_assets = _avg(a("total_assets"), p("total_assets"))
        result = {
            "gross_margin": _ratio(a("gross_profit"), a("revenue")),
            "cogs_sales_ratio": _ratio(a("cost_of_goods_sold"), a("revenue")),
            "operating_margin": _ratio(a("operating_income"), a("revenue")),
            "net_margin": _ratio(a("net_income"), a("revenue")),
            "inventory_to_assets": _ratio(a("inventory"), a("total_assets")),
            "receivables_sales_ratio": _ratio(a("accounts_receivable"), a("revenue")),
            "debt_asset_ratio": _ratio(a("total_liabilities"), a("total_assets")),
            "inventory_turnover": _ratio(a("cost_of_goods_sold"), _avg(a("inventory"), p("inventory"))),
            "inventory_growth_assets": _ratio(_diff(a("inventory"), p("inventory")), avg_assets),
            "receivables_growth_assets": _ratio(_diff(a("accounts_receivable"), p("accounts_receivable")), avg_assets),
            "earnings_cashflow_gap_proxy": _ratio(_diff(a("net_income"), a("operating_cash_flow")), avg_assets),
            "revenue_yoy": _ratio(_diff(a("revenue"), p("revenue")), p("revenue")),
            "inventory_yoy": _ratio(_diff(a("inventory"), p("inventory")), p("inventory")),
            "receivables_yoy": _ratio(_diff(a("accounts_receivable"), p("accounts_receivable")), p("accounts_receivable")),
            "cashflow_assets_ratio": _ratio(a("operating_cash_flow"), a("total_assets")),
        }
        for feature, value in result.items():
            if value is None:
                missing_counts[feature] += 1
        label = labels.get((ticker, year))
        records.append({"ticker": ticker, "fiscal_year": year, "filing_version_id": version,
                        "filing_version_type": blk["version_type"], "accounting_framework": blk["framework"],
                        "analysis_mode": mode, "label": label["label"] if label else "",
                        "label_source": label["label_source"] if label else "",
                        "outcome_known_at": label["outcome_known_at"] if label else "", **result})
    report = {"analysis_mode": mode, "input_rows": source_rows, "source_files": len(paths),
              "accepted_company_years": len(records), "companies": len({r["ticker"] for r in records}),
              "years": sorted({r["fiscal_year"] for r in records}),
              "rejection_counts": dict(sorted(reasons.items())), "ambiguous_company_years": ambiguous,
              "features": list(FEATURES), "missing_feature_counts": dict(sorted(missing_counts.items())),
              "labeled_rows": sum(r["label"] in {"0", "1"} for r in records),
              "positive_labels": sum(r["label"] == "1" for r in records),
              "strict_warning": "Retrospective data must NOT be presented as ex-ante prediction" if mode == "retrospective" else None,
              "literature_variables": "NOT computed: Beneish/Dechow require literature-specific mappings and t-2 inputs",
              "status": "ready_for_label_audit" if records else "blocked_no_unambiguous_rows"}
    return records, report


def save(records, report, output):
    dest = Path(output)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "financial_ml_pilot.csv"
    fields = ["ticker", "fiscal_year", "filing_version_id", "filing_version_type", "accounting_framework",
              "analysis_mode", "label", "label_source", "outcome_known_at", *FEATURES]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(records)
    (dest / "financial_ml_readiness.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def main(argv=None):
    cli = argparse.ArgumentParser(description="Offline XBRL financial ML pilot (never alters the DB)")
    cli.add_argument("--csv", action="append", required=True, help="historical_audit_case export CSV; repeat for multiple sources")
    cli.add_argument("--mode", choices=["retrospective", "strict"], required=True)
    cli.add_argument("--cutoffs", help="required in strict mode: ticker,fiscal_year,cutoff_at")
    cli.add_argument("--labels", help="optional independently verified label ledger CSV")
    cli.add_argument("--output", required=True, help="output directory")
    args = cli.parse_args(argv)
    rows, report = build(args.csv, mode=args.mode, cutoffs_path=args.cutoffs, labels_path=args.labels)
    path = save(rows, report, args.output)
    print(json.dumps({"dataset": str(path), **report}, ensure_ascii=False, indent=2))
    return 0 if rows else 2


if __name__ == "__main__":
    raise SystemExit(main())