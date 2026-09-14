from __future__ import annotations

from datetime import datetime, timezone

from app.phase12_models import FinancialStatementCoverageReport, StatementCoverageItem
from app.services.analysis_repository import BALANCE_FIELDS, CASH_FLOW_FIELDS, INCOME_FIELDS, MONTHLY_FIELDS


def audit_financial_statement_coverage() -> FinancialStatementCoverageReport:
    coverage = [
        StatementCoverageItem(
            statement="income_statement",
            status="SUPPORTED",
            represented_by=sorted(INCOME_FIELDS),
            limitation="Represents core income statement line items available in latest and historical pipelines.",
        ),
        StatementCoverageItem(
            statement="balance_sheet",
            status="SUPPORTED",
            represented_by=sorted(BALANCE_FIELDS),
            limitation="Represents core balance-sheet instant fields used by deterministic rules.",
        ),
        StatementCoverageItem(
            statement="cash_flow_statement",
            status="SUPPORTED",
            represented_by=sorted(CASH_FLOW_FIELDS),
            limitation="Represents operating, investing, and capital-expenditure cash-flow fields where MOPS iXBRL exposes them.",
        ),
        StatementCoverageItem(
            statement="statement_of_changes_in_equity",
            status="MISSING",
            represented_by=[],
            limitation=(
                "Current normalized model stores ending equity as a balance-sheet fact but does not ingest the "
                "traditional fourth statement or equity-change rows. Monthly revenue is not a substitute."
            ),
        ),
        StatementCoverageItem(
            statement="monthly_revenue",
            status="PARTIAL",
            represented_by=sorted(MONTHLY_FIELDS),
            limitation="Useful official operating data, but not one of the four traditional financial statements.",
        ),
    ]
    return FinancialStatementCoverageReport(
        generated_at=datetime.now(timezone.utc),
        coverage=coverage,
        fourth_statement_status="MISSING",
        limitations=[
            "No financial ingestion rewrite was performed in Phase 12.",
            "Minimum compatible fourth-statement ingestion remains a future extension after confirming stable MOPS/XBRL source concepts.",
        ],
    )
