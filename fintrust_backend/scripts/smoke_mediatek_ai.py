from __future__ import annotations

import asyncio
import json

from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService
from app.services.monitorable_rule_engine import MonitorableFinancialRuleEngine


async def main() -> None:
    # ROC 111-113 / 2022-2024 are stable, fully published annual filings.
    historical = await HistoricalFinancialAnalysisService().analyze(
        "2454",
        years=3,
        end_roc_year=113,
    )
    ai = await AIFinancialAnalysisService().analyze_report(historical, use_llm=False)
    catalog = MonitorableFinancialRuleEngine().catalog()
    metric_map = {metric.code: metric for metric in historical.trend_metrics}
    result = {
        "ticker": historical.ticker,
        "company": historical.company_name,
        "subindustry": historical.subindustry,
        "available_years": historical.available_years,
        "periods": [
            {
                "period": period.period,
                "status": period.status,
                "has_cost_of_goods_sold": period.cost_of_goods_sold is not None,
                "has_accounts_receivable": period.accounts_receivable is not None,
                "has_rd_expense": period.research_and_development_expense is not None,
                "fields_missing": period.fields_missing,
            }
            for period in historical.periods
        ],
        "required_metric_coverage": {
            code: bool(metric_map.get(code) and metric_map[code].period_values)
            for code in [
                "revenue_growth_yoy",
                "gross_margin",
                "operating_margin",
                "rd_intensity",
                "inventory_growth_yoy",
                "inventory_turnover_days",
                "receivable_turnover_days",
                "cash_conversion_ratio",
            ]
        },
        "analysis_engine_version": ai.analysis_engine_version,
        "rule_catalog_version": ai.rule_catalog_version,
        "rule_count": len(ai.rule_monitoring),
        "rule_scope_counts": catalog.rule_scope_counts,
        "dimension_count": len(ai.dimension_assessments),
        "dimension_signals": {
            item.dimension.value: item.signal.value for item in ai.dimension_assessments
        },
        "insufficient_rule_ids": [
            item.rule_id
            for item in ai.rule_monitoring
            if item.evaluation_status.value == "insufficient_data"
        ],
        "llm_status": ai.llm_trace.status,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if historical.available_years < 3:
        raise RuntimeError("聯發科 live smoke 未取得三個完整年度。")
    for required in (
        "revenue_growth_yoy",
        "gross_margin",
        "operating_margin",
        "rd_intensity",
        "inventory_growth_yoy",
        "cash_conversion_ratio",
    ):
        metric = metric_map.get(required)
        if metric is None or not metric.period_values:
            raise RuntimeError(f"聯發科 live smoke 缺少核心分析指標：{required}")
    if len(ai.rule_monitoring) != 24:
        raise RuntimeError(f"AI layered rule count 異常：{len(ai.rule_monitoring)}")
    if len(ai.dimension_assessments) != 8:
        raise RuntimeError(f"AI dimension count 異常：{len(ai.dimension_assessments)}")


if __name__ == "__main__":
    asyncio.run(main())
