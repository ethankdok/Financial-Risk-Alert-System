from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.models import CompanyMasterRecord
from app.pipeline_models import IngestionRunRecord, PersistenceCounts
from app.pipeline_models import CompanyRefreshResult
from app.services.ingestion_pipeline import (
    FinancialIngestionPipeline,
    configured_refresh_tickers,
    validate_refresh_tickers,
)
from app.services.ingestion_run_repository import SqliteIngestionRunRepository


class IngestionRunRepositoryTests(unittest.TestCase):
    def test_running_record_can_be_completed_without_duplication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteIngestionRunRepository(str(Path(directory) / "pipeline.sqlite3"))
            started_at = datetime.now(timezone.utc)
            running = IngestionRunRecord(
                run_id="run-1",
                batch_id="batch-1",
                ticker="2330",
                company_name="台積電",
                subindustry="晶圓代工",
                trigger="manual",
                source_mode="official",
                requested_years=5,
                status="running",
                started_at=started_at,
            )
            repository.save(running)
            repository.save(
                running.model_copy(
                    update={
                        "status": "completed",
                        "completed_at": datetime.now(timezone.utc),
                        "records_found": 31,
                        "records_written": 31,
                        "persistence": PersistenceCounts(
                            filings=5, facts=10, metrics=10, rule_results=5, snapshots=1
                        ),
                    }
                )
            )

            rows = repository.list(ticker="2330")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "completed")
            self.assertEqual(rows[0].records_written, 31)
            self.assertEqual(rows[0].persistence.filings, 5)

    def test_failed_record_preserves_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteIngestionRunRepository(str(Path(directory) / "pipeline.sqlite3"))
            run = IngestionRunRecord(
                run_id="run-failed",
                ticker="2454",
                company_name="聯發科",
                subindustry="IC 設計",
                trigger="manual",
                source_mode="official",
                requested_years=5,
                status="failed",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                failed_records=1,
                error_message="source timeout",
            )
            repository.save(run)

            stored = repository.get("run-failed")
            self.assertIsNotNone(stored)
            assert stored is not None
            self.assertEqual(stored.status, "failed")
            self.assertEqual(stored.error_message, "source timeout")


class FakeCompanyRepository:
    backend_name = "fake"

    def __init__(self, companies: list[CompanyMasterRecord]) -> None:
        self.companies = companies

    def list_all(self) -> list[CompanyMasterRecord]:
        return list(self.companies)


def company(ticker: str, name: str, subindustry: str) -> CompanyMasterRecord:
    return CompanyMasterRecord(
        ticker=ticker,
        name=name,
        legal_name=name,
        subindustry=subindustry,
        subindustry_source="test",
        subindustry_confidence="reviewed",
        source_url="https://openapi.twse.com.tw/test",
        synced_at=datetime.now(timezone.utc),
    )


class RefreshIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_all_never_traverses_unrequested_company_master_rows(self) -> None:
        company_repository = FakeCompanyRepository([
            company("2330", "台積電", "晶圓代工"),
            company("2454", "聯發科", "IC 設計"),
            company("2303", "聯電", "晶圓代工"),
        ])
        pipeline = FinancialIngestionPipeline(
            repository=object(),
            latest_service=object(),
            historical_service=object(),
            ai_service=object(),
            ingestion_run_repository=object(),
            company_repository=company_repository,
        )
        now = datetime.now(timezone.utc)

        async def result_for(ticker: str, **kwargs: object) -> CompanyRefreshResult:
            record = next(item for item in company_repository.companies if item.ticker == ticker)
            return CompanyRefreshResult(
                run_id=f"run-{ticker}", ticker=ticker, company_name=record.name,
                subindustry=record.subindustry, trigger="scheduler", source_mode="official",
                status="completed", started_at=now, completed_at=now,
            )

        pipeline.refresh_company = AsyncMock(side_effect=result_for)
        result = await pipeline.refresh_all()
        self.assertEqual([item.ticker for item in result.results], ["2330", "2454"])
        self.assertEqual(
            [call.args[0] for call in pipeline.refresh_company.await_args_list],
            ["2330", "2454"],
        )

    def test_batch_refresh_rejects_out_of_scope_ticker(self) -> None:
        self.assertEqual(
            validate_refresh_tickers(("2330", "2344", "3413", "2451")),
            ("2330", "2344", "3413", "2451"),
        )
        with self.assertRaisesRegex(ValueError, "reviewed semiconductor taxonomy"):
            validate_refresh_tickers(("2330", "9999"))

    def test_environment_configuration_is_deduplicated_and_scoped(self) -> None:
        with patch.dict("os.environ", {"FINANCIAL_REFRESH_TICKERS": "2454,2330,2454"}):
            self.assertEqual(configured_refresh_tickers(), ("2454", "2330"))


if __name__ == "__main__":
    unittest.main()
