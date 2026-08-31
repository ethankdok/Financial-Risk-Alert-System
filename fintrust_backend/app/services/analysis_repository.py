from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.financial_analysis_models import FinancialStatementAnalysisReport
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.models import FinancialFact
from app.pipeline_models import AnalysisRunSummary, FrontendAnalysisSnapshot, PersistenceCounts


HISTORICAL_FACT_FIELDS = [
    "revenue", "gross_profit", "operating_income", "net_income", "eps",
    "cash_and_cash_equivalents", "inventory", "current_assets", "total_assets",
    "current_liabilities", "total_liabilities", "equity", "operating_cash_flow",
    "investing_cash_flow", "capital_expenditure", "research_and_development_expense",
]

LATEST_FACT_FIELDS = [
    "revenue", "gross_profit", "operating_income", "net_income", "eps",
    "cash_and_cash_equivalents", "inventory", "current_assets", "total_assets",
    "current_liabilities", "total_liabilities", "equity", "monthly_revenue",
    "previous_month_revenue", "prior_year_month_revenue",
]

INCOME_FIELDS = {
    "revenue", "gross_profit", "operating_income", "net_income", "eps",
    "research_and_development_expense",
}
BALANCE_FIELDS = {
    "cash_and_cash_equivalents", "inventory", "current_assets", "total_assets",
    "current_liabilities", "total_liabilities", "equity",
}
CASH_FLOW_FIELDS = {"operating_cash_flow", "investing_cash_flow", "capital_expenditure"}
MONTHLY_FIELDS = {"monthly_revenue", "previous_month_revenue", "prior_year_month_revenue"}


class AnalysisRepository(Protocol):
    backend_name: str

    def save_pipeline_result(
        self,
        *,
        run_id: str,
        trigger: str,
        started_at: datetime,
        completed_at: datetime,
        latest_report: FinancialStatementAnalysisReport,
        historical_report: HistoricalFinancialAnalysisReport,
        snapshot: FrontendAnalysisSnapshot,
    ) -> PersistenceCounts: ...

    def get_latest_snapshot(self, ticker: str) -> FrontendAnalysisSnapshot | None: ...
    def list_metrics(
        self,
        ticker: str,
        limit: int = 200,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def list_runs(self, ticker: str, limit: int = 20) -> list[AnalysisRunSummary]: ...
    def get_fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None: ...


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def document_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def statement_type_for_metric(metric: str) -> str:
    if metric in INCOME_FIELDS:
        return "income_statement"
    if metric in BALANCE_FIELDS:
        return "balance_sheet"
    if metric in CASH_FLOW_FIELDS:
        return "cash_flow"
    if metric in MONTHLY_FIELDS:
        return "monthly_revenue"
    return "income_statement"


def historical_fact_rows(report: HistoricalFinancialAnalysisReport) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for period in report.periods:
        if period.status != "available":
            continue
        demo = "DEMO FIXTURE" in period.source_name.upper()
        for field in HISTORICAL_FACT_FIELDS:
            value = getattr(period, field)
            if value is None:
                continue
            rows.append({
                "ticker": report.ticker,
                "company_name": report.company_name,
                "subindustry": report.subindustry,
                "analysis_type": "historical",
                "period": period.period,
                "metric_code": field,
                "value": value,
                "unit": "元／股" if field == "eps" else period.currency_unit,
                "source_kind": "mvp_fixture" if demo else "mops_xbrl",
                "source_url": period.source_url,
                "taxonomy_concept": period.concept_matches.get(field),
            })
    return rows


def latest_fact_rows(report: FinancialStatementAnalysisReport) -> list[dict[str, Any]]:
    period = report.report_period or report.monthly_revenue_period or "latest"
    coverage = next(
        (item for item in report.statement.source_coverage if item.status == "available"),
        None,
    )
    source_url = coverage.source_url if coverage else "https://openapi.twse.com.tw/"
    demo = bool(coverage and "DEMO FIXTURE" in coverage.source_name.upper())
    rows: list[dict[str, Any]] = []
    for field in LATEST_FACT_FIELDS:
        value = getattr(report.statement, field)
        if value is None:
            continue
        rows.append({
            "ticker": report.ticker,
            "company_name": report.company_name,
            "subindustry": report.subindustry,
            "analysis_type": "latest",
            "period": period,
            "metric_code": field,
            "value": value,
            "unit": "元／股" if field == "eps" else report.statement.currency_unit,
            "source_kind": "mvp_fixture" if demo else "twse_openapi",
            "source_url": source_url,
            "taxonomy_concept": None,
        })
    return rows


def metric_rows(
    run_id: str,
    latest_report: FinancialStatementAnalysisReport,
    historical_report: HistoricalFinancialAnalysisReport,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    latest_period = latest_report.report_period or latest_report.monthly_revenue_period or "latest"
    for metric in latest_report.metrics:
        rows.append({
            "run_id": run_id, "ticker": latest_report.ticker, "analysis_type": "latest",
            "period": latest_period, "metric_code": metric.code, "label": metric.label,
            "category": metric.category, "value": metric.value, "unit": metric.unit,
            "formula": metric.formula, "source_fields": metric.source_fields,
        })
    for metric in historical_report.trend_metrics:
        for period, value in metric.period_values.items():
            rows.append({
                "run_id": run_id, "ticker": historical_report.ticker,
                "analysis_type": "historical", "period": period,
                "metric_code": metric.code, "label": metric.label,
                "category": metric.category, "value": value, "unit": metric.unit,
                "formula": metric.formula, "source_fields": metric.source_fields,
            })
    return rows


def rule_rows(
    run_id: str,
    latest_report: FinancialStatementAnalysisReport,
    historical_report: HistoricalFinancialAnalysisReport,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in latest_report.rule_results:
        rows.append({
            "run_id": run_id, "ticker": latest_report.ticker, "analysis_type": "latest",
            "rule_id": result.rule_id, "name": result.name, "category": result.category,
            "severity": result.severity.value, "triggered": result.triggered,
            "threshold_description": result.threshold_description,
            "explanation": result.explanation,
            "evidence_periods": [latest_report.report_period] if latest_report.report_period else [],
            "evidence_metrics": result.evidence_metrics,
            "rule_scope": "semiconductor_common", "logic_expression": None,
            "actual_values": {result.metric_code: result.actual_value},
        })
    for result in historical_report.rule_results:
        rows.append({
            "run_id": run_id, "ticker": historical_report.ticker,
            "analysis_type": "historical", "rule_id": result.rule_id,
            "name": result.name, "category": result.category,
            "severity": result.severity.value, "triggered": result.triggered,
            "threshold_description": result.threshold_description,
            "explanation": result.explanation,
            "evidence_periods": result.evidence_periods,
            "evidence_metrics": result.evidence_metrics,
            "rule_scope": getattr(result, "rule_scope", "semiconductor_common"),
            "logic_expression": getattr(result, "logic_expression", None),
            "actual_values": getattr(result, "actual_values", {}),
        })
    return rows


def financial_fact_from_row(row: dict[str, Any]) -> FinancialFact:
    source_kind = str(row["source_kind"])
    analysis_type = str(row["analysis_type"])
    return FinancialFact(
        ticker=str(row["ticker"]),
        company_name=str(row["company_name"]),
        semiconductor_subindustry=str(row["subindustry"]),
        metric=str(row["metric_code"]),
        period=str(row["period"]),
        value=float(row["value"]),
        unit=str(row["unit"]),
        statement_type=statement_type_for_metric(str(row["metric_code"])),
        source_kind=source_kind,
        source_url=str(row["source_url"]),
        filed_at=row["retrieved_at"],
        taxonomy_concept=row.get("taxonomy_concept"),
        statement_scope="consolidated" if analysis_type == "historical" else "unknown",
        is_demo=source_kind == "mvp_fixture",
    )


class SqliteAnalysisRepository:
    backend_name = "sqlite"

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
            CREATE TABLE IF NOT EXISTS financial_filings (
                ticker TEXT NOT NULL, period TEXT NOT NULL, company_name TEXT NOT NULL,
                subindustry TEXT NOT NULL, fiscal_year INTEGER, quarter INTEGER,
                source_name TEXT NOT NULL, source_url TEXT NOT NULL, status TEXT NOT NULL,
                concept_matches_json TEXT NOT NULL, warnings_json TEXT NOT NULL,
                retrieved_at TEXT NOT NULL, PRIMARY KEY (ticker, period)
            );
            CREATE TABLE IF NOT EXISTS normalized_financial_facts (
                fact_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, company_name TEXT NOT NULL,
                subindustry TEXT NOT NULL, analysis_type TEXT NOT NULL, period TEXT NOT NULL,
                metric_code TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL,
                source_kind TEXT NOT NULL, source_url TEXT NOT NULL,
                taxonomy_concept TEXT, retrieved_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS analysis_runs (
                run_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, company_name TEXT NOT NULL,
                subindustry TEXT NOT NULL, analysis_type TEXT NOT NULL, trigger TEXT NOT NULL,
                status TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
                rule_version TEXT, overall_severity TEXT, summary TEXT, error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS calculated_metrics (
                run_id TEXT NOT NULL, ticker TEXT NOT NULL, analysis_type TEXT NOT NULL,
                period TEXT NOT NULL, metric_code TEXT NOT NULL, label TEXT NOT NULL,
                category TEXT NOT NULL, value REAL NOT NULL, unit TEXT NOT NULL,
                formula TEXT NOT NULL, source_fields_json TEXT NOT NULL,
                PRIMARY KEY (run_id, analysis_type, period, metric_code)
            );
            CREATE TABLE IF NOT EXISTS rule_results (
                run_id TEXT NOT NULL, ticker TEXT NOT NULL, analysis_type TEXT NOT NULL,
                rule_id TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
                severity TEXT NOT NULL, triggered INTEGER NOT NULL,
                threshold_description TEXT NOT NULL, explanation TEXT NOT NULL,
                evidence_periods_json TEXT NOT NULL, evidence_metrics_json TEXT NOT NULL,
                rule_scope TEXT NOT NULL, logic_expression TEXT,
                actual_values_json TEXT NOT NULL,
                PRIMARY KEY (run_id, analysis_type, rule_id)
            );
            CREATE TABLE IF NOT EXISTS latest_analysis_snapshots (
                ticker TEXT PRIMARY KEY, run_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """)

    def save_pipeline_result(
        self,
        *,
        run_id: str,
        trigger: str,
        started_at: datetime,
        completed_at: datetime,
        latest_report: FinancialStatementAnalysisReport,
        historical_report: HistoricalFinancialAnalysisReport,
        snapshot: FrontendAnalysisSnapshot,
    ) -> PersistenceCounts:
        facts = latest_fact_rows(latest_report) + historical_fact_rows(historical_report)
        metrics = metric_rows(run_id, latest_report, historical_report)
        rules = rule_rows(run_id, latest_report, historical_report)
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO analysis_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, historical_report.ticker, historical_report.company_name,
                 historical_report.subindustry, "combined", trigger, "completed",
                 started_at.isoformat(), completed_at.isoformat(), historical_report.rule_version,
                 snapshot.overall_severity.value, snapshot.summary, None),
            )
            for period in historical_report.periods:
                connection.execute(
                    """INSERT INTO financial_filings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, period) DO UPDATE SET source_url=excluded.source_url,
                    status=excluded.status, concept_matches_json=excluded.concept_matches_json,
                    warnings_json=excluded.warnings_json, retrieved_at=excluded.retrieved_at""",
                    (historical_report.ticker, period.period, historical_report.company_name,
                     historical_report.subindustry, period.fiscal_year, period.quarter,
                     period.source_name, period.source_url, period.status,
                     to_json(period.concept_matches), to_json(period.warnings),
                     completed_at.isoformat()),
                )
            for fact in facts:
                fact_id = document_id(fact["ticker"], fact["analysis_type"], fact["period"], fact["metric_code"])
                connection.execute(
                    "INSERT OR REPLACE INTO normalized_financial_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (fact_id, fact["ticker"], fact["company_name"], fact["subindustry"],
                     fact["analysis_type"], fact["period"], fact["metric_code"], fact["value"],
                     fact["unit"], fact["source_kind"], fact["source_url"],
                     fact["taxonomy_concept"], completed_at.isoformat()),
                )
            for metric in metrics:
                connection.execute(
                    "INSERT OR REPLACE INTO calculated_metrics VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (metric["run_id"], metric["ticker"], metric["analysis_type"], metric["period"],
                     metric["metric_code"], metric["label"], metric["category"], metric["value"],
                     metric["unit"], metric["formula"], to_json(metric["source_fields"])),
                )
            for rule in rules:
                connection.execute(
                    "INSERT OR REPLACE INTO rule_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (rule["run_id"], rule["ticker"], rule["analysis_type"], rule["rule_id"],
                     rule["name"], rule["category"], rule["severity"], int(rule["triggered"]),
                     rule["threshold_description"], rule["explanation"],
                     to_json(rule["evidence_periods"]), to_json(rule["evidence_metrics"]),
                     rule["rule_scope"], rule["logic_expression"], to_json(rule["actual_values"])),
                )
            connection.execute(
                "INSERT OR REPLACE INTO latest_analysis_snapshots VALUES (?, ?, ?, ?)",
                (snapshot.ticker, run_id, to_json(snapshot.model_dump(mode="json")), completed_at.isoformat()),
            )
        return PersistenceCounts(
            filings=len(historical_report.periods), facts=len(facts), metrics=len(metrics),
            rule_results=len(rules), snapshots=1,
        )

    def get_latest_snapshot(self, ticker: str) -> FrontendAnalysisSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT snapshot_json FROM latest_analysis_snapshots WHERE ticker = ?", (ticker,)
            ).fetchone()
        return FrontendAnalysisSnapshot.model_validate_json(row["snapshot_json"]) if row else None

    def list_metrics(
        self,
        ticker: str,
        limit: int = 200,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            if run_id:
                rows = connection.execute(
                    """SELECT * FROM calculated_metrics
                    WHERE ticker = ? AND run_id = ?
                    ORDER BY analysis_type, period, metric_code LIMIT ?""",
                    (ticker, run_id, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM calculated_metrics WHERE ticker = ? ORDER BY rowid DESC LIMIT ?",
                    (ticker, limit),
                ).fetchall()
        return [dict(row) for row in rows]

    def list_runs(self, ticker: str, limit: int = 20) -> list[AnalysisRunSummary]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM analysis_runs WHERE ticker = ? ORDER BY started_at DESC LIMIT ?",
                (ticker, limit),
            ).fetchall()
        return [AnalysisRunSummary.model_validate(dict(row)) for row in rows]

    def get_fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM normalized_financial_facts
                WHERE ticker = ? AND metric_code = ? AND period = ?
                ORDER BY CASE analysis_type WHEN 'historical' THEN 0 ELSE 1 END,
                         retrieved_at DESC
                LIMIT 1""",
                (ticker, metric, period),
            ).fetchone()
        return financial_fact_from_row(dict(row)) if row else None


def build_analysis_repository() -> AnalysisRepository:
    backend = os.getenv("DATASTORE_BACKEND", "sqlite").strip().lower()
    if backend == "firestore":
        from app.services.firestore_analysis_repository import FirestoreAnalysisRepository
        return FirestoreAnalysisRepository(os.getenv("GOOGLE_CLOUD_PROJECT") or None)
    if backend != "sqlite":
        raise ValueError(f"Unsupported DATASTORE_BACKEND: {backend}")
    path = os.getenv("FINANCIAL_DATABASE_PATH", "./data/financial_pipeline.sqlite3")
    return SqliteAnalysisRepository(path)
