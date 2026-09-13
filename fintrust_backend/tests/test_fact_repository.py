from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from app.models import FinancialFact
from app.services.fact_repository import (
    SqliteFinancialFactRepository,
    fact_to_firestore_row,
    firestore_row_to_fact,
)


class FinancialFactRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fact = FinancialFact(
            ticker="2330",
            company_name="台積電",
            semiconductor_subindustry="foundry",
            metric="revenue",
            period="2025FY",
            value=100.0,
            unit="TWD",
            statement_type="income_statement",
            source_kind="mops_xbrl",
            source_url="https://example.com/filing",
            filed_at=datetime(2026, 3, 1, 9, 0, 0),
            taxonomy_concept="Revenue",
            statement_scope="consolidated",
            is_demo=False,
        )

    def test_sqlite_upsert_and_get(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteFinancialFactRepository(str(Path(directory) / "facts.sqlite3"))
            self.assertEqual(repository.upsert_many([self.fact]), 1)
            loaded = repository.get("2330", "revenue", "2025FY")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.value, 100.0)

            updated = self.fact.model_copy(update={"value": 123.0})
            repository.upsert_many([updated])
            self.assertEqual(repository.get("2330", "revenue", "2025FY").value, 123.0)

    def test_firestore_shape_round_trip(self) -> None:
        row = fact_to_firestore_row(self.fact)
        self.assertEqual(row["metric_code"], "revenue")
        self.assertEqual(row["analysis_type"], "ingested")
        loaded = firestore_row_to_fact(row)
        self.assertEqual(loaded.ticker, self.fact.ticker)
        self.assertEqual(loaded.statement_scope, "consolidated")
        self.assertEqual(loaded.filed_at, self.fact.filed_at)


if __name__ == "__main__":
    unittest.main()
