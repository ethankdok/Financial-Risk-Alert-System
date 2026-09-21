from __future__ import annotations

import asyncio

from app.models import CompanyMasterRecord
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService
from app.services.semiconductor_coverage import (
    CompanyCoverageRecord,
    SemiconductorCoverageReport,
    assess_company_coverage,
    build_coverage_report,
)


class ReadOnlyCompanyRepository:
    backend_name = "memory-read-only"

    def __init__(self, companies: list[CompanyMasterRecord]) -> None:
        self._companies = {company.ticker: company for company in companies}

    def get(self, ticker: str) -> CompanyMasterRecord | None:
        return self._companies.get(ticker.strip())

    def list_all(self) -> list[CompanyMasterRecord]:
        return sorted(self._companies.values(), key=lambda company: company.ticker)

    def upsert_many(self, companies: list[CompanyMasterRecord]) -> int:
        raise RuntimeError("Coverage audit is read-only and cannot persist company rows.")


class SemiconductorCoverageAuditor:
    def __init__(
        self,
        companies: list[CompanyMasterRecord],
        *,
        concurrency: int = 2,
        historical_service: HistoricalFinancialAnalysisService | None = None,
    ) -> None:
        self.companies = sorted(companies, key=lambda company: company.ticker)
        self.concurrency = max(1, concurrency)
        self.historical_service = historical_service or HistoricalFinancialAnalysisService(
            company_repository=ReadOnlyCompanyRepository(self.companies)
        )

    async def run(self, *, years: int = 3, scope: str = "all") -> SemiconductorCoverageReport:
        semaphore = asyncio.Semaphore(self.concurrency)

        async def audit_one(company: CompanyMasterRecord) -> CompanyCoverageRecord:
            async with semaphore:
                try:
                    report = await self.historical_service.analyze(company.ticker, years=years)
                except Exception as exc:  # Preserve a company-level diagnostic and continue the batch.
                    return assess_company_coverage(company, None, error=f"{type(exc).__name__}: {exc}")
                return assess_company_coverage(company, report)

        records = await asyncio.gather(*(audit_one(company) for company in self.companies))
        return build_coverage_report(scope, sorted(records, key=lambda record: record.ticker))
