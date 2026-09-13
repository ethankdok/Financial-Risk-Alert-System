from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Protocol

from app.models import FinancialFact
from app.services.analysis_repository import document_id


class FinancialFactRepository(Protocol):
    backend_name: str

    def upsert_many(self, facts: list[FinancialFact]) -> int: ...
    def get(self, ticker: str, metric: str, period: str) -> FinancialFact | None: ...
    def get_fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None: ...


def fact_to_firestore_row(fact: FinancialFact) -> dict[str, Any]:
    """Normalize an ingested fact into the shared Firestore fact collection."""
    return {
        "ticker": fact.ticker,
        "company_name": fact.company_name,
        "subindustry": fact.semiconductor_subindustry,
        "analysis_type": "ingested",
        "period": fact.period,
        "metric_code": fact.metric,
        "value": fact.value,
        "unit": fact.unit,
        "statement_type": fact.statement_type,
        "source_kind": fact.source_kind,
        "source_url": fact.source_url,
        "taxonomy_concept": fact.taxonomy_concept,
        "statement_scope": fact.statement_scope,
        "filed_at": fact.filed_at,
        "retrieved_at": fact.filed_at,
        "is_demo": fact.is_demo,
    }


def firestore_row_to_fact(row: dict[str, Any]) -> FinancialFact:
    return FinancialFact(
        ticker=str(row["ticker"]),
        company_name=str(row["company_name"]),
        semiconductor_subindustry=str(row.get("subindustry") or row.get("semiconductor_subindustry") or "unknown"),
        metric=str(row.get("metric_code") or row.get("metric")),
        period=str(row["period"]),
        value=float(row["value"]),
        unit=str(row["unit"]),
        statement_type=str(row.get("statement_type") or "income_statement"),
        source_kind=str(row["source_kind"]),
        source_url=str(row["source_url"]),
        filed_at=row.get("filed_at") or row.get("retrieved_at"),
        taxonomy_concept=row.get("taxonomy_concept"),
        statement_scope=str(row.get("statement_scope") or "unknown"),
        is_demo=bool(row.get("is_demo", False)),
    )


class SqliteFinancialFactRepository:
    """Local/test compatibility backend for direct fact ingestion."""

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS financial_facts (
                    ticker TEXT NOT NULL,
                    company_name TEXT NOT NULL,
                    semiconductor_subindustry TEXT NOT NULL,
                    metric TEXT NOT NULL,
                    period TEXT NOT NULL,
                    value REAL NOT NULL,
                    unit TEXT NOT NULL,
                    statement_type TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    filed_at TEXT NOT NULL,
                    taxonomy_concept TEXT,
                    statement_scope TEXT NOT NULL,
                    is_demo INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (ticker, metric, period, statement_scope)
                )
                """
            )

    def upsert_many(self, facts: list[FinancialFact]) -> int:
        with self._connect() as connection:
            for fact in facts:
                connection.execute(
                    """
                    INSERT INTO financial_facts (
                        ticker, company_name, semiconductor_subindustry, metric,
                        period, value, unit, statement_type, source_kind,
                        source_url, filed_at, taxonomy_concept, statement_scope,
                        is_demo
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(ticker, metric, period, statement_scope)
                    DO UPDATE SET
                        company_name = excluded.company_name,
                        semiconductor_subindustry = excluded.semiconductor_subindustry,
                        value = excluded.value,
                        unit = excluded.unit,
                        statement_type = excluded.statement_type,
                        source_kind = excluded.source_kind,
                        source_url = excluded.source_url,
                        filed_at = excluded.filed_at,
                        taxonomy_concept = excluded.taxonomy_concept,
                        is_demo = excluded.is_demo
                    """,
                    (
                        fact.ticker,
                        fact.company_name,
                        fact.semiconductor_subindustry,
                        fact.metric,
                        fact.period,
                        fact.value,
                        fact.unit,
                        fact.statement_type,
                        fact.source_kind,
                        fact.source_url,
                        fact.filed_at.isoformat(),
                        fact.taxonomy_concept,
                        fact.statement_scope,
                        int(fact.is_demo),
                    ),
                )
        return len(facts)

    def get(self, ticker: str, metric: str, period: str) -> FinancialFact | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM financial_facts
                WHERE ticker = ? AND metric = ? AND period = ?
                ORDER BY CASE statement_scope WHEN 'consolidated' THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (ticker, metric, period),
            ).fetchone()
        if row is None:
            return None
        return FinancialFact(
            ticker=row["ticker"],
            company_name=row["company_name"],
            semiconductor_subindustry=row["semiconductor_subindustry"],
            metric=row["metric"],
            period=row["period"],
            value=row["value"],
            unit=row["unit"],
            statement_type=row["statement_type"],
            source_kind=row["source_kind"],
            source_url=row["source_url"],
            filed_at=row["filed_at"],
            taxonomy_concept=row["taxonomy_concept"],
            statement_scope=row["statement_scope"],
            is_demo=bool(row["is_demo"]),
        )

    def get_fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None:
        return self.get(ticker, metric, period)


class FirestoreFinancialFactRepository:
    """Cloud Run production backend for the protected direct-ingest endpoint."""

    backend_name = "firestore"

    def __init__(self, project_id: str | None = None) -> None:
        from google.cloud import firestore

        self.client = firestore.Client(project=project_id or None)

    def upsert_many(self, facts: list[FinancialFact]) -> int:
        # Firestore has a 500-operation batch limit; keep headroom for future metadata writes.
        chunk_size = 400
        for start in range(0, len(facts), chunk_size):
            batch = self.client.batch()
            for fact in facts[start : start + chunk_size]:
                row = fact_to_firestore_row(fact)
                ref = self.client.collection("normalized_financial_facts").document(
                    document_id(
                        fact.ticker,
                        "ingested",
                        fact.period,
                        fact.metric,
                        fact.statement_scope,
                    )
                )
                batch.set(ref, row, merge=True)
            batch.commit()
        return len(facts)

    def get(self, ticker: str, metric: str, period: str) -> FinancialFact | None:
        from google.cloud.firestore_v1.base_query import FieldFilter

        documents = (
            self.client.collection("normalized_financial_facts")
            .where(filter=FieldFilter("ticker", "==", ticker))
            .where(filter=FieldFilter("metric_code", "==", metric))
            .where(filter=FieldFilter("period", "==", period))
            .stream()
        )
        rows = [document.to_dict() or {} for document in documents]
        if not rows:
            return None
        rows.sort(
            key=lambda row: (
                0 if row.get("statement_scope") == "consolidated" else 1,
                str(row.get("filed_at") or row.get("retrieved_at") or ""),
            ),
            reverse=False,
        )
        return firestore_row_to_fact(rows[0])

    def get_fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None:
        return self.get(ticker, metric, period)


def build_fact_repository() -> FinancialFactRepository:
    backend = os.getenv("DATASTORE_BACKEND", "sqlite").strip().lower()
    if backend == "firestore":
        return FirestoreFinancialFactRepository(os.getenv("GOOGLE_CLOUD_PROJECT") or None)
    if backend != "sqlite":
        raise ValueError(f"Unsupported DATASTORE_BACKEND for fact repository: {backend}")
    path = os.getenv("FINANCIAL_FACT_DATABASE_PATH") or os.getenv(
        "FINANCIAL_DATABASE_PATH", "./data/financial_facts.sqlite3"
    )
    return SqliteFinancialFactRepository(path)
