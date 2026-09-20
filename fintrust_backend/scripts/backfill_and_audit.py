from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.company_master_repository import build_company_master_repository
from app.services.ingestion_pipeline import FinancialIngestionPipeline, validate_refresh_tickers
from app.services.ingestion_run_repository import build_ingestion_run_repository
from app.services.twse_company_universe import TwseCompanyUniverseService


def _scalar(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> int:
    return int(connection.execute(sql, params).fetchone()[0])


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    )


def audit_database(database: Path, tickers: list[str], requested_years: int) -> dict[str, Any]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        company_count = _scalar(connection, "SELECT COUNT(*) FROM companies")
        distinct_company_count = _scalar(connection, "SELECT COUNT(DISTINCT ticker) FROM companies")
        unclassified_count = _scalar(
            connection,
            "SELECT COUNT(*) FROM companies WHERE subindustry = '待分類' OR subindustry_confidence = 'unclassified'",
        )
        subindustries = {
            row["subindustry"]: row["count"]
            for row in connection.execute(
                "SELECT subindustry, COUNT(*) AS count FROM companies GROUP BY subindustry ORDER BY subindustry"
            )
        }

        companies: dict[str, Any] = {}
        for ticker in tickers:
            run = connection.execute(
                "SELECT * FROM ingestion_runs WHERE ticker=? ORDER BY started_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            latest_run_id = run["run_id"] if run else None
            filings = connection.execute(
                """SELECT period, status, source_name, source_url, warnings_json
                FROM financial_filings WHERE ticker=? ORDER BY period""",
                (ticker,),
            ).fetchall() if _table_exists(connection, "financial_filings") else []
            available_filings = [row for row in filings if row["status"] == "available"]
            facts = _scalar(
                connection, "SELECT COUNT(*) FROM normalized_financial_facts WHERE ticker=?", (ticker,)
            ) if _table_exists(connection, "normalized_financial_facts") else 0
            distinct_facts = _scalar(
                connection,
                "SELECT COUNT(DISTINCT fact_id) FROM normalized_financial_facts WHERE ticker=?",
                (ticker,),
            ) if _table_exists(connection, "normalized_financial_facts") else 0
            blank_fact_sources = _scalar(
                connection,
                """SELECT COUNT(*) FROM normalized_financial_facts
                WHERE ticker=? AND (source_url IS NULL OR TRIM(source_url)='')""",
                (ticker,),
            ) if _table_exists(connection, "normalized_financial_facts") else 0
            demo_facts = _scalar(
                connection,
                "SELECT COUNT(*) FROM normalized_financial_facts WHERE ticker=? AND source_kind='mvp_fixture'",
                (ticker,),
            ) if _table_exists(connection, "normalized_financial_facts") else 0
            all_run_metrics = _scalar(
                connection, "SELECT COUNT(*) FROM calculated_metrics WHERE ticker=?", (ticker,)
            ) if _table_exists(connection, "calculated_metrics") else 0
            metrics = _scalar(
                connection,
                "SELECT COUNT(*) FROM calculated_metrics WHERE ticker=? AND run_id=?",
                (ticker, latest_run_id),
            ) if latest_run_id and _table_exists(connection, "calculated_metrics") else 0
            metric_keys = _scalar(
                connection,
                """SELECT COUNT(*) FROM (
                    SELECT run_id, analysis_type, period, metric_code
                    FROM calculated_metrics WHERE ticker=? AND run_id=?
                    GROUP BY run_id, analysis_type, period, metric_code
                )""",
                (ticker, latest_run_id),
            ) if latest_run_id and _table_exists(connection, "calculated_metrics") else 0
            rules = connection.execute(
                """SELECT severity, COUNT(*) AS count FROM rule_results
                WHERE ticker=? AND run_id=? GROUP BY severity""",
                (ticker, latest_run_id),
            ).fetchall() if latest_run_id and _table_exists(connection, "rule_results") else []
            rule_counts = {row["severity"]: row["count"] for row in rules}
            total_rules = sum(rule_counts.values())
            insufficient = rule_counts.get("insufficient_data", 0)

            findings: list[dict[str, str]] = []
            if run is None or run["status"] != "completed":
                findings.append({"severity": "critical", "check": "ingestion_status", "result": "failed"})
            if len(available_filings) < requested_years:
                findings.append({
                    "severity": "high",
                    "check": "historical_period_coverage",
                    "result": f"{len(available_filings)}/{requested_years}",
                })
            if facts != distinct_facts:
                findings.append({"severity": "critical", "check": "fact_key_uniqueness", "result": f"{facts-distinct_facts} duplicates"})
            if blank_fact_sources:
                findings.append({"severity": "high", "check": "fact_source_url", "result": f"{blank_fact_sources} blank"})
            if demo_facts:
                findings.append({"severity": "critical", "check": "official_source_only", "result": f"{demo_facts} demo facts"})
            if metrics != metric_keys:
                findings.append({"severity": "critical", "check": "metric_grain_uniqueness", "result": f"{metrics-metric_keys} duplicates"})
            if total_rules and insufficient / total_rules > 0.25:
                findings.append({
                    "severity": "high",
                    "check": "rule_data_coverage",
                    "result": f"{insufficient}/{total_rules} insufficient_data",
                })

            companies[ticker] = {
                "ingestion_status": run["status"] if run else "missing",
                "ingestion_error": run["error_message"] if run else "missing ingestion run",
                "records_written": run["records_written"] if run else 0,
                "filings": len(filings),
                "available_filings": len(available_filings),
                "periods": [row["period"] for row in filings],
                "facts": facts,
                "duplicate_fact_keys": facts - distinct_facts,
                "blank_fact_sources": blank_fact_sources,
                "demo_facts": demo_facts,
                "metrics": metrics,
                "all_run_metrics": all_run_metrics,
                "duplicate_metric_keys": metrics - metric_keys,
                "rule_severity_counts": rule_counts,
                "insufficient_rule_rate": round(insufficient / total_rules, 4) if total_rules else None,
                "findings": findings,
            }

        all_findings = [finding for company in companies.values() for finding in company["findings"]]
        severity_counts = dict(Counter(finding["severity"] for finding in all_findings))
        if company_count != distinct_company_count:
            severity_counts["critical"] = severity_counts.get("critical", 0) + 1
        if unclassified_count:
            severity_counts["medium"] = severity_counts.get("medium", 0) + 1

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "database": str(database),
            "grain": {
                "companies": "one row per TWSE ticker",
                "financial_filings": "one row per ticker and period",
                "normalized_financial_facts": "one row per deterministic fact_id",
                "calculated_metrics": "one row per run, analysis type, period, and metric",
            },
            "company_universe": {
                "rows": company_count,
                "distinct_tickers": distinct_company_count,
                "duplicate_tickers": company_count - distinct_company_count,
                "unclassified": unclassified_count,
                "subindustry_counts": subindustries,
            },
            "backfill": companies,
            "finding_severity_counts": severity_counts,
            "quality_gate": "pass" if not severity_counts.get("critical") else "fail",
        }
    finally:
        connection.close()


def markdown_report(report: dict[str, Any]) -> str:
    universe = report["company_universe"]
    lines = [
        "# Small-scale Historical Backfill Quality Report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "## Dataset and grain",
        "",
        f"- Company master: {universe['rows']} rows / {universe['distinct_tickers']} distinct tickers",
        f"- Unclassified companies: {universe['unclassified']}",
        "- Financial filings: one ticker-period per row",
        "- Facts: deterministic fact ID",
        "- Metrics: run + analysis type + period + metric code",
        "",
        "## Backfill results",
        "",
        "| Ticker | Status | Available periods | Facts | Metrics | Insufficient-rule rate | Findings |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for ticker, row in report["backfill"].items():
        rate = row["insufficient_rule_rate"]
        rendered_rate = "n/a" if rate is None else f"{rate:.1%}"
        lines.append(
            f"| {ticker} | {row['ingestion_status']} | {row['available_filings']} | "
            f"{row['facts']} | {row['metrics']} | {rendered_rate} | {len(row['findings'])} |"
        )
    lines.extend([
        "",
        "## Quality gate",
        "",
        f"**{report['quality_gate'].upper()}** — severity counts: "
        f"`{json.dumps(report['finding_severity_counts'], ensure_ascii=False)}`",
        "",
        "Checks cover completeness, key uniqueness, source validity, official/demo separation, "
        "period coverage, rule-data coverage, and ingestion traceability.",
    ])
    for ticker, row in report["backfill"].items():
        if not row["findings"]:
            continue
        lines.extend(["", f"### {ticker} findings", ""])
        for finding in row["findings"]:
            lines.append(
                f"- **{finding['severity']}** `{finding['check']}`: {finding['result']}"
            )
    lines.append("")
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> dict[str, Any]:
    args.tickers = list(validate_refresh_tickers(tuple(args.tickers)))
    os.environ["DATASTORE_BACKEND"] = "sqlite"
    os.environ["FINANCIAL_DATABASE_PATH"] = str(args.database)
    os.environ["FINANCIAL_FACT_DATABASE_PATH"] = str(args.database)
    os.environ["FINANCIAL_AI_AUTO_LLM_ENABLED"] = "false"
    os.environ["MOPS_XBRL_PARSER_MODE"] = "lightweight"

    args.database.parent.mkdir(parents=True, exist_ok=True)
    company_repository = build_company_master_repository()
    await TwseCompanyUniverseService(repository=company_repository).sync()

    pipeline = FinancialIngestionPipeline(
        ingestion_run_repository=build_ingestion_run_repository(),
    )
    batch_id = f"small-backfill-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    for ticker in args.tickers:
        await pipeline.refresh_company(
            ticker,
            years=args.years,
            end_year=args.end_year,
            trigger="manual",
            source_mode="official",
            batch_id=batch_id,
        )

    report = audit_database(args.database, args.tickers, args.years)
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.markdown_output.write_text(markdown_report(report), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a small official backfill and data-quality audit.")
    parser.add_argument("--database", type=Path, default=Path("data/backfill-small.sqlite3"))
    parser.add_argument("--tickers", nargs="+", default=["2330", "2454"])
    parser.add_argument("--years", type=int, default=5, choices=(3, 4, 5))
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--json-output", type=Path, default=Path("data/qa/backfill-quality.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("data/qa/backfill-quality.md"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = asyncio.run(run(args))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
