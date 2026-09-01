from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.official_event_models import OfficialEvidenceSummary, OfficialSourceLink
from app.services.analysis_repository import AnalysisRepository
from app.services.company_registry import get_company
from app.services.financial_analysis_service import UnsupportedCompanyError
from app.services.official_event_sources import (
    build_investor_conference_metadata,
    build_material_event_metadata,
)


def _model_to_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    return dict(value)


def _prefer_available_records(items: list[Any]) -> list[Any]:
    available = [item for item in items if getattr(item, "status", None) == "available"]
    return available or items


class OfficialEvidenceService:
    """Aggregate official quantitative and event disclosures for the shared frontend."""

    def __init__(self, repository: AnalysisRepository | None = None) -> None:
        self.repository = repository

    def build(
        self,
        ticker: str,
        *,
        include_conferences: bool = True,
        include_material_events: bool = True,
        fetch_conference_live: bool = False,
        material_event_year: int | None = None,
    ) -> OfficialEvidenceSummary:
        company = get_company(ticker)
        if company is None:
            raise UnsupportedCompanyError("MVP 僅分析已登錄的半導體公司；請先將公司加入 semiconductor registry。")

        snapshot_obj = self.repository.get_latest_snapshot(company.ticker) if self.repository else None
        snapshot = _model_to_dict(snapshot_obj)
        conferences = []
        if include_conferences:
            if fetch_conference_live:
                conferences = build_investor_conference_metadata(company.ticker, fetch_live=True)
            elif self.repository:
                conferences = self.repository.list_investor_conferences(company.ticker)
                conferences = _prefer_available_records(conferences)

        material_events = []
        if include_material_events:
            if self.repository:
                material_events = self.repository.list_material_events(company.ticker)
                if material_event_year is not None:
                    year_text = str(material_event_year)
                    material_events = [item for item in material_events if (item.event_date or "").startswith(year_text)]
                material_events = _prefer_available_records(material_events)
            elif material_event_year is not None:
                material_events = build_material_event_metadata(company.ticker, year=material_event_year)

        layers = []
        limitations: list[str] = []
        sources: list[OfficialSourceLink] = []
        if snapshot is not None:
            layers.append("financial_snapshot")
            limitations.extend(snapshot.get("limitations", []))
            for item in snapshot.get("sources", []):
                if isinstance(item, dict):
                    source_name = str(item.get("source_name") or item.get("name") or "official financial source")
                    source_url = str(item.get("source_url") or item.get("url") or "")
                    if source_url:
                        sources.append(
                            OfficialSourceLink(
                                source_name=source_name,
                                source_url=source_url,
                                status="available",
                            )
                        )
        else:
            limitations.append("尚未有最新財報 snapshot；請先執行官方財報 refresh。")

        if conferences:
            layers.append("investor_conference")
            limitations.extend(limitation for item in conferences for limitation in item.limitations)
            sources.extend(
                OfficialSourceLink(
                    source_name=item.source_name,
                    source_url=item.document_url or item.source_url,
                    status=item.status,
                    limitation=(
                        f"已讀取 persisted {item.source_name} 法說會附件或頁面文字 preview。"
                        if item.status == "available"
                        else "尚未取得可用 persisted 法說會資料；請執行 official-events refresh。"
                    ),
                )
                for item in conferences
            )
        if material_events:
            layers.append("material_event")
            limitations.extend(limitation for item in material_events for limitation in item.limitations)
            sources.extend(
                OfficialSourceLink(
                    source_name=item.source_name,
                    source_url=item.detail_url or item.source_url,
                    status=item.status,
                    limitation=f"已讀取 persisted {item.source_name} 重大訊息。" if item.status == "available" else "尚未取得可用 persisted 重大訊息；請執行 official-events refresh。",
                )
                for item in material_events
            )

        readiness = (
            "ready_for_frontend_integration"
            if snapshot is not None and (conferences or material_events)
            else "financial_only"
            if snapshot is not None
            else "needs_refresh"
        )
        summary_parts = []
        if snapshot is not None:
            summary_parts.append("已納入年度財報 latest snapshot 作為官方量化證據。")
        if conferences:
            parsed_count = sum(1 for item in conferences if item.status == "available")
            if parsed_count:
                summary_parts.append("已納入 persisted 官方法說會／IR 頁面文字或附件連結，可補充近期展望、產能、庫存與需求訊息。")
            else:
                summary_parts.append("法說會 persisted evidence 尚未就緒，請由管理端執行 refresh。")
        if material_events:
            summary_parts.append("已納入 persisted 官方重大訊息與事件分類層，用於補充更即時的官方事件。")
        if not summary_parts:
            summary_parts.append("尚未取得可用官方證據，請先執行 refresh。")

        return OfficialEvidenceSummary(
            ticker=company.ticker,
            company_name=company.name,
            subindustry=company.subindustry,
            generated_at=datetime.now(timezone.utc),
            evidence_layers=layers,
            financial_snapshot=snapshot,
            investor_conferences=conferences,
            material_events=material_events,
            official_evidence_summary="".join(summary_parts),
            readiness=readiness,
            limitations=list(dict.fromkeys(limitations)),
            sources=sources,
        )
