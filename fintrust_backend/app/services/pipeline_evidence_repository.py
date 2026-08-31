from __future__ import annotations

from app.models import FinancialFact
from app.services.analysis_repository import AnalysisRepository, statement_type_for_metric


DERIVED_STATEMENT_TYPES = {
    "gross_margin": "income_statement",
    "operating_margin": "income_statement",
    "net_margin": "income_statement",
    "revenue_growth_yoy": "income_statement",
    "rd_intensity": "income_statement",
    "inventory_growth_yoy": "balance_sheet",
    "debt_ratio": "balance_sheet",
    "current_ratio": "balance_sheet",
    "operating_cash_flow": "cash_flow",
    "cash_conversion_ratio": "cash_flow",
    "free_cash_flow": "cash_flow",
    "capex_intensity": "cash_flow",
}


class PipelineEvidenceRepository:
    """Read raw facts first, then derived metrics from the scheduled pipeline.

    The claim verifier uses one `get_fact` contract. Raw statement facts live in
    `normalized_financial_facts`, while ratios such as gross margin live in
    `calculated_metrics`. This adapter keeps those storage details out of the
    verification engine and preserves source provenance from the latest snapshot.
    """

    def __init__(self, repository: AnalysisRepository) -> None:
        self.repository = repository

    def get_fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None:
        raw = self.repository.get_fact(ticker, metric, period)
        if raw is not None:
            return raw

        rows = self.repository.list_metrics(ticker, limit=1000)
        row = next(
            (
                item
                for item in rows
                if item.get("metric_code") == metric and item.get("period") == period
            ),
            None,
        )
        if row is None:
            return None

        snapshot = self.repository.get_latest_snapshot(ticker)
        if snapshot is None:
            return None
        source = next(
            (item for item in snapshot.sources if item.period == period),
            snapshot.sources[0] if snapshot.sources else None,
        )
        if source is None:
            return None

        is_demo = "DEMO FIXTURE" in source.source_name.upper()
        source_kind = (
            "mvp_fixture"
            if is_demo
            else "mops_xbrl"
            if period.endswith("FY")
            else "twse_openapi"
        )
        return FinancialFact(
            ticker=ticker,
            company_name=snapshot.company_name,
            semiconductor_subindustry=snapshot.subindustry,
            metric=metric,
            period=period,
            value=float(row["value"]),
            unit=str(row["unit"]),
            statement_type=DERIVED_STATEMENT_TYPES.get(
                metric,
                statement_type_for_metric(metric),
            ),
            source_kind=source_kind,
            source_url=source.source_url,
            filed_at=snapshot.data_updated_at,
            statement_scope="consolidated" if period.endswith("FY") else "unknown",
            is_demo=is_demo,
        )
