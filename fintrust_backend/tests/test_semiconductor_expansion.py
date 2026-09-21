from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.financial_analysis_models import RuleSeverity
from app.historical_analysis_models import HistoricalPeriodRecord, HistoricalTrendMetric
from app.models import CompanyMasterRecord
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.historical_rule_engine import HistoricalFinancialRuleEngine
from app.services.monitorable_rule_engine import MonitorableFinancialRuleEngine
from app.services.mops_inline_xbrl import FIELD_ALIASES
from app.services.robust_mops_inline_xbrl import robust_extract_package_value
from app.services.semiconductor_coverage import assess_company_coverage, rule_coverage_for
from app.services.semiconductor_coverage_audit import ReadOnlyCompanyRepository
from app.services.semiconductor_subindustries import classified_tickers


def metric(
    code: str,
    values: dict[str, float],
    *,
    change_pp: float | None = None,
    unit: str = "%",
) -> HistoricalTrendMetric:
    ordered = sorted(values.items())
    return HistoricalTrendMetric(
        code=code,
        label=code,
        category="test",
        unit=unit,
        period_values=values,
        latest_value=ordered[-1][1] if ordered else None,
        previous_value=ordered[-2][1] if len(ordered) > 1 else None,
        change_percentage_points=change_pp,
        formula="test fixture",
    )


def company(ticker: str, subindustry: str) -> CompanyMasterRecord:
    return CompanyMasterRecord(
        ticker=ticker,
        name=ticker,
        legal_name=ticker,
        subindustry=subindustry,
        subindustry_source="test",
        subindustry_confidence="reviewed",
        source_url="https://openapi.twse.com.tw/test",
        synced_at=datetime.now(timezone.utc),
    )


class SemiconductorRuleScopeTests(unittest.TestCase):
    def test_gross_profit_official_concept_alias_is_normalized(self) -> None:
        package = {
            "contexts": {
                "annual": {
                    "period_start": "2024-01-01",
                    "period_end": "2024-12-31",
                }
            },
            "labels": {},
            "labels_en": {},
            "facts": [
                {
                    "concept": "tifrs-bsci-ci:GrossProfitLossFromOperations",
                    "context_ref": "annual",
                    "value": "125000",
                }
            ],
        }
        value, concept = robust_extract_package_value(
            package,
            "gross_profit",
            FIELD_ALIASES["gross_profit"],
            fiscal_year=2024,
            instant=False,
        )
        self.assertEqual(value, 125000.0)
        self.assertEqual(concept, "GrossProfitLossFromOperations")

    def test_rule_coverage_is_explicit_for_every_taxonomy_group(self) -> None:
        self.assertEqual(rule_coverage_for("記憶體製造").status, "full")
        self.assertEqual(rule_coverage_for("半導體設備").status, "full")
        self.assertEqual(rule_coverage_for("記憶體模組與儲存").status, "full")
        self.assertEqual(rule_coverage_for("晶圓代工").status, "partial")
        self.assertEqual(rule_coverage_for("分離元件與功率半導體").status, "common_only")
        self.assertEqual(rule_coverage_for("待分類").status, "unsupported")
        self.assertEqual(len(classified_tickers()), 96)

    def test_monitorable_overlays_do_not_inherit_legacy_inventory_scope(self) -> None:
        expected = {
            "記憶體製造": "memory_manufacturing",
            "半導體設備": "semiconductor_equipment",
            "記憶體模組與儲存": "memory_module_storage",
        }
        for subindustry, scope in expected.items():
            with self.subTest(subindustry=subindustry):
                catalog = MonitorableFinancialRuleEngine(subindustry=subindustry).catalog()
                ids = {rule.rule_id for rule in catalog.rules}
                self.assertIn(scope, catalog.rule_scope_counts)
                self.assertNotIn("SEM_INV_001", ids)
                self.assertNotIn("SEM_INV_002", ids)
                self.assertEqual(catalog.coverage_status, "full")

    def test_ai_layer_accepts_taxonomy_but_not_unclassified_company(self) -> None:
        for subindustry in (
            "記憶體製造",
            "半導體設備",
            "記憶體模組與儲存",
            "半導體材料與零組件",
        ):
            self.assertTrue(AIFinancialAnalysisService.supports(subindustry))
        self.assertFalse(AIFinancialAnalysisService.supports("待分類"))

    def test_memory_manufacturing_requires_compound_cycle_pressure(self) -> None:
        engine = HistoricalFinancialRuleEngine(subindustry="記憶體製造")
        metrics = [
            metric("inventory_growth_yoy", {"2023": 5, "2024": 35}),
            metric("revenue_growth_yoy", {"2023": 4, "2024": -5}),
            metric("gross_margin", {"2023": 30, "2024": 25}, change_pp=-5),
            metric("capex_intensity", {"2023": 18, "2024": 25}, change_pp=7),
            metric("free_cash_flow", {"2023": 10, "2024": -10}, unit="元"),
        ]
        results = {result.rule_id: result for result in engine.evaluate([], metrics)}
        self.assertEqual(results["MEM_HIST_CYCLE_001"].severity, RuleSeverity.HIGH_ATTENTION)
        self.assertEqual(results["MEM_HIST_CAPEX_001"].severity, RuleSeverity.HIGH_ATTENTION)
        self.assertNotIn("SEM_HIST_CAPEX_001", results)

    def test_equipment_rule_uses_demand_working_capital_not_own_capex(self) -> None:
        engine = HistoricalFinancialRuleEngine(subindustry="半導體設備")
        metrics = [
            metric("inventory_growth_yoy", {"2023": 3, "2024": 30}),
            metric("revenue_growth_yoy", {"2023": 5, "2024": -5}),
            metric("receivable_turnover_days", {"2023": 40, "2024": 52}, unit="天"),
            metric("gross_margin", {"2023": 42, "2024": 39}, change_pp=-3),
        ]
        results = {result.rule_id: result for result in engine.evaluate([], metrics)}
        self.assertEqual(results["EQUIP_HIST_CYCLE_001"].severity, RuleSeverity.ATTENTION)
        self.assertNotIn("SEM_HIST_CAPEX_001", results)

    def test_memory_module_rule_uses_inventory_margin_and_cash_conversion(self) -> None:
        engine = HistoricalFinancialRuleEngine(subindustry="記憶體模組與儲存")
        metrics = [
            metric("inventory_growth_yoy", {"2023": 4, "2024": 38}),
            metric("revenue_growth_yoy", {"2023": 3, "2024": 3}),
            metric("gross_margin", {"2023": 18, "2024": 13}, change_pp=-5),
            metric("cash_conversion_ratio", {"2023": 0.9, "2024": 0.4}, unit="倍"),
        ]
        results = {result.rule_id: result for result in engine.evaluate([], metrics)}
        self.assertEqual(results["MEMMOD_HIST_WC_001"].severity, RuleSeverity.HIGH_ATTENTION)
        self.assertNotIn("SEM_HIST_CAPEX_001", results)


class SemiconductorCoverageAuditTests(unittest.TestCase):
    def test_data_rule_and_analysis_coverage_are_separate(self) -> None:
        target = company("3413", "半導體設備")
        found = [
            "revenue", "gross_profit", "net_income", "inventory", "total_assets",
            "total_liabilities", "operating_cash_flow", "accounts_receivable",
            "research_and_development_expense",
        ]
        periods = [
            HistoricalPeriodRecord(
                ticker="3413", company_name="3413", subindustry="半導體設備",
                fiscal_year=year, roc_year=year - 1911, period=str(year),
                source_url="https://mops.twse.com.tw/test", status="available",
                fields_found=found,
            )
            for year in (2022, 2023, 2024)
        ]
        metric_codes = {
            "revenue_growth_yoy", "gross_margin", "operating_cash_flow",
            "cash_conversion_ratio", "debt_ratio", "inventory_growth_yoy",
            "receivable_turnover_days", "rd_intensity",
        }
        report = SimpleNamespace(
            periods=periods,
            requested_years=3,
            trend_metrics=[metric(code, {"2024": 1}) for code in metric_codes],
        )
        audited = assess_company_coverage(target, report)
        self.assertEqual(audited.data_coverage, "PASS")
        self.assertEqual(audited.rule_coverage_status, "full")
        self.assertEqual(audited.analysis_coverage, "PASS")
        self.assertEqual(audited.final_status, "PASS")

    def test_coverage_repository_cannot_write(self) -> None:
        repository = ReadOnlyCompanyRepository([company("2330", "晶圓代工")])
        self.assertEqual(repository.get("2330").ticker, "2330")
        with self.assertRaisesRegex(RuntimeError, "read-only"):
            repository.upsert_many([])


if __name__ == "__main__":
    unittest.main()
