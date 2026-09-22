from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


OfficialEventBatchScope = Literal["default", "classified", "explicit"]
OfficialEventBatchTrigger = Literal["scheduler", "manual"]
OfficialEventBatchCompanyStatus = Literal["completed", "partial", "failed"]
OfficialEventBatchStatus = Literal["completed", "partial", "failed"]


class OfficialEventBatchCompanyResult(BaseModel):
    ticker: str
    status: OfficialEventBatchCompanyStatus
    investor_conference_count: int = 0
    material_event_count: int = 0
    persisted: dict[str, int] = Field(default_factory=dict)
    live_source_outcome: dict[str, str] = Field(default_factory=dict)
    error: str | None = None


class OfficialEventsBatchRefreshResult(BaseModel):
    batch_id: str
    trigger: OfficialEventBatchTrigger
    scope: OfficialEventBatchScope
    started_at: datetime
    completed_at: datetime
    elapsed_seconds: float
    status: OfficialEventBatchStatus
    requested_companies: int
    completed_companies: int
    partial_companies: int
    failed_companies: int
    include_conferences: bool
    include_material_events: bool
    material_openapi_only: bool = False
    results: list[OfficialEventBatchCompanyResult] = Field(default_factory=list)
