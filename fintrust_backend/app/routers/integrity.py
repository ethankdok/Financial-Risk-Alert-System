"""Financial Integrity Workbench API (Phase 1): read-only readiness and preview assessments.

No endpoint here persists, ingests, refreshes, extracts documents, fetches MOPS live or calls an LLM. The services
are reused in-process through the same dependency providers as the financial router (no self HTTP calls).
``persist`` accepts only ``false``; ``STRICT_AS_OF`` is refused with 409 because publication instants are unknown.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from app.dependencies import get_analysis_repository
from app.routers.financial import get_jsd_bridge_service
from app.services.analysis_repository import AnalysisRepository
from app.routers.historical_research import get_research_service
from app.services.integrity.adapters import IntegrityDataUnavailable
from app.services.integrity.nfm_reviewed_release import load_approved_nfm_release
from app.services.integrity.financial_source_release import load_approved_financial_source_release
from app.services.integrity.case_study import RetrospectiveCaseService, UnsupportedResearchCase
from app.services.integrity.contracts import AssessmentRequest
from app.services.integrity.service import IntegrityWorkbench, ReviewModeNotSupported, UnsupportedTicker
from app.services.jsd_bridge_service import JsdBridgeService

router = APIRouter(prefix="/api/v1/integrity", tags=["integrity-workbench"])
TICKER = Path(..., pattern=r"^\d{4,6}$", description="Registered company ticker")


def get_integrity_workbench(
    repository: AnalysisRepository = Depends(get_analysis_repository),
    jsd_bridge: JsdBridgeService = Depends(get_jsd_bridge_service),
) -> IntegrityWorkbench:
    from app.services.claim_evidence_adapter import ClaimEvidenceAdapter
    from app.services.claim_verification_service import ClaimVerificationService
    from app.services.financial_research.service import ResearchConfig
    from app.services.pipeline_evidence_repository import PipelineEvidenceRepository

    conference_repository = jsd_bridge.conference_repository
    # Deterministic verification only: the workbench never enables the optional Gemini claim assistance.
    claim_service = ClaimVerificationService(
        ClaimEvidenceAdapter(fact_repository=PipelineEvidenceRepository(repository),
                             conference_repository=conference_repository, event_repository=repository),
        llm=None,
    )
    config = {
        "manifest": os.getenv("FINTRUST_NFM_REVIEW_MANIFEST", "").strip(),
        "sha256": os.getenv("FINTRUST_NFM_APPROVED_RELEASE_SHA256", "").strip(),
        "archive_root": os.getenv("FINTRUST_NFM_ARCHIVE_ROOT", "").strip(),
    }
    nfm_records = []
    if any(config.values()):
        if not all(config.values()):
            raise HTTPException(status_code=503, detail={
                "error_code": "nfm_release_unavailable",
                "message": "optional approved NFM release settings are incomplete",
            })
        try:
            nfm_records = load_approved_nfm_release(
                config["manifest"], approved_manifest_sha256=config["sha256"],
                pdf_archive_root=config["archive_root"],
            )["records"]
        except (ValueError, OSError, TypeError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail={
                "error_code": "nfm_release_unavailable",
                "message": f"approved nonfinancial release rejected: {type(exc).__name__}",
            }) from exc
    financial_config = {
        "manifest": os.getenv("FINTRUST_FINANCIAL_REVIEW_MANIFEST", "").strip(),
        "sha256": os.getenv("FINTRUST_FINANCIAL_APPROVED_RELEASE_SHA256", "").strip(),
        "archive_root": os.getenv("FINTRUST_FINANCIAL_ARCHIVE_ROOT", "").strip(),
    }
    financial_records = []
    if any(financial_config.values()):
        if not all(financial_config.values()):
            raise HTTPException(status_code=503, detail={
                "error_code": "financial_release_unavailable",
                "message": "optional approved financial source settings are incomplete",
            })
        try:
            financial_records = load_approved_financial_source_release(
                financial_config["manifest"],
                approved_manifest_sha256=financial_config["sha256"],
                archive_root=financial_config["archive_root"],
            )["records"]
        except (ValueError, OSError, TypeError, RuntimeError) as exc:
            raise HTTPException(status_code=503, detail={
                "error_code": "financial_release_unavailable",
                "message": f"approved financial source release rejected: {type(exc).__name__}",
            }) from exc
    return IntegrityWorkbench(repository, jsd_bridge=jsd_bridge, conference_repository=conference_repository,
                              claim_service=claim_service,
                              literature_database=ResearchConfig.from_env().literature_database,
                              nfm_records=nfm_records,
                              financial_source_records=financial_records)


def _call(fn, *args):
    try:
        return fn(*args)
    except UnsupportedTicker as exc:
        raise HTTPException(status_code=404, detail={
            "error_code": "ticker_not_supported",
            "message": f"{exc} is not a registered company of the workbench."}) from exc
    except ReviewModeNotSupported as exc:
        raise HTTPException(status_code=409, detail=exc.as_dict()) from exc
    except IntegrityDataUnavailable as exc:
        raise HTTPException(status_code=503, detail={"error_code": "integrity_data_unavailable",
                                                     "message": str(exc)}) from exc


@router.get("/companies")
def integrity_companies(workbench: IntegrityWorkbench = Depends(get_integrity_workbench)) -> dict[str, Any]:
    companies = _call(workbench.companies)
    return {"count": len(companies), "companies": companies,
            "note": "Reviewed seed companies; a company without a persisted snapshot returns explicit unavailable states."}


@router.get("/companies/{ticker}/readiness")
def integrity_readiness(ticker: str = TICKER,
                        workbench: IntegrityWorkbench = Depends(get_integrity_workbench)) -> dict[str, Any]:
    return _call(workbench.readiness, ticker)


@router.post("/assessments/preview")
def integrity_preview(request: AssessmentRequest,
                      workbench: IntegrityWorkbench = Depends(get_integrity_workbench)) -> dict[str, Any]:
    """Preview assessment (never persisted): findings, model availability, claims, data shift and B2B checks."""
    return _call(workbench.assess, request)


# ------------------------------------------------------------------ retrospective research case (RETROSPECTIVE_CASE)
def get_case_service(research=Depends(get_research_service)) -> RetrospectiveCaseService:
    return RetrospectiveCaseService(research)


@router.get("/research-cases/{ticker}/summary")
def research_case_summary(
    ticker: str = TICKER,
    version_policy: Literal["latest_available", "original_only"] = Query(..., description="Required; no default"),
    service: RetrospectiveCaseService = Depends(get_case_service),
) -> dict[str, Any]:
    """Read-only 1785 retrospective case view: unchanged Beneish / Dechow engines on frozen inputs (dry run, never
    persisted), strict pre-event status, feature crosswalk and an evidence-verified event timeline. Separate from
    CURRENT_REVIEW; hindsight; not a pre-event prediction. Unregistered tickers → 404 (no substitution)."""
    try:
        return service.summary(ticker, version_policy)
    except UnsupportedResearchCase as exc:
        raise HTTPException(status_code=404, detail={
            "error_code": "research_case_not_supported", "supported_cases": ["1785"],
            "message": f"{exc} is not a registered retrospective research case of the workbench."}) from exc
