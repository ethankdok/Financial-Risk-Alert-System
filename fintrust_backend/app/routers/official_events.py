from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from app.official_event_batch_models import OfficialEventsBatchRefreshResult
from app.routers.financial import require_ingestion_token
from app.services.financial_analysis_service import UnsupportedCompanyError
from app.services.official_event_batch_ingestion import OfficialEventBatchIngestionService


router = APIRouter(prefix="/api/v1/financial", tags=["official-event-ingestion"])


@router.post(
    "/admin/official-events/refresh-all",
    response_model=OfficialEventsBatchRefreshResult,
    dependencies=[Depends(require_ingestion_token)],
)
async def refresh_all_official_events(
    include_conferences: bool = Query(default=True),
    include_material_events: bool = Query(default=True),
    material_event_year: int | None = Query(
        default=None,
        ge=2019,
        le=datetime.now().year,
    ),
    extract_documents: bool = Query(
        default=False,
        description="Batch polling keeps document extraction off by default; use the existing on-demand extraction endpoint when needed.",
    ),
    material_fetch_details: bool = Query(
        default=False,
        description="False keeps recurring polling lightweight; persisted TWSE disclosure text remains available.",
    ),
    material_openapi_only: bool = Query(
        default=False,
        description="Material-event-only scheduler mode: fetch the TWSE OpenAPI feed once and fan it out across the classified universe.",
    ),
    trigger: Literal["scheduler", "manual"] = Query(default="scheduler"),
    batch_scope: Literal["default", "classified", "explicit"] = Query(default="default"),
    tickers: list[str] | None = Query(default=None),
) -> OfficialEventsBatchRefreshResult:
    try:
        return await OfficialEventBatchIngestionService().refresh_all(
            include_conferences=include_conferences,
            include_material_events=include_material_events,
            material_event_year=material_event_year,
            extract_documents=extract_documents,
            material_fetch_details=material_fetch_details,
            material_openapi_only=material_openapi_only,
            trigger=trigger,
            batch_scope=batch_scope,
            tickers=tickers,
        )
    except (UnsupportedCompanyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
