"""User-facing financial narrative: no rule IDs, schema keys or raw signal values.

The fixture text is the 2454 Gemini narrative that production served before this
layer existed; labels and units are the ones the same snapshot carries.
"""
from __future__ import annotations

import asyncio
import re
import unittest
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.ai_analysis_models import (
    AIFinancialAnalysisReport,
    AnalysisFeatureValue,
    DimensionAssessment,
    LLMAnalysisTrace,
    LLMNarrative,
    MonitoredRuleResult,
)
from app.financial_analysis_models import RuleSeverity
from app.pipeline_models import FrontendAnalysisSnapshot
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.gemini_financial_analyst import _SYSTEM_PROMPT, GeminiFinancialAnalyst
from app.services.narrative_presentation import (
    build_presentation_glossary,
    humanize_narrative,
    internal_identifiers,
    present_snapshot_payload,
)

FORBIDDEN = [
    "COM_GROWTH_002", "COM_PROFIT_002", "SEM_PROFIT_001", "IC_RD_001",
    "revenue_growth_yoy", "net_income_growth_yoy", "gross_margin_change_pp",
    "operating_margin_change_pp", "rd_expense_growth_yoy",
    "earnings_quality", "profitability", "investment_efficiency",
    "evaluated_rules", "actual_values", "triggered rules", "attention", "normal",
]

FEATURES = [
    ("revenue_growth_yoy", "營收年增率", "%", 12.3222),
    ("net_income_growth_yoy", "淨利年增率", "%", -0.9549),
    ("operating_income_growth_yoy", "營業利益年增率", "%", 1.0328),
    ("gross_margin_change_pp", "毛利率較前期百分點變化", "百分點", -2.1411),
    ("operating_margin_change_pp", "營業利益率較前期百分點變化", "百分點", -1.94),
    ("rd_expense_growth_yoy", "研發費用年增率", "%", 12.3592),
    ("rd_intensity_change_pp", "研發費用占營收比較前期百分點變化", "百分點", 0.0082),
]
RULES = [
    ("COM_GROWTH_002", "營收成長但獲利成長未跟上", "growth", "成長性", "common", RuleSeverity.ATTENTION, True),
    ("COM_PROFIT_002", "毛利率與營業利益率同步下滑", "profitability", "獲利能力", "common", RuleSeverity.ATTENTION, True),
    ("SEM_PROFIT_001", "營收成長但毛利率與營業利益率同步壓縮", "profitability", "獲利能力", "semiconductor", RuleSeverity.ATTENTION, True),
    ("IC_RD_001", "研發投入維持高投入趨勢", "rd_innovation", "研發與創新", "ic_design", RuleSeverity.NORMAL, True),
    ("COM_EQ_001", "盈餘與現金流同向", "earnings_quality", "盈餘品質", "common", RuleSeverity.NORMAL, False),
]
PRODUCTION_NARRATIVE = {
    "executive_summary": (
        "整體呈現營收成長但獲利指標壓縮的混合訊號。在成長性與獲利能力面向觸發了注意（attention）訊號，"
        "其中 COM_GROWTH_002 顯示營收成長（revenue_growth_yoy 為 12.3222）但獲利成長未同步跟上"
        "（net_income_growth_yoy 為 -0.9549）；獲利能力則因 COM_PROFIT_002 與 SEM_PROFIT_001 規則觸發，"
        "顯示毛利率變動（gross_margin_change_pp 為 -2.1411）與營業利益率變動（operating_margin_change_pp 為 -1.94）"
        "同步下滑。在研發與創新面向，IC_RD_001 顯示研發費用持續成長（rd_expense_growth_yoy 為 12.3592）。"
        "其餘面向皆維持正常（normal）訊號。"
    ),
    "dimension_insights": {
        "earnings_quality": "盈餘品質面向維持 normal 訊號。 evaluated_rules 為 1，目前可用規則均未觸發顯著注意或正向訊號。",
        "profitability": (
            "獲利能力面向觸發 attention 訊號。依據規則 COM_PROFIT_002 與 SEM_PROFIT_001，actual_values 顯示 "
            "gross_margin_change_pp 為 -2.1411、operating_margin_change_pp 為 -1.94。"
        ),
        "growth": "成長性面向觸發 attention 訊號。依據規則 COM_GROWTH_002，actual_values 顯示 revenue_growth_yoy 為 12.3222。",
        "investment_efficiency": "投入轉化效率面向維持 normal 訊號。 evaluated_rules 為 3。",
    },
    "watch_items": [
        "追蹤營收成長（revenue_growth_yoy 為 12.3222）與獲利成長（net_income_growth_yoy 為 -0.9549）之間的落差情況。",
        "觀察毛利率（gross_margin_change_pp 為 -2.1411）與營業利益率（operating_margin_change_pp 為 -1.94）同步下滑的後續走勢。",
    ],
    "limitations": ["未提供投資建議或股價預測。"],
}


def features() -> list[AnalysisFeatureValue]:
    return [AnalysisFeatureValue(code=code, label=label, unit=unit, value=value, formula="test") for code, label, unit, value in FEATURES]


def rules() -> list[MonitoredRuleResult]:
    values = {code: value for code, _label, _unit, value in FEATURES}
    return [
        MonitoredRuleResult(
            rule_id=rule_id, name=name, rule_scope=scope, rule_version="test", dimension=dimension,
            dimension_label=dimension_label, assessment_type="direct", severity=severity,
            evaluation_status="evaluated", triggered=triggered, logic_expression="test", rationale="test",
            threshold_basis="test", evidence_basis="test", actual_values={"revenue_growth_yoy": values["revenue_growth_yoy"]},
        )
        for rule_id, name, dimension, dimension_label, scope, severity, triggered in RULES
    ]


def dimensions() -> list[DimensionAssessment]:
    return AIFinancialAnalysisService._dimension_assessments(rules())


def glossary():
    return build_presentation_glossary(features=features(), rules=rules(), dimensions=dimensions())


def user_text(narrative: dict) -> str:
    return " ".join([narrative["executive_summary"], *narrative["dimension_insights"].values(), *narrative["watch_items"]])


def snapshot(narrative: dict | None = PRODUCTION_NARRATIVE) -> FrontendAnalysisSnapshot:
    now = datetime.now(timezone.utc)
    report = AIFinancialAnalysisReport(
        ticker="2454", company_name="聯發科", subindustry="IC 設計", analyzed_at=now,
        source_period_start=2021, source_period_end=2025, source_method="MOPS Inline XBRL annual Q4 filings",
        analysis_engine_version="test", rule_catalog_version="test", feature_count=len(FEATURES),
        features=features(), dimension_assessments=dimensions(), rule_monitoring=rules(),
        deterministic_summary="test", llm_narrative=LLMNarrative(**narrative) if narrative else None,
        llm_trace=LLMAnalysisTrace(enabled=True, status="completed", endpoint_configured=False, provider="gemini",
                                   used_rule_ids=["COM_GROWTH_002"]),
    )
    return FrontendAnalysisSnapshot(
        analysis_run_id="run-2454", ticker="2454", company_name="聯發科", subindustry="IC 設計",
        generated_at=now, data_updated_at=now, overall_severity=RuleSeverity.ATTENTION, summary="test",
        rule_version="test", threshold_basis="test", ai_analysis=report,
    )


class HumanizeNarrativeTests(unittest.TestCase):
    def test_primary_narrative_has_no_internal_identifiers(self) -> None:
        result = humanize_narrative(PRODUCTION_NARRATIVE, glossary())
        text = user_text(result)
        for token in FORBIDDEN:
            self.assertNotRegex(text, rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", token)
        self.assertEqual(internal_identifiers(text, glossary()), [])

    def test_metrics_are_named_and_formatted_without_new_numbers(self) -> None:
        result = humanize_narrative(PRODUCTION_NARRATIVE, glossary())
        summary = result["executive_summary"]
        self.assertIn("營收年增率為 12.32%", summary)
        self.assertIn("淨利年增率為 -0.95%", summary)
        self.assertIn("毛利率較前期百分點變化為 -2.14 個百分點", summary)
        self.assertIn("「營收成長但獲利成長未跟上」", summary)
        source_numbers = {round(abs(value), 2) for *_rest, value in FEATURES} | {1.0, 3.0}
        for number in re.findall(r"\d+\.\d+|\d+(?=\s*項)", user_text(result)):
            self.assertIn(round(float(number), 2), source_numbers, number)

    def test_signal_values_become_chinese_labels(self) -> None:
        insights = humanize_narrative(PRODUCTION_NARRATIVE, glossary())["dimension_insights"]
        self.assertIn("「需注意」", insights["growth"])
        self.assertIn("「未見明顯異常」", insights["earnings_quality"])
        self.assertIn("共檢視 1 項規則", insights["earnings_quality"])

    def test_dimension_keys_and_limitations_are_preserved(self) -> None:
        result = humanize_narrative(LLMNarrative(**PRODUCTION_NARRATIVE), glossary())
        self.assertIsInstance(result, LLMNarrative)
        self.assertEqual(set(result.dimension_insights), set(PRODUCTION_NARRATIVE["dimension_insights"]))
        self.assertEqual(result.limitations, PRODUCTION_NARRATIVE["limitations"])

    def test_dimension_summary_uses_chinese_signal_without_rule_scope(self) -> None:
        summaries = {item.dimension.value: item.summary for item in dimensions()}
        self.assertEqual(summaries["growth"], "營收成長但獲利成長未跟上（需注意）")
        self.assertNotIn("common", summaries["profitability"])
        self.assertNotIn("attention", summaries["profitability"])


class StoredSnapshotPresentationTests(unittest.TestCase):
    def test_stored_snapshot_is_humanized_on_read_and_keeps_audit_fields(self) -> None:
        stored = snapshot().model_dump(mode="json")
        stored["ai_analysis"]["dimension_assessments"][0]["summary"] = "營收成長但獲利成長未跟上（attention／common）"
        presented = present_snapshot_payload(stored)
        analysis = presented["ai_analysis"]
        self.assertEqual(internal_identifiers(user_text(analysis["llm_narrative"])), [])
        self.assertEqual(analysis["dimension_assessments"][0]["summary"], "營收成長但獲利成長未跟上（需注意）")
        self.assertEqual(analysis["dimension_assessments"][0]["triggered_rule_ids"], ["COM_GROWTH_002"])
        self.assertIn("COM_PROFIT_002", [rule["rule_id"] for rule in analysis["rule_monitoring"]])
        self.assertEqual(analysis["llm_trace"]["used_rule_ids"], ["COM_GROWTH_002"])
        # The stored payload itself is not modified.
        self.assertIn("COM_GROWTH_002", stored["ai_analysis"]["llm_narrative"]["executive_summary"])

    def test_snapshot_without_narrative_is_unchanged(self) -> None:
        stored = snapshot(narrative=None).model_dump(mode="json")
        self.assertIsNone(present_snapshot_payload(stored)["ai_analysis"]["llm_narrative"])
        self.assertIsNone(present_snapshot_payload(None))

    def test_latest_analysis_api_serves_the_humanized_narrative(self) -> None:
        from app.dependencies import get_analysis_repository
        from app.main import app

        class Repository:
            def get_latest_snapshot(self, _ticker):
                return snapshot()

        app.dependency_overrides[get_analysis_repository] = lambda: Repository()
        try:
            with TestClient(app) as client:
                response = client.get("/api/v1/financial/companies/2454/analysis/latest")
        finally:
            app.dependency_overrides.pop(get_analysis_repository, None)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["schema_version"], "frontend-financial-snapshot-1.1.0")
        self.assertEqual(internal_identifiers(user_text(body["ai_analysis"]["llm_narrative"])), [])
        self.assertEqual(body["ai_analysis"]["dimension_assessments"][0]["triggered_rule_ids"], ["COM_GROWTH_002"])


class _RecordingProvider:
    provider_name = "test"
    model = "test-model"
    configured = True

    def __init__(self) -> None:
        self.source_context = None

    def health(self):
        return {"provider": self.provider_name, "configured": True, "model": self.model}

    async def analyze(self, **kwargs):
        self.source_context = kwargs["source_context"]
        return LLMNarrative(**PRODUCTION_NARRATIVE), LLMAnalysisTrace(
            enabled=True, status="completed", endpoint_configured=False, provider="test",
        )


class GenerationContractTests(unittest.TestCase):
    def test_generated_narrative_is_humanized_and_prompt_gets_the_glossary(self) -> None:
        provider = _RecordingProvider()
        report = asyncio.run(AIFinancialAnalysisService(llm_analyst=provider).analyze_snapshot(snapshot(narrative=None)))
        glossary_payload = provider.source_context["presentation_glossary"]
        self.assertEqual(glossary_payload["metrics"]["revenue_growth_yoy"], {"label": "營收年增率", "unit": "%"})
        self.assertEqual(glossary_payload["rules"]["COM_GROWTH_002"], "營收成長但獲利成長未跟上")
        self.assertEqual(glossary_payload["dimensions"]["earnings_quality"], "盈餘品質")
        self.assertEqual(glossary_payload["signals"]["attention"], "需注意")
        narrative = report.llm_narrative.model_dump()
        self.assertEqual(internal_identifiers(user_text(narrative)), [])
        # Deterministic outcomes are untouched.
        self.assertEqual([item.rule_id for item in report.rule_monitoring if item.triggered],
                         ["COM_GROWTH_002", "COM_PROFIT_002", "SEM_PROFIT_001", "IC_RD_001"])

    def test_gemini_prompt_forbids_identifiers_and_recalculation(self) -> None:
        self.assertEqual(GeminiFinancialAnalyst.prompt_version, "financial-analysis-gemini-v3")
        self.assertNotIn("必須引用輸入中的期間、rule_id", _SYSTEM_PROMPT)
        for phrase in ("不得出現規則代碼", "presentation_glossary", "不得重新計算", "不得提供買進", "mixed signals"):
            self.assertIn(phrase, _SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
