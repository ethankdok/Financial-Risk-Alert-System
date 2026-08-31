from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.financial_analysis_models import RuleSeverity


class AnalysisDimension(str, Enum):
    GROWTH = "growth"
    PROFITABILITY = "profitability"
    RD_INNOVATION = "rd_innovation"
    OPERATING_EFFICIENCY = "operating_efficiency"
    CASH_FLOW = "cash_flow"
    FINANCIAL_STRUCTURE = "financial_structure"
    EARNINGS_QUALITY = "earnings_quality"
    INVESTMENT_EFFICIENCY = "investment_efficiency"


DIMENSION_LABELS: dict[AnalysisDimension, str] = {
    AnalysisDimension.GROWTH: "成長性",
    AnalysisDimension.PROFITABILITY: "獲利能力",
    AnalysisDimension.RD_INNOVATION: "研發與創新",
    AnalysisDimension.OPERATING_EFFICIENCY: "營運效率",
    AnalysisDimension.CASH_FLOW: "現金流品質",
    AnalysisDimension.FINANCIAL_STRUCTURE: "財務結構",
    AnalysisDimension.EARNINGS_QUALITY: "盈餘品質",
    AnalysisDimension.INVESTMENT_EFFICIENCY: "投入轉化效率",
}


class DimensionSignal(str, Enum):
    POSITIVE = "positive"
    NORMAL = "normal"
    ATTENTION = "attention"
    HIGH_ATTENTION = "high_attention"
    MIXED = "mixed"
    INSUFFICIENT_DATA = "insufficient_data"


class RuleEvaluationStatus(str, Enum):
    EVALUATED = "evaluated"
    INSUFFICIENT_DATA = "insufficient_data"
    ERROR = "error"


class AnalysisFeatureValue(BaseModel):
    code: str
    value: float
    unit: str
    label: str
    source_metrics: list[str] = Field(default_factory=list)
    formula: str


class MonitoredRuleResult(BaseModel):
    rule_id: str
    name: str
    rule_scope: Literal["common", "semiconductor", "ic_design"]
    rule_version: str
    dimension: AnalysisDimension
    dimension_label: str
    assessment_type: Literal["direct", "indirect", "cross_factor", "trend"]
    severity: RuleSeverity
    evaluation_status: RuleEvaluationStatus
    triggered: bool
    logic_expression: str
    rationale: str
    threshold_basis: str
    evidence_basis: str
    evidence_references: list[str] = Field(default_factory=list)
    direct_metrics: list[str] = Field(default_factory=list)
    indirect_metrics: list[str] = Field(default_factory=list)
    required_features: list[str] = Field(default_factory=list)
    missing_features: list[str] = Field(default_factory=list)
    actual_values: dict[str, float | None] = Field(default_factory=dict)


class DimensionAssessment(BaseModel):
    dimension: AnalysisDimension
    label: str
    signal: DimensionSignal
    coverage_ratio: float = Field(ge=0.0, le=1.0)
    evaluated_rules: int
    total_rules: int
    triggered_rule_ids: list[str] = Field(default_factory=list)
    direct_metrics: list[str] = Field(default_factory=list)
    indirect_metrics: list[str] = Field(default_factory=list)
    summary: str


class AnalysisRuleCatalogItem(BaseModel):
    rule_id: str
    name: str
    rule_scope: Literal["common", "semiconductor", "ic_design"]
    rule_version: str
    dimension: AnalysisDimension
    dimension_label: str
    assessment_type: Literal["direct", "indirect", "cross_factor", "trend"]
    severity: RuleSeverity
    logic_expression: str
    rationale: str
    threshold_basis: str
    evidence_basis: str
    evidence_references: list[str] = Field(default_factory=list)
    direct_metrics: list[str] = Field(default_factory=list)
    indirect_metrics: list[str] = Field(default_factory=list)
    required_features: list[str] = Field(default_factory=list)


class AnalysisRuleCatalogResponse(BaseModel):
    version: str
    subindustry: str
    rule_count: int
    rule_scope_counts: dict[str, int] = Field(default_factory=dict)
    dimensions: list[AnalysisDimension]
    rules: list[AnalysisRuleCatalogItem]


class LLMNarrative(BaseModel):
    executive_summary: str
    dimension_insights: dict[str, str] = Field(default_factory=dict)
    watch_items: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class LLMAnalysisTrace(BaseModel):
    enabled: bool
    status: Literal["not_configured", "skipped", "completed", "failed"]
    endpoint_configured: bool
    provider: str | None = None
    provider_configured: bool | None = None
    model: str | None = None
    prompt_version: str = "financial-analysis-v1"
    latency_ms: int | None = None
    used_rule_ids: list[str] = Field(default_factory=list)
    error: str | None = None


class AIFinancialAnalysisReport(BaseModel):
    ticker: str
    company_name: str
    industry: Literal["半導體"] = "半導體"
    subindustry: str
    analyzed_at: datetime
    source_period_start: int | None = None
    source_period_end: int | None = None
    source_method: str
    analysis_engine_version: str
    rule_catalog_version: str
    feature_count: int
    features: list[AnalysisFeatureValue]
    dimension_assessments: list[DimensionAssessment]
    rule_monitoring: list[MonitoredRuleResult]
    deterministic_summary: str
    llm_narrative: LLMNarrative | None = None
    llm_trace: LLMAnalysisTrace
    limitations: list[str] = Field(default_factory=list)
