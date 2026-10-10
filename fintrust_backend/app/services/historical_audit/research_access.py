"""Unified, read-only research access over the local archive or the cloud mirror.

Downstream research code depends on ``ResearchBackend`` only. Both
implementations feed the same backend-independent rules
(``reader.finalize_fact_rows``, ``evidence_export.finalize_comparisons`` /
``finalize_summaries``), so filing-version ids, fact ids, hashes, revision
status, scope, dates and point-in-time eligibility agree by construction; the
contract tests compare them field by field.

This is also the read contract for a future API (Phase 4/5). No FastAPI route
is registered in Phase 1C.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from app.services.historical_audit.evidence_export import (
    finalize_comparisons,
    finalize_summaries,
    list_restatement_comparisons,
    list_summary_observations,
    summary_evidence_map,
)
from app.services.historical_audit.firestore_repository import FirestoreHistoricalResearchRepository, strip_internal
from app.services.historical_audit.models import VersionPolicy, parse_timestamp
from app.services.historical_audit.reader import finalize_fact_rows, list_historical_facts
from app.services.historical_audit.repository import HistoricalAuditRepository

AsOf = date | datetime | str | None
_FACT_COLUMNS = (
    "fact_id", "filing_version_id", "ticker", "period", "fiscal_year", "metric_code", "value", "value_text", "unit",
    "statement_type", "statement_scope", "taxonomy_concept", "context_ref", "mapping_method", "quality_status",
    "quality_notes_json", "source_kind", "source_url",
)
_VERSION_COLUMNS = (
    "filing_version_type", "version_type_evidence_json", "source_published_at", "available_at", "availability_status",
    "availability_basis", "verification_evidence_json", "document_dated_at", "retrieved_at", "content_hash",
    "raw_storage_path", "parser_version", "validation_status", "statement_scope_evidence",
)


class ResearchBackend(Protocol):
    backend_name: str

    def list_facts(self, ticker: str, start_year: int, end_year: int, *, as_of: AsOf = None,
                   version_policy: VersionPolicy = "all") -> list[dict[str, Any]]: ...
    def list_filing_versions(self, ticker: str, start_year: int, end_year: int) -> list[dict[str, Any]]: ...
    def list_restatement_comparisons(self, ticker: str, *, as_of: AsOf = None) -> list[dict[str, Any]]: ...
    def list_summary_observations(self, ticker: str, *, as_of: AsOf = None) -> list[dict[str, Any]]: ...


class LocalResearchBackend:
    backend_name = "local"

    def __init__(self, repository: HistoricalAuditRepository) -> None:
        self.repository = repository

    def list_facts(self, ticker, start_year, end_year, *, as_of=None, version_policy="all"):
        return list_historical_facts(self.repository, ticker, start_year, end_year, as_of=as_of,
                                     version_policy=version_policy, include_test_fixtures=False)

    def list_filing_versions(self, ticker, start_year, end_year):
        return [_public_version(v) for v in self.repository.list_filing_versions(ticker, start_year, end_year)]

    def list_restatement_comparisons(self, ticker, *, as_of=None):
        return list_restatement_comparisons(self.repository, ticker, as_of=as_of)

    def list_summary_observations(self, ticker, *, as_of=None):
        return list_summary_observations(self.repository, ticker, as_of=as_of)


class FirestoreResearchBackend:
    """Reads the ``historical_research_*`` mirror written by ``cloud_sync``."""

    backend_name = "firestore"

    def __init__(self, repository: FirestoreHistoricalResearchRepository) -> None:
        self.repository = repository

    def _rows(self, kind: str, ticker: str) -> list[dict[str, Any]]:
        return strip_internal(self.repository.list(kind, ticker=ticker))

    def _documents(self, ticker: str) -> dict[str, dict[str, Any]]:
        return {d["source_document_id"]: d for d in self._rows("source_documents", ticker)}

    def _events(self, ticker: str) -> dict[str, dict[str, Any]]:
        return {e["event_id"]: e for e in self._rows("publication_events", ticker)}

    def list_facts(self, ticker, start_year, end_year, *, as_of=None, version_policy="all"):
        versions = {v["filing_version_id"]: v for v in self._rows("filing_versions", ticker)}
        comparisons = {c["comparison_id"]: c for c in self._rows("comparisons", ticker)}
        documents, events = self._documents(ticker), self._events(ticker)
        availability: dict[str, list[dict[str, Any]]] = {}
        for row in self._rows("observation_availability", ticker):
            if row["observation_kind"] == "versioned_fact":
                availability.setdefault(row["observation_id"], []).append(row)
        rows, evidence = [], {}
        for fact in self._rows("facts", ticker):
            version = versions.get(fact["filing_version_id"])
            if version is None or not start_year <= fact["fiscal_year"] <= end_year:
                continue
            if version["validation_status"] not in {"validated", "validated_with_warnings"} or fact["source_kind"] == "test_fixture":
                continue
            row = {key: fact.get(key) for key in _FACT_COLUMNS}
            row.update({key: version.get(key) for key in _VERSION_COLUMNS})
            items = availability.get(fact["fact_id"], [])
            row["observation_available_at"] = min((i["available_at"] for i in items), key=parse_timestamp) if items else None
            row["observation_basis"] = " | ".join(i["basis"] for i in items) if items else None
            if items:
                best = min(items, key=lambda i: (parse_timestamp(i["available_at"]), i["corroborating_id"]))
                comparison = comparisons.get(best["corroborating_id"], {})
                document = documents.get(comparison.get("source_document_id"), {})
                event = events.get(comparison.get("event_id"), {})
                evidence[fact["fact_id"]] = {
                    "observation_id": fact["fact_id"], "available_at": best["available_at"],
                    "corroborating_id": best["corroborating_id"], "match_detail": best["match_detail"],
                    "source_url": document.get("source_url"), "content_hash": document.get("content_hash"),
                    "event_key": event.get("event_key"),
                }
            rows.append(row)
        return finalize_fact_rows(rows, evidence, as_of=as_of, version_policy=version_policy)

    def list_filing_versions(self, ticker, start_year, end_year):
        rows = [v for v in self._rows("filing_versions", ticker) if start_year <= v["fiscal_year"] <= end_year]
        return sorted((_public_version(v) for v in rows),
                      key=lambda v: (v["fiscal_year"], v["retrieved_at"], v["filing_version_id"]))

    def list_restatement_comparisons(self, ticker, *, as_of=None):
        documents, events = self._documents(ticker), self._events(ticker)
        rows = []
        for comparison in self._rows("comparisons", ticker):
            document = documents[comparison["source_document_id"]]
            rows.append({**comparison, "source_url": document["source_url"], "content_hash": document["content_hash"],
                         "event_key": events[comparison["event_id"]]["event_key"]})
        return finalize_comparisons(rows, ticker, as_of=as_of)

    def list_summary_observations(self, ticker, *, as_of=None):
        documents, events = self._documents(ticker), self._events(ticker)
        comparisons = {c["comparison_id"]: c for c in self._rows("comparisons", ticker)}
        availability = [row for row in self._rows("observation_availability", ticker)
                        if row["observation_kind"] == "summary_observation"]
        rows = []
        for summary in self._rows("summary_observations", ticker):
            document = documents[summary["source_document_id"]]
            rows.append({**summary, "source_url": document["source_url"], "content_hash": document["content_hash"],
                         "retrieved_at": document["retrieved_at"]})
        return finalize_summaries(rows, ticker, as_of=as_of,
                                  evidence=summary_evidence_map(availability, comparisons, documents, events))


_VERSION_PUBLIC_FIELDS = (
    "filing_version_id", "ticker", "period", "fiscal_year", "statement_scope", "filing_version_type", "source_kind",
    "source_url", "content_hash", "content_length", "available_at", "availability_status", "availability_basis",
    "source_published_at", "document_dated_at", "retrieved_at", "validation_status", "quarantine_reason",
)


def _public_version(version: dict[str, Any]) -> dict[str, Any]:
    """Backend-neutral view (no local paths, no cloud object names)."""
    return {key: version.get(key) for key in _VERSION_PUBLIC_FIELDS}
