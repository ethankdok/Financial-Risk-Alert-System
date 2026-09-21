from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from app.models import CompanyMasterRecord


class CompanyMasterRepository(Protocol):
    backend_name: str

    def upsert_many(self, companies: list[CompanyMasterRecord]) -> int: ...
    def get(self, ticker: str) -> CompanyMasterRecord | None: ...
    def list_all(self) -> list[CompanyMasterRecord]: ...


class SqliteCompanyMasterRepository:
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
                CREATE TABLE IF NOT EXISTS companies (
                    ticker TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    legal_name TEXT NOT NULL,
                    english_name TEXT,
                    market TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    industry_code TEXT NOT NULL,
                    subindustry TEXT NOT NULL,
                    subindustry_source TEXT NOT NULL DEFAULT 'unclassified',
                    subindustry_confidence TEXT NOT NULL DEFAULT 'unclassified',
                    aliases_json TEXT NOT NULL,
                    listing_status TEXT NOT NULL,
                    listed_at TEXT,
                    source_kind TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_report_date TEXT,
                    synced_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_companies_scope
                    ON companies (market, industry_code, listing_status, ticker);
                """
            )
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(companies)").fetchall()
            }
            if "subindustry_source" not in columns:
                connection.execute(
                    "ALTER TABLE companies ADD COLUMN subindustry_source TEXT NOT NULL DEFAULT 'unclassified'"
                )
            if "subindustry_confidence" not in columns:
                connection.execute(
                    "ALTER TABLE companies ADD COLUMN subindustry_confidence TEXT NOT NULL DEFAULT 'unclassified'"
                )

    @staticmethod
    def _values(company: CompanyMasterRecord) -> tuple[object, ...]:
        return (
            company.ticker,
            company.name,
            company.legal_name,
            company.english_name,
            company.market,
            company.industry,
            company.industry_code,
            company.subindustry,
            company.subindustry_source,
            company.subindustry_confidence,
            json.dumps(company.aliases, ensure_ascii=False, separators=(",", ":")),
            company.listing_status,
            company.listed_at.isoformat() if company.listed_at else None,
            company.source_kind,
            company.source_url,
            company.source_report_date.isoformat() if company.source_report_date else None,
            company.synced_at.isoformat(),
        )

    def upsert_many(self, companies: list[CompanyMasterRecord]) -> int:
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO companies (
                    ticker, name, legal_name, english_name, market, industry,
                    industry_code, subindustry, subindustry_source,
                    subindustry_confidence, aliases_json, listing_status, listed_at,
                    source_kind, source_url, source_report_date, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    name=excluded.name,
                    legal_name=excluded.legal_name,
                    english_name=excluded.english_name,
                    market=excluded.market,
                    industry=excluded.industry,
                    industry_code=excluded.industry_code,
                    subindustry=excluded.subindustry,
                    subindustry_source=excluded.subindustry_source,
                    subindustry_confidence=excluded.subindustry_confidence,
                    aliases_json=excluded.aliases_json,
                    listing_status=excluded.listing_status,
                    listed_at=excluded.listed_at,
                    source_kind=excluded.source_kind,
                    source_url=excluded.source_url,
                    source_report_date=excluded.source_report_date,
                    synced_at=excluded.synced_at
                """,
                [self._values(company) for company in companies],
            )
        return len(companies)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CompanyMasterRecord:
        payload = dict(row)
        payload["aliases"] = json.loads(payload.pop("aliases_json"))
        return CompanyMasterRecord.model_validate(payload)

    def get(self, ticker: str) -> CompanyMasterRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM companies WHERE ticker = ?", (ticker.strip(),)
            ).fetchone()
        return self._from_row(row) if row else None

    def list_all(self) -> list[CompanyMasterRecord]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM companies ORDER BY ticker").fetchall()
        return [self._from_row(row) for row in rows]


class FirestoreCompanyMasterRepository:
    backend_name = "firestore"

    def __init__(self, project_id: str | None = None) -> None:
        from google.cloud import firestore

        self.client = firestore.Client(project=project_id or None)

    def upsert_many(self, companies: list[CompanyMasterRecord]) -> int:
        chunk_size = 400
        for start in range(0, len(companies), chunk_size):
            batch = self.client.batch()
            for company in companies[start : start + chunk_size]:
                batch.set(
                    self.client.collection("companies").document(company.ticker),
                    company.model_dump(mode="json"),
                    merge=True,
                )
            batch.commit()
        return len(companies)

    def get(self, ticker: str) -> CompanyMasterRecord | None:
        document = self.client.collection("companies").document(ticker.strip()).get()
        if not document.exists:
            return None
        return CompanyMasterRecord.model_validate(document.to_dict() or {})

    def list_all(self) -> list[CompanyMasterRecord]:
        companies = [
            CompanyMasterRecord.model_validate(document.to_dict() or {})
            for document in self.client.collection("companies").stream()
        ]
        return sorted(companies, key=lambda company: company.ticker)


def build_company_master_repository() -> CompanyMasterRepository:
    backend = os.getenv("DATASTORE_BACKEND", "sqlite").strip().lower()
    if backend == "firestore":
        return FirestoreCompanyMasterRepository(os.getenv("GOOGLE_CLOUD_PROJECT") or None)
    if backend != "sqlite":
        raise ValueError(f"Unsupported DATASTORE_BACKEND for company repository: {backend}")
    path = os.getenv("FINANCIAL_DATABASE_PATH", "./data/financial_pipeline.sqlite3")
    return SqliteCompanyMasterRepository(path)
