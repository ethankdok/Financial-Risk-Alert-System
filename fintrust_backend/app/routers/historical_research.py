"""Historical research API (Phase 4): read-only research views of reviewed historical cases.

Every computation requires an explicit ``analysis_mode``; ``STRICT_AS_OF`` requires a timezone-aware exclusive
``cutoff_at``. Only registered historical cases are served (production tickers are not research cases). Responses
never include filesystem paths, raw document bytes or non-official URLs. Computation is bounded and dry-run by
default; persisting a run requires the existing ingestion token.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.routers.financial import require_ingestion_token
from app.services.financial_research.modes import (
    AnalysisMode,
    AnalysisRequestError,
    ModeNotSupportedError,
    build_context,
)
from app.services.financial_research.result_store import DEFAULT_RESULTS_DATABASE, SqliteResearchResultStore
from app.services.financial_research.service import ResearchDatasetUnavailable, ResearchService
from app.services.historical_audit.case_registry import UnknownHistoricalCaseError

router = APIRouter(prefix="/api/v1/research", tags=["historical-research"])
TICKER = Path(..., pattern=r"^\d{4,6}$", description="Registered historical research case ticker")
MODE_QUERY = Query(..., description="RETROSPECTIVE_FORENSIC | STRICT_AS_OF | CURRENT_EVIDENCE_RECONCILIATION (required)")
CUTOFF_QUERY = Query(None, description="Required for STRICT_AS_OF: timezone-aware ISO-8601 instant, exclusive")
_RUN_ID = re.compile(r"^rrun1_[0-9a-f]{32}$")


@lru_cache(maxsize=1)
def get_research_service() -> ResearchService:
    return ResearchService()


def results_path() -> str:
    return os.getenv("RESEARCH_RESULTS_DATABASE_PATH", DEFAULT_RESULTS_DATABASE)


def get_result_store() -> SqliteResearchResultStore:
    from app.services.financial_research.service import ResearchConfig

    return SqliteResearchResultStore(results_path(), protected=(ResearchConfig.from_env().database,))


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ModeNotSupportedError as exc:
        raise HTTPException(status_code=409, detail=exc.as_dict()) from exc
    except AnalysisRequestError as exc:
        raise HTTPException(status_code=422, detail=exc.as_dict()) from exc
    except UnknownHistoricalCaseError as exc:
        raise HTTPException(status_code=404, detail={"error_code": "not_a_historical_research_case",
                                                     "message": str(exc)}) from exc
    except ResearchDatasetUnavailable as exc:
        raise HTTPException(status_code=503, detail={"error_code": "research_dataset_unavailable",
                                                     "message": str(exc)}) from exc


def _context(mode: str | None, cutoff_at: str | None, allowed: tuple[AnalysisMode, ...] | None = None):
    return _call(build_context, mode, cutoff_at, allowed=allowed)


@router.get("/health")
def research_health(service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    """Readiness of the research dataset (separate from the service liveness ``/health``)."""
    status = service.health()
    return {"status": "ready" if status["dataset_available"] else "degraded", **status}


@router.get("/cases")
def list_cases(service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    cases = _call(service.cases)
    return {"count": len(cases), "cases": cases,
            "note": "Historical audit research cases only; they are not part of the production company universe."}


@router.get("/cases/{ticker}")
def case_overview(ticker: str = TICKER, service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    return _call(service.case_overview, ticker)


@router.get("/cases/{ticker}/timeline")
def case_timeline(ticker: str = TICKER, analysis_mode: str = MODE_QUERY, cutoff_at: str | None = CUTOFF_QUERY,
                  evidence_tier: Literal["E1", "E2"] | None = Query(None),
                  limit: int = Query(200, ge=1, le=1000), offset: int = Query(0, ge=0),
                  service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    context = _context(analysis_mode, cutoff_at, (AnalysisMode.RETROSPECTIVE_FORENSIC, AnalysisMode.STRICT_AS_OF))
    return _call(service.timeline, ticker, context, evidence_tier=evidence_tier, limit=limit, offset=offset)


@router.get("/cases/{ticker}/original-ai1-reviewed")
def original_ai1_reviewed(
    ticker: str = TICKER,
    analysis_mode: Literal["RETROSPECTIVE_FORENSIC"] = Query(...),
) -> dict[str, Any]:
    """Explicit opt-in local research only; not a fabricated historical alert.

    No change to production snapshot/score pipeline or existing frontend.
    The isolated SQLite path is configured by deployment admin.
    """
    if ticker!="1785" or os.getenv("FINTRUST_1785_ORIGINAL_REVIEW_API_ENABLED")!="1":
        raise HTTPException(status_code=404,detail="research_original_review_not_enabled")
    path=os.getenv("FINTRUST_1785_ORIGINAL_REVIEW_DB","").strip()
    if not path:
        raise HTTPException(status_code=503,detail="research_original_review_db_not_configured")
    from app.services.financial_research.original_ai1_research_reader import get_1785_original_ai1
    try:
        return get_1785_original_ai1(path)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc


@router.get("/cases/{ticker}/restatement-bridge")
def restatement_bridge(ticker: str = TICKER, analysis_mode: str = MODE_QUERY, cutoff_at: str | None = CUTOFF_QUERY,
                       scope: Literal["all", "consolidated", "individual"] = Query("all"),
                       service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    context = _context(analysis_mode, cutoff_at, (AnalysisMode.RETROSPECTIVE_FORENSIC, AnalysisMode.STRICT_AS_OF))
    return _call(service.bridge, ticker, context, scope=scope)


@router.get("/cases/{ticker}/feature-registry")
def feature_registry(ticker: str = TICKER, analysis_mode: str = MODE_QUERY, cutoff_at: str | None = CUTOFF_QUERY,
                     service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    return _call(service.feature_registry, ticker, _context(analysis_mode, cutoff_at))


@router.get("/cases/{ticker}/source-discrepancies")
def source_discrepancies(ticker: str = TICKER, analysis_mode: str = MODE_QUERY,
                         cutoff_at: str | None = CUTOFF_QUERY,
                         service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    context = _context(analysis_mode, cutoff_at, (AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION,))
    return _call(service.discrepancies, ticker, context)


@router.get("/cases/{ticker}/text-readiness")
def text_readiness(ticker: str = TICKER, analysis_mode: str = MODE_QUERY, cutoff_at: str | None = CUTOFF_QUERY,
                   service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    context = _context(analysis_mode, cutoff_at, (AnalysisMode.RETROSPECTIVE_FORENSIC, AnalysisMode.STRICT_AS_OF))
    return _call(service.text, ticker, context)


class ComputeRequest(BaseModel):
    ticker: str = Field(..., pattern=r"^\d{4,6}$")
    analysis_mode: str | None = Field(None, description="Required; no default")
    cutoff_at: str | None = None
    start_year: int | None = Field(None, ge=1990, le=2100)
    end_year: int | None = Field(None, ge=1990, le=2100)
    version_policy: Literal["latest_available", "earliest_available", "original_only"] | None = Field(
        None, description="Required; explicit version selection (no default)")
    persist: bool = False
    supersedes_run_id: str | None = Field(None, pattern=r"^rrun1_[0-9a-f]{32}$")


@router.post("/financial-signals/compute")
def compute_financial_signals(request: ComputeRequest,
                              x_ingestion_token: str | None = Header(default=None, alias="X-Ingestion-Token"),
                              service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    """Explicit-mode feature computation. Dry-run unless ``persist=true`` (requires the ingestion token)."""
    context = _context(request.analysis_mode, request.cutoff_at)
    if request.version_policy is None:
        raise HTTPException(status_code=422, detail={"error_code": "version_policy_required",
                                                     "message": "version_policy is required (no default)."})
    run = _call(service.build_run, "financial_signals", request.ticker, context, start_year=request.start_year,
                end_year=request.end_year, version_policy=request.version_policy,
                supersedes_run_id=request.supersedes_run_id, git_commit=os.getenv("FINTRUST_BUILD_COMMIT") or None)
    persisted = {"persisted": False, "created": False}
    if request.persist:
        require_ingestion_token(x_ingestion_token)
        run_id, created = get_result_store().record_run(run)
        persisted = {"persisted": True, "created": created}
    return {"run_id": run["run_id"], "input_digest": run["input_digest"], "output_digest": run["output_digest"],
            "method_version": run["method_version"], **persisted, "result": run["output"]}


# ---------------------------------------------------------------------------------- literature models
LITERATURE_POLICY = Literal["latest_available", "original_only"]
LITERATURE_MODEL = Literal["beneish_1999_full8_v1", "dechow_2011_model1_v1"]
_LITERATURE_MODES = (AnalysisMode.RETROSPECTIVE_FORENSIC, AnalysisMode.STRICT_AS_OF)


@router.get("/literature/models")
def literature_models(service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    """Source-verified method lock (Beneish 1999 full 8-variable; Dechow et al. 2011 Table 7 Model 1), approval
    status and the DRAFT Taiwan input mapping."""
    return _call(service.literature_registry)


@router.get("/cases/{ticker}/literature/coverage")
def literature_coverage(ticker: str = TICKER, analysis_mode: str = MODE_QUERY, cutoff_at: str | None = CUTOFF_QUERY,
                        version_policy: LITERATURE_POLICY = Query(..., description="Required; no default"),
                        start_year: int | None = Query(None, ge=1990, le=2100),
                        end_year: int | None = Query(None, ge=1990, le=2100),
                        service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    """Model / variable / year / t-relative input readiness with official-source provenance (no scores)."""
    context = _context(analysis_mode, cutoff_at, _LITERATURE_MODES)
    return _call(service.literature_coverage, ticker, context, version_policy=version_policy,
                 start_year=start_year, end_year=end_year)


class LiteratureRequest(BaseModel):
    ticker: str = Field(..., pattern=r"^\d{4,6}$")
    analysis_mode: str | None = Field(None, description="Required; RETROSPECTIVE_FORENSIC or STRICT_AS_OF")
    cutoff_at: str | None = None
    start_year: int | None = Field(None, ge=1990, le=2100)
    end_year: int | None = Field(None, ge=1990, le=2100)
    version_policy: LITERATURE_POLICY | None = Field(None, description="Required; latest_available or original_only")
    persist: bool = False
    supersedes_run_id: str | None = Field(None, pattern=r"^rrun1_[0-9a-f]{32}$")


class LiteratureComputeRequest(LiteratureRequest):
    model_ids: list[LITERATURE_MODEL] | None = Field(None, min_length=1, max_length=2,
                                                     description="Required; explicit model ids (no default)")


def _literature_run(kind: str, request: LiteratureRequest, token: str | None, service: ResearchService,
                    parameters: dict[str, Any]) -> dict[str, Any]:
    context = _context(request.analysis_mode, request.cutoff_at)
    if request.version_policy is None:
        raise HTTPException(status_code=422, detail={"error_code": "version_policy_required",
                                                     "message": "version_policy is required (no default)."})
    run = _call(service.build_run, kind, request.ticker, context, start_year=request.start_year,
                end_year=request.end_year, version_policy=request.version_policy, parameters=parameters,
                supersedes_run_id=request.supersedes_run_id, git_commit=os.getenv("FINTRUST_BUILD_COMMIT") or None)
    persisted = {"persisted": False, "created": False}
    if request.persist:
        require_ingestion_token(token)
        run_id, created = get_result_store().record_run(run)
        persisted = {"persisted": True, "created": created}
    return {"run_id": run["run_id"], "input_digest": run["input_digest"], "output_digest": run["output_digest"],
            "method_version": run["method_version"], **persisted, "result": run["output"]}


@router.post("/literature/compute")
def literature_compute(request: LiteratureComputeRequest,
                       x_ingestion_token: str | None = Header(default=None, alias="X-Ingestion-Token"),
                       service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    """Explicit model(s), years, mode, cutoff and version policy; dry-run unless ``persist=true`` (token)."""
    if not request.model_ids:
        raise HTTPException(status_code=422, detail={"error_code": "model_ids_required",
                                                     "message": "model_ids is required (no default)."})
    return _literature_run("literature_models", request, x_ingestion_token, service,
                           {"model_ids": sorted(set(request.model_ids))})


@router.post("/literature/compare")
def literature_compare(request: LiteratureRequest,
                       x_ingestion_token: str | None = Header(default=None, alias="X-Ingestion-Token"),
                       service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    """Both published models on the same frozen snapshot; paired comparable observations and limitations."""
    return _literature_run("literature_comparison", request, x_ingestion_token, service, {})


@router.get("/runs/{run_id}")
def get_run(run_id: str = Path(..., pattern=_RUN_ID.pattern)) -> dict[str, Any]:
    from pathlib import Path as FilePath

    run = get_result_store().get_run(run_id) if FilePath(results_path()).is_file() else None  # GET never creates a store
    if run is None:
        raise HTTPException(status_code=404, detail={"error_code": "run_not_found", "message": "No persisted run with this id."})
    return run


@router.get("/runs/{run_id}/verify")
def verify_run(run_id: str = Path(..., pattern=_RUN_ID.pattern),
               service: ResearchService = Depends(get_research_service)) -> dict[str, Any]:
    """Recompute a persisted run from the current archive and compare input/output digests (read-only)."""
    from pathlib import Path as FilePath

    run = get_result_store().get_run(run_id) if FilePath(results_path()).is_file() else None
    if run is None:
        raise HTTPException(status_code=404, detail={"error_code": "run_not_found", "message": "No persisted run with this id."})
    return _call(service.verify_run, run)
