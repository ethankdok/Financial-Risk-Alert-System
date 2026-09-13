from __future__ import annotations

from datetime import datetime, timezone

from app.ai_analysis_models import (
    AIFinancialAnalysisReport,
    AnalysisDimension,
    DIMENSION_LABELS,
    DimensionAssessment,
    DimensionSignal,
    LLMAnalysisTrace,
    MonitoredRuleResult,
    RuleEvaluationStatus,
)
from app.financial_analysis_models import RuleSeverity
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.services.analysis_feature_engine import AnalysisFeatureEngine
from app.services.llm_provider_protocol import FinancialLLMProvider, create_financial_llm_provider
from app.services.monitorable_rule_engine import MonitorableFinancialRuleEngine


class AIFinancialAnalysisService:
    version = "ai-financial-analysis-0.2.0"
    supported_subindustries = {"IC 設計"}

    def __init__(
        self,
        *,
        feature_engine: AnalysisFeatureEngine | None = None,
        rule_engine: MonitorableFinancialRuleEngine | None = None,
        llm_analyst: FinancialLLMProvider | None = None,
    ) -> None:
        self.feature_engine = feature_engine or AnalysisFeatureEngine()
        self.rule_engine = rule_engine
        self.llm_analyst = llm_analyst or create_financial_llm_provider()

    @classmethod
    def supports(cls, subindustry: str) -> bool:
        return subindustry in cls.supported_subindustries

    @staticmethod
    def _signal(results: list[MonitoredRuleResult]) -> DimensionSignal:
        evaluated = [item for item in results if item.evaluation_status == RuleEvaluationStatus.EVALUATED]
        if not evaluated:
            return DimensionSignal.INSUFFICIENT_DATA
        triggered = [item for item in evaluated if item.triggered]
        severities = {item.severity for item in triggered}
        if RuleSeverity.HIGH_ATTENTION in severities:
            return DimensionSignal.HIGH_ATTENTION
        if RuleSeverity.ATTENTION in severities and RuleSeverity.POSITIVE in severities:
            return DimensionSignal.MIXED
        if RuleSeverity.ATTENTION in severities:
            return DimensionSignal.ATTENTION
        if RuleSeverity.POSITIVE in severities:
            return DimensionSignal.POSITIVE
        return DimensionSignal.NORMAL

    @classmethod
    def _dimension_assessments(cls, rules: list[MonitoredRuleResult]) -> list[DimensionAssessment]:
        assessments: list[DimensionAssessment] = []
        for dimension in AnalysisDimension:
            items = [item for item in rules if item.dimension == dimension]
            if not items:
                continue
            evaluated = [item for item in items if item.evaluation_status == RuleEvaluationStatus.EVALUATED]
            triggered = [item for item in evaluated if item.triggered]
            signal = cls._signal(items)
            direct = sorted({metric for item in items for metric in item.direct_metrics})
            indirect = sorted({metric for item in items for metric in item.indirect_metrics})
            coverage = round(len(evaluated) / len(items), 4) if items else 0.0
            if signal == DimensionSignal.INSUFFICIENT_DATA:
                summary = "目前缺少足夠欄位，暫不形成此面向結論。"
            elif triggered:
                summary = "；".join(
                    f"{item.name}（{item.severity.value}／{item.rule_scope}）" for item in triggered
                )
            else:
                summary = "目前可用規則均未觸發顯著注意或正向訊號。"
            assessments.append(
                DimensionAssessment(
                    dimension=dimension,
                    label=DIMENSION_LABELS[dimension],
                    signal=signal,
                    coverage_ratio=coverage,
                    evaluated_rules=len(evaluated),
                    total_rules=len(items),
                    triggered_rule_ids=[item.rule_id for item in triggered],
                    direct_metrics=direct,
                    indirect_metrics=indirect,
                    summary=summary,
                )
            )
        return assessments

    @staticmethod
    def _deterministic_summary(dimensions: list[DimensionAssessment]) -> str:
        parts = [f"{item.label}：{item.signal.value}" for item in dimensions]
        return "；".join(parts) + "。此摘要由可重現的財務特徵與分層 IF–THEN 規則產生，LLM 僅負責後續語意整合。"

    def health(self, *, subindustry: str = "IC 設計") -> dict[str, object]:
        engine = self.rule_engine or MonitorableFinancialRuleEngine(subindustry=subindustry)
        catalog = engine.catalog()
        return {
            "module": "ai_financial_analysis_engine",
            "version": self.version,
            "subindustry": subindustry,
            "rule_version": engine.version,
            "rule_count": catalog.rule_count,
            "rule_scope_counts": catalog.rule_scope_counts,
            "dimensions": [dimension.value for dimension in catalog.dimensions],
            "llm": self.llm_analyst.health(),
            "monitorable_rules": True,
            "automatic_pipeline_supported": True,
        }

    async def analyze_report(
        self,
        report: HistoricalFinancialAnalysisReport,
        *,
        use_llm: bool = True,
    ) -> AIFinancialAnalysisReport:
        if not self.supports(report.subindustry):
            raise ValueError(f"AI analysis v2 尚未建立 {report.subindustry} 的完整產業規則層。")
        rule_engine = self.rule_engine or MonitorableFinancialRuleEngine(subindustry=report.subindustry)
        features = self.feature_engine.build(report.trend_metrics)
        rules = rule_engine.evaluate(features)
        dimensions = self._dimension_assessments(rules)
        if use_llm:
            narrative, trace = await self.llm_analyst.analyze(
                company_name=report.company_name,
                ticker=report.ticker,
                subindustry=report.subindustry,
                dimensions=dimensions,
                rules=rules,
            )
        else:
            narrative = None
            llm_health = self.llm_analyst.health()
            trace = LLMAnalysisTrace(
                enabled=False,
                status="skipped",
                endpoint_configured=bool(llm_health.get("endpoint_configured", False)),
                provider=str(llm_health.get("provider") or self.llm_analyst.provider_name),
                provider_configured=bool(llm_health.get("configured", self.llm_analyst.configured)),
                model=self.llm_analyst.model or None,
                prompt_version=str(llm_health.get("prompt_version") or "financial-analysis-v2"),
                used_rule_ids=[item.rule_id for item in rules if item.triggered],
            )

        limitations = list(report.limitations)
        limitations.append(
            "AI v2 規則分為 common、semiconductor、ic_design 三層；heuristic_mvp 門檻僅供架構驗證，尚不是產業公認標準。"
        )
        if trace.status == "not_configured":
            limitations.append("LLM 尚未設定；目前仍完成財務特徵、規則監控與八大面向 deterministic 分析。")
        if trace.status == "failed":
            limitations.append("LLM 分析呼叫失敗；deterministic 分析結果仍可使用，請依 llm_trace 檢查設定。")

        return AIFinancialAnalysisReport(
            ticker=report.ticker,
            company_name=report.company_name,
            subindustry=report.subindustry,
            analyzed_at=datetime.now(timezone.utc),
            source_period_start=report.start_year,
            source_period_end=report.end_year,
            source_method=report.source_method,
            analysis_engine_version=self.version,
            rule_catalog_version=rule_engine.version,
            feature_count=len(features),
            features=sorted(features.values(), key=lambda item: item.code),
            dimension_assessments=dimensions,
            rule_monitoring=rules,
            deterministic_summary=self._deterministic_summary(dimensions),
            llm_narrative=narrative,
            llm_trace=trace,
            limitations=list(dict.fromkeys(limitations)),
        )
