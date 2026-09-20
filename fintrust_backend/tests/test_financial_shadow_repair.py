from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from app.services.analysis_repository import SqliteAnalysisRepository, document_id
from scripts.prepare_financial_sqlite_shadow import prepare_shadow


class FinancialShadowRepairTests(unittest.TestCase):
    def test_repairs_copy_without_modifying_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            output = Path(directory) / "shadow.sqlite3"
            repository = SqliteAnalysisRepository(str(source))
            connection = sqlite3.connect(source)
            snapshot = {
                "ticker": "2330",
                "sources": [
                    {"source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci", "period": "2026Q2"},
                    {"source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci", "period": "2026Q2"},
                    {"source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L", "period": "2026-07"},
                ],
            }
            connection.execute(
                """INSERT INTO latest_analysis_snapshots
                   (ticker, run_id, snapshot_json, updated_at) VALUES (?, ?, ?, ?)""",
                (
                    "2330", "run-1", json.dumps(snapshot),
                    "2026-08-01T00:00:00+00:00",
                ),
            )
            connection.execute(
                """INSERT INTO normalized_financial_facts (
                    fact_id, ticker, company_name, subindustry, analysis_type, period,
                    metric_code, value, unit, source_kind, source_url, taxonomy_concept,
                    retrieved_at, statement_type, statement_scope, filed_at, is_demo,
                    source_field, fact_key_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    document_id("legacy"), "2330", "台積電", "晶圓代工", "latest",
                    "2026Q2", "previous_month_revenue", 90, "TWD", "twse_openapi",
                    "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci", None,
                    "2026-08-01T00:00:00+00:00", "income_statement", "unknown",
                    "2026-08-01T00:00:00+00:00", 0, None, "legacy",
                ),
            )
            connection.commit()
            connection.close()
            before = source.read_bytes()

            report = prepare_shadow(source, output)
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(report["repaired_facts"], 1)
            connection = sqlite3.connect(output)
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM normalized_financial_facts").fetchone()
            self.assertEqual(row["metric_code"], "monthly_revenue")
            self.assertEqual(row["source_field"], "previous_month_revenue")
            self.assertEqual(row["period"], "2026-06")
            self.assertTrue(row["source_url"].endswith("t187ap05_L"))
            self.assertIsNone(row["filed_at"])
            self.assertEqual(row["fact_key_version"], "financial-fact-v2")
            connection.close()

    def test_refuses_to_overwrite_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            output = Path(directory) / "shadow.sqlite3"
            source.touch()
            output.touch()
            with self.assertRaises(FileExistsError):
                prepare_shadow(source, output)


if __name__ == "__main__":
    unittest.main()
