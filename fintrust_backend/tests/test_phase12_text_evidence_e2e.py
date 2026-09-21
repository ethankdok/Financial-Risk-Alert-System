from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ai_analysis_models import AnalysisDimension, DimensionAssessment, DimensionSignal, MonitoredRuleResult, RuleEvaluationStatus
from app.financial_analysis_models import RuleSeverity
from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord, OfficialDocumentExtractionRequest, OfficialEventsRefreshResult
from app.phase12_models import PipelineStageResult
from app.pipeline_models import CompanyRefreshResult, FrontendAnalysisSnapshot, PersistenceCounts
from app.services.analysis_repository import SqliteAnalysisRepository
from app.services.financial_statement_coverage import audit_financial_statement_coverage
from app.services.gemini_financial_analyst import GeminiFinancialAnalyst
from app.services.official_document_extraction import OfficialDocumentExtractionService
from app.services.text_embedding_provider import EmbeddingBatchResult, EmbeddingProviderMetadata
from app.services.text_experiments import (
    group_aware_split,
    rank_active_learning_candidates,
    to_train_ready_rows,
    validate_annotation_rows,
)
from app.services.text_intelligence import FinancialTextIntelligenceService, documents_from_official_events
from app.services.unified_analysis_orchestrator import UnifiedAnalysisOrchestrator
from app.text_intelligence_models import OfficialTextDocumentInput


class _Headers(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class _FakeResponse:
    status = 200
    url = "https://example.test/doc.html"
    headers = _Headers({"Content-Type": "text/html; charset=utf-8"})

    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.body


class _FakeEmbeddingProvider:
    provider_name = "fake_embedding"
    model = "fake-v1"
    configured = True

    def health(self):
        return {"provider": self.provider_name, "configured": True, "model": self.model, "dimension": 3, "status": "configured"}

    def embed_sentences(self, sentences):
        vectors = []
        for index, _sentence in enumerate(sentences):
            vectors.append([1.0, float(index % 2), 0.5])
        return EmbeddingBatchResult(
            vectors=vectors,
            metadata=EmbeddingProviderMetadata(
                provider=self.provider_name,
                model=self.model,
                dimension=3,
                status="completed",
                latency_ms=1,
            ),
        )


class _FakeGeminiModels:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.last_prompt = None
        self.last_request = None

    async def generate_content(self, **kwargs):
        self.last_prompt = kwargs["contents"]
        self.last_request = kwargs
        if self.fail:
            error = RuntimeError("quota exhausted")
            setattr(error, "code", 429)
            raise error

        class Response:
            parsed = {
                "executive_summary": "Official text evidence is bounded and deterministic rules remain unchanged.",
                "dimension_insights": {
                    "growth": "資料足夠。",
                    "profitability": "資料足夠。",
                    "rd_innovation": "資料足夠。",
                    "operating_efficiency": "資料足夠。",
                    "cash_flow": "資料足夠。",
                    "financial_structure": "資料足夠。",
                    "earnings_quality": "資料足夠。",
                    "investment_efficiency": "資料足夠。",
                },
                "watch_items": ["Watch official outlook changes."],
                "limitations": ["No investment advice."],
            }

        return Response()


class _FakeGeminiClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.models = _FakeGeminiModels(fail=fail)


class _FakeFinancialPipeline:
    async def refresh_company(self, ticker, **kwargs):
        return CompanyRefreshResult(
            run_id="financial-run",
            ticker=ticker,
            company_name="聯發科",
            subindustry="IC 設計",
            trigger="manual",
            source_mode="official",
            status="completed",
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            latest_report_period="2026Q2",
            history_available_years=3,
            persistence=PersistenceCounts(facts=4),
        )


class _FakeOfficialEventService:
    def __init__(self, repository):
        self.repository = repository

    def refresh_company(self, ticker, **kwargs):
        refreshed_at = datetime.now(timezone.utc)
        conferences = [
            InvestorConferenceRecord(
                event_id="conf-2026q1",
                ticker=ticker,
                company_name="聯發科",
                subindustry="IC 設計",
                fiscal_year=2026,
                quarter=1,
                conference_date="2026-04-30",
                title="MediaTek 2026 Q1 Results",
                source_name="company_official_ir",
                source_url="https://example.test/q1",
                status="available",
                document_text_preview="Management expects inventory correction to improve and revenue orders to recover.",
                document_extract_status="text_extracted",
            ),
            InvestorConferenceRecord(
                event_id="conf-2026q2",
                ticker=ticker,
                company_name="聯發科",
                subindustry="IC 設計",
                fiscal_year=2026,
                quarter=2,
                conference_date="2026-07-31",
                title="MediaTek 2026 Q2 Results",
                source_name="company_official_ir",
                source_url="https://example.test/q2",
                status="available",
                document_text_preview="Management expects AI product momentum, revenue growth, and customer demand recovery.",
                document_extract_status="text_extracted",
            ),
        ]
        self.repository.save_official_events(ticker=ticker, investor_conferences=conferences, material_events=[], refreshed_at=refreshed_at)
        return OfficialEventsRefreshResult(
            ticker=ticker,
            company_name="聯發科",
            subindustry="IC 設計",
            refreshed_at=refreshed_at,
            investor_conference_count=2,
            material_event_count=0,
            persisted={"investor_conferences": 2, "material_events": 0},
            live_source_outcome={"investor_conference": "PASS", "material_event": "NO_DATA"},
            investor_conferences=conferences,
        )


class _FakeEmptyOfficialEventService:
    def refresh_company(self, ticker, **kwargs):
        refreshed_at = datetime.now(timezone.utc)
        return OfficialEventsRefreshResult(
            ticker=ticker,
            company_name="聯發科",
            subindustry="IC 設計",
            refreshed_at=refreshed_at,
            investor_conference_count=0,
            material_event_count=0,
            persisted={"investor_conferences": 0, "material_events": 0},
            live_source_outcome={"investor_conference": "NO_DATA", "material_event": "NO_DATA"},
        )


class Phase12TextEvidenceE2ETests(unittest.TestCase):
    def test_document_extraction_preserves_full_text_preview_and_paragraphs(self) -> None:
        html = """
        <html><body><nav>download menu</nav>
        <p>Management expects demand visibility to improve in the second half.</p>
        <p>Inventory correction is ending and revenue growth may recover.</p>
        <footer>copyright</footer></body></html>
        """
        service = OfficialDocumentExtractionService(opener=lambda request, timeout: _FakeResponse(html))

        result = service.extract(
            OfficialDocumentExtractionRequest(
                ticker="2454",
                document_url="https://example.test/doc.html",
                source_url="https://example.test/ir",
                document_title="Transcript",
                max_preview_chars=200,
                max_full_text_chars=2000,
            )
        )

        self.assertEqual(result.extract_status, "text_extracted")
        self.assertIn("Management expects", result.full_text or "")
        self.assertLessEqual(len(result.text_preview or ""), 200)
        self.assertGreaterEqual(result.paragraph_count or 0, 2)

    def test_document_extraction_rejects_unapproved_document_host(self) -> None:
        service = OfficialDocumentExtractionService()

        with self.assertRaises(ValueError):
            service.extract(
                OfficialDocumentExtractionRequest(
                    ticker="2454",
                    document_url="http://169.254.169.254/latest/meta-data",
                    source_url="https://www.mediatek.com/investor-relations/financial-information",
                    document_title="Metadata",
                )
            )

    def test_semantic_provider_scores_are_additive_and_narrative_shift_keeps_metrics_separate(self) -> None:
        service = FinancialTextIntelligenceService(embedding_provider=_FakeEmbeddingProvider())
        first = OfficialTextDocumentInput(
            ticker="2454",
            company_name="聯發科",
            source_type="investor_conference",
            source_name="unit",
            source_url="https://example.test/q1",
            period="2026Q1",
            text="Management expects inventory correction to improve and revenue growth to recover.",
        )
        second = OfficialTextDocumentInput(
            ticker="2454",
            company_name="聯發科",
            source_type="investor_conference",
            source_name="unit",
            source_url="https://example.test/q2",
            period="2026Q2",
            text="Management expects AI product momentum and customer demand recovery.",
        )

        analysis = service.analyze_documents([first, second])
        shift = service.narrative_shift(first, second)

        self.assertEqual(analysis.semantic_analysis["status"], "completed")
        self.assertIsNotNone(analysis.documents[0].sentences[0].semantic_relevance_score)
        self.assertIn("semantic_embedding_cosine_similarity", shift.metrics)
        self.assertIsNone(shift.method["combined_weighted_score"])

    def test_annotation_validation_group_split_and_active_learning(self) -> None:
        rows = [
            {"sample_id": "a", "ticker": "2454", "document_id": "d1", "period": "2026Q1", "original_text": "revenue growth", "relevant_label": "1", "primary_topic": "revenue_orders", "annotator_id": "ann1", "annotation_round": "r1"},
            {"sample_id": "b", "ticker": "2454", "document_id": "d2", "period": "2026Q2", "original_text": "operator welcome", "relevant_label": "0", "primary_topic": "", "annotator_id": "ann1", "annotation_round": "r1"},
        ]
        validation = validate_annotation_rows(rows)
        ready = to_train_ready_rows(rows)
        split = group_aware_split(ready, seed=7)
        ranked = rank_active_learning_candidates(ready, [{"1": 0.52}, {"1": 0.95}])

        self.assertTrue(validation["valid"])
        self.assertEqual(len(ready), 2)
        self.assertTrue(split["document_leakage_prevented"])
        self.assertEqual(ranked[0]["sample_id"], "a")

    def test_sqlite_persists_text_intelligence_result_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteAnalysisRepository(str(Path(directory) / "pipeline.sqlite3"))
            documents = [
                OfficialTextDocumentInput(
                    ticker="2454",
                    company_name="聯發科",
                    source_type="synthetic_fixture",
                    source_name="unit",
                    source_url="https://example.test",
                    period="2026Q2",
                    text="Management expects revenue growth and customer demand recovery.",
                )
            ]
            analysis = FinancialTextIntelligenceService().analyze_documents(documents)
            counts = repository.save_text_intelligence_result(ticker="2454", run_id="text-run", analysis=analysis)
            repository.save_text_intelligence_result(ticker="2454", run_id="text-run", analysis=analysis)
            loaded = repository.get_latest_text_intelligence_result("2454")

        self.assertEqual(counts["text_model_runs"], 1)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["run_id"], "text-run")
        self.assertGreaterEqual(len(loaded["text_evidence"]), 1)

    def test_gemini_receives_bounded_official_text_and_reports_failure_diagnostics(self) -> None:
        dimensions = [
            DimensionAssessment(
                dimension=AnalysisDimension.GROWTH,
                label="成長性",
                signal=DimensionSignal.NORMAL,
                coverage_ratio=1.0,
                evaluated_rules=1,
                total_rules=1,
                summary="normal",
            )
        ]
        rules = [
            MonitoredRuleResult(
                rule_id="r1",
                name="rule",
                rule_scope="ic_design",
                rule_version="v1",
                dimension=AnalysisDimension.GROWTH,
                dimension_label="成長性",
                assessment_type="direct",
                severity=RuleSeverity.NORMAL,
                evaluation_status=RuleEvaluationStatus.EVALUATED,
                triggered=False,
                logic_expression="x",
                rationale="x",
                threshold_basis="x",
                evidence_basis="x",
            )
        ]
        evidence = [{"evidence_id": "e1", "text": "official sentence", "source_url": "https://example.test"}]
        client = _FakeGeminiClient()
        analyst = GeminiFinancialAnalyst(api_key="AIzaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", client=client)

        narrative, trace = asyncio.run(
            analyst.analyze(
                company_name="聯發科",
                ticker="2454",
                subindustry="IC 設計",
                dimensions=dimensions,
                rules=rules,
                official_text_evidence=evidence,
                narrative_shift={"metrics": {"topic_distribution_jsd": 0.1}},
                source_context={"analysis_run_id": "run-2454", "source_period_end": 2025},
            )
        )
        failed, failed_trace = asyncio.run(
            GeminiFinancialAnalyst(api_key="AIzaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", client=_FakeGeminiClient(fail=True)).analyze(
                company_name="聯發科",
                ticker="2454",
                subindustry="IC 設計",
                dimensions=dimensions,
                rules=rules,
            )
        )

        self.assertIsNotNone(narrative)
        self.assertEqual(trace.status, "completed")
        self.assertIn("official_text_evidence", client.models.last_prompt)
        self.assertIn("run-2454", client.models.last_prompt)
        self.assertEqual(client.models.last_request["config"]["temperature"], 0.1)
        self.assertEqual(trace.model, "gemini-3.6-flash")
        self.assertIsNone(failed)
        self.assertEqual(failed_trace.error_code, 429)
        self.assertEqual(failed_trace.error_type, "RuntimeError")
        self.assertTrue(failed_trace.retryable)

    def test_gemini_handles_missing_key_malformed_json_and_timeout(self) -> None:
        class Models:
            def __init__(self, mode):
                self.mode = mode

            async def generate_content(self, **kwargs):
                if self.mode == "timeout":
                    await asyncio.sleep(0.02)

                class Response:
                    parsed = None
                    text = "not-json"

                return Response()

        class Client:
            def __init__(self, mode):
                self.models = Models(mode)

        kwargs = {
            "company_name": "台積電",
            "ticker": "2330",
            "subindustry": "晶圓代工",
            "dimensions": [],
            "rules": [],
        }
        missing, missing_trace = asyncio.run(GeminiFinancialAnalyst(api_key="").analyze(**kwargs))
        malformed_key, malformed_key_trace = asyncio.run(GeminiFinancialAnalyst(api_key="x").analyze(**kwargs))
        malformed, malformed_trace = asyncio.run(
            GeminiFinancialAnalyst(api_key="AIzaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", client=Client("malformed"), fallback_model="").analyze(**kwargs)
        )
        timed_out, timeout_trace = asyncio.run(
            GeminiFinancialAnalyst(
                api_key="AIzaAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                client=Client("timeout"),
                fallback_model="",
                timeout_seconds=0.001,
            ).analyze(**kwargs)
        )

        self.assertIsNone(missing)
        self.assertEqual(missing_trace.status, "not_configured")
        self.assertIsNone(malformed_key)
        self.assertEqual(malformed_key_trace.status, "not_configured")
        self.assertIsNone(malformed)
        self.assertEqual(malformed_trace.status, "failed")
        self.assertEqual(malformed_trace.error_type, "JSONDecodeError")
        self.assertIsNone(timed_out)
        self.assertEqual(timeout_trace.status, "failed")
        self.assertTrue(timeout_trace.retryable)

    def test_unified_orchestrator_preserves_stage_level_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteAnalysisRepository(str(Path(directory) / "pipeline.sqlite3"))
            result = asyncio.run(
                UnifiedAnalysisOrchestrator(
                    repository=repository,
                    financial_pipeline=_FakeFinancialPipeline(),
                    official_event_service=_FakeOfficialEventService(repository),
                    text_service=FinancialTextIntelligenceService(),
                ).refresh_company("2454", include_gemini=False)
            )

        stages = {stage.name: stage.status for stage in result.stages}
        self.assertEqual(stages["financial_data"], "PASS")
        self.assertEqual(stages["investor_conference"], "PASS")
        self.assertIn(stages["text_intelligence"], {"PASS", "NO_DATA"})
        self.assertEqual(result.persistence["text_model_runs"], 1)

    def test_unified_orchestrator_does_not_persist_empty_text_intelligence_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteAnalysisRepository(str(Path(directory) / "pipeline.sqlite3"))
            result = asyncio.run(
                UnifiedAnalysisOrchestrator(
                    repository=repository,
                    financial_pipeline=_FakeFinancialPipeline(),
                    official_event_service=_FakeEmptyOfficialEventService(),
                    text_service=FinancialTextIntelligenceService(),
                ).refresh_company("2454", include_gemini=False)
            )
            latest = repository.get_latest_text_intelligence_result("2454")

        stages = {stage.name: stage.status for stage in result.stages}
        self.assertEqual(stages["text_intelligence"], "NO_DATA")
        self.assertEqual(result.persistence["text_model_runs"], 0)
        self.assertIsNone(latest)

    def test_statement_coverage_api_reports_fourth_statement_missing(self) -> None:
        report = audit_financial_statement_coverage()
        self.assertEqual(report.fourth_statement_status, "MISSING")
        self.assertTrue(any(item.statement == "monthly_revenue" and item.status == "PARTIAL" for item in report.coverage))

    def test_statement_coverage_endpoint_is_additive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            import os

            os.environ["DATASTORE_BACKEND"] = "sqlite"
            os.environ["FINANCIAL_DATABASE_PATH"] = str(Path(directory) / "pipeline.sqlite3")
            from app.dependencies import get_analysis_repository, get_fact_repository

            get_analysis_repository.cache_clear()
            get_fact_repository.cache_clear()
            from app.main import app

            response = TestClient(app, raise_server_exceptions=False).get("/api/v1/financial/statement-coverage")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fourth_statement_status"], "MISSING")


if __name__ == "__main__":
    unittest.main()
