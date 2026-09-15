from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.phase12_models import PipelineStageResult, UnifiedCompanyAnalysisResponse
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.analysis_repository import AnalysisRepository, build_analysis_repository
from app.services.company_registry import get_company
from app.services.financial_analysis_service import UnsupportedCompanyError
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService
from app.services.ingestion_pipeline import FinancialIngestionPipeline
from app.services.official_evidence_cards import OfficialEvidenceCardBuilder
from app.services.official_event_ingestion import OfficialEventIngestionService
from app.services.text_intelligence import FinancialTextIntelligenceService, documents_from_official_events


def _stage(name: str, status: str, *, count: int = 0, limitations: list[str] | None = None, error: str | None = None, metadata: dict | None = None) -> PipelineStageResult:
    return PipelineStageResult(
        name=name,
        status=status,  # type: ignore[arg-type]
        count=count,
        limitations=list(dict.fromkeys(limitations or [])),
        error=error,
        metadata=metadata or {},
    )


def _status_from_outcome(outcomes: list[str], *, count: int) -> str:
    if count > 0 and any(status in {"PASS", "LIVE_OFFICIAL_DATA", "OFFICIAL_COMPANY_IR"} for status in outcomes):
        return "PASS"
    if any(status == "BLOCKED_BY_SOURCE" for status in outcomes):
        return "BLOCKED_BY_SOURCE"
    if any(status in {"NETWORK_ERROR", "FAIL"} for status in outcomes):
        return "FAIL"
    if count:
        return "PARTIAL"
    return "NO_DATA"


class UnifiedAnalysisOrchestrator:
    """Additive orchestration over existing financial, official-event, text, and AI services."""

    def __init__(
        self,
        *,
        repository: AnalysisRepository | None = None,
        financial_pipeline: FinancialIngestionPipeline | None = None,
        official_event_service: OfficialEventIngestionService | None = None,
        text_service: FinancialTextIntelligenceService | None = None,
    ) -> None:
        self.repository = repository or build_analysis_repository()
        self.financial_pipeline = financial_pipeline or FinancialIngestionPipeline(repository=self.repository)
        self.official_event_service = official_event_service or OfficialEventIngestionService(repository=self.repository)
        self.text_service = text_service or FinancialTextIntelligenceService()

    async def refresh_company(
        self,
        ticker: str,
        *,
        years: int = 5,
        end_year: int | None = None,
        trigger: str = "manual",
        source_mode: str = "official",
        include_gemini: bool = True,
    ) -> UnifiedCompanyAnalysisResponse:
        company = get_company(ticker)
        if company is None:
            raise UnsupportedCompanyError("MVP 僅分析已登錄的半導體公司；請先將公司加入 semiconductor registry。")
        stages: list[PipelineStageResult] = []
        limitations: list[str] = []
        generated_at = datetime.now(timezone.utc)
        text_run_id = uuid4().hex

        financial_result = await self.financial_pipeline.refresh_company(
            company.ticker,
            years=years,
            end_year=end_year,
            trigger=trigger,  # type: ignore[arg-type]
            source_mode=source_mode,  # type: ignore[arg-type]
        )
        stages.append(
            _stage(
                "financial_data",
                "PASS" if financial_result.status == "completed" else "FAIL",
                count=financial_result.persistence.facts,
                limitations=financial_result.snapshot.limitations if financial_result.snapshot else [],
                error=financial_result.error,
                metadata={"run_id": financial_result.run_id, "history_available_years": financial_result.history_available_years},
            )
        )
        if financial_result.status != "completed":
            limitations.append(financial_result.error or "Financial refresh failed.")

        official_result = self.official_event_service.refresh_company(company.ticker, extract_documents=True)
        conference_status = _status_from_outcome(
            [official_result.live_source_outcome.get("investor_conference", "NO_DATA")],
            count=official_result.investor_conference_count,
        )
        material_status = _status_from_outcome(
            [official_result.live_source_outcome.get("material_event", "NO_DATA")],
            count=official_result.material_event_count,
        )
        stages.append(_stage("investor_conference", conference_status, count=official_result.investor_conference_count, limitations=official_result.limitations))
        stages.append(_stage("material_event", material_status, count=official_result.material_event_count, limitations=official_result.limitations))

        card = OfficialEvidenceCardBuilder(repository=self.repository).build(company.ticker)
        stages.append(
            _stage(
                "official_evidence",
                "PASS" if card.text_evidence or card.disclosure_claims or card.financial_snapshot else "NO_DATA",
                count=len(card.text_evidence) + len(card.disclosure_claims),
                limitations=card.limitations,
                metadata={"readiness": card.evidence_readiness},
            )
        )

        documents = documents_from_official_events(
            ticker=company.ticker,
            conferences=self.repository.list_investor_conferences(company.ticker),
            material_events=self.repository.list_material_events(company.ticker),
        )
        text_analysis = self.text_service.analyze_documents(documents)
        text_sentence_count = sum(document.relevant_sentence_count for document in text_analysis.documents)
        stages.append(
            _stage(
                "text_intelligence",
                "PASS" if text_sentence_count else "NO_DATA",
                count=text_sentence_count,
                limitations=[limitation for document in documents for limitation in document.limitations],
                metadata=text_analysis.semantic_analysis,
            )
        )

        narrative_shift = None
        comparable = sorted([document for document in documents if document.period and document.text.strip()], key=lambda item: item.period or "")
        if len(comparable) >= 2:
            narrative_shift = self.text_service.narrative_shift(comparable[-2], comparable[-1])
            stages.append(_stage("narrative_shift", "PASS", count=len(narrative_shift.supporting_sentences), metadata=narrative_shift.metrics))
        else:
            stages.append(_stage("narrative_shift", "NO_DATA", limitations=["At least two comparable official-text periods are required."]))

        if text_sentence_count:
            persistence = self.repository.save_text_intelligence_result(
                ticker=company.ticker,
                run_id=text_run_id,
                analysis=text_analysis,
                narrative_shift=narrative_shift,
            )
        else:
            persistence = {"text_model_runs": 0, "text_evidence": 0, "narrative_shift_results": 0}

        ai_analysis = None
        if include_gemini and financial_result.status == "completed" and AIFinancialAnalysisService.supports(company.subindustry):
            historical_report = await HistoricalFinancialAnalysisService().analyze(
                company.ticker,
                years=years,
                end_roc_year=end_year - 1911 if end_year is not None else None,
            )
            ai_analysis = await AIFinancialAnalysisService().analyze_report(
                historical_report,
                use_llm=True,
                official_text_evidence=card.text_evidence,
                narrative_shift=narrative_shift.model_dump(mode="json") if narrative_shift else None,
            )
            stages.append(
                _stage(
                    "ai_financial",
                    "PASS" if ai_analysis.llm_trace.status == "completed" else "NOT_CONFIGURED" if ai_analysis.llm_trace.status == "not_configured" else "PARTIAL",
                    count=len(ai_analysis.llm_evidence_ids),
                    limitations=ai_analysis.limitations,
                    metadata={"llm_trace": ai_analysis.llm_trace.model_dump(mode="json")},
                )
            )
        else:
            stages.append(_stage("ai_financial", "NOT_CONFIGURED", limitations=["Gemini/LLM execution was disabled, financial data failed, or subindustry is unsupported."]))

        card_payload = card.model_dump(mode="json")
        if ai_analysis is not None:
            card_payload["ai_analysis_with_text_evidence"] = ai_analysis.model_dump(mode="json")
            card_payload["llm_evidence_ids"] = ai_analysis.llm_evidence_ids

        return UnifiedCompanyAnalysisResponse(
            ticker=company.ticker,
            company_name=company.name,
            generated_at=generated_at,
            stages=stages,
            financial_refresh=financial_result.model_dump(mode="json"),
            official_events_refresh=official_result.model_dump(mode="json"),
            official_evidence_card=card_payload,
            text_intelligence=text_analysis.model_dump(mode="json"),
            narrative_shift=narrative_shift.model_dump(mode="json") if narrative_shift else None,
            persistence=persistence,
            limitations=list(dict.fromkeys([*limitations, *card.limitations])),
        )
