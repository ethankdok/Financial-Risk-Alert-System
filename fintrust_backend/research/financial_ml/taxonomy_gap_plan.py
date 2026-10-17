"""Build a candidate-only 2011-15 financial ML acquisition plan from archived 2026 taxonomy.

IMPORTANT: The current (2026) semiconductor taxonomy is not a historical
company master, does not establish 2011-15 listings, and creates NO normal labels.
Read-only on existing SQLite data. No network access, DB writes, cloud access,
or production changes. Outputs are local CSV/JSON only.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

FIELDS = (
    "ticker", "company", "subindustry", "fiscal_year", "current_taxonomy_source",
    "historical_listing_status", "historical_industry_status", "normal_label_status",
    "local_filing_rows", "local_annual_fact_rows", "local_data_status", "next_action",
)


def _readonly(path: str | Path) -> sqlite3.Connection | None:
    p = Path(path).resolve()
    if not p.is_file():
        return None
    db = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)
    db.execute("PRAGMA query_only=ON")
    return db


def _has_columns(db: sqlite3.Connection, name: str, cols: set[str]) -> bool:
    available = {c[1] for c in db.execute(f'PRAGMA table_info("{name}")')}
    return cols.issubset(available)


def _local_counts(db_path: str | Path) -> tuple[dict, dict, str]:
    filing, facts = defaultdict(int), defaultdict(int)
    db = _readonly(db_path)
    if db is None:
        return {}, {}, "local_database_absent"
    try:
        if _has_columns(db, "financial_filings", {"ticker", "fiscal_year"}):
            for ticker, year, count in db.execute(
                "SELECT ticker, fiscal_year, COUNT(*) FROM financial_filings "
                "WHERE ticker IS NOT NULL AND fiscal_year IS NOT NULL "
                "GROUP BY ticker, fiscal_year"
            ):
                try:
                    filing[(str(ticker).strip(), int(year))] += count
                except (ValueError, TypeError):
                    continue
        if _has_columns(db, "normalized_financial_facts", {"ticker", "period"}):
            for ticker, period, count in db.execute(
                "SELECT ticker, period, COUNT(*) FROM normalized_financial_facts "
                "WHERE ticker IS NOT NULL AND period IS NOT NULL GROUP BY ticker, period"
            ):
                period = str(period)
                if len(period) == 6 and period.endswith("FY") and period[:4].isdigit():
                    facts[(str(ticker).strip(), int(period[:4]))] += count
        return dict(filing), dict(facts), "read_only_local_db"
    finally:
        db.close()


def build(coverage_path: str | Path, *, facts_db: str | Path,
          start_year: int = 2011, end_year: int = 2015,
          reserved_ticker: str = "1785") -> tuple[list[dict], dict]:
    if not (1990 <= start_year <= end_year <= 2100):
        raise ValueError("Invalid year range")
    content = json.loads(Path(coverage_path).read_text(encoding="utf-8-sig"))
    companies = content.get("companies")
    if not isinstance(companies, list):
        raise ValueError("Source coverage report requires a companies array")
    if content.get("requested_companies") != len(companies):
        raise ValueError("Source coverage report company count mismatch")
    observed = {}
    for company in companies:
        if not isinstance(company, dict):
            raise ValueError("Invalid company entry")
        ticker = str(company.get("ticker") or "").strip()
        if not ticker.isdigit() or not ticker or ticker in observed:
            raise ValueError("Missing, nonnumeric, or duplicate ticker")
        if not company.get("subindustry"):
            raise ValueError(f"Missing subindustry for {ticker}")
        observed[ticker] = company
    filings, facts, database_status = _local_counts(facts_db)
    out = []
    statuses = Counter()
    for ticker, company in sorted(observed.items()):
        if ticker == reserved_ticker:
            continue
        for year in range(start_year, end_year + 1):
            n_filing = filings.get((ticker, year), 0)
            n_fact = facts.get((ticker, year), 0)
            if n_filing and n_fact:
                status, action = "local_records_unverified", "check_version_scope_vintage_then_cloud"
            elif n_filing or n_fact:
                status, action = "partial_local_records", "reconcile_existing_then_cloud"
            else:
                status, action = "not_in_local_financial_db", "verify_historical_listing_industry_then_cloud_and_official"
            statuses[status] += 1
            out.append({
                "ticker": ticker, "company": str(company.get("company") or ""),
                "subindustry": str(company["subindustry"]), "fiscal_year": year,
                "current_taxonomy_source": str(coverage_path),
                "historical_listing_status": "UNVERIFIED",
                "historical_industry_status": "UNVERIFIED",
                "normal_label_status": "UNREVIEWED",
                "local_filing_rows": n_filing, "local_annual_fact_rows": n_fact,
                "local_data_status": status, "next_action": action,
            })
    report = {
        "status": "candidate_gap_plan_created_not_training_ready",
        "candidate_source": str(coverage_path),
        "candidate_source_generated_at": content.get("generated_at"),
        "candidate_source_scope": content.get("scope"),
        "reference_coverage_counts_2026_only": {
            "PASS": content.get("pass_count"), "PARTIAL": content.get("partial_count"),
            "FAIL": content.get("fail_count"),
        },
        "facts_database": str(facts_db), "local_database_status": database_status,
        "start_year": start_year, "end_year": end_year,
        "reserved_ticker": reserved_ticker,
        "candidate_companies": len({r["ticker"] for r in out}),
        "candidate_company_years": len(out),
        "verified_historical_eligible_company_years": 0,
        "reviewed_normal_company_years": 0,
        "local_data_counts": dict(sorted(statuses.items())),
        "source_databases_modified": False,
        "warnings": [
            "The 2026 company list and coverage PASS/PARTIAL/FAIL are NOT 2011-2015 availability, historical industry membership, or normal labels.",
            "No historical listing dates or delisting dates were verified; all company-years are candidates only.",
            "Issuer survival and industry migrations create survivorship bias; include historical delisted issuers after source verification.",
            "Local metadata counts do not prove original filing availability, data quality, or model-ready feature coverage.",
            "No cloud query, network acquisition, data labeling, or ML training was performed.",
        ],
    }
    return out, report


def save(rows: list[dict], report: dict, output_dir: str | Path) -> tuple[str, str]:
    p = Path(output_dir)
    p.mkdir(parents=True, exist_ok=True)
    csvpath, jsonpath = p / "historical_candidate_gap_plan.csv", p / "historical_candidate_summary.json"
    with csvpath.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    jsonpath.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(csvpath), str(jsonpath)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Historical candidate gaps from a 2026 taxonomy report; read-only")
    p.add_argument("--coverage-report", default="../docs/database/semiconductor-expansion-coverage-2026-09-21.json")
    p.add_argument("--facts-db", default="data/financial_pipeline.sqlite3")
    p.add_argument("--start-year", type=int, default=2011)
    p.add_argument("--end-year", type=int, default=2015)
    p.add_argument("--reserve-ticker", default="1785")
    p.add_argument("--output-dir", default="data/financial_ml/historical_candidate_coverage")
    args = p.parse_args(argv)
    rows, report = build(args.coverage_report, facts_db=args.facts_db,
                         start_year=args.start_year, end_year=args.end_year,
                         reserved_ticker=args.reserve_ticker)
    paths = save(rows, report, args.output_dir)
    print(json.dumps({"outputs": paths, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())