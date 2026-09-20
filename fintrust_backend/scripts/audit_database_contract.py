"""Read-only, offline schema/semantic audit. Does not initialize repositories."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path


def audit(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        profile = {}
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = [dict(r) for r in connection.execute(f"PRAGMA table_info({quoted})")]
            profile[table] = {
                "rows": connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0],
                "columns": columns,
            }
        required = {"companies", "normalized_financial_facts", "financial_filings", "ingestion_runs",
                    "calculated_metrics", "analysis_runs", "latest_analysis_snapshots"}
        missing = sorted(required - set(tables))
        findings = []
        if missing:
            findings.append({"code": "missing_tables", "severity": "high", "tables": missing})
        if missing:
            return {"database": str(path), "profile": profile, "findings": findings, "gate": "BLOCKED"}

        def count(sql):
            return connection.execute(sql).fetchone()[0]

        facts = [dict(r) for r in connection.execute("SELECT * FROM normalized_financial_facts")]
        if not facts:
            findings.append({"code": "no_financial_facts", "severity": "high", "count": 0})
        monthly = {"monthly_revenue", "previous_month_revenue", "prior_year_month_revenue"}
        balance = {"cash_and_cash_equivalents", "inventory", "current_assets", "total_assets",
                   "current_liabilities", "total_liabilities", "equity"}
        bad_period = [r for r in facts if r["metric_code"] in monthly
                      and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", r["period"])]
        bad_source = []
        for row in facts:
            if row["source_kind"] != "twse_openapi":
                continue
            expected = ("t187ap05_L" if row["metric_code"] in monthly else
                        "t187ap07_L_ci" if row["metric_code"] in balance else "t187ap06_L_ci")
            if not row["source_url"].rstrip("/").endswith("/" + expected):
                bad_source.append(row)
        for code, rows in [("monthly_period_mismatch", bad_period), ("source_dataset_mismatch", bad_source)]:
            if rows:
                findings.append({"code": code, "severity": "high", "count": len(rows),
                                 "fact_ids": [r["fact_id"] for r in rows]})
        checks = {
            "sqlite_integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
            "fact_count": len(facts),
            "monthly_fact_count": sum(r["metric_code"] in monthly for r in facts),
            "blank_source_count": sum(not str(r["source_url"] or "").strip() for r in facts),
            "demo_fact_count": sum(r["source_kind"] == "mvp_fixture" for r in facts),
            "duplicate_fact_keys": count("SELECT COUNT(*) FROM (SELECT ticker,analysis_type,period,metric_code FROM normalized_financial_facts GROUP BY 1,2,3,4 HAVING COUNT(*)>1)"),
            "orphan_company_facts": count("SELECT COUNT(*) FROM normalized_financial_facts f LEFT JOIN companies c ON f.ticker=c.ticker WHERE c.ticker IS NULL"),
            "orphan_metric_runs": count("SELECT COUNT(*) FROM calculated_metrics m LEFT JOIN analysis_runs r ON m.run_id=r.run_id WHERE r.run_id IS NULL"),
            "orphan_snapshot_runs": count("SELECT COUNT(*) FROM latest_analysis_snapshots s LEFT JOIN analysis_runs r ON s.run_id=r.run_id WHERE r.run_id IS NULL"),
        }
        for key, value in checks.items():
            if key in {"blank_source_count", "demo_fact_count", "duplicate_fact_keys", "orphan_company_facts", "orphan_metric_runs", "orphan_snapshot_runs"} and value:
                findings.append({"code": key, "severity": "high", "count": value})
        if checks["sqlite_integrity"] != "ok":
            findings.append({"code": "sqlite_integrity", "severity": "critical"})
        return {
            "database": str(path), "scope": "local SQLite only; no live source reconciliation",
            "profile": profile, "checks": checks,
            "classification": [dict(r) for r in connection.execute("SELECT subindustry_confidence,COUNT(*) AS count FROM companies GROUP BY 1")],
            "fact_periods": [dict(r) for r in connection.execute("SELECT ticker,analysis_type,period,COUNT(*) AS count FROM normalized_financial_facts GROUP BY 1,2,3")],
            "findings": findings, "gate": "BLOCKED" if findings else "PASS",
        }
    finally:
        connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    result = audit(args.database)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2 if result["gate"] == "BLOCKED" else 0)
