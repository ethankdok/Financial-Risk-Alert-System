"""Append-only literature-input extension store (separate SQLite sidecar; owner: financial-research layer).

Holds the line-level official observations used by the literature models and the per-artifact extraction
diagnostics. It never touches the 16 approved historical tables: it is a different file
(``data/literature_models/literature_inputs.sqlite3``), the approved database path is refused, and SQL triggers
forbid UPDATE and DELETE.

Idempotency: an observation id is the hash of (extractor version, filing version, raw SHA-256, line, period, value).
Re-importing identical evidence is a no-op; the same id with different content is an integrity error. A source
correction or a new extractor version produces new ids (new records), never a silent replacement.

Migration plan: schema version ``1`` is created on first write; future versions add tables/columns only. The store
can be rebuilt from the immutable raw archive at any time with ``scripts/ingest_literature_inputs.py``.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.financial_research.input_snapshot import canonical_json, digest

STORE_SCHEMA_VERSION = "1"
DEFAULT_LITERATURE_DATABASE = "./data/literature_models/literature_inputs.sqlite3"
OBSERVATION_FIELDS = (
    "observation_id", "ticker", "filing_version_id", "filing_version_type", "filing_fiscal_year", "source_kind",
    "accounting_framework", "statement_scope", "statement", "line_key", "source_concept", "period_type",
    "period_start", "period_end", "value", "published_value", "published_unit", "locator", "raw_sha256", "source_url",
    "extraction_method", "extractor_version", "artifact_available_at", "artifact_availability_status", "pit_admitted",
    "pit_basis", "checks")

SCHEMA = """
CREATE TABLE IF NOT EXISTS literature_store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS literature_extraction_runs (
    extraction_run_id TEXT PRIMARY KEY, extractor_version TEXT NOT NULL, ticker TEXT NOT NULL,
    artifacts_json TEXT NOT NULL, observation_count INTEGER NOT NULL, new_observation_count INTEGER NOT NULL,
    git_commit TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS literature_line_observations (
    observation_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, filing_version_id TEXT NOT NULL,
    filing_version_type TEXT NOT NULL, filing_fiscal_year INTEGER NOT NULL, source_kind TEXT NOT NULL,
    accounting_framework TEXT NOT NULL, statement_scope TEXT NOT NULL, statement TEXT NOT NULL, line_key TEXT NOT NULL,
    source_concept TEXT NOT NULL, period_type TEXT NOT NULL, period_start TEXT, period_end TEXT NOT NULL,
    value TEXT NOT NULL, published_value TEXT, published_unit TEXT NOT NULL, locator TEXT NOT NULL,
    raw_sha256 TEXT NOT NULL, source_url TEXT, extraction_method TEXT NOT NULL, extractor_version TEXT NOT NULL,
    artifact_available_at TEXT, artifact_availability_status TEXT, pit_admitted INTEGER NOT NULL, pit_basis TEXT NOT NULL,
    checks_json TEXT NOT NULL, content_digest TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_literature_obs_filing
    ON literature_line_observations (ticker, filing_fiscal_year, filing_version_id);
CREATE TABLE IF NOT EXISTS literature_artifact_diagnostics (
    diagnostic_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, filing_version_id TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
    extractor_version TEXT NOT NULL, status TEXT NOT NULL, diagnostics_json TEXT NOT NULL, created_at TEXT NOT NULL);
"""
_TABLES = ("literature_extraction_runs", "literature_line_observations", "literature_artifact_diagnostics")


class LiteratureStoreIntegrityError(RuntimeError):
    pass


class LiteratureInputsUnavailable(RuntimeError):
    """The literature-input store is not present in this deployment (maps to HTTP 503 / ``source_unavailable``)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_digest(observation: dict[str, Any]) -> str:
    return digest({key: observation.get(key) for key in OBSERVATION_FIELDS})


class LiteratureInputStore:
    def __init__(self, path: str | os.PathLike[str] = DEFAULT_LITERATURE_DATABASE, *,
                 protected: tuple[str, ...] = (), read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        for other in protected:
            if other and Path(other).resolve() == self.path.resolve():
                raise LiteratureStoreIntegrityError("the literature store must not share the approved historical database")
        if read_only:
            if not self.path.is_file():
                raise LiteratureInputsUnavailable("literature input store is not available in this deployment")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            for table in _TABLES:
                for action in ("UPDATE", "DELETE"):
                    connection.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
                        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END")
            connection.execute("INSERT OR IGNORE INTO literature_store_meta VALUES ('schema_version', ?)",
                               (STORE_SCHEMA_VERSION,))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        uri = f"file:{self.path.resolve().as_posix()}" + ("?mode=ro" if self.read_only else "")
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            if not self.read_only:
                connection.commit()
        finally:
            connection.close()

    # ------------------------------------------------------------------ writes (ingestion CLI only)
    def record_observations(self, observations: list[dict[str, Any]]) -> int:
        created = 0
        with self._connect() as connection:
            for obs in observations:
                digest_value = content_digest(obs)
                row = connection.execute("SELECT content_digest FROM literature_line_observations WHERE observation_id = ?",
                                         (obs["observation_id"],)).fetchone()
                if row is not None:
                    if row["content_digest"] != digest_value:
                        raise LiteratureStoreIntegrityError(f"{obs['observation_id']}: different content for an existing id")
                    continue
                values = {key: obs.get(key) for key in OBSERVATION_FIELDS if key != "checks"}
                values["pit_admitted"] = 1 if obs.get("pit_admitted") else 0
                connection.execute(
                    f"INSERT INTO literature_line_observations ({', '.join(values)}, checks_json, content_digest, created_at) "
                    f"VALUES ({', '.join('?' * len(values))}, ?, ?, ?)",
                    (*values.values(), canonical_json(obs.get("checks") or {}), digest_value, _now()))
                created += 1
        return created

    def record_diagnostics(self, ticker: str, diagnostics: list[dict[str, Any]], extractor_version: str) -> int:
        created = 0
        with self._connect() as connection:
            for item in diagnostics:
                diagnostic_id = "ldiag1_" + digest({"extractor": extractor_version, **item})[:32]
                if connection.execute("SELECT 1 FROM literature_artifact_diagnostics WHERE diagnostic_id = ?",
                                      (diagnostic_id,)).fetchone():
                    continue
                connection.execute("INSERT INTO literature_artifact_diagnostics VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                   (diagnostic_id, ticker, item["filing_version_id"], int(item["fiscal_year"]),
                                    extractor_version, item.get("status", "unknown"), canonical_json(item), _now()))
                created += 1
        return created

    def record_run(self, run: dict[str, Any]) -> bool:
        with self._connect() as connection:
            if connection.execute("SELECT 1 FROM literature_extraction_runs WHERE extraction_run_id = ?",
                                  (run["extraction_run_id"],)).fetchone():
                return False
            connection.execute("INSERT INTO literature_extraction_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                               (run["extraction_run_id"], run["extractor_version"], run["ticker"],
                                canonical_json(run["artifacts"]), run["observation_count"],
                                run["new_observation_count"], run.get("git_commit"), _now()))
        return True

    # ------------------------------------------------------------------ reads
    def list_observations(self, ticker: str, *, filing_version_ids: list[str] | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM literature_line_observations WHERE ticker = ?"
        params: list[Any] = [ticker]
        if filing_version_ids is not None:
            if not filing_version_ids:
                return []
            query += f" AND filing_version_id IN ({','.join('?' * len(filing_version_ids))})"
            params.extend(filing_version_ids)
        with self._connect() as connection:
            rows = [dict(row) for row in connection.execute(query + " ORDER BY observation_id", params)]
        for row in rows:
            row["checks"] = json.loads(row.pop("checks_json"))
            row["pit_admitted"] = bool(row["pit_admitted"])
            row.pop("created_at", None)
            row.pop("content_digest", None)
        return rows

    def list_diagnostics(self, ticker: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT diagnostics_json FROM literature_artifact_diagnostics WHERE ticker = ? "
                                      "ORDER BY fiscal_year, filing_version_id, diagnostic_id", (ticker,)).fetchall()
        return [json.loads(row["diagnostics_json"]) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _TABLES}
