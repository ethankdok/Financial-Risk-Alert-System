from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any, Protocol

from app.financial_analysis_models import FinancialStatementAnalysisReport
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.models import FinancialFact
from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord
from app.pipeline_models import AnalysisRunSummary, FrontendAnalysisSnapshot, PersistenceCounts
from app.services.official_event_sources import (
    investor_conference_identity,
    is_persistable_investor_conference,
    is_persistable_material_event,
    material_event_identity,
)
from app.text_intelligence_models import NarrativeShiftResponse, TextMiningAnalysisResponse


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
FACT_KEY_VERSION = "financial-fact-v2"


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
    def save_official_events(
        self,
        *,
        ticker: str,
        investor_conferences: list[InvestorConferenceRecord],
        material_events: list[MaterialEventRecord],
        refreshed_at: datetime,
    ) -> dict[str, int]: ...
    def list_investor_conferences(self, ticker: str, limit: int = 20) -> list[InvestorConferenceRecord]: ...
    def list_material_events(self, ticker: str, limit: int = 50) -> list[MaterialEventRecord]: ...
    def list_metrics(
        self,
        ticker: str,
        limit: int = 200,
        run_id: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def list_facts(
        self,
        ticker: str,
        limit: int = 500,
        run_id: str | None = None,
        period: str | None = None,
        statement_type: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]: ...
    def list_rule_results(
        self,
        ticker: str,
        limit: int = 500,
        run_id: str | None = None,
        triggered: bool | None = None,
    ) -> list[dict[str, Any]]: ...
    def list_runs(self, ticker: str, limit: int = 20) -> list[AnalysisRunSummary]: ...
    def get_fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None: ...
    def save_text_intelligence_result(
        self,
        *,
        ticker: str,
        run_id: str,
        analysis: TextMiningAnalysisResponse,
        narrative_shift: NarrativeShiftResponse | None = None,
    ) -> dict[str, int]: ...
    def get_latest_text_intelligence_result(self, ticker: str) -> dict[str, Any] | None: ...
    def ingest_facts(self, facts: list[FinancialFact]) -> int: ...


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def document_id(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def fact_document_id(row: dict[str, Any]) -> str:
    metric_code = str(row.get("metric_code") or row.get("metric"))
    identity = [
        FACT_KEY_VERSION,
        "demo" if bool(row.get("is_demo")) or row.get("source_kind") == "mvp_fixture" else "official",
        str(row["ticker"]),
        metric_code,
        str(row["period"]),
        str(row.get("statement_scope") or "unknown"),
        str(row.get("statement_type") or statement_type_for_metric(metric_code)),
        str(row.get("unit") or ""),
        str(row.get("source_kind") or ""),
        str(row.get("source_url") or ""),
    ]
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def legacy_fact_document_ids(row: dict[str, Any]) -> list[str]:
    metric_code = _fact_metric_code(row)
    ids = {
        document_id(row["ticker"], row.get("analysis_type"), row["period"], metric_code),
        document_id(
            row["ticker"],
            row.get("analysis_type"),
            row["period"],
            metric_code,
            row.get("statement_scope") or "unknown",
        ),
    }
    ids.discard(fact_document_id(row))
    return sorted(ids)


def _fact_metric_code(row: dict[str, Any]) -> str:
    return str(row.get("metric_code") or row.get("metric") or "")


def _fact_core_key(row: dict[str, Any]) -> tuple[str, ...]:
    source_kind = str(row.get("source_kind") or "")
    return (
        "demo" if bool(row.get("is_demo")) or source_kind == "mvp_fixture" else "official",
        str(row.get("ticker") or ""),
        _fact_metric_code(row),
        str(row.get("period") or ""),
        str(row.get("unit") or ""),
        source_kind,
        str(row.get("source_url") or ""),
    )


def _fact_dimension(row: dict[str, Any], name: str) -> str | None:
    value = row.get(name)
    if value not in (None, ""):
        return str(value)
    if name == "statement_type" and row.get("fact_key_version") == FACT_KEY_VERSION:
        return statement_type_for_metric(_fact_metric_code(row))
    return None


def _facts_are_compatible(legacy: dict[str, Any], versioned: dict[str, Any]) -> bool:
    legacy_document_id = legacy.get("_document_id")
    if legacy_document_id and legacy_document_id in legacy_fact_document_ids(versioned):
        return True
    if _fact_core_key(legacy) != _fact_core_key(versioned):
        return False
    for dimension in ("statement_scope", "statement_type"):
        legacy_value = _fact_dimension(legacy, dimension)
        versioned_value = _fact_dimension(versioned, dimension)
        if legacy_value is not None and legacy_value != versioned_value:
            return False
    return True


def _fact_timestamp(row: dict[str, Any]) -> float:
    value = row.get("filed_at") or row.get("retrieved_at")
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    else:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _fact_preference_key(row: dict[str, Any]) -> tuple[int, int, int, float, str]:
    stable = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return (
        1 if row.get("fact_key_version") == FACT_KEY_VERSION else 0,
        1 if row.get("statement_scope") == "consolidated" else 0,
        1 if row.get("analysis_type") == "historical" else 0,
        _fact_timestamp(row),
        stable,
    )


def deduplicate_financial_fact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prefer v2 facts while retaining unmatched legacy facts and valid v2 variants."""
    versioned: dict[tuple[str, ...], dict[str, Any]] = {}
    legacy: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        core = _fact_core_key(row)
        if row.get("fact_key_version") == FACT_KEY_VERSION:
            key = core + (
                _fact_dimension(row, "statement_scope") or "",
                _fact_dimension(row, "statement_type") or "",
            )
            previous = versioned.get(key)
            if previous is None or _fact_preference_key(row) > _fact_preference_key(previous):
                versioned[key] = row
        else:
            key = core + (
                _fact_dimension(row, "statement_scope") or "",
                _fact_dimension(row, "statement_type") or "",
            )
            previous = legacy.get(key)
            if previous is None or _fact_preference_key(row) > _fact_preference_key(previous):
                legacy[key] = row

    selected = list(versioned.values())
    for row in legacy.values():
        if not any(_facts_are_compatible(row, candidate) for candidate in versioned.values()):
            selected.append(row)
    return sorted(selected, key=_fact_preference_key, reverse=True)


def preferred_financial_fact_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    selected = deduplicate_financial_fact_rows(rows)
    return selected[0] if selected else None


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
                "statement_type": statement_type_for_metric(field),
                "statement_scope": "unknown",
                "source_field": field,
                "filed_at": None,
            })
    return rows


def shift_month_period(period: str, months: int) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2})", period)
    if match is None:
        raise ValueError(f"Expected monthly period YYYY-MM, got: {period}")
    year = int(match.group(1))
    month = int(match.group(2))
    offset = year * 12 + month - 1 + months
    return f"{offset // 12:04d}-{offset % 12 + 1:02d}"


def _latest_fact_identity(field: str, report: FinancialStatementAnalysisReport) -> tuple[str, str] | None:
    if field == "monthly_revenue":
        return ("monthly_revenue", report.monthly_revenue_period) if report.monthly_revenue_period else None
    if field == "previous_month_revenue":
        return (
            "monthly_revenue",
            shift_month_period(report.monthly_revenue_period, -1),
        ) if report.monthly_revenue_period else None
    if field == "prior_year_month_revenue":
        return (
            "monthly_revenue",
            shift_month_period(report.monthly_revenue_period, -12),
        ) if report.monthly_revenue_period else None
    return (field, report.report_period) if report.report_period else None


def latest_fact_rows(report: FinancialStatementAnalysisReport) -> list[dict[str, Any]]:
    source_by_field = {
        field: coverage
        for coverage in report.statement.source_coverage
        if coverage.status == "available"
        for field in coverage.fields_found
    }
    rows: list[dict[str, Any]] = []
    for field in LATEST_FACT_FIELDS:
        value = getattr(report.statement, field)
        if value is None:
            continue
        coverage = source_by_field.get(field)
        identity = _latest_fact_identity(field, report)
        if coverage is None or identity is None:
            # Never borrow another statement's source or invent a period.
            continue
        metric_code, period = identity
        demo = "DEMO FIXTURE" in coverage.source_name.upper()
        rows.append({
            "ticker": report.ticker,
            "company_name": report.company_name,
            "subindustry": report.subindustry,
            "analysis_type": "latest",
            "period": period,
            "metric_code": metric_code,
            "value": value,
            "unit": "元／股" if field == "eps" else report.statement.currency_unit,
            "source_kind": "mvp_fixture" if demo else "twse_openapi",
            "source_url": coverage.source_url,
            "taxonomy_concept": None,
            "statement_type": statement_type_for_metric(metric_code),
            "statement_scope": "unknown",
            "source_field": field,
            "filed_at": None,
        })
    return rows


def metric_rows(
    run_id: str,
    latest_report: FinancialStatementAnalysisReport,
    historical_report: HistoricalFinancialAnalysisReport,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric in latest_report.metrics:
        is_monthly = bool(set(metric.source_fields) & MONTHLY_FIELDS)
        period = latest_report.monthly_revenue_period if is_monthly else latest_report.report_period
        if period is None:
            continue
        comparison_periods: list[str] = []
        if is_monthly:
            if "previous_month_revenue" in metric.source_fields:
                comparison_periods.append(shift_month_period(period, -1))
            if "prior_year_month_revenue" in metric.source_fields:
                comparison_periods.append(shift_month_period(period, -12))
        rows.append({
            "run_id": run_id, "ticker": latest_report.ticker, "analysis_type": "latest",
            "period": period, "metric_code": metric.code, "label": metric.label,
            "category": metric.category, "value": metric.value, "unit": metric.unit,
            "formula": metric.formula, "source_fields": metric.source_fields,
            "comparison_periods": comparison_periods,
        })
    for metric in historical_report.trend_metrics:
        for period, value in metric.period_values.items():
            rows.append({
                "run_id": run_id, "ticker": historical_report.ticker,
                "analysis_type": "historical", "period": period,
                "metric_code": metric.code, "label": metric.label,
                "category": metric.category, "value": value, "unit": metric.unit,
                "formula": metric.formula, "source_fields": metric.source_fields,
                "comparison_periods": [],
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
        statement_type=str(row.get("statement_type") or statement_type_for_metric(str(row["metric_code"]))),
        source_kind=source_kind,
        source_url=str(row["source_url"]),
        filed_at=row.get("filed_at"),
        taxonomy_concept=row.get("taxonomy_concept"),
        statement_scope=str(row.get("statement_scope") or ("consolidated" if analysis_type == "historical" else "unknown")),
        is_demo=bool(row.get("is_demo", source_kind == "mvp_fixture")),
    )


class SqliteAnalysisRepository:
    backend_name = "sqlite"

    def __init__(self, database_path: str) -> None:
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

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
                taxonomy_concept TEXT, retrieved_at TEXT NOT NULL,
                statement_type TEXT NOT NULL DEFAULT 'income_statement',
                statement_scope TEXT NOT NULL DEFAULT 'unknown',
                filed_at TEXT,
                is_demo INTEGER NOT NULL DEFAULT 0,
                source_field TEXT,
                fact_key_version TEXT NOT NULL DEFAULT 'legacy'
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
                comparison_periods_json TEXT NOT NULL DEFAULT '[]',
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
            CREATE TABLE IF NOT EXISTS analysis_snapshots (
                run_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS official_events (
                event_type TEXT NOT NULL,
                event_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                company_name TEXT NOT NULL,
                event_date TEXT,
                event_time TEXT,
                title TEXT NOT NULL,
                source_url TEXT NOT NULL,
                detail_url TEXT,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                retrieved_at TEXT NOT NULL,
                PRIMARY KEY (event_type, event_id)
            );
            CREATE INDEX IF NOT EXISTS idx_official_events_ticker_type
                ON official_events (ticker, event_type, event_date DESC, retrieved_at DESC);
            CREATE TABLE IF NOT EXISTS text_model_runs (
                run_id TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                model_summary_json TEXT NOT NULL,
                semantic_analysis_json TEXT NOT NULL,
                narrative_shift_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS text_evidence (
                evidence_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                document_id TEXT NOT NULL,
                sentence_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_url TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_text_evidence_ticker_run
                ON text_evidence (ticker, run_id);
            """)
            columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(normalized_financial_facts)"
                ).fetchall()
            }
            migrations = {
                "statement_type": "ALTER TABLE normalized_financial_facts ADD COLUMN statement_type TEXT NOT NULL DEFAULT 'income_statement'",
                "statement_scope": "ALTER TABLE normalized_financial_facts ADD COLUMN statement_scope TEXT NOT NULL DEFAULT 'unknown'",
                "filed_at": "ALTER TABLE normalized_financial_facts ADD COLUMN filed_at TEXT",
                "is_demo": "ALTER TABLE normalized_financial_facts ADD COLUMN is_demo INTEGER NOT NULL DEFAULT 0",
                "source_field": "ALTER TABLE normalized_financial_facts ADD COLUMN source_field TEXT",
                "fact_key_version": "ALTER TABLE normalized_financial_facts ADD COLUMN fact_key_version TEXT NOT NULL DEFAULT 'legacy'",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    connection.execute(statement)
            metric_columns = {
                row["name"] for row in connection.execute(
                    "PRAGMA table_info(calculated_metrics)"
                ).fetchall()
            }
            if "comparison_periods_json" not in metric_columns:
                connection.execute(
                    "ALTER TABLE calculated_metrics ADD COLUMN comparison_periods_json TEXT NOT NULL DEFAULT '[]'"
                )

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
                fact["fact_key_version"] = FACT_KEY_VERSION
                fact_id = fact_document_id(fact)
                connection.execute(
                    """INSERT OR REPLACE INTO normalized_financial_facts (
                        fact_id, ticker, company_name, subindustry, analysis_type, period,
                        metric_code, value, unit, source_kind, source_url,
                        taxonomy_concept, retrieved_at, statement_type, statement_scope,
                        filed_at, is_demo, source_field, fact_key_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (fact_id, fact["ticker"], fact["company_name"], fact["subindustry"],
                     fact["analysis_type"], fact["period"], fact["metric_code"], fact["value"],
                     fact["unit"], fact["source_kind"], fact["source_url"],
                     fact["taxonomy_concept"], completed_at.isoformat(),
                      fact.get("statement_type", statement_type_for_metric(fact["metric_code"])),
                      fact.get("statement_scope", "unknown"), fact.get("filed_at"),
                      int(fact.get("source_kind") == "mvp_fixture"), fact.get("source_field"),
                      FACT_KEY_VERSION),
                )
            for metric in metrics:
                connection.execute(
                    """INSERT OR REPLACE INTO calculated_metrics (
                        run_id, ticker, analysis_type, period, metric_code, label,
                        category, value, unit, formula, source_fields_json,
                        comparison_periods_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (metric["run_id"], metric["ticker"], metric["analysis_type"], metric["period"],
                     metric["metric_code"], metric["label"], metric["category"], metric["value"],
                     metric["unit"], metric["formula"], to_json(metric["source_fields"]),
                     to_json(metric.get("comparison_periods", []))),
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
            connection.execute(
                "INSERT OR REPLACE INTO analysis_snapshots VALUES (?, ?, ?, ?)",
                (run_id, snapshot.ticker, to_json(snapshot.model_dump(mode="json")), completed_at.isoformat()),
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

    def save_official_events(
        self,
        *,
        ticker: str,
        investor_conferences: list[InvestorConferenceRecord],
        material_events: list[MaterialEventRecord],
        refreshed_at: datetime,
    ) -> dict[str, int]:
        conference_count = 0
        material_count = 0
        with self._connect() as connection:
            for record in investor_conferences:
                if not is_persistable_investor_conference(record):
                    continue
                event_id = investor_conference_identity(record)
                payload = record.model_copy(update={"event_id": event_id, "retrieved_at": record.retrieved_at or refreshed_at})
                connection.execute(
                    """INSERT INTO official_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_type, event_id) DO UPDATE SET
                        ticker=excluded.ticker,
                        company_name=excluded.company_name,
                        event_date=excluded.event_date,
                        event_time=excluded.event_time,
                        title=excluded.title,
                        source_url=excluded.source_url,
                        detail_url=excluded.detail_url,
                        status=excluded.status,
                        payload_json=excluded.payload_json,
                        retrieved_at=excluded.retrieved_at""",
                    (
                        "investor_conference",
                        event_id,
                        ticker,
                        payload.company_name,
                        payload.conference_date,
                        None,
                        payload.title,
                        payload.source_url,
                        payload.document_url,
                        payload.status,
                        to_json(payload.model_dump(mode="json")),
                        refreshed_at.isoformat(),
                    ),
                )
                conference_count += 1
            for record in material_events:
                if not is_persistable_material_event(record):
                    continue
                event_id = material_event_identity(record)
                payload = record.model_copy(update={"event_id": event_id, "retrieved_at": record.retrieved_at or refreshed_at})
                connection.execute(
                    """INSERT INTO official_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_type, event_id) DO UPDATE SET
                        ticker=excluded.ticker,
                        company_name=excluded.company_name,
                        event_date=excluded.event_date,
                        event_time=excluded.event_time,
                        title=excluded.title,
                        source_url=excluded.source_url,
                        detail_url=excluded.detail_url,
                        status=excluded.status,
                        payload_json=excluded.payload_json,
                        retrieved_at=excluded.retrieved_at""",
                    (
                        "material_event",
                        event_id,
                        ticker,
                        payload.company_name,
                        payload.event_date,
                        payload.event_time,
                        payload.title,
                        payload.source_url,
                        payload.detail_url,
                        payload.status,
                        to_json(payload.model_dump(mode="json")),
                        refreshed_at.isoformat(),
                    ),
                )
                material_count += 1
        return {"investor_conferences": conference_count, "material_events": material_count}

    def list_investor_conferences(self, ticker: str, limit: int = 20) -> list[InvestorConferenceRecord]:
        read_limit = max(limit * 5, limit)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM official_events
                WHERE ticker = ? AND event_type = 'investor_conference'
                ORDER BY COALESCE(event_date, '') DESC, retrieved_at DESC
                LIMIT ?""",
                (ticker, read_limit),
            ).fetchall()
        records = [InvestorConferenceRecord.model_validate_json(row["payload_json"]) for row in rows]
        return [record for record in records if is_persistable_investor_conference(record)][:limit]

    def list_material_events(self, ticker: str, limit: int = 50) -> list[MaterialEventRecord]:
        read_limit = max(limit * 5, limit)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT payload_json FROM official_events
                WHERE ticker = ? AND event_type = 'material_event'
                ORDER BY COALESCE(event_date, '') DESC, COALESCE(event_time, '') DESC, retrieved_at DESC
                LIMIT ?""",
                (ticker, read_limit),
            ).fetchall()
        records = [MaterialEventRecord.model_validate_json(row["payload_json"]) for row in rows]
        return [record for record in records if is_persistable_material_event(record)][:limit]

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
        payloads = []
        for row in rows:
            payload = dict(row)
            payload["source_fields"] = json.loads(payload.pop("source_fields_json"))
            payload["comparison_periods"] = json.loads(
                payload.pop("comparison_periods_json", "[]")
            )
            payloads.append(payload)
        return payloads

    def list_facts(
        self,
        ticker: str,
        limit: int = 500,
        run_id: str | None = None,
        period: str | None = None,
        statement_type: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM normalized_financial_facts WHERE ticker = ?"
        params: list[Any] = [ticker]
        if period:
            query += " AND period = ?"
            params.append(period)
        if search:
            query += " AND (metric_code LIKE ? OR taxonomy_concept LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY retrieved_at DESC, period DESC, metric_code LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = [dict(row) for row in connection.execute(query, params).fetchall()]
        for row in rows:
            row["statement_type"] = statement_type_for_metric(str(row.get("metric_code") or ""))
            row["label"] = row.get("metric_code")
            row["run_id"] = run_id
        if statement_type:
            rows = [row for row in rows if row.get("statement_type") == statement_type]
        return rows

    def list_rule_results(
        self,
        ticker: str,
        limit: int = 500,
        run_id: str | None = None,
        triggered: bool | None = None,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM rule_results WHERE ticker = ?"
        params: list[Any] = [ticker]
        if run_id:
            query += " AND run_id = ?"
            params.append(run_id)
        if triggered is not None:
            query += " AND triggered = ?"
            params.append(1 if triggered else 0)
        query += " ORDER BY rowid DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = [dict(row) for row in connection.execute(query, params).fetchall()]
        for row in rows:
            row["triggered"] = bool(row.get("triggered"))
            row["evidence_periods"] = json.loads(row.pop("evidence_periods_json") or "[]")
            row["evidence_metrics"] = json.loads(row.pop("evidence_metrics_json") or "[]")
            row["actual_values"] = json.loads(row.pop("actual_values_json") or "{}")
        return rows

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

    def save_text_intelligence_result(
        self,
        *,
        ticker: str,
        run_id: str,
        analysis: TextMiningAnalysisResponse,
        narrative_shift: NarrativeShiftResponse | None = None,
    ) -> dict[str, int]:
        created_at = analysis.generated_at.isoformat()
        sentences = [sentence for document in analysis.documents for sentence in document.sentences]
        with self._connect() as connection:
            connection.execute(
                """INSERT OR REPLACE INTO text_model_runs
                (run_id, ticker, model_summary_json, semantic_analysis_json, narrative_shift_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    run_id,
                    ticker,
                    to_json(analysis.model_summary),
                    to_json(analysis.semantic_analysis),
                    to_json(narrative_shift.model_dump(mode="json")) if narrative_shift else None,
                    created_at,
                ),
            )
            for sentence in sentences:
                connection.execute(
                    """INSERT OR REPLACE INTO text_evidence
                    (evidence_id, run_id, ticker, document_id, sentence_id, source_type, source_url, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sentence.evidence_id,
                        run_id,
                        ticker,
                        sentence.document_id,
                        sentence.sentence_id,
                        sentence.source_type,
                        sentence.source_url,
                        to_json(sentence.model_dump(mode="json")),
                        created_at,
                    ),
                )
        return {"text_model_runs": 1, "text_evidence": len(sentences), "narrative_shift_results": 1 if narrative_shift else 0}

    def get_latest_text_intelligence_result(self, ticker: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            run = connection.execute(
                "SELECT * FROM text_model_runs WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if run is None:
                return None
            evidence_rows = connection.execute(
                "SELECT payload_json FROM text_evidence WHERE ticker = ? AND run_id = ? ORDER BY sentence_id",
                (ticker, run["run_id"]),
            ).fetchall()
        return {
            "run_id": run["run_id"],
            "ticker": run["ticker"],
            "model_summary": json.loads(run["model_summary_json"]),
            "semantic_analysis": json.loads(run["semantic_analysis_json"]),
            "narrative_shift": json.loads(run["narrative_shift_json"]) if run["narrative_shift_json"] else None,
            "text_evidence": [json.loads(row["payload_json"]) for row in evidence_rows],
            "created_at": run["created_at"],
        }

    def ingest_facts(self, facts: list[FinancialFact]) -> int:
        with self._connect() as connection:
            for fact in facts:
                fact_row = {
                    "ticker": fact.ticker,
                    "period": fact.period,
                    "metric_code": fact.metric,
                    "unit": fact.unit,
                    "statement_type": fact.statement_type,
                    "statement_scope": fact.statement_scope,
                    "source_kind": fact.source_kind,
                    "source_url": fact.source_url,
                    "is_demo": fact.is_demo,
                }
                fact_id = fact_document_id(fact_row)
                connection.execute(
                    """INSERT OR REPLACE INTO normalized_financial_facts (
                        fact_id, ticker, company_name, subindustry, analysis_type, period,
                        metric_code, value, unit, source_kind, source_url,
                        taxonomy_concept, retrieved_at, statement_type, statement_scope,
                        filed_at, is_demo, source_field, fact_key_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        fact_id, fact.ticker, fact.company_name, fact.semiconductor_subindustry,
                        "ingested", fact.period, fact.metric, fact.value, fact.unit,
                        fact.source_kind, fact.source_url, fact.taxonomy_concept,
                        datetime.now(timezone.utc).isoformat(), fact.statement_type,
                        fact.statement_scope,
                        fact.filed_at.isoformat() if fact.filed_at else None,
                        int(fact.is_demo), fact.metric, FACT_KEY_VERSION,
                    ),
                )
        return len(facts)


def build_analysis_repository() -> AnalysisRepository:
    backend = os.getenv("DATASTORE_BACKEND", "sqlite").strip().lower()
    if backend == "firestore":
        from app.services.firestore_analysis_repository import FirestoreAnalysisRepository
        return FirestoreAnalysisRepository(os.getenv("GOOGLE_CLOUD_PROJECT") or None)
    if backend != "sqlite":
        raise ValueError(f"Unsupported DATASTORE_BACKEND: {backend}")
    path = os.getenv("FINANCIAL_DATABASE_PATH", "./data/financial_pipeline.sqlite3")
    return SqliteAnalysisRepository(path)
