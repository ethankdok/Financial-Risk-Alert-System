from __future__ import annotations

import sqlite3
from pathlib import Path

from app.models import FinancialFact


class FinancialFactRepository:
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
        """Compatibility with the scheduled pipeline AnalysisRepository protocol."""
        return self.get(ticker, metric, period)
