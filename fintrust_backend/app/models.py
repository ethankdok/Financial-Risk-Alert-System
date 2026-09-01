from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class VerificationVerdict(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NOT_APPLICABLE = "not_applicable"


class ClaimDirection(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    HIGHER_THAN = "higher_than"
    LOWER_THAN = "lower_than"
    EQUAL = "equal"
    UNSPECIFIED = "unspecified"


class ComparisonKind(str, Enum):
    VALUE = "value"
    YOY = "yoy"
    QOQ = "qoq"
    PERCENTAGE_POINT = "percentage_point"
    DIRECTION_ONLY = "direction_only"


class CompanyProfile(BaseModel):
    ticker: str
    name: str
    subindustry: str
    aliases: list[str]


class ExtractedFinancialClaim(BaseModel):
    original_text: str
    ticker: str | None = None
    company_name: str | None = None
    semiconductor_subindustry: str | None = None
    metric: str | None = None
    period: str | None = None
    comparison_period: str | None = None
    comparison_kind: ComparisonKind | None = None
    direction: ClaimDirection = ClaimDirection.UNSPECIFIED
    claimed_value: float | None = None
    claimed_change_percent: float | None = None
    claimed_percentage_points: float | None = None
    unit: str | None = None
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)


class FinancialFact(BaseModel):
    ticker: str
    company_name: str
    semiconductor_subindustry: str
    metric: str
    period: str
    value: float
    unit: str
    statement_type: Literal[
        "income_statement", "balance_sheet", "cash_flow", "monthly_revenue"
    ]
    source_kind: Literal["mops_xbrl", "twse_openapi", "mvp_fixture"]
    source_url: str
    filed_at: datetime
    taxonomy_concept: str | None = None
    statement_scope: Literal["consolidated", "individual", "unknown"] = "unknown"
    is_demo: bool = False


class FactIngestRequest(BaseModel):
    facts: list[FinancialFact]


class ClaimExtractionRequest(BaseModel):
    text: str = Field(min_length=2, max_length=5000)
    ticker: str | None = None
    period: str | None = None
    comparison_period: str | None = None


class ClaimVerificationRequest(ClaimExtractionRequest):
    tolerance_percentage_points: float = Field(default=2.0, ge=0.0, le=20.0)


class EvidenceCalculation(BaseModel):
    metric: str
    period: str
    comparison_period: str | None = None
    current_value: float | None = None
    comparison_value: float | None = None
    unit: str | None = None
    formula: str | None = None
    calculated_value: float | None = None
    tolerance_percentage_points: float | None = None
    source_urls: list[str] = Field(default_factory=list)
    is_demo: bool = False


class ClaimVerificationResult(BaseModel):
    claim: ExtractedFinancialClaim
    verdict: VerificationVerdict
    explanation: str
    difference: float | None = None
    evidence: EvidenceCalculation | None = None
    limitations: list[str] = Field(default_factory=list)


class CompanyListResponse(BaseModel):
    industry: Literal["半導體"] = "半導體"
    companies: list[CompanyProfile]
    note: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    module: str
    industry: Literal["半導體"] = "半導體"
    method: str
    readiness_scope: Literal["configuration_only"] = "configuration_only"
    persistence_backend: str = "configured_by_environment"
    twse_openapi_ready: bool = True
    rule_engine_ready: bool = True
    historical_xbrl_ready: bool
    note: str = (
        "Health 僅確認服務、依賴與設定可載入；官方資料完整度須以 refresh、"
        "latest snapshot 與 pipeline audit 驗證。"
    )
