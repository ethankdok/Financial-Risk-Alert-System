from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.ai_analysis_models import AIFinancialAnalysisReport
from app.financial_analysis_models import RuleSeverity


class FrontendMetricCard(BaseModel):
    code: str
    label: str
    category: str
    unit: str
    latest_value: float | None = None
    previous_value: float | None = None
    change_percent: float | None = None
    change_percentage_points: float | None = None
    formula: str
    period_values: dict[str, float] = Field(default_factory=dict)


class FrontendRuleCard(BaseModel):
    rule_id: str
    name: str
    category: str
    severity: RuleSeverity
    triggered: bool
    explanation: str
    threshold_description: str
    evidence_periods: list[str] = Field(default_factory=list)
    evidence_metrics: list[str] = Field(default_factory=list)
    rule_scope: str = "semiconductor_common"
    logic_expression: str | None = None
    actual_values: dict[str, float | None] = Field(default_factory=dict)


class FrontendSourceItem(BaseModel):
    source_name: str
    source_url: str
    period: str | None = None
    status: str


class FrontendAnalysisSnapshot(BaseModel):
    schema_version: str = "frontend-financial-snapshot-1.1.0"
    analysis_run_id: str
    ticker: str
    company_name: str
    industry: Literal["半導體"] = "半導體"
    subindustry: str
    generated_at: datetime
    data_updated_at: datetime
    overall_severity: RuleSeverity
    summary: str
    rule_version: str
    threshold_basis: str
    key_metrics: list[FrontendMetricCard] = Field(default_factory=list)
    rule_cards: list[FrontendRuleCard] = Field(default_factory=list)
    ai_analysis: AIFinancialAnalysisReport | None = None
    sources: list[FrontendSourceItem] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PersistenceCounts(BaseModel):
    filings: int = 0
    facts: int = 0
    metrics: int = 0
    rule_results: int = 0
    snapshots: int = 0


class CompanyRefreshResult(BaseModel):
    run_id: str
    ticker: str
    company_name: str
    subindustry: str
    trigger: Literal["scheduler", "manual", "demo", "startup"]
    source_mode: Literal["official", "demo_fixture"] = "official"
    status: Literal["completed", "failed"]
    started_at: datetime
    completed_at: datetime
    latest_report_period: str | None = None
    history_available_years: int = 0
    persistence: PersistenceCounts = Field(default_factory=PersistenceCounts)
    snapshot: FrontendAnalysisSnapshot | None = None
    ai_analysis: AIFinancialAnalysisReport | None = None
    error: str | None = None


class RefreshAllResult(BaseModel):
    started_at: datetime
    completed_at: datetime
    trigger: Literal["scheduler", "manual", "demo", "startup"]
    source_mode: Literal["official", "demo_fixture"] = "official"
    requested_companies: int
    completed_companies: int
    failed_companies: int
    results: list[CompanyRefreshResult] = Field(default_factory=list)


class AnalysisRunSummary(BaseModel):
    run_id: str
    ticker: str
    analysis_type: str
    trigger: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    rule_version: str | None = None
    overall_severity: str | None = None
    summary: str | None = None
    error_message: str | None = None
