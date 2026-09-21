from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.ai_analysis_models import AIFinancialAnalysisReport, AnalysisRuleCatalogResponse
from app.dependencies import (
    get_analysis_repository,
    get_company_master_repository,
    get_ingestion_run_repository,
)
from app.financial_analysis_models import (
    FinancialStatementAnalysisReport,
    RuleCatalogResponse,
)
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.models import (
    ClaimExtractionRequest,
    ClaimVerificationRequest,
    ClaimVerificationResult,
    CompanyMasterRecord,
    CompanyListResponse,
    CompanyUniverseSyncResult,
    FactIngestRequest,
    HealthResponse,
)
from app.official_event_models import (
    InvestorConferenceRecord,
    MaterialEventRecord,
    OfficialDocumentExtractionRequest,
    OfficialDocumentExtractionResult,
    OfficialEvidenceCardResponse,
    OfficialEvidenceSummary,
    OfficialEventsRefreshResult,
)
from app.phase12_models import FinancialStatementCoverageReport, UnifiedCompanyAnalysisResponse
from app.pipeline_models import (
    AnalysisRunSummary,
    BatchIngestionRunRecord,
    CompanyRefreshResult,
    FrontendAnalysisSnapshot,
    IngestionRunRecord,
    RefreshAllResult,
)
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.analysis_repository import AnalysisRepository, SnapshotConcurrencyError
from app.services.claim_parser import extract_claim
from app.services.company_master_repository import CompanyMasterRepository
from app.services.company_registry import list_companies
from app.services.financial_analysis_service import (
    FinancialAnalysisService,
    UnsupportedCompanyError,
)
from app.services.financial_rule_engine import FinancialRuleEngine
from app.services.financial_statement_coverage import audit_financial_statement_coverage
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService
from app.services.ingestion_pipeline import FinancialIngestionPipeline
from app.services.ingestion_run_repository import IngestionRunRepository
from app.services.monitorable_rule_engine import MonitorableFinancialRuleEngine
from app.services.mops_inline_xbrl import MopsInlineXbrlError
from app.services.official_document_extraction import (
    OfficialDocumentExtractionService,
    enrich_conferences_with_document_extraction,
)
from app.services.official_evidence_cards import OfficialEvidenceCardBuilder
from app.services.official_event_ingestion import OfficialEventIngestionService
from app.services.official_event_sources import (
    build_investor_conference_metadata,
    build_material_event_metadata,
)
from app.services.official_evidence_service import OfficialEvidenceService
from app.services.pipeline_evidence_repository import PipelineEvidenceRepository
from app.services.twse_openapi import TwseOpenApiError
from app.services.unified_analysis_orchestrator import UnifiedAnalysisOrchestrator
from app.services.twse_company_universe import TwseCompanyUniverseService
from app.services.verifier import verify_claim


router = APIRouter(prefix="/api/v1/financial", tags=["financial-evidence"])


def require_ingestion_token(
    x_ingestion_token: str | None = Header(default=None, alias="X-Ingestion-Token"),
) -> None:
    expected = os.getenv("INGESTION_API_TOKEN", "").strip()
    production = os.getenv("APP_ENV", "development").strip().lower() == "production"
    if not expected:
        if production:
            raise HTTPException(
                status_code=503,
                detail="Production ingestion endpoint requires INGESTION_API_TOKEN.",
            )
        return
    if x_ingestion_token is None or not secrets.compare_digest(x_ingestion_token, expected):
        raise HTTPException(status_code=401, detail="Invalid ingestion token.")


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        module="semiconductor_financial_rule_engine_mvp",
        method="scheduled_ingestion_plus_persistent_analysis_snapshots",
        twse_openapi_ready=True,
        rule_engine_ready=True,
        historical_xbrl_ready=True,
    )


@router.get("/ai/health")
def ai_analysis_health(subindustry: str = Query(default="IC 設計")):
    return AIFinancialAnalysisService().health(subindustry=subindustry)


@router.get("/ai/rules", response_model=AnalysisRuleCatalogResponse)
def ai_analysis_rules(subindustry: str = Query(default="IC 設計")) -> AnalysisRuleCatalogResponse:
    return MonitorableFinancialRuleEngine(subindustry=subindustry).catalog()


@router.get("/statement-coverage", response_model=FinancialStatementCoverageReport)
def statement_coverage() -> FinancialStatementCoverageReport:
    return audit_financial_statement_coverage()


@router.post(
    "/ai/companies/{ticker}/analyze",
    response_model=AIFinancialAnalysisReport,
    dependencies=[Depends(require_ingestion_token)],
)
async def analyze_company_with_ai(
    ticker: str,
    years: int = Query(default=3, ge=3, le=5),
    end_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    use_llm: bool = Query(default=True),
) -> AIFinancialAnalysisReport:
    end_roc_year = end_year - 1911 if end_year is not None else None
    try:
        historical = await HistoricalFinancialAnalysisService().analyze(
            ticker,
            years=years,
            end_roc_year=end_roc_year,
        )
        return await AIFinancialAnalysisService().analyze_report(historical, use_llm=use_llm)
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MopsInlineXbrlError as exc:
        raise HTTPException(status_code=502, detail=f"無法取得 MOPS Inline XBRL 歷史財報：{exc}") from exc


@router.post(
    "/ai/companies/{ticker}/narrative",
    response_model=AIFinancialAnalysisReport,
    dependencies=[Depends(require_ingestion_token)],
)
async def generate_narrative_from_latest_snapshot(
    ticker: str,
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> AIFinancialAnalysisReport:
    """Generate an LLM supplement from the latest completed snapshot without persisting it."""
    snapshot = repository.get_latest_snapshot(ticker)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No completed analysis snapshot is available.")
    try:
        return await AIFinancialAnalysisService().analyze_snapshot(snapshot)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/ai/companies/{ticker}/narrative/persist",
    response_model=AIFinancialAnalysisReport,
    dependencies=[Depends(require_ingestion_token)],
)
async def generate_and_persist_narrative_from_latest_snapshot(
    ticker: str,
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> AIFinancialAnalysisReport:
    """Generate and atomically attach an LLM supplement to the current snapshot."""
    snapshot = repository.get_latest_snapshot(ticker)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No completed analysis snapshot is available.")
    try:
        report = await AIFinancialAnalysisService().analyze_snapshot(snapshot)
        if report.llm_narrative is None or report.llm_trace.status != "completed":
            raise HTTPException(status_code=502, detail="Gemini narrative generation did not complete.")
        repository.persist_snapshot_narrative(
            ticker=ticker,
            expected_run_id=snapshot.analysis_run_id,
            report=report,
        )
        return report
    except SnapshotConcurrencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/companies", response_model=CompanyListResponse)
def companies() -> CompanyListResponse:
    return CompanyListResponse(
        companies=list_companies(),
        note="此為可擴充的半導體公司 seed registry；系統依晶圓代工、IC 設計、封裝測試載入共通規則與子產業複合規則。",
    )


@router.get("/company-universe", response_model=list[CompanyMasterRecord])
def company_universe(
    repository: CompanyMasterRepository = Depends(get_company_master_repository),
) -> list[CompanyMasterRecord]:
    return repository.list_all()


@router.post(
    "/admin/company-universe/sync",
    response_model=CompanyUniverseSyncResult,
    dependencies=[Depends(require_ingestion_token)],
)
async def sync_company_universe(
    repository: CompanyMasterRepository = Depends(get_company_master_repository),
) -> CompanyUniverseSyncResult:
    return await TwseCompanyUniverseService(repository=repository).sync()


@router.get(
    "/admin/ingestion-runs",
    response_model=list[IngestionRunRecord],
    dependencies=[Depends(require_ingestion_token)],
)
def ingestion_runs(
    ticker: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    repository: IngestionRunRepository = Depends(get_ingestion_run_repository),
) -> list[IngestionRunRecord]:
    return repository.list(ticker=ticker, limit=limit)


@router.get(
    "/admin/ingestion-batches",
    response_model=list[BatchIngestionRunRecord],
    dependencies=[Depends(require_ingestion_token)],
)
def ingestion_batches(
    limit: int = Query(default=50, ge=1, le=200),
    repository: IngestionRunRepository = Depends(get_ingestion_run_repository),
) -> list[BatchIngestionRunRecord]:
    return repository.list_batches(limit=limit)


@router.get("/rules", response_model=RuleCatalogResponse)
def rules() -> RuleCatalogResponse:
    return FinancialRuleEngine().catalog()


@router.get("/statements/{ticker}/analyze", response_model=FinancialStatementAnalysisReport)
async def analyze_financial_statement(ticker: str) -> FinancialStatementAnalysisReport:
    try:
        return await FinancialAnalysisService().analyze(ticker)
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwseOpenApiError as exc:
        raise HTTPException(status_code=502, detail=f"無法取得臺灣證券交易所財報資料：{exc}") from exc


@router.get("/statements/{ticker}/history", response_model=HistoricalFinancialAnalysisReport)
async def analyze_historical_financial_statements(
    ticker: str,
    years: int = Query(default=5, ge=3, le=5),
    end_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
) -> HistoricalFinancialAnalysisReport:
    end_roc_year = end_year - 1911 if end_year is not None else None
    try:
        return await HistoricalFinancialAnalysisService().analyze(ticker, years=years, end_roc_year=end_roc_year)
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MopsInlineXbrlError as exc:
        raise HTTPException(status_code=502, detail=f"無法取得 MOPS Inline XBRL 歷史財報：{exc}") from exc


@router.get("/companies/{ticker}/conferences", response_model=list[InvestorConferenceRecord])
def investor_conferences(
    ticker: str,
    fetch_live: bool = Query(
        default=False,
        description="True 時診斷性讀取 MOPS live；預設 False 讀取 persisted official evidence。",
    ),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> list[InvestorConferenceRecord]:
    try:
        if fetch_live:
            return build_investor_conference_metadata(ticker, fetch_live=True)
        return repository.list_investor_conferences(ticker)
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/companies/{ticker}/conference-documents", response_model=list[OfficialDocumentExtractionResult])
def investor_conference_documents(
    ticker: str,
    fetch_live: bool = Query(default=True),
) -> list[OfficialDocumentExtractionResult]:
    try:
        conferences = build_investor_conference_metadata(ticker, fetch_live=fetch_live)
        _enriched, results, _debug = enrich_conferences_with_document_extraction(conferences)
        return results
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/official-documents/extract", response_model=OfficialDocumentExtractionResult)
def extract_official_document(request: OfficialDocumentExtractionRequest) -> OfficialDocumentExtractionResult:
    try:
        return OfficialDocumentExtractionService().extract(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/companies/{ticker}/material-events", response_model=list[MaterialEventRecord])
def material_events(
    ticker: str,
    year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    title: str | None = Query(default=None),
    fetch_live: bool = Query(default=False, description="True 時診斷性讀取 MOPS live；預設 False 讀取 persisted official evidence。"),
    fetch_details: bool = Query(default=False),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> list[MaterialEventRecord]:
    try:
        if fetch_live:
            return build_material_event_metadata(ticker, year=year, title=title, fetch_live=True, fetch_details=fetch_details)
        events = repository.list_material_events(ticker)
        if year is not None:
            events = [event for event in events if (event.event_date or "").startswith(str(year))]
        if title:
            events = [event for event in events if title in event.title]
        return events
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/companies/{ticker}/official-evidence", response_model=OfficialEvidenceSummary)
def official_evidence(
    ticker: str,
    include_conferences: bool = Query(default=True),
    include_material_events: bool = Query(default=True),
    fetch_conference_live: bool = Query(
        default=False,
        description="True 時嘗試以 live MOPS HTML preview 補強法說會 metadata；失敗時回到可解釋 limitation。",
    ),
    material_event_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> OfficialEvidenceSummary:
    try:
        return OfficialEvidenceService(repository=repository).build(
            ticker,
            include_conferences=include_conferences,
            include_material_events=include_material_events,
            fetch_conference_live=fetch_conference_live,
            material_event_year=material_event_year,
        )
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/companies/{ticker}/official-evidence-card", response_model=OfficialEvidenceCardResponse)
def official_evidence_card(
    ticker: str,
    include_conferences: bool = Query(default=True),
    include_material_events: bool = Query(default=True),
    fetch_conference_live: bool = Query(default=False),
    extract_documents: bool = Query(default=False),
    material_event_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> OfficialEvidenceCardResponse:
    try:
        return OfficialEvidenceCardBuilder(repository=repository).build(
            ticker,
            include_conferences=include_conferences,
            include_material_events=include_material_events,
            fetch_conference_live=fetch_conference_live,
            extract_documents=extract_documents,
            material_event_year=material_event_year,
        )
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/admin/companies/{ticker}/refresh",
    response_model=CompanyRefreshResult,
    dependencies=[Depends(require_ingestion_token)],
)
async def refresh_company_pipeline(
    ticker: str,
    years: int = Query(default=5, ge=3, le=5),
    end_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    trigger: Literal["scheduler", "manual", "demo", "startup"] = Query(default="manual"),
    source_mode: Literal["official", "demo_fixture"] = Query(default="official"),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> CompanyRefreshResult:
    result = await FinancialIngestionPipeline(repository=repository).refresh_company(
        ticker,
        years=years,
        end_year=end_year,
        trigger=trigger,
        source_mode=source_mode,
    )
    if result.status == "failed":
        raise HTTPException(status_code=502, detail=result.error or "Financial refresh failed.")
    return result


@router.post(
    "/admin/companies/{ticker}/unified-refresh",
    response_model=UnifiedCompanyAnalysisResponse,
    dependencies=[Depends(require_ingestion_token)],
)
async def unified_company_refresh(
    ticker: str,
    years: int = Query(default=5, ge=3, le=5),
    end_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    trigger: Literal["scheduler", "manual", "demo", "startup"] = Query(default="manual"),
    source_mode: Literal["official", "demo_fixture"] = Query(default="official"),
    include_gemini: bool = Query(default=True),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> UnifiedCompanyAnalysisResponse:
    try:
        return await UnifiedAnalysisOrchestrator(repository=repository).refresh_company(
            ticker,
            years=years,
            end_year=end_year,
            trigger=trigger,
            source_mode=source_mode,
            include_gemini=include_gemini,
        )
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/admin/companies/{ticker}/official-events/refresh",
    response_model=OfficialEventsRefreshResult,
    dependencies=[Depends(require_ingestion_token)],
)
def refresh_company_official_events(
    ticker: str,
    include_conferences: bool = Query(default=True),
    include_material_events: bool = Query(default=True),
    material_event_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    extract_documents: bool = Query(default=True),
    material_fetch_details: bool = Query(default=True),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> OfficialEventsRefreshResult:
    try:
        return OfficialEventIngestionService(repository=repository).refresh_company(
            ticker,
            include_conferences=include_conferences,
            include_material_events=include_material_events,
            material_event_year=material_event_year,
            extract_documents=extract_documents,
            material_fetch_details=material_fetch_details,
        )
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/admin/refresh-all",
    response_model=RefreshAllResult,
    dependencies=[Depends(require_ingestion_token)],
)
async def refresh_all_company_pipelines(
    years: int = Query(default=5, ge=3, le=5),
    end_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    trigger: Literal["scheduler", "manual", "demo", "startup"] = Query(default="scheduler"),
    source_mode: Literal["official", "demo_fixture"] = Query(default="official"),
    tickers: list[str] | None = Query(default=None),
    batch_scope: Literal["default", "eligible", "explicit"] = Query(default="default"),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> RefreshAllResult:
    try:
        return await FinancialIngestionPipeline(repository=repository).refresh_all(
            years=years,
            end_year=end_year,
            trigger=trigger,
            source_mode=source_mode,
            tickers=tickers,
            batch_scope=batch_scope,
        )
    except (UnsupportedCompanyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/companies/{ticker}/analysis/latest", response_model=FrontendAnalysisSnapshot)
def latest_persisted_analysis(
    ticker: str,
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> FrontendAnalysisSnapshot:
    snapshot = repository.get_latest_snapshot(ticker)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="尚無已完成的分析快照；請等待排程或由管理端執行 refresh。")
    return snapshot


@router.get("/companies/{ticker}/metrics")
def persisted_metrics(
    ticker: str,
    limit: int = Query(default=1000, ge=1, le=5000),
    latest_only: bool = Query(default=True),
    repository: AnalysisRepository = Depends(get_analysis_repository),
):
    run_id = None
    if latest_only:
        runs = repository.list_runs(ticker, limit=1)
        run_id = runs[0].run_id if runs else None
        if not run_id:
            return {"ticker": ticker, "latest_only": True, "count": 0, "metrics": []}
    metrics = repository.list_metrics(ticker, limit=limit, run_id=run_id)
    return {"ticker": ticker, "latest_only": latest_only, "count": len(metrics), "metrics": metrics}


@router.get("/companies/{ticker}/facts")
def persisted_facts(
    ticker: str,
    limit: int = Query(default=1000, ge=1, le=5000),
    run_id: str | None = Query(default=None),
    period: str | None = Query(default=None),
    statement_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    repository: AnalysisRepository = Depends(get_analysis_repository),
):
    facts = repository.list_facts(
        ticker,
        limit=limit,
        run_id=run_id,
        period=period,
        statement_type=statement_type,
        search=search,
    )
    return {"ticker": ticker, "count": len(facts), "facts": facts}


@router.get("/companies/{ticker}/rule-results")
def persisted_rule_results(
    ticker: str,
    limit: int = Query(default=1000, ge=1, le=5000),
    run_id: str | None = Query(default=None),
    triggered: bool | None = Query(default=None),
    repository: AnalysisRepository = Depends(get_analysis_repository),
):
    rules = repository.list_rule_results(ticker, limit=limit, run_id=run_id, triggered=triggered)
    return {"ticker": ticker, "count": len(rules), "rule_results": rules}


@router.get("/companies/{ticker}/analysis-runs", response_model=list[AnalysisRunSummary])
def persisted_analysis_runs(
    ticker: str,
    limit: int = Query(default=20, ge=1, le=100),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> list[AnalysisRunSummary]:
    return repository.list_runs(ticker, limit=limit)


@router.post("/facts/ingest", dependencies=[Depends(require_ingestion_token)])
def ingest_fact(request: FactIngestRequest, repository: AnalysisRepository = Depends(get_analysis_repository)):
    count = repository.ingest_facts(request.facts)
    return {"status": "ok", "count": count}


@router.post("/claims/extract", response_model=ClaimVerificationResult)
def extract_financial_claim(request: ClaimExtractionRequest) -> ClaimVerificationResult:
    claim = extract_claim(
        request.text,
        ticker_hint=request.ticker,
        period_hint=request.period,
        comparison_period_hint=request.comparison_period,
    )
    return ClaimVerificationResult(
        claim=claim,
        verdict="not_applicable",
        evidence=None,
        explanation="已完成主張抽取，尚未進行官方資料比對。",
    )


def get_pipeline_evidence_repository(
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> PipelineEvidenceRepository:
    return PipelineEvidenceRepository(repository)


@router.post("/claims/verify", response_model=ClaimVerificationResult)
def verify_financial_claim(
    request: ClaimVerificationRequest,
    repository: PipelineEvidenceRepository = Depends(get_pipeline_evidence_repository),
) -> ClaimVerificationResult:
    claim = extract_claim(
        request.text,
        ticker_hint=request.ticker,
        period_hint=request.period,
        comparison_period_hint=request.comparison_period,
    )
    return verify_claim(
        claim,
        repository=repository,
        tolerance_percentage_points=request.tolerance_percentage_points,
    )
