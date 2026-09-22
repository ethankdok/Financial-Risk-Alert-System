from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.official_event_batch_models import (
    OfficialEventBatchCompanyResult,
    OfficialEventBatchScope,
    OfficialEventBatchTrigger,
    OfficialEventsBatchRefreshResult,
)
from app.official_event_models import OfficialEventsRefreshResult
from app.services.analysis_repository import AnalysisRepository, build_analysis_repository
from app.services.company_master_repository import (
    CompanyMasterRepository,
    build_company_master_repository,
)
from app.services.company_registry import (
    get_company,
    profile_from_master,
    register_company_profile,
)
from app.services.financial_analysis_service import UnsupportedCompanyError
from app.services.official_event_ingestion import OfficialEventIngestionService
from app.services.official_event_sources import (
    fetch_twse_material_event_rows,
    is_persistable_material_event,
    parse_twse_material_event_rows,
)
from app.services.semiconductor_subindustries import classified_tickers


logger = logging.getLogger("fintrust.official_events")
DEFAULT_OFFICIAL_EVENT_TICKERS = ("2330", "2454")
ALLOWED_OFFICIAL_EVENT_TICKERS = frozenset(classified_tickers())
PARTIAL_SOURCE_OUTCOMES = {"NETWORK_ERROR", "BLOCKED_BY_SOURCE"}


def validate_official_event_tickers(tickers: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(dict.fromkeys(str(ticker).strip() for ticker in tickers if str(ticker).strip()))
    if not normalized:
        raise ValueError("At least one official-event ticker is required.")
    unsupported = sorted(set(normalized) - ALLOWED_OFFICIAL_EVENT_TICKERS)
    if unsupported:
        raise ValueError(
            "Official-event refresh is limited to the classified semiconductor taxonomy; "
            f"unsupported tickers: {', '.join(unsupported)}"
        )
    return normalized


def configured_official_event_tickers() -> tuple[str, ...]:
    raw = os.getenv("OFFICIAL_EVENT_REFRESH_TICKERS", ",".join(DEFAULT_OFFICIAL_EVENT_TICKERS))
    return validate_official_event_tickers(tuple(raw.split(",")))


class OfficialEventBatchIngestionService:
    """Batch official-event refresh using the existing evidence parsers and repository.

    The financial 9-company exclusion policy is deliberately not reused here:
    investor-conference and material-event sources do not require historical
    consolidated financial statements, so the event scheduler can cover the full
    classified semiconductor universe.
    """

    def __init__(
        self,
        *,
        repository: AnalysisRepository | None = None,
        company_repository: CompanyMasterRepository | None = None,
        company_service: OfficialEventIngestionService | None = None,
        material_rows_fetcher=None,
    ) -> None:
        self.repository = repository or build_analysis_repository()
        self.company_repository = company_repository or build_company_master_repository()
        self.company_service = company_service or OfficialEventIngestionService(repository=self.repository)
        self.material_rows_fetcher = material_rows_fetcher or fetch_twse_material_event_rows

    def _resolve_tickers(
        self,
        *,
        scope: OfficialEventBatchScope,
        tickers: list[str] | None,
    ) -> tuple[str, ...]:
        if scope == "classified":
            return tuple(sorted(ALLOWED_OFFICIAL_EVENT_TICKERS))
        if scope == "explicit":
            return validate_official_event_tickers(tickers or [])
        if tickers:
            raise ValueError("tickers may only be supplied when batch_scope=explicit.")
        return configured_official_event_tickers()

    def _prime_company_profiles(self, tickers: tuple[str, ...]) -> None:
        missing: list[str] = []
        for ticker in tickers:
            master = self.company_repository.get(ticker)
            if master is not None:
                register_company_profile(profile_from_master(master))
                continue
            if get_company(ticker) is None:
                missing.append(ticker)
        if missing:
            raise UnsupportedCompanyError(
                "Official-event batch contains tickers absent from company master and seed registry: "
                + ", ".join(missing)
            )

    @staticmethod
    def _company_status(
        result: OfficialEventsRefreshResult,
        *,
        include_conferences: bool,
        include_material_events: bool,
    ) -> str:
        requested_outcomes: list[str] = []
        if include_conferences:
            requested_outcomes.append(result.live_source_outcome.get("investor_conference", "NO_DATA"))
        if include_material_events:
            requested_outcomes.append(result.live_source_outcome.get("material_event", "NO_DATA"))
        if any(outcome in PARTIAL_SOURCE_OUTCOMES for outcome in requested_outcomes):
            return "partial"
        return "completed"

    def _material_from_shared_rows(
        self,
        ticker: str,
        rows: list[dict[str, Any]],
        *,
        material_event_year: int | None,
    ) -> OfficialEventsRefreshResult:
        company = get_company(ticker)
        if company is None:
            raise UnsupportedCompanyError(
                "Official-event refresh requires a company in the persisted semiconductor master."
            )
        refreshed_at = datetime.now(timezone.utc)
        material_events = parse_twse_material_event_rows(company.ticker, rows)
        if material_event_year is not None:
            material_events = [
                record
                for record in material_events
                if (record.event_date or "").startswith(str(material_event_year))
            ]
        persistable = [record for record in material_events if is_persistable_material_event(record)]
        persisted = self.repository.save_official_events(
            ticker=company.ticker,
            investor_conferences=[],
            material_events=persistable,
            refreshed_at=refreshed_at,
        )
        outcome = "PASS" if persistable else "NO_DATA"
        return OfficialEventsRefreshResult(
            ticker=company.ticker,
            company_name=company.name,
            subindustry=company.subindustry,
            refreshed_at=refreshed_at,
            investor_conference_count=0,
            material_event_count=len(persistable),
            persisted=persisted,
            live_source_outcome={"material_event": outcome},
            source_health=[
                {
                    "source": "material_event",
                    "status": outcome,
                    "records_found": len(material_events),
                    "records_persistable": len(persistable),
                    "last_attempt": refreshed_at.isoformat(),
                    "last_success": refreshed_at.isoformat() if persistable else None,
                }
            ],
            investor_conferences=[],
            material_events=material_events,
            limitations=[],
        )

    @staticmethod
    def _concurrency() -> int:
        return max(1, min(16, int(os.getenv("OFFICIAL_EVENT_BATCH_CONCURRENCY", "4"))))

    @staticmethod
    def _max_attempts() -> int:
        return max(1, min(4, int(os.getenv("OFFICIAL_EVENT_BATCH_MAX_ATTEMPTS", "2"))))

    @staticmethod
    def _request_delay_seconds() -> float:
        return max(0.0, min(5.0, float(os.getenv("OFFICIAL_EVENT_BATCH_REQUEST_DELAY_SECONDS", "0.10"))))

    async def _fetch_shared_material_rows(self) -> list[dict[str, Any]]:
        attempts = self._max_attempts()
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return await asyncio.to_thread(self.material_rows_fetcher)
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
        assert last_error is not None
        raise last_error

    async def refresh_all(
        self,
        *,
        include_conferences: bool = True,
        include_material_events: bool = True,
        material_event_year: int | None = None,
        extract_documents: bool = False,
        material_fetch_details: bool = False,
        material_openapi_only: bool = False,
        trigger: OfficialEventBatchTrigger = "scheduler",
        batch_scope: OfficialEventBatchScope = "default",
        tickers: list[str] | None = None,
    ) -> OfficialEventsBatchRefreshResult:
        if not include_conferences and not include_material_events:
            raise ValueError("At least one official-event source must be enabled.")
        if material_openapi_only and (include_conferences or not include_material_events):
            raise ValueError(
                "material_openapi_only is only valid for a material-event-only batch."
            )

        requested_tickers = self._resolve_tickers(scope=batch_scope, tickers=tickers)
        self._prime_company_profiles(requested_tickers)
        batch_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        logger.info(
            "official_events_batch_started batch_id=%s trigger=%s scope=%s companies=%s "
            "conferences=%s material_events=%s material_openapi_only=%s",
            batch_id,
            trigger,
            batch_scope,
            len(requested_tickers),
            include_conferences,
            include_material_events,
            material_openapi_only,
        )

        shared_material_rows: list[dict[str, Any]] | None = None
        if material_openapi_only:
            shared_material_rows = await self._fetch_shared_material_rows()
            logger.info(
                "official_events_material_feed batch_id=%s rows=%s",
                batch_id,
                len(shared_material_rows),
            )

        semaphore = asyncio.Semaphore(self._concurrency())
        delay = self._request_delay_seconds()

        async def run_one(ticker: str, index: int) -> OfficialEventBatchCompanyResult:
            async with semaphore:
                if delay and index:
                    await asyncio.sleep(delay * (index % self._concurrency()))
                try:
                    if shared_material_rows is not None:
                        result = await asyncio.to_thread(
                            self._material_from_shared_rows,
                            ticker,
                            shared_material_rows,
                            material_event_year=material_event_year,
                        )
                    else:
                        result = await asyncio.to_thread(
                            self.company_service.refresh_company,
                            ticker,
                            include_conferences=include_conferences,
                            include_material_events=include_material_events,
                            material_event_year=material_event_year,
                            extract_documents=extract_documents,
                            material_fetch_details=material_fetch_details,
                        )
                    status = self._company_status(
                        result,
                        include_conferences=include_conferences,
                        include_material_events=include_material_events,
                    )
                    logger.info(
                        "official_events_company_complete batch_id=%s ticker=%s status=%s "
                        "conferences=%s material_events=%s outcomes=%s",
                        batch_id,
                        ticker,
                        status,
                        result.investor_conference_count,
                        result.material_event_count,
                        result.live_source_outcome,
                    )
                    return OfficialEventBatchCompanyResult(
                        ticker=ticker,
                        status=status,
                        investor_conference_count=result.investor_conference_count,
                        material_event_count=result.material_event_count,
                        persisted=result.persisted,
                        live_source_outcome=result.live_source_outcome,
                    )
                except Exception as exc:
                    logger.exception(
                        "official_events_company_failed batch_id=%s ticker=%s error=%s",
                        batch_id,
                        ticker,
                        exc,
                    )
                    return OfficialEventBatchCompanyResult(
                        ticker=ticker,
                        status="failed",
                        error=str(exc),
                    )

        results = list(
            await asyncio.gather(
                *(run_one(ticker, index) for index, ticker in enumerate(requested_tickers))
            )
        )
        completed_at = datetime.now(timezone.utc)
        elapsed_seconds = (completed_at - started_at).total_seconds()
        completed_count = sum(item.status == "completed" for item in results)
        partial_count = sum(item.status == "partial" for item in results)
        failed_count = sum(item.status == "failed" for item in results)
        if failed_count == len(results):
            aggregate_status = "failed"
        elif failed_count or partial_count:
            aggregate_status = "partial"
        else:
            aggregate_status = "completed"
        logger.info(
            "official_events_batch_completed batch_id=%s status=%s requested=%s completed=%s "
            "partial=%s failed=%s elapsed_seconds=%.3f",
            batch_id,
            aggregate_status,
            len(results),
            completed_count,
            partial_count,
            failed_count,
            elapsed_seconds,
        )
        return OfficialEventsBatchRefreshResult(
            batch_id=batch_id,
            trigger=trigger,
            scope=batch_scope,
            started_at=started_at,
            completed_at=completed_at,
            elapsed_seconds=elapsed_seconds,
            status=aggregate_status,
            requested_companies=len(results),
            completed_companies=completed_count,
            partial_companies=partial_count,
            failed_companies=failed_count,
            include_conferences=include_conferences,
            include_material_events=include_material_events,
            material_openapi_only=material_openapi_only,
            results=results,
        )
