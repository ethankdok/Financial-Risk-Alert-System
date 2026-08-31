from __future__ import annotations

import os
import secrets
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.ai_analysis_models import AIFinancialAnalysisReport, AnalysisRuleCatalogResponse
from app.dependencies import get_analysis_repository, get_fact_repository
from app.financial_analysis_models import (
    FinancialStatementAnalysisReport,
    RuleCatalogResponse,
)
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.models import (
    ClaimExtractionRequest,
    ClaimVerificationRequest,
    ClaimVerificationResult,
    CompanyListResponse,
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
)
from app.pipeline_models import (
    AnalysisRunSummary,
    CompanyRefreshResult,
    FrontendAnalysisSnapshot,
    RefreshAllResult,
)
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.analysis_repository import AnalysisRepository
from app.services.claim_parser import extract_claim
from app.services.company_registry import list_companies
from app.services.fact_repository import FinancialFactRepository
from app.services.financial_analysis_service import (
    FinancialAnalysisService,
    UnsupportedCompanyError,
)
from app.services.financial_rule_engine import FinancialRuleEngine
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService
from app.services.ingestion_pipeline import FinancialIngestionPipeline
from app.services.monitorable_rule_engine import MonitorableFinancialRuleEngine
from app.services.mops_inline_xbrl import MopsInlineXbrlError
from app.services.official_document_extraction import (
    OfficialDocumentExtractionService,
    enrich_conferences_with_document_extraction,
)
from app.services.official_evidence_cards import OfficialEvidenceCardBuilder
from app.services.official_event_sources import (
    build_investor_conference_metadata,
    build_material_event_metadata,
)
from app.services.official_evidence_service import OfficialEvidenceService
from app.services.pipeline_evidence_repository import PipelineEvidenceRepository
from app.services.twse_openapi import TwseOpenApiError
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
def ai_analysis_health():
    return AIFinancialAnalysisService().health(subindustry="IC 設計")


@router.get("/ai/rules", response_model=AnalysisRuleCatalogResponse)
def ai_analysis_rules() -> AnalysisRuleCatalogResponse:
    return MonitorableFinancialRuleEngine(subindustry="IC 設計").catalog()


@router.post("/ai/companies/{ticker}/analyze", response_model=AIFinancialAnalysisReport)
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


@router.get("/companies", response_model=CompanyListResponse)
def companies() -> CompanyListResponse:
    return CompanyListResponse(
        companies=list_companies(),
        note="此為可擴充的半導體公司 seed registry；系統依晶圓代工、IC 設計、封裝測試載入共通規則與子產業複合規則。",
    )


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
        description="True 時嘗試讀取 MOPS 法說會頁面並解析 HTML preview / 附件連結；預設 False 以保持 demo 穩定。",
    ),
) -> list[InvestorConferenceRecord]:
    try:
        return build_investor_conference_metadata(ticker, fetch_live=fetch_live)
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
) -> list[MaterialEventRecord]:
    try:
        return build_material_event_metadata(ticker, year=year, title=title)
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
    "/admin/refresh-all",
    response_model=RefreshAllResult,
    dependencies=[Depends(require_ingestion_token)],
)
async def refresh_all_company_pipelines(
    years: int = Query(default=5, ge=3, le=5),
    end_year: int | None = Query(default=None, ge=2019, le=datetime.now().year),
    trigger: Literal["scheduler", "manual", "demo", "startup"] = Query(default="scheduler"),
    source_mode: Literal["official", "demo_fixture"] = Query(default="official"),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> RefreshAllResult:
    return await FinancialIngestionPipeline(repository=repository).refresh_all(
        years=years,
        end_year=end_year,
        trigger=trigger,
        source_mode=source_mode,
    )


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
    metrics = repository.list_metrics(ticker, limit=limit, latest_only=latest_only)
    return {"ticker": ticker, "latest_only": latest_only, "count": len(metrics), "metrics": metrics}


@router.get("/companies/{ticker}/analysis-runs", response_model=list[AnalysisRunSummary])
def persisted_analysis_runs(
    ticker: str,
    limit: int = Query(default=20, ge=1, le=100),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> list[AnalysisRunSummary]:
    return repository.list_analysis_runs(ticker, limit=limit)


@router.post("/facts/ingest", dependencies=[Depends(require_ingestion_token)])
def ingest_fact(request: FactIngestRequest, repository: FinancialFactRepository = Depends(get_fact_repository)):
    fact = repository.upsert_fact(request)
    return {"status": "ok", "fact": fact}


@router.post("/claims/extract", response_model=ClaimVerificationResult)
def extract_financial_claim(request: ClaimExtractionRequest) -> ClaimVerificationResult:
    claim = extract_claim(request.text, ticker_hint=request.ticker_hint)
    return ClaimVerificationResult(claim=claim, verdict="not_verified", evidence=[], explanation="已完成主張抽取，尚未進行官方資料比對。")


@router.post("/claims/verify", response_model=ClaimVerificationResult)
def verify_financial_claim(
    request: ClaimVerificationRequest,
    repository: PipelineEvidenceRepository = Depends(lambda: PipelineEvidenceRepository()),
) -> ClaimVerificationResult:
    return verify_claim(request.claim, repository=repository)
