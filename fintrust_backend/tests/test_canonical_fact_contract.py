from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.financial_analysis_models import (
    CalculatedMetric,
    FinancialStatementAnalysisReport,
    RuleSeverity,
)
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.models import CompanyProfile, FinancialFact
from app.services.analysis_repository import (
    SqliteAnalysisRepository,
    fact_document_id,
    latest_fact_rows,
    metric_rows,
    shift_month_period,
)
from app.services.fact_repository import fact_to_firestore_row, firestore_row_to_fact
from app.services.statement_normalizer import normalize_twse_bundle


class CanonicalFactContractTests(unittest.TestCase):
    def test_latest_rows_keep_statement_source_and_month_period(self) -> None:
        profile = CompanyProfile(ticker="2330", name="台積電", subindustry="晶圓代工", aliases=[])
        statement = normalize_twse_bundle(
            profile,
            {
                "income_statement": {"年度": "115", "季別": "2", "營業收入": "100"},
                "balance_sheet": {"年度": "115", "季別": "2", "流動資產": "200"},
                "monthly_revenue": {
                    "資料年月": "11506",
                    "營業收入-當月營收": "30",
                    "營業收入-上月營收": "29",
                },
            },
        )
        report = FinancialStatementAnalysisReport(
            ticker="2330", company_name="台積電", subindustry="晶圓代工",
            report_period=statement.report_period,
            monthly_revenue_period=statement.monthly_revenue_period,
            analyzed_at=datetime.now(timezone.utc), rule_version="test",
            threshold_basis="test", overall_severity=RuleSeverity.NORMAL,
            summary="test", statement=statement, metrics=[], rule_results=[],
        )
        rows = latest_fact_rows(report)
        by_source_field = {row["source_field"]: row for row in rows}
        self.assertEqual(by_source_field["monthly_revenue"]["period"], "2026-06")
        self.assertEqual(by_source_field["previous_month_revenue"]["period"], "2026-05")
        self.assertEqual(by_source_field["monthly_revenue"]["metric_code"], "monthly_revenue")
        self.assertEqual(by_source_field["previous_month_revenue"]["metric_code"], "monthly_revenue")
        self.assertTrue(
            by_source_field["monthly_revenue"]["source_url"].endswith("t187ap05_L")
        )
        self.assertEqual(by_source_field["current_assets"]["period"], "2026Q2")
        self.assertTrue(
            by_source_field["current_assets"]["source_url"].endswith("t187ap07_L_ci")
        )
        self.assertTrue(all(row["filed_at"] is None for row in rows))

    def test_latest_rows_do_not_borrow_another_statement_source(self) -> None:
        profile = CompanyProfile(ticker="2330", name="台積電", subindustry="晶圓代工", aliases=[])
        statement = normalize_twse_bundle(
            profile,
            {
                "income_statement": {"年度": "115", "季別": "2", "營業收入": "100"},
                "monthly_revenue": {"資料年月": "11501", "營業收入-當月營收": "30"},
            },
        )
        statement.source_coverage = [
            coverage
            for coverage in statement.source_coverage
            if "monthly_revenue" not in coverage.fields_found
        ]
        report = FinancialStatementAnalysisReport(
            ticker="2330", company_name="台積電", subindustry="晶圓代工",
            report_period=statement.report_period,
            monthly_revenue_period=statement.monthly_revenue_period,
            analyzed_at=datetime.now(timezone.utc), rule_version="test",
            threshold_basis="test", overall_severity=RuleSeverity.NORMAL,
            summary="test", statement=statement, metrics=[], rule_results=[],
        )
        self.assertNotIn(
            "monthly_revenue",
            {row["source_field"] for row in latest_fact_rows(report)},
        )

    def test_month_period_and_metric_comparisons_are_calendar_based(self) -> None:
        self.assertEqual(shift_month_period("2026-01", -1), "2025-12")
        self.assertEqual(shift_month_period("2026-01", -12), "2025-01")
        profile = CompanyProfile(ticker="2454", name="聯發科", subindustry="IC 設計", aliases=[])
        statement = normalize_twse_bundle(
            profile,
            {"monthly_revenue": {
                "資料年月": "11501",
                "營業收入-當月營收": "30",
                "營業收入-上月營收": "29",
                "營業收入-去年同月營收": "25",
            }},
        )
        latest = FinancialStatementAnalysisReport(
            ticker="2454", company_name="聯發科", subindustry="IC 設計",
            report_period=None, monthly_revenue_period="2026-01",
            analyzed_at=datetime.now(timezone.utc), rule_version="test",
            threshold_basis="test", overall_severity=RuleSeverity.NORMAL,
            summary="test", statement=statement,
            metrics=[CalculatedMetric(
                code="monthly_revenue_mom",
                label="月營收月增率",
                category="growth",
                value=3.45,
                unit="%",
                formula="test",
                source_fields=["monthly_revenue", "previous_month_revenue"],
            )],
            rule_results=[],
        )
        historical = HistoricalFinancialAnalysisReport(
            ticker="2454", company_name="聯發科", subindustry="IC 設計",
            requested_years=1, available_years=0,
            analyzed_at=datetime.now(timezone.utc), rule_version="test",
            threshold_basis="test", overall_severity=RuleSeverity.INSUFFICIENT_DATA,
            summary="test", periods=[], trend_metrics=[], rule_results=[],
        )
        metric = metric_rows("run-1", latest, historical)[0]
        self.assertEqual(metric["period"], "2026-01")
        self.assertEqual(metric["comparison_periods"], ["2025-12"])

    def test_fact_identity_is_stable_across_write_paths(self) -> None:
        fact = FinancialFact(
            ticker="2330", company_name="台積電", semiconductor_subindustry="晶圓代工",
            metric="revenue", period="2025FY", value=100, unit="TWD",
            statement_type="income_statement", source_kind="mops_xbrl",
            source_url="https://example.com/filing", statement_scope="consolidated",
        )
        direct_row = fact_to_firestore_row(fact)
        pipeline_row = {
            **direct_row,
            "analysis_type": "historical",
            "metric_code": direct_row["metric_code"],
        }
        self.assertEqual(fact_document_id(direct_row), fact_document_id(pipeline_row))
        changed_scope = {**direct_row, "statement_scope": "standalone"}
        self.assertNotEqual(fact_document_id(direct_row), fact_document_id(changed_scope))

    def test_firestore_deserialization_does_not_treat_retrieval_as_filing(self) -> None:
        fact = firestore_row_to_fact({
            "ticker": "2330", "company_name": "台積電", "subindustry": "晶圓代工",
            "metric_code": "revenue", "period": "2025FY", "value": 100,
            "unit": "TWD", "statement_type": "income_statement",
            "source_kind": "mops_xbrl", "source_url": "https://example.com/filing",
            "statement_scope": "consolidated",
            "retrieved_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
        })
        self.assertIsNone(fact.filed_at)

    def test_direct_ingest_uses_analysis_repository_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteAnalysisRepository(str(Path(directory) / "pipeline.sqlite3"))
            fact = FinancialFact(
                ticker="2330", company_name="台積電", semiconductor_subindustry="晶圓代工",
                metric="revenue", period="2025FY", value=100, unit="TWD",
                statement_type="income_statement", source_kind="mops_xbrl",
                source_url="https://example.com/filing",
                filed_at=datetime(2026, 3, 1, tzinfo=timezone.utc),
                statement_scope="consolidated",
            )
            self.assertEqual(repository.ingest_facts([fact]), 1)
            loaded = repository.get_fact("2330", "revenue", "2025FY")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.statement_scope, "consolidated")
            self.assertEqual(loaded.source_url, fact.source_url)


if __name__ == "__main__":
    unittest.main()
