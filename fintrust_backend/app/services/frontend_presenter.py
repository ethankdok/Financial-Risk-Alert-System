from __future__ import annotations

from datetime import datetime, timezone

from app.financial_analysis_models import FinancialStatementAnalysisReport, RuleSeverity
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.pipeline_models import (
    FrontendAnalysisSnapshot,
    FrontendMetricCard,
    FrontendRuleCard,
    FrontendSourceItem,
)


SUBINDUSTRY_METRICS: dict[str, list[str]] = {
    "晶圓代工": [
        "capex_intensity",
        "free_cash_flow",
        "gross_margin",
        "operating_margin",
        "cash_conversion_ratio",
        "debt_ratio",
    ],
    "IC 設計": [
        "rd_intensity",
        "gross_margin",
        "revenue_growth_yoy",
        "inventory_growth_yoy",
        "cash_conversion_ratio",
        "operating_margin",
    ],
    "封裝測試": [
        "capex_intensity",
        "inventory_growth_yoy",
        "revenue_growth_yoy",
        "operating_cash_flow",
        "debt_ratio",
        "current_ratio",
    ],
}

SEVERITY_ORDER = {
    RuleSeverity.HIGH_ATTENTION: 0,
    RuleSeverity.ATTENTION: 1,
    RuleSeverity.DATA_ISSUE: 2,
    RuleSeverity.INSUFFICIENT_DATA: 3,
    RuleSeverity.POSITIVE: 4,
    RuleSeverity.NORMAL: 5,
}

BLOCKING_SEVERITIES = {
    RuleSeverity.DATA_ISSUE,
    RuleSeverity.HIGH_ATTENTION,
    RuleSeverity.ATTENTION,
    RuleSeverity.INSUFFICIENT_DATA,
}


def _count_rules(rule_results, severity: RuleSeverity) -> int:
    return sum(result.severity == severity for result in rule_results)


def _combined_overall(
    latest_report: FinancialStatementAnalysisReport,
    historical_report: HistoricalFinancialAnalysisReport,
) -> RuleSeverity:
    """Prioritize the annual MOPS rule coverage used by the front-end snapshot.

    The TWSE latest endpoint is useful as a same-run latest-data reference, but
    its OpenAPI datasets do not expose every field needed by the annual
    semiconductor rule engine.  A latest-layer `insufficient_data` therefore
    should not make the combined read model look failed when the MOPS annual
    pipeline produced complete historical metrics and rules.
    """

    if historical_report.overall_severity in BLOCKING_SEVERITIES:
        return historical_report.overall_severity
    if latest_report.overall_severity in {
        RuleSeverity.DATA_ISSUE,
        RuleSeverity.HIGH_ATTENTION,
        RuleSeverity.ATTENTION,
    }:
        return latest_report.overall_severity
    if RuleSeverity.POSITIVE in {
        historical_report.overall_severity,
        latest_report.overall_severity,
    }:
        return RuleSeverity.POSITIVE
    return RuleSeverity.NORMAL


def _snapshot_summary(
    latest_report: FinancialStatementAnalysisReport,
    historical_report: HistoricalFinancialAnalysisReport,
) -> str:
    start = historical_report.start_year
    end = historical_report.end_year
    period_text = f"{start}–{end}" if start and end else "近年"
    high = _count_rules(historical_report.rule_results, RuleSeverity.HIGH_ATTENTION)
    attention = _count_rules(historical_report.rule_results, RuleSeverity.ATTENTION)
    data_issue = _count_rules(historical_report.rule_results, RuleSeverity.DATA_ISSUE)
    insufficient = _count_rules(historical_report.rule_results, RuleSeverity.INSUFFICIENT_DATA)
    positive = _count_rules(historical_report.rule_results, RuleSeverity.POSITIVE)
    normal = _count_rules(historical_report.rule_results, RuleSeverity.NORMAL)
    available = historical_report.available_years
    rule_count = len(historical_report.rule_results)
    metric_count = sum(1 for metric in historical_report.trend_metrics if metric.period_values)

    return (
        f"{historical_report.company_name}已完成官方財報資料管線：TWSE 最新快照與 "
        f"MOPS {period_text} 年度合併 iXBRL。後端已取得 {available} 個可用年度，"
        f"產生 {metric_count} 類歷史財務指標與 {rule_count} 條半導體／"
        f"{historical_report.subindustry}規則。歷史規則結果：高關注 {high} 項、"
        f"需注意 {attention} 項、資料問題 {data_issue} 項、資料不足 {insufficient} 項、"
        f"正向觀察 {positive} 項、正常 {normal} 項。此 snapshot 已保存為前端可直接讀取的最新分析結果。"
    )


def build_frontend_snapshot(
    *,
    run_id: str,
    latest_report: FinancialStatementAnalysisReport,
    historical_report: HistoricalFinancialAnalysisReport,
) -> FrontendAnalysisSnapshot:
    metric_map = {metric.code: metric for metric in historical_report.trend_metrics}
    preferred = SUBINDUSTRY_METRICS.get(
        historical_report.subindustry,
        ["revenue_growth_yoy", "gross_margin", "operating_margin", "free_cash_flow"],
    )
    key_metrics = [
        FrontendMetricCard(
            code=metric.code,
            label=metric.label,
            category=metric.category,
            unit=metric.unit,
            latest_value=metric.latest_value,
            previous_value=metric.previous_value,
            change_percent=metric.change_percent,
            change_percentage_points=metric.change_percentage_points,
            formula=metric.formula,
            period_values=metric.period_values,
        )
        for code in preferred
        if (metric := metric_map.get(code)) is not None and metric.period_values
    ]

    rules = sorted(
        historical_report.rule_results,
        key=lambda result: (SEVERITY_ORDER[result.severity], result.rule_id),
    )
    rule_cards = [
        FrontendRuleCard(
            rule_id=result.rule_id,
            name=result.name,
            category=result.category,
            severity=result.severity,
            triggered=result.triggered,
            explanation=result.explanation,
            threshold_description=result.threshold_description,
            evidence_periods=result.evidence_periods,
            evidence_metrics=result.evidence_metrics,
            rule_scope=getattr(result, "rule_scope", "semiconductor_common"),
            logic_expression=getattr(result, "logic_expression", None),
            actual_values=getattr(result, "actual_values", {}),
        )
        for result in rules
    ]

    sources: list[FrontendSourceItem] = []
    seen: set[tuple[str, str, str | None]] = set()
    for period in historical_report.periods:
        key = (period.source_name, period.source_url, period.period)
        if key not in seen:
            seen.add(key)
            sources.append(
                FrontendSourceItem(
                    source_name=period.source_name,
                    source_url=period.source_url,
                    period=period.period,
                    status=period.status,
                )
            )
    for coverage in latest_report.statement.source_coverage:
        key = (coverage.source_name, coverage.source_url, coverage.report_period)
        if key not in seen:
            seen.add(key)
            sources.append(
                FrontendSourceItem(
                    source_name=coverage.source_name,
                    source_url=coverage.source_url,
                    period=coverage.report_period,
                    status=coverage.status,
                )
            )

    return FrontendAnalysisSnapshot(
        analysis_run_id=run_id,
        ticker=historical_report.ticker,
        company_name=historical_report.company_name,
        subindustry=historical_report.subindustry,
        generated_at=datetime.now(timezone.utc),
        data_updated_at=max(latest_report.analyzed_at, historical_report.analyzed_at),
        overall_severity=_combined_overall(latest_report, historical_report),
        summary=_snapshot_summary(latest_report, historical_report),
        rule_version=historical_report.rule_version,
        threshold_basis=historical_report.threshold_basis,
        key_metrics=key_metrics,
        rule_cards=rule_cards,
        sources=sources,
        limitations=list(
            dict.fromkeys(latest_report.limitations + historical_report.limitations)
        ),
    )
