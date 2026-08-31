from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RuleSeverity(str, Enum):
    POSITIVE = "positive"
    NORMAL = "normal"
    ATTENTION = "attention"
    HIGH_ATTENTION = "high_attention"
    DATA_ISSUE = "data_issue"
    INSUFFICIENT_DATA = "insufficient_data"


class SourceCoverage(BaseModel):
    source_name: str
    source_url: str
    status: Literal["available", "missing", "error"]
    report_period: str | None = None
    fields_found: list[str] = Field(default_factory=list)
    fields_missing: list[str] = Field(default_factory=list)


class NormalizedFinancialStatement(BaseModel):
    ticker: str
    company_name: str
    industry: Literal["半導體"] = "半導體"
    subindustry: str
    report_period: str | None = None
    monthly_revenue_period: str | None = None

    revenue: float | None = None
    gross_profit: float | None = None
    operating_income: float | None = None
    net_income: float | None = None
    eps: float | None = None

    cash_and_cash_equivalents: float | None = None
    inventory: float | None = None
    current_assets: float | None = None
    total_assets: float | None = None
    current_liabilities: float | None = None
    total_liabilities: float | None = None
    equity: float | None = None

    monthly_revenue: float | None = None
    previous_month_revenue: float | None = None
    prior_year_month_revenue: float | None = None
    monthly_revenue_mom_reported: float | None = None
    monthly_revenue_yoy_reported: float | None = None

    currency_unit: str = "新台幣仟元"
    source_coverage: list[SourceCoverage] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)


class CalculatedMetric(BaseModel):
    code: str
    label: str
    category: str
    value: float
    unit: str
    formula: str
    inputs: dict[str, float] = Field(default_factory=dict)
    source_fields: list[str] = Field(default_factory=list)


class RuleResult(BaseModel):
    rule_id: str
    name: str
    category: str
    severity: RuleSeverity
    triggered: bool
    metric_code: str
    actual_value: float | None = None
    unit: str | None = None
    threshold_description: str
    explanation: str
    evidence_metrics: list[str] = Field(default_factory=list)


class RuleCatalogItem(BaseModel):
    rule_id: str
    name: str
    category: str
    metric: str
    operator: str
    thresholds: dict[str, float] = Field(default_factory=dict)
    unit: str
    rationale: str


class RuleCatalogResponse(BaseModel):
    version: str
    industry: Literal["半導體"] = "半導體"
    threshold_basis: str
    rules: list[RuleCatalogItem]


class FinancialStatementAnalysisReport(BaseModel):
    ticker: str
    company_name: str
    industry: Literal["半導體"] = "半導體"
    subindustry: str
    report_period: str | None = None
    monthly_revenue_period: str | None = None
    analyzed_at: datetime
    rule_version: str
    threshold_basis: str
    overall_severity: RuleSeverity
    summary: str
    statement: NormalizedFinancialStatement
    metrics: list[CalculatedMetric]
    rule_results: list[RuleResult]
    limitations: list[str] = Field(default_factory=list)
