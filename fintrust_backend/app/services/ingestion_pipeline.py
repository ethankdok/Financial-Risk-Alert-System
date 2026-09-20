from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from app.ai_analysis_models import AIFinancialAnalysisReport
from app.financial_analysis_models import FinancialStatementAnalysisReport
from app.historical_analysis_models import HistoricalFinancialAnalysisReport
from app.pipeline_models import (
    CompanyRefreshResult,
    IngestionRunRecord,
    PersistenceCounts,
    RefreshAllResult,
)
from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.analysis_repository import AnalysisRepository, build_analysis_repository
from app.services.company_registry import get_company, list_companies
from app.services.company_registry import profile_from_master
from app.services.company_master_repository import build_company_master_repository, CompanyMasterRepository
from app.services.demo_fixture_sources import DEMO_SOURCE_URL, DemoMopsInlineXbrlClient, DemoTwseOpenApiClient
from app.services.financial_analysis_service import FinancialAnalysisService, UnsupportedCompanyError
from app.services.frontend_presenter import build_frontend_snapshot
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService
from app.services.ingestion_run_repository import (
    IngestionRunRepository,
    build_ingestion_run_repository,
)


logger = logging.getLogger("fintrust.ingestion")
TriggerKind = Literal["scheduler", "manual", "demo", "startup"]
SourceMode = Literal["official", "demo_fixture"]


class FinancialIngestionPipeline:
    def __init__(
        self,
        *,
        repository: AnalysisRepository | None = None,
        latest_service: FinancialAnalysisService | None = None,
        historical_service: HistoricalFinancialAnalysisService | None = None,
        ai_service: AIFinancialAnalysisService | None = None,
        ingestion_run_repository: IngestionRunRepository | None = None,
        company_repository: CompanyMasterRepository | None = None,
    ) -> None:
        self.repository = repository or build_analysis_repository()
        self.latest_service = latest_service or FinancialAnalysisService()
        self.historical_service = historical_service or HistoricalFinancialAnalysisService()
        self.ai_service = ai_service or AIFinancialAnalysisService()
        self.ingestion_run_repository = ingestion_run_repository or build_ingestion_run_repository()
        self.company_repository = company_repository or build_company_master_repository()
        if latest_service is None:
            self.latest_service = FinancialAnalysisService(company_repository=self.company_repository)
        if historical_service is None:
            self.historical_service = HistoricalFinancialAnalysisService(company_repository=self.company_repository)

    def _services_for_mode(self, source_mode: SourceMode) -> tuple[FinancialAnalysisService, HistoricalFinancialAnalysisService]:
        if source_mode == "official":
            return self.latest_service, self.historical_service
        if source_mode == "demo_fixture":
            return (
                FinancialAnalysisService(twse_client=DemoTwseOpenApiClient(), company_repository=self.company_repository),
                HistoricalFinancialAnalysisService(mops_client=DemoMopsInlineXbrlClient(), company_repository=self.company_repository),
            )
        raise ValueError(f"Unsupported source mode: {source_mode}")

    @staticmethod
    def _auto_llm_enabled(source_mode: SourceMode) -> bool:
        if source_mode != "official":
            return False
        raw = os.getenv("FINANCIAL_AI_AUTO_LLM_ENABLED", "true").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _label_demo_reports(
        latest_report: FinancialStatementAnalysisReport,
        historical_report: HistoricalFinancialAnalysisReport,
    ) -> None:
        warning = (
            "DEMO FIXTURE：本次使用合成資料驗證正規化、指標、規則、資料庫與前端快照流程；"
            "不得解讀為公司真實財報或官方最新數值。"
        )
        latest_report.summary = f"[DEMO FIXTURE] {latest_report.summary}"
        latest_report.limitations = [warning, *latest_report.limitations]
        latest_report.statement.data_quality_warnings = [warning, *latest_report.statement.data_quality_warnings]
        for source in latest_report.statement.source_coverage:
            source.source_name = f"DEMO FIXTURE／{source.source_name}欄位結構"
            source.source_url = DEMO_SOURCE_URL
        historical_report.source_method = "DEMO FIXTURE synthetic annual Q4 records"
        historical_report.summary = f"[DEMO FIXTURE] {historical_report.summary}"
        historical_report.limitations = [warning, *historical_report.limitations]

    async def _run_ai_analysis(
        self,
        historical_report: HistoricalFinancialAnalysisReport,
        *,
        source_mode: SourceMode,
        run_id: str,
    ) -> AIFinancialAnalysisReport | None:
        if not self.ai_service.supports(historical_report.subindustry):
            logger.info(
                "stage=ai_skipped run_id=%s ticker=%s subindustry=%s reason=unsupported_subindustry",
                run_id,
                historical_report.ticker,
                historical_report.subindustry,
            )
            return None
        use_llm = self._auto_llm_enabled(source_mode)
        try:
            logger.info(
                "stage=ai_analysis run_id=%s ticker=%s use_llm=%s",
                run_id,
                historical_report.ticker,
                use_llm,
            )
            result = await self.ai_service.analyze_report(historical_report, use_llm=use_llm)
            logger.info(
                "stage=ai_complete run_id=%s ticker=%s features=%s rules=%s dimensions=%s llm_status=%s",
                run_id,
                historical_report.ticker,
                result.feature_count,
                len(result.rule_monitoring),
                len(result.dimension_assessments),
                result.llm_trace.status,
            )
            return result
        except Exception as exc:
            logger.exception(
                "stage=ai_failed run_id=%s ticker=%s error=%s",
                run_id,
                historical_report.ticker,
                exc,
            )
            historical_report.limitations.append(
                f"AI 分析層本次執行失敗：{exc}。官方財報與原 historical analysis 仍已保留。"
            )
            return None

    async def refresh_company(
        self,
        ticker: str,
        *,
        years: int = 5,
        end_year: int | None = None,
        trigger: TriggerKind = "manual",
        source_mode: SourceMode = "official",
        batch_id: str | None = None,
    ) -> CompanyRefreshResult:
        master_record = self.company_repository.get(ticker)
        profile = profile_from_master(master_record) if master_record else get_company(ticker)
        if profile is None:
            raise UnsupportedCompanyError("MVP 僅分析已登錄的半導體公司；請先將公司加入 semiconductor registry。")

        latest_service, historical_service = self._services_for_mode(source_mode)
        run_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        ingestion_run = IngestionRunRecord(
            run_id=run_id,
            batch_id=batch_id,
            ticker=profile.ticker,
            company_name=profile.name,
            subindustry=profile.subindustry,
            trigger=trigger,
            source_mode=source_mode,
            requested_years=years,
            end_year=end_year,
            status="running",
            started_at=started_at,
        )
        self.ingestion_run_repository.save(ingestion_run)
        logger.info(
            "pipeline_started run_id=%s ticker=%s subindustry=%s years=%s trigger=%s source_mode=%s",
            run_id, profile.ticker, profile.subindustry, years, trigger, source_mode,
        )
        try:
            logger.info("stage=twse_fetch run_id=%s ticker=%s source_mode=%s", run_id, profile.ticker, source_mode)
            latest_report = await latest_service.analyze(profile.ticker)
            logger.info(
                "stage=twse_complete run_id=%s ticker=%s report_period=%s metrics=%s rules=%s",
                run_id, profile.ticker, latest_report.report_period, len(latest_report.metrics), len(latest_report.rule_results),
            )

            logger.info("stage=mops_fetch run_id=%s ticker=%s years=%s source_mode=%s", run_id, profile.ticker, years, source_mode)
            historical_report = await historical_service.analyze(
                profile.ticker,
                years=years,
                end_roc_year=end_year - 1911 if end_year is not None else None,
            )
            logger.info(
                "stage=mops_complete run_id=%s ticker=%s available_years=%s metrics=%s rules=%s rule_version=%s",
                run_id, profile.ticker, historical_report.available_years,
                len(historical_report.trend_metrics), len(historical_report.rule_results), historical_report.rule_version,
            )

            if source_mode == "demo_fixture":
                self._label_demo_reports(latest_report, historical_report)

            ai_analysis = await self._run_ai_analysis(
                historical_report,
                source_mode=source_mode,
                run_id=run_id,
            )

            logger.info("stage=frontend_transform run_id=%s ticker=%s", run_id, profile.ticker)
            snapshot = build_frontend_snapshot(
                run_id=run_id,
                latest_report=latest_report,
                historical_report=historical_report,
            )
            snapshot.ai_analysis = ai_analysis
            completed_at = datetime.now(timezone.utc)

            logger.info("stage=persist run_id=%s ticker=%s backend=%s", run_id, profile.ticker, self.repository.backend_name)
            persistence = self.repository.save_pipeline_result(
                run_id=run_id,
                trigger=trigger,
                started_at=started_at,
                completed_at=completed_at,
                latest_report=latest_report,
                historical_report=historical_report,
                snapshot=snapshot,
            )
            logger.info(
                "pipeline_completed run_id=%s ticker=%s source_mode=%s filings=%s facts=%s metrics=%s rules=%s snapshots=%s ai=%s",
                run_id, profile.ticker, source_mode, persistence.filings, persistence.facts,
                persistence.metrics, persistence.rule_results, persistence.snapshots, ai_analysis is not None,
            )
            self.ingestion_run_repository.save(
                ingestion_run.model_copy(
                    update={
                        "status": "completed",
                        "completed_at": completed_at,
                        "records_found": persistence.total,
                        "records_written": persistence.total,
                        "persistence": persistence,
                    }
                )
            )
            return CompanyRefreshResult(
                run_id=run_id,
                batch_id=batch_id,
                ticker=profile.ticker,
                company_name=profile.name,
                subindustry=profile.subindustry,
                trigger=trigger,
                source_mode=source_mode,
                status="completed",
                started_at=started_at,
                completed_at=completed_at,
                latest_report_period=latest_report.report_period,
                history_available_years=historical_report.available_years,
                persistence=persistence,
                snapshot=snapshot,
                ai_analysis=ai_analysis,
            )
        except Exception as exc:
            completed_at = datetime.now(timezone.utc)
            logger.exception("pipeline_failed run_id=%s ticker=%s source_mode=%s error=%s", run_id, profile.ticker, source_mode, exc)
            self.ingestion_run_repository.save(
                ingestion_run.model_copy(
                    update={
                        "status": "failed",
                        "completed_at": completed_at,
                        "failed_records": 1,
                        "persistence": PersistenceCounts(),
                        "error_message": str(exc),
                    }
                )
            )
            return CompanyRefreshResult(
                run_id=run_id,
                batch_id=batch_id,
                ticker=profile.ticker,
                company_name=profile.name,
                subindustry=profile.subindustry,
                trigger=trigger,
                source_mode=source_mode,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                error=str(exc),
            )

    async def refresh_all(
        self,
        *,
        years: int = 5,
        end_year: int | None = None,
        trigger: TriggerKind = "scheduler",
        source_mode: SourceMode = "official",
    ) -> RefreshAllResult:
        started_at = datetime.now(timezone.utc)
        batch_id = uuid4().hex
        results: list[CompanyRefreshResult] = []
        if source_mode == "official":
            master_companies = [
                profile_from_master(company)
                for company in self.company_repository.list_all()
                if company.listing_status == "listed" and company.subindustry != "待分類"
            ]
            companies = master_companies or list_companies()
        else:
            companies = list_companies()
        for company in companies:
            results.append(
                await self.refresh_company(
                    company.ticker,
                    years=years,
                    end_year=end_year,
                    trigger=trigger,
                    source_mode=source_mode,
                    batch_id=batch_id,
                )
            )
        completed_at = datetime.now(timezone.utc)
        completed = sum(result.status == "completed" for result in results)
        return RefreshAllResult(
            batch_id=batch_id,
            started_at=started_at,
            completed_at=completed_at,
            trigger=trigger,
            source_mode=source_mode,
            requested_companies=len(results),
            completed_companies=completed,
            failed_companies=len(results) - completed,
            results=results,
        )
