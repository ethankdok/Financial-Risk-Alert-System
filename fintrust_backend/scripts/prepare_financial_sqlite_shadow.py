"""Create a corrected shadow copy of a legacy financial SQLite database.

The source is opened read-only and is never modified. The output must not
already exist. Only latest facts and metrics for 2330/2454 are normalized;
missing company/ingestion metadata remains an audit blocker rather than being
invented by this tool.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

from app.services.analysis_repository import (
    BALANCE_FIELDS,
    INCOME_FIELDS,
    MONTHLY_FIELDS,
    SqliteAnalysisRepository,
    fact_document_id,
    shift_month_period,
    statement_type_for_metric,
)


ALLOWED_TICKERS = ("2330", "2454")


def _source_contract(snapshot: dict[str, Any]) -> dict[str, tuple[str, str]]:
    contract: dict[str, tuple[str, str]] = {}
    for source in snapshot.get("sources", []):
        url = str(source.get("source_url") or "")
        period = str(source.get("period") or "")
        if url.endswith("t187ap05_L"):
            contract["monthly_revenue"] = (url, period)
        elif url.endswith("t187ap06_L_ci"):
            contract["income_statement"] = (url, period)
        elif url.endswith("t187ap07_L_ci"):
            contract["balance_sheet"] = (url, period)
    return contract


def _fact_contract(metric_code: str, contract: dict[str, tuple[str, str]]) -> dict[str, str] | None:
    if metric_code in MONTHLY_FIELDS:
        source = contract.get("monthly_revenue")
        if source is None:
            return None
        source_url, current_period = source
        period = current_period
        if metric_code == "previous_month_revenue":
            period = shift_month_period(current_period, -1)
        elif metric_code == "prior_year_month_revenue":
            period = shift_month_period(current_period, -12)
        return {
            "metric_code": "monthly_revenue",
            "source_field": metric_code,
            "period": period,
            "source_url": source_url,
            "statement_type": "monthly_revenue",
        }
    if metric_code in BALANCE_FIELDS:
        statement_type = "balance_sheet"
    elif metric_code in INCOME_FIELDS:
        statement_type = "income_statement"
    else:
        statement_type = statement_type_for_metric(metric_code)
    source = contract.get(statement_type)
    if source is None:
        return None
    return {
        "metric_code": metric_code,
        "source_field": metric_code,
        "period": source[1],
        "source_url": source[0],
        "statement_type": statement_type,
    }


def prepare_shadow(source: Path, output: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite shadow database: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    read_only = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    destination = sqlite3.connect(output)
    try:
        read_only.backup(destination)
    finally:
        read_only.close()
        destination.close()

    SqliteAnalysisRepository(str(output))
    connection = sqlite3.connect(output)
    connection.row_factory = sqlite3.Row
    repaired_facts = 0
    repaired_metrics = 0
    skipped: list[dict[str, str]] = []
    try:
        for ticker in ALLOWED_TICKERS:
            snapshot_row = connection.execute(
                "SELECT snapshot_json FROM latest_analysis_snapshots WHERE ticker = ?", (ticker,)
            ).fetchone()
            if snapshot_row is None:
                skipped.append({"ticker": ticker, "reason": "latest_snapshot_missing"})
                continue
            contract = _source_contract(json.loads(snapshot_row["snapshot_json"]))
            rows = connection.execute(
                """SELECT * FROM normalized_financial_facts
                   WHERE ticker = ? AND analysis_type = 'latest'""",
                (ticker,),
            ).fetchall()
            for row in rows:
                normalized = _fact_contract(str(row["metric_code"]), contract)
                if normalized is None:
                    skipped.append({
                        "ticker": ticker,
                        "reason": f"source_contract_missing:{row['metric_code']}",
                    })
                    continue
                payload = dict(row)
                payload.update(normalized)
                payload.update({
                    "statement_scope": "unknown",
                    "filed_at": None,
                    "fact_key_version": "financial-fact-v2",
                })
                new_fact_id = fact_document_id(payload)
                collision = connection.execute(
                    "SELECT fact_id FROM normalized_financial_facts WHERE fact_id = ? AND fact_id <> ?",
                    (new_fact_id, row["fact_id"]),
                ).fetchone()
                if collision is not None:
                    raise RuntimeError(
                        f"Fact key collision for {ticker}/{normalized['metric_code']}/{normalized['period']}"
                    )
                connection.execute(
                    """UPDATE normalized_financial_facts
                       SET fact_id = ?, period = ?, metric_code = ?, source_url = ?,
                           statement_type = ?, statement_scope = 'unknown', filed_at = NULL,
                           source_field = ?, fact_key_version = 'financial-fact-v2'
                       WHERE fact_id = ?""",
                    (
                        new_fact_id,
                        normalized["period"],
                        normalized["metric_code"],
                        normalized["source_url"],
                        normalized["statement_type"],
                        normalized["source_field"],
                        row["fact_id"],
                    ),
                )
                repaired_facts += 1

            monthly_period = contract.get("monthly_revenue", (None, None))[1]
            if monthly_period:
                metric_rows = connection.execute(
                    """SELECT rowid, source_fields_json FROM calculated_metrics
                       WHERE ticker = ? AND analysis_type = 'latest'""",
                    (ticker,),
                ).fetchall()
                for metric in metric_rows:
                    source_fields = json.loads(metric["source_fields_json"])
                    if not set(source_fields) & MONTHLY_FIELDS:
                        continue
                    comparisons = []
                    if "previous_month_revenue" in source_fields:
                        comparisons.append(shift_month_period(monthly_period, -1))
                    if "prior_year_month_revenue" in source_fields:
                        comparisons.append(shift_month_period(monthly_period, -12))
                    connection.execute(
                        """UPDATE calculated_metrics
                           SET period = ?, comparison_periods_json = ? WHERE rowid = ?""",
                        (monthly_period, json.dumps(comparisons), metric["rowid"]),
                    )
                    repaired_metrics += 1
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        output.unlink(missing_ok=True)
        raise
    connection.close()
    return {
        "source": str(source),
        "output": str(output),
        "tickers": list(ALLOWED_TICKERS),
        "repaired_facts": repaired_facts,
        "repaired_metrics": repaired_metrics,
        "skipped": skipped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare_shadow(args.source, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
