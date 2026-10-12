"""Independent Phase 6 counterparty preview API.

No routes are added under /api/v1/integrity: the Phase 1.1 API and UI
contracts stay unchanged. POST performs read-only calculations, no writes.
"""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, ConfigDict, Field

from app.routers.integrity import get_integrity_workbench
from app.services.integrity.adapters import IntegrityDataUnavailable
from app.services.integrity.b2b_dossier import build_dossier
from app.services.integrity.source_readiness import summarize_source_readiness
from app.services.integrity.contracts import AssessmentRequest, Section
from app.services.integrity.service import IntegrityWorkbench, UnsupportedTicker

router = APIRouter(prefix="/api/v1/b2b", tags=["b2b-due-diligence"])


class DossierRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(..., pattern=r"^\d{4,6}$")
    relationship_type: Literal["supplier", "customer", "partner", "potential_counterparty"] = (
        "potential_counterparty"
    )
    persist: Literal[False] = False


@router.post("/dossiers/preview")
def preview_dossier(
    request: DossierRequest,
    workbench: IntegrityWorkbench = Depends(get_integrity_workbench),
) -> dict[str, Any]:
    """No user-supplied URLs, external fetch, company-link discovery or persistence."""
    try:
        assessment = workbench.assess(
            AssessmentRequest(
                ticker=request.ticker,
                persist=False,
                sections=[Section.financial_checks, Section.claims, Section.jsd],
            )
        )
        return build_dossier(assessment, request.relationship_type)
    except UnsupportedTicker as exc:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ticker_not_supported", "message": str(exc)},
        ) from exc
    except IntegrityDataUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"error_code": "integrity_data_unavailable", "message": str(exc)},
        ) from exc

@router.get("/companies/{ticker}/source-readiness")
def source_readiness(
    ticker: str = Path(..., pattern=r"^\d{4,6}$"),
    workbench: IntegrityWorkbench = Depends(get_integrity_workbench),
) -> dict[str, Any]:
    """Per-company coverage gaps only; does not populate or change any facts."""
    try:
        workbench.resolve(ticker)
        facts = workbench.facts.collect(ticker)
        count, problem = workbench.literature.frozen_observation_count(ticker)
        return summarize_source_readiness(
            facts, ticker=ticker, frozen_literature_observations=count,
            frozen_store_reason=problem, nfm_records=workbench.nfm_records,
        )
    except UnsupportedTicker as exc:
        raise HTTPException(status_code=404, detail={
            "error_code": "ticker_not_supported", "message": str(exc),
        }) from exc
    except IntegrityDataUnavailable as exc:
        raise HTTPException(status_code=503, detail={
            "error_code": "integrity_data_unavailable", "message": str(exc),
        }) from exc
