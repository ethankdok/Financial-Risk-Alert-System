from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


StageStatus = Literal["PASS", "PARTIAL", "NO_DATA", "BLOCKED_BY_SOURCE", "NOT_CONFIGURED", "FAIL"]


class PipelineStageResult(BaseModel):
    name: str
    status: StageStatus
    count: int = 0
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnifiedCompanyAnalysisResponse(BaseModel):
    schema_version: str = "unified-financial-text-evidence-v1.0"
    ticker: str
    company_name: str | None = None
    generated_at: datetime
    stages: list[PipelineStageResult]
    financial_refresh: dict[str, Any] | None = None
    official_events_refresh: dict[str, Any] | None = None
    official_evidence_card: dict[str, Any] | None = None
    text_intelligence: dict[str, Any] | None = None
    narrative_shift: dict[str, Any] | None = None
    persistence: dict[str, int] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class StatementCoverageItem(BaseModel):
    statement: str
    status: Literal["SUPPORTED", "PARTIAL", "MISSING"]
    represented_by: list[str] = Field(default_factory=list)
    limitation: str | None = None


class FinancialStatementCoverageReport(BaseModel):
    schema_version: str = "financial-statement-coverage-v1.0"
    generated_at: datetime
    coverage: list[StatementCoverageItem]
    fourth_statement_status: Literal["SUPPORTED", "PARTIAL", "MISSING"]
    limitations: list[str] = Field(default_factory=list)
