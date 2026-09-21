from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from app.pipeline_models import BatchIngestionRunRecord, IngestionRunRecord


class IngestionRunRepository(Protocol):
    backend_name: str

    def save(self, run: IngestionRunRecord) -> None: ...
    def get(self, run_id: str) -> IngestionRunRecord | None: ...
    def list(self, *, ticker: str | None = None, limit: int = 100) -> list[IngestionRunRecord]: ...
    def save_batch(self, run: BatchIngestionRunRecord) -> None: ...
    def get_batch(self, batch_id: str) -> BatchIngestionRunRecord | None: ...
    def list_batches(self, *, limit: int = 50) -> list[BatchIngestionRunRecord]: ...


class SqliteIngestionRunRepository:
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
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingestion_runs (
                    run_id TEXT PRIMARY KEY,
                    batch_id TEXT,
                    ticker TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    subindustry TEXT NOT NULL,
                    pipeline TEXT NOT NULL,
                    trigger TEXT NOT NULL,
                    source_mode TEXT NOT NULL,
                    requested_years INTEGER NOT NULL,
                    end_year INTEGER,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    records_found INTEGER NOT NULL DEFAULT 0,
                    records_written INTEGER NOT NULL DEFAULT 0,
                    failed_records INTEGER NOT NULL DEFAULT 0,
                    persistence_json TEXT NOT NULL,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ingestion_runs_ticker_started
                    ON ingestion_runs (ticker, started_at DESC);
                CREATE INDEX IF NOT EXISTS idx_ingestion_runs_batch
                    ON ingestion_runs (batch_id, started_at);
                CREATE TABLE IF NOT EXISTS ingestion_batches (
                    batch_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_ingestion_batches_started
                    ON ingestion_batches (started_at DESC);
                """
            )

    def save(self, run: IngestionRunRecord) -> None:
        payload = run.model_dump(mode="json")
        persistence_json = json.dumps(
            payload.pop("persistence"), ensure_ascii=False, separators=(",", ":")
        )
        columns = [
            "run_id", "batch_id", "ticker", "company_name", "subindustry", "pipeline",
            "trigger", "source_mode", "requested_years", "end_year", "status",
            "started_at", "completed_at", "records_found", "records_written",
            "failed_records", "error_message",
        ]
        values = [payload[column] for column in columns]
        values.insert(16, persistence_json)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO ingestion_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    batch_id=excluded.batch_id,
                    status=excluded.status,
                    completed_at=excluded.completed_at,
                    records_found=excluded.records_found,
                    records_written=excluded.records_written,
                    failed_records=excluded.failed_records,
                    persistence_json=excluded.persistence_json,
                    error_message=excluded.error_message
                """,
                values,
            )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> IngestionRunRecord:
        payload = dict(row)
        payload["persistence"] = json.loads(payload.pop("persistence_json"))
        return IngestionRunRecord.model_validate(payload)

    def get(self, run_id: str) -> IngestionRunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list(self, *, ticker: str | None = None, limit: int = 100) -> list[IngestionRunRecord]:
        with self._connect() as connection:
            if ticker:
                rows = connection.execute(
                    "SELECT * FROM ingestion_runs WHERE ticker = ? ORDER BY started_at DESC LIMIT ?",
                    (ticker, limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [self._from_row(row) for row in rows]

    def save_batch(self, run: BatchIngestionRunRecord) -> None:
        payload = run.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO ingestion_batches VALUES (?, ?, ?, ?)
                ON CONFLICT(batch_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    completed_at=excluded.completed_at""",
                (
                    run.batch_id,
                    payload,
                    run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                ),
            )

    def get_batch(self, batch_id: str) -> BatchIngestionRunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM ingestion_batches WHERE batch_id = ?",
                (batch_id,),
            ).fetchone()
        return BatchIngestionRunRecord.model_validate_json(row["payload_json"]) if row else None

    def list_batches(self, *, limit: int = 50) -> list[BatchIngestionRunRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM ingestion_batches ORDER BY started_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [BatchIngestionRunRecord.model_validate_json(row["payload_json"]) for row in rows]


class FirestoreIngestionRunRepository:
    backend_name = "firestore"

    def __init__(self, project_id: str | None = None) -> None:
        from google.cloud import firestore

        self.client = firestore.Client(project=project_id or None)

    def save(self, run: IngestionRunRecord) -> None:
        self.client.collection("ingestion_runs").document(run.run_id).set(
            run.model_dump(mode="python"), merge=True
        )

    def get(self, run_id: str) -> IngestionRunRecord | None:
        document = self.client.collection("ingestion_runs").document(run_id).get()
        if not document.exists:
            return None
        return IngestionRunRecord.model_validate(document.to_dict() or {})

    def list(self, *, ticker: str | None = None, limit: int = 100) -> list[IngestionRunRecord]:
        from google.cloud.firestore_v1.base_query import FieldFilter

        query = self.client.collection("ingestion_runs")
        if ticker:
            query = query.where(filter=FieldFilter("ticker", "==", ticker))
        rows = [IngestionRunRecord.model_validate(doc.to_dict() or {}) for doc in query.stream()]
        rows.sort(key=lambda row: row.started_at, reverse=True)
        return rows[:limit]

    def save_batch(self, run: BatchIngestionRunRecord) -> None:
        self.client.collection("ingestion_batches").document(run.batch_id).set(
            run.model_dump(mode="python"), merge=True
        )

    def get_batch(self, batch_id: str) -> BatchIngestionRunRecord | None:
        document = self.client.collection("ingestion_batches").document(batch_id).get()
        if not document.exists:
            return None
        return BatchIngestionRunRecord.model_validate(document.to_dict() or {})

    def list_batches(self, *, limit: int = 50) -> list[BatchIngestionRunRecord]:
        rows = [
            BatchIngestionRunRecord.model_validate(document.to_dict() or {})
            for document in self.client.collection("ingestion_batches").stream()
        ]
        rows.sort(key=lambda row: row.started_at, reverse=True)
        return rows[:limit]


def build_ingestion_run_repository() -> IngestionRunRepository:
    backend = os.getenv("DATASTORE_BACKEND", "sqlite").strip().lower()
    if backend == "firestore":
        return FirestoreIngestionRunRepository(os.getenv("GOOGLE_CLOUD_PROJECT") or None)
    if backend != "sqlite":
        raise ValueError(f"Unsupported DATASTORE_BACKEND for ingestion runs: {backend}")
    path = os.getenv("FINANCIAL_DATABASE_PATH", "./data/financial_pipeline.sqlite3")
    return SqliteIngestionRunRepository(path)
