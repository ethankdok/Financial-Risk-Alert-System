from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.financial_analysis_models import FinancialStatementAnalysisReport, RuleSeverity
from app.models import CompanyProfile, FinancialFact
from app.services.analysis_repository import SqliteAnalysisRepository, latest_fact_rows
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
        rows = {row["metric_code"]: row for row in latest_fact_rows(report)}
        self.assertEqual(rows["monthly_revenue"]["period"], "2026-06")
        self.assertTrue(rows["monthly_revenue"]["source_url"].endswith("t187ap05_L"))
        self.assertEqual(rows["current_assets"]["period"], "2026Q2")
        self.assertTrue(rows["current_assets"]["source_url"].endswith("t187ap07_L_ci"))

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
