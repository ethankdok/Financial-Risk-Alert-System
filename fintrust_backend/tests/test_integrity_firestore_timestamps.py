"""Regression: Firestore native datetime values must satisfy the strict evidence contract."""
from datetime import datetime, timedelta, timezone
import unittest

from app.services.integrity.adapters import FactsAdapter, public_record
from app.services.integrity.contracts import AssessmentRequest, EvidenceRecord
from app.services.integrity.service import IntegrityWorkbench
from tests.integrity_fixtures import FakeRepository, annual_rows


class FirestoreTimestampTests(unittest.TestCase):
    def test_native_timestamp_and_null_fields(self):
        retrieved = datetime(2026, 11, 26, 16, 0, tzinfo=timezone.utc)
        filed = datetime(2025, 3, 15, 9, 30, tzinfo=timezone(timedelta(hours=8)))
        rows = annual_rows("2330", {"revenue": {2024: 1000}, "accounts_receivable": {2024: 200}})
        rows[0]["retrieved_at"] = retrieved
        rows[0]["filed_at"] = filed
        rows[1]["retrieved_at"] = retrieved
        rows[1]["filed_at"] = None
        repo = FakeRepository(rows)
        facts = FactsAdapter(repo).collect("2330")
        record = EvidenceRecord.model_validate(public_record(facts["index"][("revenue", 2024)]))
        self.assertEqual(record.ingested_at, retrieved.isoformat())
        self.assertEqual(record.published_at, filed.isoformat())
        self.assertIsNone(record.effective_available_at)
        self.assertFalse(record.pit_eligible)
        result = IntegrityWorkbench(repo).assess(AssessmentRequest(ticker="2330", sections=["financial_checks"]))
        records = {r["concept"]: r for r in result["evidence_records"]}
        self.assertEqual(records["revenue"]["ingested_at"], retrieved.isoformat())
        self.assertIsNone(records["accounts_receivable"]["published_at"])
        self.assertEqual(result["data_latest_ingested_at"], retrieved.isoformat())

    def test_sqlite_text_is_unchanged(self):
        row = annual_rows("2330", {"revenue": {2024: 1000}})[0]
        record = EvidenceRecord.model_validate(public_record(FactsAdapter.record(row, "2330")))
        self.assertEqual(record.ingested_at, row["retrieved_at"])
        self.assertIsNone(record.published_at)


if __name__ == "__main__":
    unittest.main()
