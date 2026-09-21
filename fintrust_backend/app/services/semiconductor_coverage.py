from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.models import CompanyMasterRecord
from app.services.semiconductor_subindustries import classified_tickers


RuleCoverageStatus = Literal["full", "partial", "common_only", "unsupported"]
AuditStatus = Literal["PASS", "PARTIAL", "FAIL"]


@dataclass(frozen=True)
class RuleCoverageProfile:
    status: RuleCoverageStatus
    overlay: str | None
    note: str


RULE_COVERAGE: dict[str, RuleCoverageProfile] = {
    "IC 設計": RuleCoverageProfile("full", "ic_design", "Common, semiconductor and IC-design monitorable/historical rules are available."),
    "記憶體製造": RuleCoverageProfile("full", "memory_manufacturing", "Commodity-cycle inventory, margin, CapEx and FCF overlay is available."),
    "半導體設備": RuleCoverageProfile("full", "semiconductor_equipment", "Demand and working-capital overlay is available; own CapEx is not treated as foundry CapEx."),
    "記憶體模組與儲存": RuleCoverageProfile("full", "memory_module_storage", "Inventory-price, margin and cash-conversion overlay is available."),
    "晶圓代工": RuleCoverageProfile("partial", "foundry", "Historical foundry overlay is available; monitorable layer remains common/semiconductor."),
    "封裝測試": RuleCoverageProfile("partial", "packaging_testing", "Historical packaging/testing overlay is available; monitorable layer remains common/semiconductor."),
    "分離元件與功率半導體": RuleCoverageProfile("common_only", None, "Only broadly applicable financial rules are enabled; a dedicated power-device overlay is pending."),
    "半導體材料與零組件": RuleCoverageProfile("common_only", None, "Only broadly applicable financial rules are enabled; a dedicated materials overlay is pending."),
    "光電與新型顯示半導體": RuleCoverageProfile("common_only", None, "Only broadly applicable financial rules are enabled; a dedicated optoelectronics overlay is pending."),
}

BASE_REQUIRED_FACTS = {
    "revenue",
    "gross_profit",
    "net_income",
    "total_assets",
    "total_liabilities",
    "operating_cash_flow",
}
BASE_REQUIRED_METRICS = {
    "revenue_growth_yoy",
    "gross_margin",
    "operating_cash_flow",
    "cash_conversion_ratio",
    "debt_ratio",
}
SUBINDUSTRY_REQUIRED_FACTS: dict[str, set[str]] = {
    "晶圓代工": {"inventory", "capital_expenditure"},
    "IC 設計": {"inventory", "research_and_development_expense"},
    "封裝測試": {"inventory", "current_assets", "current_liabilities"},
    "記憶體製造": {"inventory", "capital_expenditure"},
    "半導體設備": {"inventory", "accounts_receivable", "research_and_development_expense"},
    "記憶體模組與儲存": {"inventory", "current_assets", "current_liabilities"},
}
SUBINDUSTRY_REQUIRED_METRICS: dict[str, set[str]] = {
    "晶圓代工": {"inventory_growth_yoy", "capex_intensity", "free_cash_flow"},
    "IC 設計": {"rd_intensity", "inventory_growth_yoy"},
    "封裝測試": {"inventory_growth_yoy", "current_ratio"},
    "記憶體製造": {"inventory_growth_yoy", "capex_intensity", "free_cash_flow"},
    "半導體設備": {"inventory_growth_yoy", "receivable_turnover_days", "rd_intensity"},
    "記憶體模組與儲存": {"inventory_growth_yoy", "current_ratio"},
}


def rule_coverage_for(subindustry: str) -> RuleCoverageProfile:
    return RULE_COVERAGE.get(subindustry, RuleCoverageProfile("unsupported", None, "Subindustry is unclassified or outside the current semiconductor rule scope."))


def technically_supported(subindustry: str) -> bool:
    return rule_coverage_for(subindustry).status != "unsupported"


def production_batch_policy() -> dict[str, object]:
    path = Path(__file__).resolve().parents[1] / "rules" / "semiconductor_batch_policy.json"
    return json.loads(path.read_text(encoding="utf-8"))


def production_excluded_tickers() -> dict[str, str]:
    policy = production_batch_policy()
    return {
        str(item["ticker"]): str(item["reason"])
        for item in policy.get("excluded", [])
    }


def production_eligible_tickers() -> tuple[str, ...]:
    excluded = production_excluded_tickers()
    return tuple(sorted(classified_tickers() - set(excluded)))


class CompanyCoverageRecord(BaseModel):
    ticker: str
    company: str
    subindustry: str
    filing_available: int = 0
    filing_requested: int = 0
    filing_coverage_ratio: float = 0.0
    financial_fact_available: int = 0
    financial_fact_required: int = 0
    financial_fact_coverage_ratio: float = 0.0
    metric_available: int = 0
    metric_required: int = 0
    metric_coverage_ratio: float = 0.0
    rule_coverage_status: RuleCoverageStatus
    filing_diagnostics: list[str] = Field(default_factory=list)
    missing_concepts: list[str] = Field(default_factory=list)
    missing_metrics: list[str] = Field(default_factory=list)
    data_coverage: AuditStatus
    analysis_coverage: AuditStatus
    final_status: AuditStatus
    error: str | None = None


class SemiconductorCoverageReport(BaseModel):
    generated_at: datetime
    scope: str
    requested_companies: int
    pass_count: int
    partial_count: int
    fail_count: int
    companies: list[CompanyCoverageRecord]


def assess_company_coverage(
    company: CompanyMasterRecord,
    report: HistoricalFinancialAnalysisReport | None,
    *,
    error: str | None = None,
) -> CompanyCoverageRecord:
    rule_profile = rule_coverage_for(company.subindustry)
    if report is None:
        return CompanyCoverageRecord(
            ticker=company.ticker,
            company=company.name,
            subindustry=company.subindustry,
            rule_coverage_status=rule_profile.status,
            data_coverage="FAIL",
            analysis_coverage="FAIL",
            final_status="FAIL",
            error=error or "No historical analysis report was produced.",
        )
    available_periods = [period for period in report.periods if period.status == "available"]
    filing_diagnostics = [
        f"{period.period}: {period.status}: {'; '.join(period.warnings) or 'No additional source diagnostic.'}"
        for period in report.periods
        if period.status != "available"
    ]
    required_facts = BASE_REQUIRED_FACTS | SUBINDUSTRY_REQUIRED_FACTS.get(company.subindustry, set())
    found_facts = {field for period in available_periods for field in period.fields_found}
    missing_facts = sorted(required_facts - found_facts)
    metrics_with_values = {metric.code for metric in report.trend_metrics if metric.period_values}
    required_metrics = BASE_REQUIRED_METRICS | SUBINDUSTRY_REQUIRED_METRICS.get(company.subindustry, set())
    missing_metrics = sorted(required_metrics - metrics_with_values)
    filing_ratio = len(available_periods) / report.requested_years if report.requested_years else 0.0
    fact_ratio = len(required_facts & found_facts) / len(required_facts) if required_facts else 1.0
    metric_ratio = len(required_metrics & metrics_with_values) / len(required_metrics) if required_metrics else 1.0
    if len(available_periods) >= 3 and fact_ratio >= 0.75 and metric_ratio >= 0.75:
        data_status: AuditStatus = "PASS"
    elif available_periods:
        data_status = "PARTIAL"
    else:
        data_status = "FAIL"
    if data_status == "FAIL" or rule_profile.status == "unsupported":
        analysis_status: AuditStatus = "FAIL"
    elif data_status == "PASS" and rule_profile.status == "full" and not missing_metrics:
        analysis_status = "PASS"
    else:
        analysis_status = "PARTIAL"
    return CompanyCoverageRecord(
        ticker=company.ticker,
        company=company.name,
        subindustry=company.subindustry,
        filing_available=len(available_periods),
        filing_requested=report.requested_years,
        filing_coverage_ratio=round(filing_ratio, 4),
        financial_fact_available=len(required_facts & found_facts),
        financial_fact_required=len(required_facts),
        financial_fact_coverage_ratio=round(fact_ratio, 4),
        metric_available=len(required_metrics & metrics_with_values),
        metric_required=len(required_metrics),
        metric_coverage_ratio=round(metric_ratio, 4),
        rule_coverage_status=rule_profile.status,
        filing_diagnostics=filing_diagnostics,
        missing_concepts=missing_facts,
        missing_metrics=missing_metrics,
        data_coverage=data_status,
        analysis_coverage=analysis_status,
        final_status=analysis_status,
        error=error,
    )


def build_coverage_report(scope: str, records: list[CompanyCoverageRecord]) -> SemiconductorCoverageReport:
    return SemiconductorCoverageReport(
        generated_at=datetime.now(timezone.utc),
        scope=scope,
        requested_companies=len(records),
        pass_count=sum(record.final_status == "PASS" for record in records),
        partial_count=sum(record.final_status == "PARTIAL" for record in records),
        fail_count=sum(record.final_status == "FAIL" for record in records),
        companies=records,
    )
