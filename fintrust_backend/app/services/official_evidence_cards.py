from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.official_event_models import OfficialEvidenceCardResponse
from app.services.analysis_repository import AnalysisRepository
from app.services.conference_document_digest import (
    ConferenceDocumentDigestService,
    archive_identity,
    conference_target,
)
from app.services.material_event_status import material_event_status, read_material_event_sync
from app.services.official_document_extraction import enrich_conferences_with_document_extraction
from app.services.official_evidence_service import OfficialEvidenceService
from app.services.text_intelligence import FinancialTextIntelligenceService, documents_from_official_events
from app.services.llm_evidence_selection import select_llm_text_evidence


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


def _attach_document_digests(
    ticker: str,
    items: list[dict[str, Any]],
    service: ConferenceDocumentDigestService,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Attach an archived MOPS PDF digest to each conference item whose period or
    date matches the archived document; never borrow another period's document.

    Returns the card-level digest (latest archived document, only when no item
    matched) and a status summary. Items keep every existing field.
    """
    by_target: dict[tuple[str | None, str | None], tuple[dict[str, Any] | None, str]] = {}
    matched = 0
    for item in items:
        target = conference_target(item)
        if target == (None, None):
            item["summary_status"] = "no_conference_period"
            continue
        if target not in by_target:
            by_target[target] = service.digest_for(ticker, period=target[0], conference_date=target[1])
        digest, status = by_target[target]
        item["summary_status"] = status
        if digest is not None:
            matched += 1
            item["document_digest"] = digest
            item["evidence_coverage"] = digest["coverage"]
            item["archive_identity"] = archive_identity(digest)
    card_digest = None
    card_status = "attached_to_conference" if matched else "not_requested"
    if not matched:
        card_digest, card_status = service.digest_for(ticker)
    return card_digest, {
        "matched_conference_count": matched,
        "card_level_digest_status": card_status,
        "conference_summary_statuses": [item.get("summary_status") for item in items],
    }


# --- source identity (frontend contract 1.2.0) --------------------------------------
# Derived only from fields each record already carries; anything not on the record
# stays null. A conference or announcement date is never turned into a fiscal period.

_SOURCE_TYPES_BY_NAME = {
    "company_official_ir": "company_ir",
    "twse_openapi": "twse_openapi",
    "mops": "mops_listing",
    "公開資訊觀測站 法說會": "mops_listing",
    "公開資訊觀測站 重大訊息": "mops_listing",
}
_AVAILABILITY_BY_STATUS = {
    "available": "available",
    "metadata_only": "metadata_only",
    "needs_manual_review": "needs_review",
    "blocked_by_source": "blocked",
    "missing": "unavailable",
    "error": "unavailable",
}


def _record_source_type(record: dict[str, Any], event_date: str | None) -> str:
    name = str(record.get("source_name") or "")
    source_type = _SOURCE_TYPES_BY_NAME.get(name)
    if source_type is None:
        return "demo_fixture" if "DEMO" in name.upper() else "unknown"
    # MOPS query-entry placeholders carry no date and no available content.
    if source_type == "mops_listing" and not event_date and record.get("status") != "available":
        return "metadata_placeholder"
    return source_type


def record_source_identity(record: dict[str, Any], kind: str) -> dict[str, Any]:
    """Identity of a persisted conference ("investor_conference") or material event record."""
    if kind == "investor_conference":
        event_date = record.get("conference_date")
        year, quarter = record.get("fiscal_year"), record.get("quarter")
        period = f"{int(year)}Q{int(quarter)}" if year and quarter else None
        url = record.get("document_url") or record.get("source_url")
    else:
        event_date = record.get("event_date")
        period = None
        url = record.get("detail_url") or record.get("source_url")
    return {
        "source_type": _record_source_type(record, event_date),
        "source_name": record.get("source_name"),
        "period": period,
        "period_basis": "fiscal_year_quarter" if period else "none",
        "document_type": None,
        "filename": None,
        "event_date": event_date,
        "availability": _AVAILABILITY_BY_STATUS.get(str(record.get("status") or ""), "unavailable"),
        "provenance": {"url": url, "sha256": None, "retrieved_at": record.get("retrieved_at")},
    }


def digest_source_identity(digest: dict[str, Any]) -> dict[str, Any]:
    """Identity of an archived MOPS conference PDF digest; provenance stays MOPS-only."""
    source = digest.get("source") or {}
    period = digest.get("period")
    return {
        "source_type": "mops_conference_pdf",
        "source_name": "MOPS",
        "period": period,
        "period_basis": "document_identity" if period else "none",
        "document_type": digest.get("document_type"),
        "filename": source.get("filename"),
        "event_date": digest.get("conference_date"),
        "availability": "available",
        "provenance": {"url": source.get("listing_url"), "sha256": source.get("sha256"), "retrieved_at": None},
    }


# Precedence, first match wins: not_configured (no digest service, or conferences
# not requested) > attached (a conference item carries its matching digest) >
# standalone_latest (a separate latest MOPS digest) > archive_unavailable >
# digest_failed > digest_timeout > no_matching_archive.
_FAILURE_STATES = ("archive_unavailable", "digest_failed", "digest_timeout", "no_matching_archive")


def conference_summary_state(digest_status: dict[str, Any] | None, card_digest: dict[str, Any] | None) -> str:
    if digest_status is None:
        return "not_configured"
    if digest_status.get("matched_conference_count"):
        return "attached"
    if card_digest is not None:
        return "standalone_latest"
    statuses = {digest_status.get("card_level_digest_status"), *(digest_status.get("conference_summary_statuses") or [])}
    return next((state for state in _FAILURE_STATES if state in statuses), "no_matching_archive")


class OfficialEvidenceCardBuilder:
    """Build a stable UI payload for Flask/Jinja dashboards and detail pages."""

    def __init__(
        self,
        repository: AnalysisRepository | None = None,
        digest_service: ConferenceDocumentDigestService | None = None,
    ) -> None:
        self.repository = repository
        self.digest_service = digest_service

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
        text_documents = documents_from_official_events(
            ticker=summary.ticker,
            conferences=conferences,
            material_events=summary.material_events,
        )
        text_service = FinancialTextIntelligenceService()
        text_analysis = text_service.analyze_documents(text_documents)
        text_evidence = [
            sentence.model_dump(mode="json")
            for document in text_analysis.documents
            for sentence in document.sentences
            if sentence.relevant
        ][:8]
        comparable_documents = [document for document in text_documents if document.period and document.text.strip()]
        narrative_shift = None
        if len(comparable_documents) >= 2:
            ordered = sorted(comparable_documents, key=lambda item: item.period or "")
            narrative_shift = text_service.narrative_shift(ordered[-2], ordered[-1]).model_dump(mode="json")
        _selected_evidence, llm_evidence_ids = select_llm_text_evidence(
            text_evidence,
            narrative_shift=narrative_shift,
        )
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
        conference_items = [_dump(item) for item in conferences]
        conference_document_digest = None
        if self.digest_service is not None and include_conferences:
            try:
                conference_document_digest, status["document_digest_status"] = _attach_document_digests(
                    summary.ticker, conference_items, self.digest_service,
                )
            except Exception:
                status["document_digest_status"] = {"card_level_digest_status": "digest_failed"}
        summary_state = conference_summary_state(status.get("document_digest_status"), conference_document_digest)
        for item in conference_items:
            item["source_identity"] = record_source_identity(item, "investor_conference")
            if isinstance(item.get("document_digest"), dict):
                item["document_digest"]["source_identity"] = digest_source_identity(item["document_digest"])
        if conference_document_digest is not None:
            conference_document_digest["source_identity"] = digest_source_identity(conference_document_digest)
        material_event_items = [_dump(item) for item in summary.material_events]
        for item in material_event_items:
            item["source_identity"] = record_source_identity(item, "material_event")
        event_status = (
            material_event_status(summary.material_events, read_material_event_sync(self.repository, summary.ticker))
            if include_material_events
            else None
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
            investor_conferences=conference_items,
            conference_document_digest=conference_document_digest,
            conference_summary_state=summary_state,
            material_events=material_event_items,
            material_event_status=event_status,
            disclosure_claims=claims,
            text_evidence=text_evidence,
            narrative_shift=narrative_shift,
            semantic_analysis=text_analysis.semantic_analysis,
            llm_evidence_ids=llm_evidence_ids,
            sources=[source.model_dump(mode="json") for source in summary.sources],
            source_status=status,
            limitations=limitations,
            frontend_hints={
                "recommended_cards": ["risk_summary", "key_metrics", "official_sources", "limitations"],
                "detail_sections": ["financial_snapshot", "rule_cards", "investor_conferences", "material_events", "disclosure_claims"],
                "empty_state_strategy": "來源抓取失敗時仍顯示財報 snapshot 與 limitations，不讓整頁空白。",
            },
        )
