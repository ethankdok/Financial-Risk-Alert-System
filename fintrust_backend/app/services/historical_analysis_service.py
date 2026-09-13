from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.financial_analysis_models import RuleSeverity
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.services.company_registry import get_company
from app.services.financial_analysis_service import UnsupportedCompanyError
from app.services.financial_field_extensions import (
    register_analysis_field_aliases,
    register_persistence_fields,
)
from app.services.historical_metrics import calculate_historical_metrics
from app.services.historical_rule_engine import HistoricalFinancialRuleEngine
from app.services.robust_mops_inline_xbrl import RobustMopsInlineXbrlClient


class HistoricalFinancialAnalysisService:
    def __init__(
        self,
        *,
        mops_client: Any | None = None,
        rule_engine: HistoricalFinancialRuleEngine | None = None,
    ) -> None:
        register_analysis_field_aliases()
        register_persistence_fields()
        self.mops_client = mops_client or RobustMopsInlineXbrlClient()
        self.rule_engine = rule_engine

    @staticmethod
    def _overall_severity(rule_results) -> RuleSeverity:
        severities = {result.severity for result in rule_results}
        if RuleSeverity.DATA_ISSUE in severities:
            return RuleSeverity.DATA_ISSUE
        if RuleSeverity.HIGH_ATTENTION in severities:
            return RuleSeverity.HIGH_ATTENTION
        if RuleSeverity.ATTENTION in severities:
            return RuleSeverity.ATTENTION
        if RuleSeverity.INSUFFICIENT_DATA in severities:
            return RuleSeverity.INSUFFICIENT_DATA
        if RuleSeverity.POSITIVE in severities:
            return RuleSeverity.POSITIVE
        return RuleSeverity.NORMAL

    @staticmethod
    def _summary(company_name: str, available_years: int, rule_results, overall: RuleSeverity) -> str:
        high = sum(result.severity == RuleSeverity.HIGH_ATTENTION for result in rule_results)
        attention = sum(result.severity == RuleSeverity.ATTENTION for result in rule_results)
        data_issues = sum(result.severity == RuleSeverity.DATA_ISSUE for result in rule_results)
        positive = sum(result.severity == RuleSeverity.POSITIVE for result in rule_results)
        insufficient = sum(result.severity == RuleSeverity.INSUFFICIENT_DATA for result in rule_results)
        return (
            f"{company_name}已取得 {available_years} 個可用年度的 MOPS iXBRL 申報；"
            f"『可用』代表核心科目足以進行部分分析，不代表所有規則欄位皆完整。"
            f"歷史規則結果為高關注 {high} 項、需注意 {attention} 項、"
            f"資料問題 {data_issues} 項、趨勢觀察 {positive} 項、"
            f"資料不足 {insufficient} 項，整體狀態為 {overall.value}。"
        )

    async def analyze(
        self,
        ticker: str,
        *,
        years: int = 5,
        end_roc_year: int | None = None,
    ) -> HistoricalFinancialAnalysisReport:
        profile = get_company(ticker)
        if profile is None:
            raise UnsupportedCompanyError(
                "MVP 僅分析已登錄的半導體公司；請先將公司加入 semiconductor registry。"
            )

        periods = await self.mops_client.fetch_history(profile, years=years, end_roc_year=end_roc_year)
        available = [period for period in periods if period.status == "available"]
        metrics = calculate_historical_metrics(periods)
        rule_engine = self.rule_engine or HistoricalFinancialRuleEngine(subindustry=profile.subindustry)
        rule_results = rule_engine.evaluate(periods, metrics)
        overall = self._overall_severity(rule_results)

        failed_periods = [period for period in periods if period.status != "available"]
        missing_metric_codes = sorted(metric.code for metric in metrics if not metric.period_values)
        limitations = [
            "第一版只使用 MOPS 第 4 季／年度合併財報，避免把第二、三季累計數誤當成單季數值。",
            "MOPS iXBRL taxonomy 與公司自訂概念可能跨年度變動；無法可靠映射的欄位會標為資料不足。",
            "系統依公司 registry 的半導體子產業載入共通規則與子產業複合規則。",
            "規則門檻是可調整的 MVP 預設值，後續仍需使用同子產業中位數與 MAD 校準。",
            "歷史規則結果只提供財務趨勢與風險提示，不構成投資建議或最終企業評價。",
        ]
        if missing_metric_codes:
            limitations.append(
                "本次無法產生的歷史指標：" + "、".join(missing_metric_codes)
                + "。依賴這些指標的規則保留為資料不足。"
            )
        if failed_periods:
            limitations.append(
                "部分年度無法完整取得或解析："
                + "、".join(period.period for period in failed_periods)
                + "。系統保留錯誤狀態，不以零值補齊。"
            )

        years_present = [period.fiscal_year for period in available]
        return HistoricalFinancialAnalysisReport(
            ticker=profile.ticker,
            company_name=profile.name,
            subindustry=profile.subindustry,
            requested_years=years,
            available_years=len(available),
            start_year=min(years_present) if years_present else None,
            end_year=max(years_present) if years_present else None,
            analyzed_at=datetime.now(timezone.utc),
            rule_version=rule_engine.version,
            threshold_basis=rule_engine.threshold_basis,
            overall_severity=overall,
            summary=self._summary(profile.name, len(available), rule_results, overall),
            periods=periods,
            trend_metrics=metrics,
            rule_results=rule_results,
            limitations=list(dict.fromkeys(limitations)),
        )
