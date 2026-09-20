from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.pipeline_models import IngestionRunRecord, PersistenceCounts
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


if __name__ == "__main__":
    unittest.main()
