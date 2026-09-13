from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


TABLES = [
    "financial_filings",
    "normalized_financial_facts",
    "calculated_metrics",
    "analysis_runs",
    "rule_results",
    "latest_analysis_snapshots",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect FinTrust demo SQLite persistence.")
    parser.add_argument(
        "--database",
        default="data/financial_pipeline.sqlite3",
        help="SQLite database path relative to backend/ unless absolute.",
    )
    parser.add_argument("--ticker", default="2330")
    args = parser.parse_args()

    database = Path(args.database)
    if not database.is_absolute():
        database = Path(__file__).resolve().parents[1] / database
    if not database.exists():
        raise SystemExit(f"Database does not exist: {database}")

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row

    print(f"Database: {database}")
    print("=" * 72)
    for table in TABLES:
        count = connection.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
        print(f"{table:32s} {count:>8} records")

    print("=" * 72)
    print(f"Recent analysis runs for ticker {args.ticker}")
    runs = connection.execute(
        """
        SELECT run_id, ticker, subindustry, trigger, status,
               overall_severity, started_at, completed_at
        FROM analysis_runs
        WHERE ticker = ?
        ORDER BY started_at DESC
        LIMIT 5
        """,
        (args.ticker,),
    ).fetchall()
    if not runs:
        print("No runs found.")
    for row in runs:
        print(dict(row))

    snapshot_row = connection.execute(
        "SELECT snapshot_json FROM latest_analysis_snapshots WHERE ticker = ?",
        (args.ticker,),
    ).fetchone()
    if snapshot_row:
        snapshot = json.loads(snapshot_row["snapshot_json"])
        print("=" * 72)
        print("Latest snapshot summary")
        print(
            json.dumps(
                {
                    "analysis_run_id": snapshot.get("analysis_run_id"),
                    "ticker": snapshot.get("ticker"),
                    "company_name": snapshot.get("company_name"),
                    "subindustry": snapshot.get("subindustry"),
                    "overall_severity": snapshot.get("overall_severity"),
                    "rule_version": snapshot.get("rule_version"),
                    "key_metric_count": len(snapshot.get("key_metrics", [])),
                    "rule_card_count": len(snapshot.get("rule_cards", [])),
                    "limitations": snapshot.get("limitations", [])[:2],
                },
                ensure_ascii=False,
                indent=2,
            )
        )

    connection.close()


if __name__ == "__main__":
    main()
