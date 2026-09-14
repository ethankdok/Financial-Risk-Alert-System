from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from app.main import app
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.monitorable_rule_engine import MonitorableFinancialRuleEngine


class Phase15BackendReleaseReadinessTests(unittest.TestCase):
    def test_ai_financial_service_supports_registered_semiconductor_scope(self) -> None:
        self.assertTrue(AIFinancialAnalysisService.supports("IC 設計"))
        self.assertTrue(AIFinancialAnalysisService.supports("晶圓代工"))
        self.assertTrue(AIFinancialAnalysisService.supports("封裝測試"))

    def test_non_ic_semiconductor_uses_common_rule_layers_without_ic_overlay(self) -> None:
        catalog = MonitorableFinancialRuleEngine(subindustry="晶圓代工").catalog()

        self.assertIn("common", catalog.rule_scope_counts)
        self.assertIn("semiconductor", catalog.rule_scope_counts)
        self.assertNotIn("ic_design", catalog.rule_scope_counts)
        self.assertGreater(catalog.rule_count, 0)

    def test_ic_design_still_uses_ic_overlay(self) -> None:
        catalog = MonitorableFinancialRuleEngine(subindustry="IC 設計").catalog()

        self.assertIn("common", catalog.rule_scope_counts)
        self.assertIn("semiconductor", catalog.rule_scope_counts)
        self.assertIn("ic_design", catalog.rule_scope_counts)

    def test_ai_health_and_rules_accept_subindustry_query(self) -> None:
        client = TestClient(app, raise_server_exceptions=False)

        health = client.get("/api/v1/financial/ai/health", params={"subindustry": "晶圓代工"})
        rules = client.get("/api/v1/financial/ai/rules", params={"subindustry": "晶圓代工"})

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["subindustry"], "晶圓代工")
        self.assertEqual(rules.status_code, 200)
        self.assertNotIn("ic_design", rules.json()["rule_scope_counts"])


if __name__ == "__main__":
    unittest.main()
