"""Read-only local semiconductor company-year coverage planner (research only).

Only inventories existing canonical local SQLite tables. Does not download filings,
read financial amounts, create normal labels, authenticate cloud services, or
write to source databases. Its coverage statuses are NOT model readiness gates.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

_ANNUAL = re.compile(r"^(\d{4})FY$")
_PLAN_FIELDS = ("ticker", "fiscal_year", "subindustry", "filing_rows", "annual_fact_rows",
                "coverage_status", "source_action", "listed_at")


def _open_readonly(path: str | Path) -> sqlite3.Connection | None:
    p = Path(path).resolve()
    if not p.is_file():
        return None
    con = sqlite3.connect(p.as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    if not any(r[0] == table for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")):
        return set()
    return {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}


def _universe(db: sqlite3.Connection, *, markets: tuple[str, ...],
              industry_codes: tuple[str, ...]) -> tuple[list[dict], int, str]:
    cols = _columns(db, "companies")
    required = {"ticker", "market", "industry_code", "listing_status"}
    if not required.issubset(cols):
        return [], 0, "blocked_missing_company_master"
    total = db.execute('SELECT COUNT(*) FROM "companies"').fetchone()[0]
    selected = ["ticker", "market", "industry_code", "listing_status"]
    selected += [c for c in ("subindustry", "listed_at") if c in cols]
    sql = f'SELECT {", ".join("\"" + c + "\"" for c in selected)} FROM "companies"'
    records = []
    for r in db.execute(sql):
        d = dict(r)
        if (d["market"] in markets and str(d["industry_code"]) in industry_codes
                and d["listing_status"] == "listed" and str(d["ticker"]).strip()):
            records.append(d)
    unique = {str(r["ticker"]).strip(): r for r in records}
    return list(unique.values()), total, "local_company_master"


def _filing_counts(db: sqlite3.Connection) -> tuple[dict[tuple[str, int], int], str]:
    cols = _columns(db, "financial_filings")
    if not {"ticker", "fiscal_year"}.issubset(cols):
        return {}, "filing_table_missing_or_unrecognized"
    counts = {}
    for r in db.execute('SELECT ticker, fiscal_year, COUNT(*) FROM "financial_filings" '
                        'WHERE ticker IS NOT NULL AND fiscal_year IS NOT NULL '
                        'GROUP BY ticker, fiscal_year'):
        try:
            counts[(str(r[0]).strip(), int(r[1]))] = int(r[2])
        except (ValueError, TypeError):
            continue
    return counts, "filing_table_read"


def _fact_counts(db: sqlite3.Connection) -> tuple[dict[tuple[str, int], int], str]:
    cols = _columns(db, "normalized_financial_facts")
    if "ticker" not in cols:
        return {}, "fact_table_missing_or_unrecognized"
    if "period" in cols:
        sql = 'SELECT ticker, period, COUNT(*) FROM "normalized_financial_facts" GROUP BY ticker, period'
        extractor = lambda x: int(_ANNUAL.fullmatch(str(x)).group(1)) if _ANNUAL.fullmatch(str(x)) else None
    elif "fiscal_year" in cols:
        sql = 'SELECT ticker, fiscal_year, COUNT(*) FROM "normalized_financial_facts" GROUP BY ticker, fiscal_year'
        def extractor(x):
            try:
                return int(x)
            except (ValueError, TypeError):
                return None
    else:
        return {}, "fact_year_column_missing"
    counts = defaultdict(int)
    for r in db.execute(sql):
        year = extractor(r[1])
        if year is not None and r[0] is not None:
            counts[(str(r[0]).strip(), year)] += int(r[2])
    return dict(counts), "fact_table_read"


def assess(master_db: str | Path, facts_db: str | Path, *, start_year: int = 2011,
           end_year: int = 2015, reserve_ticker: str = "1785",
           markets: tuple[str, ...] = ("TWSE",),
           industry_codes: tuple[str, ...] = ("24",)) -> tuple[list[dict], dict]:
    if start_year > end_year or not 1990 <= start_year <= 2100 or not 1990 <= end_year <= 2100:
        raise ValueError("Invalid fiscal year range")
    if not markets or not industry_codes:
        raise ValueError("At least one market and one industry code are required")
    report = {"scope": "local_currently_listed_candidate_universe",
              "markets": list(markets), "industry_codes": list(industry_codes),
              "start_year": start_year, "end_year": end_year,
              "reserved_case": reserve_ticker, "source_master": str(master_db),
              "source_facts": str(facts_db), "read_only": True,
              "warning": [
                  "Current listed-company master is NOT the complete historical issuer population: delisted and legacy issuers may be missing (survivorship bias).",
                  "Filing/fact counts are metadata only: source version, consolidation scope, vintage and original availability are NOT verified.",
                  "Zero local rows do not prove that filings are absent from cloud stores or official sources.",
                  "No company is classified normal and no ML samples are created by this planner.",
              ]}
    master = _open_readonly(master_db)
    if master is None:
        report.update(status="blocked_master_database_absent", company_master_rows=0,
                      candidate_companies=0, company_years=0)
        return [], report
    try:
        universe, master_count, source = _universe(master, markets=markets,
                                                   industry_codes=industry_codes)
        report["company_master_rows"] = master_count
        report["master_status"] = source
    finally:
        master.close()
    if source != "local_company_master" or not universe:
        report.update(status="blocked_no_local_semiconductor_master", candidate_companies=0,
                      company_years=0)
        return [], report
    facts = _open_readonly(facts_db)
    filing_counts, fact_counts = {}, {}
    if facts is None:
        report["facts_database_status"] = "absent"
    else:
        try:
            filing_counts, f_status = _filing_counts(facts)
            fact_counts, x_status = _fact_counts(facts)
            report["facts_database_status"] = [f_status, x_status]
        finally:
            facts.close()
    plan = []
    reasons = Counter()
    post_listing_exclusions = 0
    eligible_issuers = set()
    for company in sorted(universe, key=lambda c: str(c["ticker"])):
        ticker = str(company["ticker"]).strip()
        if ticker == reserve_ticker:
            continue
        listed_at = str(company.get("listed_at") or "")
        try:
            listing_date = date.fromisoformat(listed_at[:10]) if listed_at else None
        except ValueError:
            listing_date = None
        for year in range(start_year, end_year + 1):
            # A company listed after year end cannot be part of that year's listed-company cohort.
            if listing_date and listing_date > date(year, 12, 31):
                post_listing_exclusions += 1
                continue
            eligible_issuers.add(ticker)
            filing_rows = filing_counts.get((ticker, year), 0)
            fact_rows = fact_counts.get((ticker, year), 0)
            if filing_rows and fact_rows:
                status, action = "recorded_but_unverified", "review_version_scope_and_asof"
            elif filing_rows or fact_rows:
                status, action = "partial_local_records", "reconcile_existing_rows_then_plan_gap"
            else:
                status, action = "no_local_record", "check_cloud_then_official_acquisition"
            reasons[status] += 1
            plan.append({"ticker": ticker, "fiscal_year": year,
                         "subindustry": company.get("subindustry") or "unclassified",
                         "filing_rows": filing_rows, "annual_fact_rows": fact_rows,
                         "coverage_status": status, "source_action": action,
                         "listed_at": listed_at})
    report.update(status="local_gap_plan_created", candidate_companies=len(eligible_issuers),
                  company_years=len(plan), excluded_post_listing_company_years=post_listing_exclusions,
                  coverage_counts=dict(sorted(reasons.items())))
    return plan, report


def save(plan: list[dict], report: dict, output_dir: str | Path) -> tuple[Path, Path]:
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    csv_path = folder / "company_year_gap_plan.csv"
    json_path = folder / "coverage_summary.json"
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=_PLAN_FIELDS)
        writer.writeheader()
        writer.writerows(plan)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return csv_path, json_path


def main(argv=None):
    p = argparse.ArgumentParser(description="Plan local semiconductor data gaps without any database writes or network access")
    p.add_argument("--master-db", default="data/financial_pipeline.sqlite3")
    p.add_argument("--facts-db", default="data/financial_pipeline.sqlite3")
    p.add_argument("--start-year", type=int, default=2011)
    p.add_argument("--end-year", type=int, default=2015)
    p.add_argument("--reserve-ticker", default="1785")
    p.add_argument("--market", action="append", help="TWSE or TPEX; repeat to include both (default TWSE)")
    p.add_argument("--industry-code", action="append", help="Repeat for each official industry code (default 24)")
    p.add_argument("--output-dir", default="data/financial_ml/industry_coverage")
    a = p.parse_args(argv)
    plan, summary = assess(a.master_db, a.facts_db, start_year=a.start_year,
                           end_year=a.end_year, reserve_ticker=a.reserve_ticker,
                           markets=tuple(a.market or ("TWSE",)),
                           industry_codes=tuple(a.industry_code or ("24",)))
    paths = save(plan, summary, a.output_dir)
    print(json.dumps({"outputs": [str(x) for x in paths], **summary}, ensure_ascii=False, indent=2))
    return 0 if summary["status"] == "local_gap_plan_created" else 2


if __name__ == "__main__":
    raise SystemExit(main())