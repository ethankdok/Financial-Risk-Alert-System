from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(cls.tempdir.name)
        cls.pipeline_path = root / "pipeline.sqlite3"
        os.environ["DATASTORE_BACKEND"] = "sqlite"
        os.environ["FINANCIAL_DATABASE_PATH"] = str(cls.pipeline_path)
        os.environ["FINANCIAL_FACT_DATABASE_PATH"] = str(root / "facts.sqlite3")
        os.environ["APP_ENV"] = "development"
        from app.dependencies import get_analysis_repository, get_fact_repository
        get_analysis_repository.cache_clear()
        get_fact_repository.cache_clear()
        from app.main import app
        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.close()
        from app.dependencies import get_analysis_repository, get_fact_repository

        get_analysis_repository.cache_clear()
        get_fact_repository.cache_clear()
        cls.tempdir.cleanup()

    def test_empty_persisted_endpoints_do_not_500(self) -> None:
        metrics = self.client.get("/api/v1/financial/companies/2330/metrics?limit=10")
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json()["metrics"], [])

        runs = self.client.get("/api/v1/financial/companies/2330/analysis-runs?limit=5")
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(runs.json(), [])

        facts = self.client.get("/api/v1/financial/companies/2330/facts?limit=10")
        self.assertEqual(facts.status_code, 200)
        self.assertEqual(facts.json()["facts"], [])

        rules = self.client.get("/api/v1/financial/companies/2330/rule-results?limit=10")
        self.assertEqual(rules.status_code, 200)
        self.assertEqual(rules.json()["rule_results"], [])

    def test_persisted_fact_and_rule_result_listing_contract(self) -> None:
        from app.dependencies import get_analysis_repository

        get_analysis_repository()._init_schema()
        with sqlite3.connect(self.pipeline_path) as connection:
            connection.execute(
                """INSERT OR REPLACE INTO normalized_financial_facts
                (fact_id,ticker,company_name,subindustry,analysis_type,period,metric_code,value,unit,source_kind,source_url,taxonomy_concept,retrieved_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("fact-2454-revenue", "2454", "聯發科", "IC 設計", "historical", "2026Q2", "revenue", 100.0, "元", "mops_xbrl", "https://example.test", "Revenue", "2026-09-14T00:00:00Z"),
            )
            connection.execute(
                """INSERT OR REPLACE INTO rule_results
                (run_id,ticker,analysis_type,rule_id,name,category,severity,triggered,threshold_description,explanation,evidence_periods_json,evidence_metrics_json,rule_scope,logic_expression,actual_values_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("run-2454", "2454", "historical", "rule-1", "Revenue risk", "growth", "high", 1, "threshold", "explanation", "[\"2026Q2\"]", "[\"revenue\"]", "semiconductor_common", None, "{\"revenue\":100}"),
            )

        facts = self.client.get("/api/v1/financial/companies/2454/facts?search=revenue")
        self.assertEqual(facts.status_code, 200)
        self.assertEqual(facts.json()["facts"][0]["statement_type"], "income_statement")

        rules = self.client.get("/api/v1/financial/companies/2454/rule-results?triggered=true")
        self.assertEqual(rules.status_code, 200)
        self.assertTrue(rules.json()["rule_results"][0]["triggered"])

    def test_historical_snapshot_is_retained_when_latest_pointer_updates(self) -> None:
        from datetime import datetime, timezone

        from app.dependencies import get_analysis_repository
        from app.financial_analysis_models import FinancialStatementAnalysisReport, NormalizedFinancialStatement, RuleSeverity
        from app.historical_analysis_models import HistoricalFinancialAnalysisReport
        from app.pipeline_models import FrontendAnalysisSnapshot

        repository = get_analysis_repository()
        now = datetime.now(timezone.utc)

        def save(run_id: str, summary: str) -> None:
            latest = FinancialStatementAnalysisReport(
                ticker="2454",
                company_name="聯發科",
                subindustry="IC 設計",
                report_period="2026Q2",
                analyzed_at=now,
                rule_version="test",
                threshold_basis="test",
                overall_severity=RuleSeverity.NORMAL,
                summary=summary,
                statement=NormalizedFinancialStatement(ticker="2454", company_name="聯發科", subindustry="IC 設計", report_period="2026Q2"),
                metrics=[],
                rule_results=[],
            )
            historical = HistoricalFinancialAnalysisReport(
                ticker="2454",
                company_name="聯發科",
                subindustry="IC 設計",
                requested_years=1,
                available_years=0,
                analyzed_at=now,
                rule_version="test",
                threshold_basis="test",
                overall_severity=RuleSeverity.NORMAL,
                summary=summary,
                periods=[],
                trend_metrics=[],
                rule_results=[],
            )
            snapshot = FrontendAnalysisSnapshot(
                analysis_run_id=run_id,
                ticker="2454",
                company_name="聯發科",
                subindustry="IC 設計",
                generated_at=now,
                data_updated_at=now,
                overall_severity=RuleSeverity.NORMAL,
                summary=summary,
                rule_version="test",
                threshold_basis="test",
            )
            repository.save_pipeline_result(
                run_id=run_id,
                trigger="manual",
                started_at=now,
                completed_at=now,
                latest_report=latest,
                historical_report=historical,
                snapshot=snapshot,
            )

        save("run-history-1", "first")
        save("run-history-2", "second")

        with sqlite3.connect(self.pipeline_path) as connection:
            latest = connection.execute("SELECT run_id FROM latest_analysis_snapshots WHERE ticker='2454'").fetchone()[0]
            retained = connection.execute("SELECT run_id FROM analysis_snapshots WHERE run_id LIKE 'run-history-%' ORDER BY run_id").fetchall()

        self.assertEqual(latest, "run-history-2")
        self.assertEqual([row[0] for row in retained], ["run-history-1", "run-history-2"])

    def test_claim_extract_contract(self) -> None:
        response = self.client.post(
            "/api/v1/financial/claims/extract",
            json={"text": "台積電 2025 年營收成長 10%", "ticker": "2330", "period": "2025FY"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["claim"]["ticker"], "2330")
        self.assertIn("verdict", payload)

    def test_claim_verify_returns_structured_insufficient_evidence(self) -> None:
        response = self.client.post(
            "/api/v1/financial/claims/verify",
            json={"text": "台積電 2025 年營收成長 10%", "ticker": "2330", "period": "2025FY"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["verdict"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
