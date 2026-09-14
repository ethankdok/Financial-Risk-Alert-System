from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.dependencies import get_analysis_repository
from app.services.analysis_repository import AnalysisRepository
from app.services.financial_analysis_service import UnsupportedCompanyError
from app.services.text_intelligence import (
    TEXT_INTELLIGENCE_VERSION,
    FinancialTextIntelligenceService,
    documents_from_official_events,
    export_annotation_candidates_csv,
)
from app.services.text_embedding_provider import create_text_embedding_provider
from app.text_intelligence_models import (
    NarrativeShiftRequest,
    NarrativeShiftResponse,
    TextMiningAnalysisRequest,
    TextMiningAnalysisResponse,
)


router = APIRouter(prefix="/api/v1/financial/text-mining", tags=["text-mining-v2"])


@router.get("/health")
def text_mining_health():
    embedding_provider = create_text_embedding_provider()
    return {
        "module": "financial_text_intelligence_v2",
        "version": TEXT_INTELLIGENCE_VERSION,
        "baseline": "PROTOTYPE_BASELINE",
        "semantic_embedding": embedding_provider.health(),
        "ground_truth_required_for_performance_claims": True,
    }


@router.post("/analyze", response_model=TextMiningAnalysisResponse)
def analyze_text_documents(request: TextMiningAnalysisRequest) -> TextMiningAnalysisResponse:
    return FinancialTextIntelligenceService().analyze_documents(
        request.documents,
        include_irrelevant_sentences=request.include_irrelevant_sentences,
    )


@router.post("/narrative-shift", response_model=NarrativeShiftResponse)
def analyze_narrative_shift(request: NarrativeShiftRequest) -> NarrativeShiftResponse:
    if request.document_1.ticker != request.document_2.ticker:
        raise HTTPException(status_code=400, detail="Narrative shift comparison requires the same ticker.")
    return FinancialTextIntelligenceService().narrative_shift(request.document_1, request.document_2)


@router.get("/companies/{ticker}/text-evidence", response_model=TextMiningAnalysisResponse)
def company_text_evidence(
    ticker: str,
    include_irrelevant_sentences: bool = Query(default=False),
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> TextMiningAnalysisResponse:
    try:
        conferences = repository.list_investor_conferences(ticker)
        material_events = repository.list_material_events(ticker)
    except UnsupportedCompanyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    documents = documents_from_official_events(
        ticker=ticker,
        conferences=conferences,
        material_events=material_events,
    )
    return FinancialTextIntelligenceService().analyze_documents(
        documents,
        include_irrelevant_sentences=include_irrelevant_sentences,
    )


@router.get("/companies/{ticker}/annotation-candidates.csv")
def company_annotation_candidates_csv(
    ticker: str,
    repository: AnalysisRepository = Depends(get_analysis_repository),
) -> Response:
    analysis = company_text_evidence(ticker, include_irrelevant_sentences=True, repository=repository)
    sentences = [sentence for document in analysis.documents for sentence in document.sentences]
    return Response(
        export_annotation_candidates_csv(sentences),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{ticker}-annotation-candidates.csv"'},
    )


@router.get("/companies/{ticker}/latest-run")
def company_latest_text_intelligence_run(
    ticker: str,
    repository: AnalysisRepository = Depends(get_analysis_repository),
):
    latest = repository.get_latest_text_intelligence_result(ticker)
    if latest is None:
        raise HTTPException(status_code=404, detail="No persisted text intelligence run is available for this ticker.")
    return latest
