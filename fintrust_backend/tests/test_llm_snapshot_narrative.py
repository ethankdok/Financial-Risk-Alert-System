from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.ai_analysis_models import AIFinancialAnalysisReport, LLMAnalysisTrace, LLMNarrative
from app.financial_analysis_models import RuleSeverity
from app.pipeline_models import FrontendAnalysisSnapshot
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.analysis_repository import SnapshotConcurrencyError, SqliteAnalysisRepository, to_json
from app.services.firestore_analysis_repository import FirestoreAnalysisRepository


class _FirestoreDocumentSnapshot:
    exists = True

    def __init__(self, payload) -> None:
        self._payload = payload

    def to_dict(self):
        return self._payload


class _FirestoreDocumentReference:
    def __init__(self, payload) -> None:
        self._payload = payload

    def get(self, *, transaction=None):
        return _FirestoreDocumentSnapshot(self._payload)


class _FirestoreCollection:
    def __init__(self, reference) -> None:
        self._reference = reference

    def document(self, _document_id):
        return self._reference


class _FirestoreTransaction:
    def __init__(self) -> None:
        self.updates = None

    def update(self, _reference, updates) -> None:
        self.updates = updates


class _FirestoreClient:
    def __init__(self, payload) -> None:
        self.reference = _FirestoreDocumentReference(payload)
        self.current_transaction = _FirestoreTransaction()

    def collection(self, _name):
        return _FirestoreCollection(self.reference)

    def transaction(self):
        return self.current_transaction


class _RecordingProvider:
    provider_name = "test"
    model = "test-model"
    configured = True

    def __init__(self) -> None:
        self.source_context = None

    def health(self):
        return {"provider": self.provider_name, "configured": True, "model": self.model}

    async def analyze(self, **kwargs):
        self.source_context = kwargs["source_context"]
        return (
            LLMNarrative(
                executive_summary="Grounded supplement.",
                dimension_insights={},
                watch_items=[],
                limitations=["No investment advice."],
            ),
            LLMAnalysisTrace(
                enabled=True,
                status="completed",
                endpoint_configured=False,
                provider=self.provider_name,
                provider_configured=True,
                model=self.model,
            ),
        )


class SnapshotNarrativeTests(unittest.TestCase):
    @staticmethod
    def _snapshot() -> FrontendAnalysisSnapshot:
        now = datetime.now(timezone.utc)
        original = AIFinancialAnalysisReport(
            ticker="2330",
            company_name="台積電",
            subindustry="晶圓代工",
            analyzed_at=now,
            source_period_start=2023,
            source_period_end=2025,
            source_method="MOPS Inline XBRL annual Q4 filings",
            analysis_engine_version="test",
            rule_catalog_version="test",
            feature_count=0,
            features=[],
            dimension_assessments=[],
            rule_monitoring=[],
            deterministic_summary="Deterministic result.",
            llm_trace=LLMAnalysisTrace(
                enabled=False,
                status="skipped",
                endpoint_configured=False,
            ),
        )
        return FrontendAnalysisSnapshot(
            analysis_run_id="completed-run-2330",
            ticker="2330",
            company_name="台積電",
            subindustry="晶圓代工",
            generated_at=now,
            data_updated_at=now,
            overall_severity=RuleSeverity.NORMAL,
            summary="Stored summary.",
            rule_version="test",
            threshold_basis="test",
            ai_analysis=original,
        )

    def test_generation_uses_persisted_run_context_without_mutating_snapshot(self) -> None:
        snapshot = self._snapshot()
        provider = _RecordingProvider()

        result = asyncio.run(AIFinancialAnalysisService(llm_analyst=provider).analyze_snapshot(snapshot))

        self.assertEqual(provider.source_context["analysis_run_id"], "completed-run-2330")
        self.assertEqual(provider.source_context["source_period_end"], 2025)
        self.assertEqual(result.llm_trace.status, "completed")
        self.assertEqual(result.llm_narrative.executive_summary, "Grounded supplement.")
        self.assertIsNone(snapshot.ai_analysis.llm_narrative)

    def test_sqlite_persists_only_completed_narrative_for_expected_run(self) -> None:
        snapshot = self._snapshot()
        provider = _RecordingProvider()
        report = asyncio.run(AIFinancialAnalysisService(llm_analyst=provider).analyze_snapshot(snapshot))

        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteAnalysisRepository(str(Path(directory) / "pipeline.sqlite3"))
            with repository._connect() as connection:
                connection.execute(
                    "INSERT INTO latest_analysis_snapshots VALUES (?, ?, ?, ?)",
                    (
                        snapshot.ticker,
                        snapshot.analysis_run_id,
                        to_json(snapshot.model_dump(mode="json")),
                        snapshot.generated_at.isoformat(),
                    ),
                )

            persisted = repository.persist_snapshot_narrative(
                ticker="2330",
                expected_run_id=snapshot.analysis_run_id,
                report=report,
            )
            loaded = repository.get_latest_snapshot("2330")

            self.assertEqual(persisted.summary, snapshot.summary)
            self.assertEqual(loaded.ai_analysis.deterministic_summary, "Deterministic result.")
            self.assertEqual(loaded.ai_analysis.llm_narrative.executive_summary, "Grounded supplement.")
            with self.assertRaises(SnapshotConcurrencyError):
                repository.persist_snapshot_narrative(
                    ticker="2330",
                    expected_run_id="stale-run",
                    report=report,
                )

    def test_firestore_transaction_updates_only_narrative_owned_fields(self) -> None:
        snapshot = self._snapshot()
        report = asyncio.run(
            AIFinancialAnalysisService(llm_analyst=_RecordingProvider()).analyze_snapshot(snapshot)
        )
        repository = FirestoreAnalysisRepository.__new__(FirestoreAnalysisRepository)
        repository.client = _FirestoreClient(
            {**snapshot.model_dump(mode="python"), "updated_at": snapshot.generated_at}
        )

        with patch("google.cloud.firestore.transactional", side_effect=lambda function: function):
            merged = repository.persist_snapshot_narrative(
                ticker="2330",
                expected_run_id=snapshot.analysis_run_id,
                report=report,
            )

        updates = repository.client.current_transaction.updates
        self.assertEqual(merged.summary, snapshot.summary)
        self.assertNotIn("ai_analysis", updates)
        self.assertEqual(updates["narrative_analysis_run_id"], snapshot.analysis_run_id)
        self.assertEqual(
            set(updates),
            {
                "ai_analysis.analyzed_at",
                "ai_analysis.llm_narrative",
                "ai_analysis.llm_trace",
                "ai_analysis.llm_evidence_ids",
                "narrative_analysis_run_id",
                "narrative_updated_at",
            },
        )


if __name__ == "__main__":
    unittest.main()
