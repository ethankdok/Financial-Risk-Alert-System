from __future__ import annotations

from datetime import datetime, timezone

from app.financial_analysis_models import (
    FinancialStatementAnalysisReport,
    RuleSeverity,
)
from app.services.company_registry import get_company
from app.services.financial_metrics import calculate_financial_metrics
from app.services.financial_rule_engine import FinancialRuleEngine
from app.services.statement_normalizer import normalize_twse_bundle
from app.services.twse_openapi import TwseOpenApiClient


class UnsupportedCompanyError(ValueError):
    pass


class FinancialAnalysisService:
    def __init__(
        self,
        *,
        twse_client: TwseOpenApiClient | None = None,
        rule_engine: FinancialRuleEngine | None = None,
    ) -> None:
        self.twse_client = twse_client or TwseOpenApiClient()
        self.rule_engine = rule_engine or FinancialRuleEngine()

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
    def _summary(company_name: str, rule_results, overall: RuleSeverity) -> str:
        high = sum(result.severity == RuleSeverity.HIGH_ATTENTION for result in rule_results)
        attention = sum(result.severity == RuleSeverity.ATTENTION for result in rule_results)
        data_issues = sum(result.severity == RuleSeverity.DATA_ISSUE for result in rule_results)
        positive = sum(result.severity == RuleSeverity.POSITIVE for result in rule_results)
        insufficient = sum(
            result.severity == RuleSeverity.INSUFFICIENT_DATA for result in rule_results
        )
        return (
            f"{company_name}本次規則分析結果：高關注 {high} 項、需注意 {attention} 項、"
            f"資料一致性問題 {data_issues} 項、正向觀察 {positive} 項、"
            f"資料不足 {insufficient} 項；整體狀態為 {overall.value}。"
        )

    async def analyze(self, ticker: str) -> FinancialStatementAnalysisReport:
        profile = get_company(ticker)
        if profile is None:
            raise UnsupportedCompanyError(
                "MVP 僅分析已登錄的半導體公司；請先將公司加入 semiconductor registry。"
            )

        bundle = await self.twse_client.fetch_company_bundle(profile.ticker)
        statement = normalize_twse_bundle(profile, bundle)
        metrics = calculate_financial_metrics(statement)
        rule_results = self.rule_engine.evaluate(metrics)
        overall = self._overall_severity(rule_results)

        limitations = [
            "TWSE OpenAPI 財務報表資料集屬最新公開快照；此端點本身不提供任意歷史期間查詢。",
            "完整 pipeline 會另由 MOPS Inline XBRL 取得 3–5 年年度資料並執行歷史與子產業規則。",
            "目前門檻為版本化、可調整的 MVP 預設值，不應解讀為所有半導體子產業的永久標準。",
            "規則結果是財務風險與趨勢提示，不構成投資建議或最終企業評價。",
        ]
        limitations.extend(statement.data_quality_warnings)

        return FinancialStatementAnalysisReport(
            ticker=profile.ticker,
            company_name=profile.name,
            subindustry=profile.subindustry,
            report_period=statement.report_period,
            monthly_revenue_period=statement.monthly_revenue_period,
            analyzed_at=datetime.now(timezone.utc),
            rule_version=self.rule_engine.version,
            threshold_basis=self.rule_engine.threshold_basis,
            overall_severity=overall,
            summary=self._summary(profile.name, rule_results, overall),
            statement=statement,
            metrics=metrics,
            rule_results=rule_results,
            limitations=list(dict.fromkeys(limitations)),
        )
