from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timezone

from app.ai_analysis_models import AIFinancialAnalysisReport, LLMAnalysisTrace, LLMNarrative
from app.financial_analysis_models import RuleSeverity
from app.pipeline_models import FrontendAnalysisSnapshot
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService


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
    def test_generation_uses_persisted_run_context_without_mutating_snapshot(self) -> None:
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
        snapshot = FrontendAnalysisSnapshot(
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
        provider = _RecordingProvider()

        result = asyncio.run(AIFinancialAnalysisService(llm_analyst=provider).analyze_snapshot(snapshot))

        self.assertEqual(provider.source_context["analysis_run_id"], "completed-run-2330")
        self.assertEqual(provider.source_context["source_period_end"], 2025)
        self.assertEqual(result.llm_trace.status, "completed")
        self.assertEqual(result.llm_narrative.executive_summary, "Grounded supplement.")
        self.assertIsNone(snapshot.ai_analysis.llm_narrative)


if __name__ == "__main__":
    unittest.main()
