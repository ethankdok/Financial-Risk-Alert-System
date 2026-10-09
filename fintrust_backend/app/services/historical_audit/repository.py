"""Version-aware SQLite persistence for the historical audit archive.

All tables are additive and namespaced; none of the production tables
(financial_filings, normalized_financial_facts, latest_analysis_snapshots, …)
is read, altered or written. Filing versions and facts are immutable
observations: reruns insert nothing new for identical content, and a later
artifact never overwrites an earlier one.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.historical_audit.evidence_store import EVIDENCE_TABLES, initialize_evidence_schema
from app.services.historical_audit.models import (
    HistoricalAuditCase,
    PARSER_VERSION,
    iso,
    utc_now,
)


SCHEMA_VERSION = "1"
DEFAULT_DATABASE_PATH = "./data/historical_audit/historical_audit.sqlite3"
_PRODUCTION_DEFAULTS = ("./data/financial_pipeline.sqlite3", "./data/financial_facts.sqlite3")

SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS historical_audit_cases (
    ticker TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    market TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    registered_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS financial_filing_versions (
    filing_version_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    statement_scope TEXT NOT NULL,
    statement_scope_evidence TEXT,
    filing_version_type TEXT NOT NULL,
    version_type_evidence_json TEXT NOT NULL DEFAULT '[]',
    source_kind TEXT NOT NULL,
    source_url TEXT,
    source_published_at TEXT,
    available_at TEXT,
    availability_status TEXT NOT NULL DEFAULT 'unverified',
    availability_basis TEXT,
    verification_evidence_json TEXT NOT NULL DEFAULT '[]',
    document_dated_at TEXT,
    retrieved_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content_length INTEGER NOT NULL,
    detected_format TEXT,
    raw_storage_path TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    quarantine_reason TEXT,
    warnings_json TEXT NOT NULL DEFAULT '[]',
    diagnostics_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (ticker, period, statement_scope, content_hash)
);
CREATE INDEX IF NOT EXISTS idx_filing_versions_period
    ON financial_filing_versions (ticker, period, available_at);
CREATE TABLE IF NOT EXISTS versioned_financial_facts (
    fact_id TEXT PRIMARY KEY,
    filing_version_id TEXT NOT NULL REFERENCES financial_filing_versions (filing_version_id),
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    metric_code TEXT NOT NULL,
    value REAL NOT NULL,
    value_text TEXT NOT NULL,
    unit TEXT NOT NULL,
    source_unit_ref TEXT,
    decimals TEXT,
    statement_type TEXT NOT NULL,
    statement_scope TEXT NOT NULL,
    taxonomy_concept TEXT NOT NULL,
    context_ref TEXT NOT NULL,
    mapping_method TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_url TEXT,
    available_at TEXT,
    quality_status TEXT NOT NULL,
    quality_notes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE (filing_version_id, metric_code, period, statement_scope, unit)
);
CREATE INDEX IF NOT EXISTS idx_versioned_facts_lookup
    ON versioned_financial_facts (ticker, period, metric_code);
CREATE TABLE IF NOT EXISTS filing_version_annotations (
    annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    filing_version_id TEXT NOT NULL REFERENCES financial_filing_versions (filing_version_id),
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    evidence_json TEXT NOT NULL,
    source TEXT NOT NULL,
    annotated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS historical_ingestion_runs (
    run_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    start_year INTEGER NOT NULL,
    end_year INTEGER NOT NULL,
    source_strategy TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS historical_acquisition_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    status TEXT NOT NULL,
    source_kind TEXT,
    source_url TEXT,
    retrieved_at TEXT,
    content_hash TEXT,
    raw_storage_path TEXT,
    filing_version_id TEXT,
    new_version INTEGER NOT NULL DEFAULT 0,
    facts_inserted INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_acquisition_attempts_run
    ON historical_acquisition_attempts (run_id, fiscal_year);
"""


class ProductionDatabaseRefusedError(RuntimeError):
    pass


def _resolved(path: str | os.PathLike[str]) -> Path:
    return Path(path).expanduser().resolve()


def assert_isolated_database(database_path: str | os.PathLike[str]) -> None:
    """Refuse the configured production/default pipeline databases."""
    target = _resolved(database_path)
    protected = {
        _resolved(candidate)
        for candidate in (
            os.getenv("FINANCIAL_DATABASE_PATH"),
            os.getenv("FINANCIAL_FACT_DATABASE_PATH"),
            *_PRODUCTION_DEFAULTS,
        )
        if candidate
    }
    if target in protected:
        raise ProductionDatabaseRefusedError(
            f"{target} is a configured production/pipeline database; historical ingestion requires an isolated SQLite file."
        )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


@dataclass
class FilingVersionRecord:
    filing_version_id: str
    ticker: str
    period: str
    fiscal_year: int
    statement_scope: str
    statement_scope_evidence: str | None
    filing_version_type: str
    version_type_evidence: list[str]
    source_kind: str
    source_url: str | None
    source_published_at: str | None
    available_at: str | None
    availability_status: str
    availability_basis: str | None
    verification_evidence: list[str]
    document_dated_at: str | None
    retrieved_at: str
    content_hash: str
    content_length: int
    detected_format: str | None
    raw_storage_path: str
    validation_status: str
    quarantine_reason: str | None
    warnings: list[str] = field(default_factory=list)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    parser_version: str = PARSER_VERSION


@dataclass
class VersionUpsertResult:
    created: bool
    annotations: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    stored_parser_version: str = PARSER_VERSION


class HistoricalAuditRepository:
    backend_name = "sqlite"

    def __init__(self, database_path: str, *, allow_shared_database: bool = False) -> None:
        if not allow_shared_database:
            assert_isolated_database(database_path)
        self.database_path = database_path
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @classmethod
    def for_planning(cls, database_path: str) -> "HistoricalAuditRepository":
        """Read-only handle for dry runs: enforces isolation but creates and migrates nothing."""
        assert_isolated_database(database_path)
        repository = cls.__new__(cls)
        repository.database_path = database_path
        return repository

    def is_initialized(self) -> bool:
        if not Path(self.database_path).exists():
            return False
        connection = sqlite3.connect(f"file:{Path(self.database_path).as_posix()}?mode=ro", uri=True)
        try:
            return connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='financial_filing_versions'"
            ).fetchone() is not None
        finally:
            connection.close()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        """Idempotent additive migration."""
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute(
                "INSERT INTO historical_schema_meta (key, value) VALUES ('schema_version', ?) "
                "ON CONFLICT(key) DO NOTHING",
                (SCHEMA_VERSION,),
            )
            initialize_evidence_schema(connection)

    def schema_version(self) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM historical_schema_meta WHERE key = 'schema_version'"
            ).fetchone()
        return row["value"] if row else None

    def register_case(self, case: HistoricalAuditCase) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO historical_audit_cases VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET case_id=excluded.case_id,
                company_name=excluded.company_name, market=excluded.market,
                payload_json=excluded.payload_json""",
                (case.ticker, case.case_id, case.company_name, case.market,
                 _json(case.model_dump(mode="json")), iso(utc_now())),
            )

    def get_case(self, ticker: str) -> HistoricalAuditCase | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM historical_audit_cases WHERE ticker = ?", (ticker,)
            ).fetchone()
        return HistoricalAuditCase.model_validate_json(row["payload_json"]) if row else None

    def upsert_filing_version(
        self, connection: sqlite3.Connection, record: FilingVersionRecord, *, annotation_source: str
    ) -> VersionUpsertResult:
        existing = connection.execute(
            "SELECT * FROM financial_filing_versions WHERE filing_version_id = ?",
            (record.filing_version_id,),
        ).fetchone()
        now = iso(utc_now())
        if existing is None:
            connection.execute(
                """INSERT INTO financial_filing_versions (
                    filing_version_id, ticker, period, fiscal_year, statement_scope,
                    statement_scope_evidence, filing_version_type, version_type_evidence_json,
                    source_kind, source_url, source_published_at, available_at,
                    availability_status, availability_basis, verification_evidence_json,
                    document_dated_at, retrieved_at, content_hash, content_length,
                    detected_format, raw_storage_path, parser_version, validation_status,
                    quarantine_reason, warnings_json, diagnostics_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.filing_version_id, record.ticker, record.period, record.fiscal_year,
                    record.statement_scope, record.statement_scope_evidence,
                    record.filing_version_type, _json(record.version_type_evidence),
                    record.source_kind, record.source_url, record.source_published_at,
                    record.available_at, record.availability_status, record.availability_basis,
                    _json(record.verification_evidence), record.document_dated_at,
                    record.retrieved_at, record.content_hash, record.content_length,
                    record.detected_format, record.raw_storage_path, record.parser_version,
                    record.validation_status, record.quarantine_reason,
                    _json(record.warnings), _json(record.diagnostics), now,
                ),
            )
            return VersionUpsertResult(created=True)

        result = VersionUpsertResult(created=False, stored_parser_version=existing["parser_version"])
        # Evidence fields are immutable. Only unknown classification/timing may be
        # filled in later, and only with supporting evidence; each change is logged.
        updates: dict[str, Any] = {}
        if record.filing_version_type != "unknown_revision":
            if existing["filing_version_type"] == "unknown_revision":
                updates["filing_version_type"] = record.filing_version_type
                updates["version_type_evidence_json"] = _json(record.version_type_evidence)
            elif existing["filing_version_type"] != record.filing_version_type:
                result.conflicts.append(
                    f"filing_version_type: stored {existing['filing_version_type']} vs incoming {record.filing_version_type}"
                )
        for name in ("source_published_at", "available_at"):
            incoming = getattr(record, name)
            if incoming is None:
                continue
            if existing[name] is None:
                updates[name] = incoming
            elif existing[name] != incoming:
                result.conflicts.append(f"{name}: stored {existing[name]} vs incoming {incoming}")
        if "available_at" in updates:
            updates["availability_status"] = record.availability_status
            updates["availability_basis"] = record.availability_basis
        if updates:
            evidence = sorted(set(json.loads(existing["verification_evidence_json"])) | set(record.verification_evidence))
            updates["verification_evidence_json"] = _json(evidence)
            assignments = ", ".join(f"{name} = ?" for name in updates)
            connection.execute(
                f"UPDATE financial_filing_versions SET {assignments} WHERE filing_version_id = ?",
                (*updates.values(), record.filing_version_id),
            )
            if "available_at" in updates:
                connection.execute(
                    "UPDATE versioned_financial_facts SET available_at = ? WHERE filing_version_id = ?",
                    (updates["available_at"], record.filing_version_id),
                )
            for name, value in updates.items():
                if name.endswith("_json") or name in {"availability_status", "availability_basis"}:
                    continue
                connection.execute(
                    """INSERT INTO filing_version_annotations
                    (filing_version_id, field, old_value, new_value, evidence_json, source, annotated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (record.filing_version_id, name, existing[name], value,
                     _json(record.verification_evidence), annotation_source, now),
                )
                result.annotations.append(name)
        return result

    def insert_facts(self, connection: sqlite3.Connection, rows: list[dict[str, Any]]) -> int:
        inserted = 0
        now = iso(utc_now())
        for row in rows:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO versioned_financial_facts (
                    fact_id, filing_version_id, ticker, period, fiscal_year, metric_code,
                    value, value_text, unit, source_unit_ref, decimals, statement_type,
                    statement_scope, taxonomy_concept, context_ref, mapping_method,
                    source_kind, source_url, available_at, quality_status,
                    quality_notes_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["fact_id"], row["filing_version_id"], row["ticker"], row["period"],
                    row["fiscal_year"], row["metric_code"], row["value"], row["value_text"],
                    row["unit"], row["source_unit_ref"], row["decimals"], row["statement_type"],
                    row["statement_scope"], row["taxonomy_concept"], row["context_ref"],
                    row["mapping_method"], row["source_kind"], row["source_url"],
                    row["available_at"], row["quality_status"], _json(row["quality_notes"]), now,
                ),
            )
            inserted += cursor.rowcount
        return inserted

    def record_attempt(self, connection: sqlite3.Connection, run_id: str, payload: dict[str, Any]) -> None:
        connection.execute(
            """INSERT INTO historical_acquisition_attempts (
                run_id, ticker, period, fiscal_year, status, source_kind, source_url,
                retrieved_at, content_hash, raw_storage_path, filing_version_id,
                new_version, facts_inserted, error, payload_json, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, payload["ticker"], payload["period"], payload["fiscal_year"],
                payload["status"], payload.get("source_kind"), payload.get("source_url"),
                payload.get("downloaded_at"), payload.get("content_hash"),
                payload.get("raw_storage_path"), payload.get("filing_version_id"),
                int(bool(payload.get("new_version"))), payload.get("facts_inserted", 0),
                payload.get("error"), _json(payload), iso(utc_now()),
            ),
        )

    def save_run(self, run: dict[str, Any]) -> None:
        with self.connect() as connection:
            connection.execute(
                """INSERT INTO historical_ingestion_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET status=excluded.status,
                completed_at=excluded.completed_at, summary_json=excluded.summary_json""",
                (run["run_id"], run["ticker"], run["start_year"], run["end_year"],
                 run["source_strategy"], run["status"], run["started_at"],
                 run.get("completed_at"), _json(run.get("summary", {}))),
            )

    def list_filing_versions(self, ticker: str, start_year: int | None = None, end_year: int | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM financial_filing_versions WHERE ticker = ?"
        params: list[Any] = [ticker]
        if start_year is not None:
            query += " AND fiscal_year >= ?"
            params.append(start_year)
        if end_year is not None:
            query += " AND fiscal_year <= ?"
            params.append(end_year)
        query += " ORDER BY fiscal_year, retrieved_at, filing_version_id"
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, params).fetchall()]

    def list_attempts(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [
                dict(row) for row in connection.execute(
                    "SELECT * FROM historical_acquisition_attempts WHERE run_id = ? ORDER BY fiscal_year, attempt_id",
                    (run_id,),
                ).fetchall()
            ]

    def table_counts(self) -> dict[str, int]:
        tables = (
            "historical_audit_cases", "financial_filing_versions", "versioned_financial_facts",
            "filing_version_annotations", "historical_ingestion_runs", "historical_acquisition_attempts",
            *EVIDENCE_TABLES,
        )
        with self.connect() as connection:
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in tables
            }
