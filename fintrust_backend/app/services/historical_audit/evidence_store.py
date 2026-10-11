"""Additive persistence for historical publication / source evidence (Phase 1B).

None of these tables changes the Phase 1 filing-version or fact tables. Every
row is an immutable observation with a deterministic id; re-imports insert
nothing new (``INSERT OR IGNORE``).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from app.services.historical_audit.models import stable_hash


EVIDENCE_SCHEMA_VERSION = "1"

SOURCE_CATEGORIES = (
    "official_original_filing",
    "official_restated_filing",
    "official_filing_unknown_revision",
    "official_historical_summary",
    "official_restatement_comparison",
    "official_publication_notice",
    "official_document_index",
    "unverified_candidate",
)
LINK_STATUSES = ("verified_linkage", "period_level_only", "unverified_linkage", "conflicting_evidence")

EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_source_documents (
    source_document_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    source_key TEXT NOT NULL,
    source_category TEXT NOT NULL,
    issuer TEXT NOT NULL,
    document_type TEXT NOT NULL,
    parser TEXT NOT NULL,
    request_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    final_url TEXT,
    retrieved_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content_length INTEGER NOT NULL,
    detected_format TEXT,
    raw_storage_path TEXT NOT NULL,
    http_last_modified TEXT,
    response_metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (source_key, content_hash)
);
CREATE TABLE IF NOT EXISTS historical_publication_events (
    event_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    event_key TEXT NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    announcement_id TEXT,
    publication_at TEXT NOT NULL,
    publication_precision TEXT NOT NULL,
    event_date TEXT,
    event_date_basis TEXT,
    affected_periods_json TEXT NOT NULL DEFAULT '[]',
    affected_scopes_json TEXT NOT NULL DEFAULT '[]',
    source_document_id TEXT NOT NULL REFERENCES historical_source_documents (source_document_id),
    evidence_text TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_publication_events_time ON historical_publication_events (ticker, publication_at);
CREATE TABLE IF NOT EXISTS publication_evidence_links (
    link_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES historical_publication_events (event_id),
    target_kind TEXT NOT NULL,
    target_id TEXT,
    period TEXT NOT NULL,
    statement_scope TEXT NOT NULL,
    link_status TEXT NOT NULL,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS official_summary_observations (
    observation_id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL REFERENCES historical_source_documents (source_document_id),
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    report_period TEXT NOT NULL,
    observation_role TEXT NOT NULL,
    accounting_framework TEXT NOT NULL,
    source_label TEXT NOT NULL,
    source_metric_code TEXT NOT NULL,
    canonical_metric TEXT,
    mapping_status TEXT NOT NULL,
    value_text TEXT NOT NULL,
    published_unit TEXT NOT NULL,
    normalized_value_text TEXT NOT NULL,
    normalized_unit TEXT NOT NULL,
    statement_scope TEXT NOT NULL,
    statement_scope_basis TEXT,
    available_at TEXT,
    availability_status TEXT NOT NULL DEFAULT 'unverified',
    availability_basis TEXT,
    quality_notes_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    UNIQUE (source_document_id, period, observation_role, source_metric_code)
);
CREATE TABLE IF NOT EXISTS restatement_comparisons (
    comparison_id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL REFERENCES historical_source_documents (source_document_id),
    event_id TEXT NOT NULL REFERENCES historical_publication_events (event_id),
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    statement_scope TEXT NOT NULL,
    accounting_framework TEXT NOT NULL,
    statement_type TEXT NOT NULL,
    pre_label TEXT,
    post_label TEXT,
    canonical_metric TEXT,
    sign_factor INTEGER NOT NULL,
    pre_value_text TEXT,
    post_value_text TEXT,
    difference_text TEXT,
    published_unit TEXT NOT NULL,
    disclosed_at TEXT NOT NULL,
    availability_status TEXT NOT NULL,
    availability_basis TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS disclosed_financial_values (
    disclosed_value_id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL REFERENCES historical_source_documents (source_document_id),
    event_id TEXT NOT NULL REFERENCES historical_publication_events (event_id),
    ticker TEXT NOT NULL,
    period TEXT NOT NULL,
    fiscal_year INTEGER NOT NULL,
    statement_scope TEXT NOT NULL,
    accounting_framework TEXT NOT NULL,
    disclosure_kind TEXT NOT NULL,
    source_label TEXT NOT NULL,
    canonical_metric TEXT,
    value_text TEXT NOT NULL,
    published_unit TEXT NOT NULL,
    normalized_value_text TEXT NOT NULL,
    normalized_unit TEXT NOT NULL,
    disclosed_at TEXT NOT NULL,
    availability_status TEXT NOT NULL,
    availability_basis TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (source_document_id, source_label)
);
CREATE TABLE IF NOT EXISTS observation_availability (
    availability_id TEXT PRIMARY KEY,
    observation_kind TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    available_at TEXT NOT NULL,
    basis TEXT NOT NULL,
    corroborating_kind TEXT NOT NULL,
    corroborating_id TEXT NOT NULL,
    match_detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (observation_kind, observation_id, corroborating_id)
);
"""


def initialize_evidence_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(EVIDENCE_SCHEMA)
    connection.execute(
        "INSERT INTO historical_schema_meta (key, value) VALUES ('evidence_schema_version', ?) "
        "ON CONFLICT(key) DO NOTHING",
        (EVIDENCE_SCHEMA_VERSION,),
    )


def evidence_id(prefix: str, *parts: object) -> str:
    return f"{prefix}_" + stable_hash(prefix, *parts)[:32]


def to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def insert_ignore(connection: sqlite3.Connection, table: str, row: dict[str, Any]) -> int:
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    cursor = connection.execute(
        f"INSERT OR IGNORE INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values())
    )
    return cursor.rowcount


EVIDENCE_TABLES = (
    "historical_source_documents",
    "historical_publication_events",
    "publication_evidence_links",
    "official_summary_observations",
    "restatement_comparisons",
    "disclosed_financial_values",
    "observation_availability",
)
