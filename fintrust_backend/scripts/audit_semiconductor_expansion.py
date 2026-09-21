from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from app.services.semiconductor_coverage import technically_supported
from app.services.semiconductor_coverage_audit import (
    ReadOnlyCompanyRepository,
    SemiconductorCoverageAuditor,
)
from app.services.semiconductor_subindustries import classified_tickers
from app.services.twse_company_universe import TwseCompanyUniverseService


PILOT_TICKERS = (
    "2330",  # foundry
    "2344",  # memory manufacturing
    "3711",  # packaging/testing
    "2454",  # IC design
    "2302",  # power semiconductor
    "2338",  # materials/components
    "3413",  # semiconductor equipment
    "2451",  # memory module/storage
    "3450",  # optoelectronics/display semiconductor
)


async def run(args: argparse.Namespace) -> int:
    _, companies = await TwseCompanyUniverseService(
        repository=ReadOnlyCompanyRepository([])
    ).fetch()
    taxonomy = classified_tickers()
    companies = [
        company
        for company in companies
        if company.ticker in taxonomy and technically_supported(company.subindustry)
    ]
    by_ticker = {company.ticker: company for company in companies}
    if args.tickers:
        requested = tuple(dict.fromkeys(part.strip() for part in args.tickers.split(",") if part.strip()))
    elif args.scope == "pilot":
        requested = PILOT_TICKERS
    else:
        requested = tuple(sorted(taxonomy))
    missing = sorted(set(requested) - set(by_ticker))
    selected = [by_ticker[ticker] for ticker in requested if ticker in by_ticker]

    report = await SemiconductorCoverageAuditor(
        selected,
        concurrency=args.concurrency,
    ).run(years=args.years, scope=args.scope)
    payload = report.model_dump(mode="json")
    payload["universe_count"] = len(companies)
    payload["missing_universe_tickers"] = missing
    payload["read_only"] = True
    payload["parser_mode"] = os.getenv("MOPS_XBRL_PARSER_MODE", "arelle")
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if report.fail_count or missing else 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only filing, fact, metric and rule coverage audit for the semiconductor universe."
    )
    parser.add_argument("--scope", choices=("pilot", "all"), default="pilot")
    parser.add_argument("--tickers", help="Optional comma-separated override.")
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--output")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
