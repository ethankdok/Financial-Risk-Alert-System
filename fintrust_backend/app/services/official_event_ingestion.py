from __future__ import annotations

from datetime import datetime, timezone

from app.official_event_models import OfficialEventsRefreshResult
from app.services.analysis_repository import AnalysisRepository, build_analysis_repository
from app.services.company_registry import get_company
from app.services.financial_analysis_service import UnsupportedCompanyError
from app.services.official_document_extraction import enrich_conferences_with_document_extraction
from app.services.official_event_sources import (
    build_investor_conference_metadata,
    build_material_event_metadata,
    is_persistable_investor_conference,
    is_persistable_material_event,
)


class OfficialEventIngestionService:
    """Refresh recent official disclosure evidence without touching financial rules."""

    def __init__(self, *, repository: AnalysisRepository | None = None) -> None:
        self.repository = repository or build_analysis_repository()

    def refresh_company(
        self,
        ticker: str,
        *,
        include_conferences: bool = True,
        include_material_events: bool = True,
        material_event_year: int | None = None,
        extract_documents: bool = True,
        material_fetch_details: bool = True,
    ) -> OfficialEventsRefreshResult:
        company = get_company(ticker)
        if company is None:
            raise UnsupportedCompanyError("MVP 僅分析已登錄的半導體公司；請先將公司加入 semiconductor registry。")

        refreshed_at = datetime.now(timezone.utc)
        conferences = []
        material_events = []
        outcomes: dict[str, str] = {}
        limitations: list[str] = []

        if include_conferences:
            conferences = build_investor_conference_metadata(company.ticker, fetch_live=True)
            if extract_documents:
                conferences, _documents, _debug = enrich_conferences_with_document_extraction(conferences)
            outcomes["investor_conference"] = _source_outcome([item.status for item in conferences])
            limitations.extend(item for record in conferences for item in record.limitations)

        if include_material_events:
            material_events = build_material_event_metadata(
                company.ticker,
                year=material_event_year,
                fetch_live=True,
                fetch_details=material_fetch_details,
            )
            outcomes["material_event"] = _source_outcome([item.status for item in material_events])
            limitations.extend(item for record in material_events for item in record.limitations)

        persistable_conferences = [record for record in conferences if is_persistable_investor_conference(record)]
        persistable_material_events = [record for record in material_events if is_persistable_material_event(record)]
        persisted = self.repository.save_official_events(
            ticker=company.ticker,
            investor_conferences=persistable_conferences,
            material_events=persistable_material_events,
            refreshed_at=refreshed_at,
        )
        if include_material_events and material_events and not persistable_material_events:
            limitations.append("重大訊息 live refresh 僅取得來源診斷或查詢入口；未覆蓋既有 persisted material events。")
        return OfficialEventsRefreshResult(
            ticker=company.ticker,
            company_name=company.name,
            subindustry=company.subindustry,
            refreshed_at=refreshed_at,
            investor_conference_count=len(persistable_conferences),
            material_event_count=len(persistable_material_events),
            persisted=persisted,
            live_source_outcome=outcomes,
            source_health=[
                {
                    "source": "investor_conference",
                    "status": outcomes.get("investor_conference", "NO_DATA"),
                    "records_found": len(conferences),
                    "records_persistable": len(persistable_conferences),
                    "last_attempt": refreshed_at.isoformat(),
                    "last_success": refreshed_at.isoformat() if persistable_conferences else None,
                },
                {
                    "source": "material_event",
                    "status": outcomes.get("material_event", "NO_DATA"),
                    "records_found": len(material_events),
                    "records_persistable": len(persistable_material_events),
                    "last_attempt": refreshed_at.isoformat(),
                    "last_success": refreshed_at.isoformat() if persistable_material_events else None,
                },
            ],
            investor_conferences=conferences,
            material_events=material_events,
            limitations=list(dict.fromkeys(limitations)),
        )


def _source_outcome(statuses: list[str]) -> str:
    if any(status == "available" for status in statuses):
        return "PASS"
    if any(status in {"metadata_only", "needs_manual_review"} for status in statuses):
        return "NO_DATA"
    if any(status == "blocked_by_source" for status in statuses):
        return "BLOCKED_BY_SOURCE"
    if any(status == "error" for status in statuses):
        return "NETWORK_ERROR"
    return "NO_DATA"
