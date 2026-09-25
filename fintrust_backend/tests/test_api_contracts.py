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
        os.environ["CONFERENCE_PDF_ARCHIVE_ROOT"] = str(root / "official-ir-pdfs")
        os.environ["APP_ENV"] = "development"
        from app.dependencies import (
            get_analysis_repository,
            get_company_master_repository,
            get_fact_repository,
            get_ingestion_run_repository,
        )
        get_analysis_repository.cache_clear()
        get_fact_repository.cache_clear()
        get_company_master_repository.cache_clear()
        get_ingestion_run_repository.cache_clear()
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

    def test_conference_pdf_archive_query_contract_reads_manifest_pages_and_analysis(self) -> None:
        root = Path(os.environ["CONFERENCE_PDF_ARCHIVE_ROOT"]) / "2330" / "2025"
        root.mkdir(parents=True, exist_ok=True)
        pages = root / "233020250116M001.pages.json"
        analysis = root / "233020250116M001.analysis.json"
        pages.write_text(
            '[{"page":1,"text":"Revenue 100 gross margin 55%","text_length":28,'
            '"analysis_results":[],"visual_review_required":true}]',
            encoding="utf-8",
        )
        analysis.write_text(
            '[{"kind":"chart_or_image_region","filename":"233020250116M001.pdf","page":1,'
            '"verification_status":"needs_manual_chart_value_verification"}]',
            encoding="utf-8",
        )
        (root / "manifest.json").write_text(
            """{
              "ticker":"2330","year":2025,"market":"sii","status":"failed",
              "retrieved_at":"2026-09-26T00:00:00+00:00","rows":16,
              "listing_pages":[1],"expected_pdfs":1,"downloaded_pdfs":1,
              "integrity":{"pages_requiring_manual_review":1,"unverified_chart_page_count":1},
              "errors":[],
              "documents":[{
                "filename":"233020250116M001.pdf","status":"needs_review",
                "page_count":1,"analysis_results":1,
                "pages_path":"%s","analysis_path":"%s"
              }]
            }""" % (str(pages).replace("\\", "\\\\"), str(analysis).replace("\\", "\\\\")),
            encoding="utf-8",
        )

        status = self.client.get("/api/v1/financial/companies/2330/conference-pdfs/2025/status?year=2025")
        documents = self.client.get("/api/v1/financial/companies/2330/conference-pdfs/2025/documents?year=2025")
        page_response = self.client.get("/api/v1/financial/companies/2330/conference-pdfs/2025/documents/233020250116M001.pdf/pages?year=2025")
        analysis_response = self.client.get("/api/v1/financial/companies/2330/conference-pdfs/2025/documents/233020250116M001.pdf/analysis?year=2025")

        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "failed")
        self.assertEqual(documents.status_code, 200)
        self.assertEqual(documents.json()["count"], 1)
        self.assertEqual(page_response.status_code, 200)
        self.assertEqual(page_response.json()["pages"][0]["page"], 1)
        self.assertEqual(analysis_response.status_code, 200)
        self.assertEqual(analysis_response.json()["analysis"][0]["verification_status"], "needs_manual_chart_value_verification")

    def test_paid_ai_routes_require_ingestion_token(self) -> None:
        previous = os.environ.get("INGESTION_API_TOKEN")
        os.environ["INGESTION_API_TOKEN"] = "test-ingestion-token"
        try:
            live = self.client.post("/api/v1/financial/ai/companies/2330/analyze?years=3")
            snapshot = self.client.post("/api/v1/financial/ai/companies/9999/narrative")
            persist = self.client.post("/api/v1/financial/ai/companies/9999/narrative/persist")
            authorized_missing = self.client.post(
                "/api/v1/financial/ai/companies/9999/narrative",
                headers={"X-Ingestion-Token": "test-ingestion-token"},
            )
        finally:
            if previous is None:
                os.environ.pop("INGESTION_API_TOKEN", None)
            else:
                os.environ["INGESTION_API_TOKEN"] = previous

        self.assertEqual(live.status_code, 401)
        self.assertEqual(snapshot.status_code, 401)
        self.assertEqual(persist.status_code, 401)
        self.assertEqual(authorized_missing.status_code, 404)

    def test_direct_ingest_uses_canonical_analysis_repository(self) -> None:
        response = self.client.post(
            "/api/v1/financial/facts/ingest",
            json={"facts": [{
                "ticker": "3711",
                "company_name": "日月光投控",
                "semiconductor_subindustry": "封裝測試",
                "metric": "revenue",
                "period": "2025FY",
                "value": 100,
                "unit": "TWD",
                "statement_type": "income_statement",
                "source_kind": "mops_xbrl",
                "source_url": "https://example.test/filing",
                "statement_scope": "consolidated",
            }]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        with sqlite3.connect(self.pipeline_path) as connection:
            row = connection.execute(
                """SELECT analysis_type, fact_key_version
                   FROM normalized_financial_facts
                   WHERE ticker = '3711' AND metric_code = 'revenue' AND period = '2025FY'"""
            ).fetchone()
        self.assertEqual(row, ("ingested", "financial-fact-v2"))

    def test_refresh_all_rejects_ticker_outside_taxonomy_scope(self) -> None:
        response = self.client.post(
            "/api/v1/financial/admin/refresh-all?tickers=9999"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("reviewed semiconductor taxonomy", response.json()["detail"])

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

        universe = self.client.get("/api/v1/financial/company-universe")
        self.assertEqual(universe.status_code, 200)
        self.assertEqual(universe.json(), [])

        ingestion_runs = self.client.get("/api/v1/financial/admin/ingestion-runs")
        self.assertEqual(ingestion_runs.status_code, 200)
        self.assertEqual(ingestion_runs.json(), [])

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
