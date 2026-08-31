from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.official_event_models import OfficialEvidenceCardResponse
from app.services.analysis_repository import AnalysisRepository
from app.services.official_document_extraction import enrich_conferences_with_document_extraction
from app.services.official_evidence_service import OfficialEvidenceService


def _dump(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value or {})


def _claim_dicts(items: list[Any]) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        for claim in getattr(item, "disclosure_claims", []) or []:
            dumped = claim.model_dump(mode="json") if hasattr(claim, "model_dump") else dict(claim)
            key = (str(dumped.get("claim_type")), str(dumped.get("text")))
            if key not in seen:
                seen.add(key)
                claims.append(dumped)
    return claims


def _source_status(conferences: list[Any], material_events: list[Any], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    conference_statuses = [getattr(item, "status", "metadata_only") for item in conferences]
    extract_statuses = [getattr(item, "document_extract_status", "metadata_only") for item in conferences]
    return {
        "financial_snapshot_present": snapshot is not None,
        "conference_count": len(conferences),
        "conference_available_count": sum(1 for status in conference_statuses if status == "available"),
        "conference_statuses": conference_statuses,
        "document_extract_statuses": extract_statuses,
        "document_link_count": sum(1 for item in conferences if getattr(item, "document_url", None)),
        "text_preview_count": sum(1 for item in conferences if getattr(item, "document_text_preview", None)),
        "claim_count": len(_claim_dicts([*conferences, *material_events])),
        "material_event_count": len(material_events),
    }


class OfficialEvidenceCardBuilder:
    """Build a stable UI payload for Flask/Jinja dashboards and detail pages."""

    def __init__(self, repository: AnalysisRepository | None = None) -> None:
        self.repository = repository

    def build(
        self,
        ticker: str,
        *,
        include_conferences: bool = True,
        include_material_events: bool = True,
        fetch_conference_live: bool = False,
        extract_documents: bool = False,
        material_event_year: int | None = None,
    ) -> OfficialEvidenceCardResponse:
        summary = OfficialEvidenceService(repository=self.repository).build(
            ticker,
            include_conferences=include_conferences,
            include_material_events=include_material_events,
            fetch_conference_live=fetch_conference_live,
            material_event_year=material_event_year,
        )
        conferences = list(summary.investor_conferences)
        extraction_debug: dict[str, Any] | None = None
        if extract_documents and conferences:
            conferences, _results, extraction_debug = enrich_conferences_with_document_extraction(conferences)
        snapshot = summary.financial_snapshot
        key_metrics = list((snapshot or {}).get("key_metrics", []))[:6]
        rule_cards = list((snapshot or {}).get("rule_cards", []))[:8]
        claims = _claim_dicts([*conferences, *summary.material_events])
        status = _source_status(conferences, summary.material_events, snapshot)
        limitations = list(dict.fromkeys([
            *summary.limitations,
            *[limitation for item in conferences for limitation in item.limitations],
            *[limitation for item in summary.material_events for limitation in item.limitations],
        ]))
        if extraction_debug:
            status["document_extraction"] = extraction_debug
        headline = (
            f"{summary.company_name} 官方證據層已整合"
            if snapshot is not None
            else f"{summary.company_name} 尚未建立財報 snapshot"
        )
        if status["conference_available_count"]:
            headline += "，並含法說會／IR 證據"
        elif include_conferences:
            headline += "，法說會層仍需補強"
        return OfficialEvidenceCardResponse(
            ticker=summary.ticker,
            company_name=summary.company_name,
            subindustry=summary.subindustry,
            generated_at=datetime.now(timezone.utc),
            evidence_readiness=summary.readiness,
            overall_severity=(snapshot or {}).get("overall_severity"),
            headline=headline,
            summary=summary.official_evidence_summary,
            financial_snapshot=snapshot,
            key_metrics=key_metrics,
            rule_cards=rule_cards,
            investor_conferences=[_dump(item) for item in conferences],
            material_events=[_dump(item) for item in summary.material_events],
            disclosure_claims=claims,
            sources=[source.model_dump(mode="json") for source in summary.sources],
            source_status=status,
            limitations=limitations,
            frontend_hints={
                "recommended_cards": ["risk_summary", "key_metrics", "official_sources", "limitations"],
                "detail_sections": ["financial_snapshot", "rule_cards", "investor_conferences", "material_events", "disclosure_claims"],
                "empty_state_strategy": "來源抓取失敗時仍顯示財報 snapshot 與 limitations，不讓整頁空白。",
            },
        )
