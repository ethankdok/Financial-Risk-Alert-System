"""Unified, read-only research access over the local archive or the cloud mirror.

Downstream research code depends on ``ResearchBackend`` only. Both
implementations feed the same backend-independent rules
(``reader.finalize_fact_rows``, ``evidence_export.finalize_comparisons`` /
``finalize_summaries``), so filing-version ids, fact ids, hashes, revision
status, scope, dates and point-in-time eligibility agree by construction; the
contract tests compare them field by field.

This is also the read contract of the Phase 4 research API
(``app/routers/historical_research.py``), which reads through it only.
Phase 3 added ``list_disclosed_values`` and ``list_publication_events``
(additive; both backends, parity-tested).
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Protocol

from app.services.historical_audit.evidence_export import (
    finalize_comparisons,
    list_disclosed_financial_values,
    list_publication_timeline,
    finalize_summaries,
    list_restatement_comparisons,
    list_summary_observations,
    summary_evidence_map,
)
from app.services.historical_audit.firestore_repository import FirestoreHistoricalResearchRepository, strip_internal
from app.services.historical_audit.evidence_import import availability_instant
from app.services.historical_audit.models import VersionPolicy, as_of_cutoff, parse_timestamp
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


def event_order(row: dict[str, Any]) -> tuple:
    """Total order for timeline rows (a listing row and its verified notice can share time and event_key)."""
    return (row["available_from"], row["event_key"], row["event_type"], row["verification_status"],
            row["content_hash"], row["title"])


class ResearchBackend(Protocol):
    backend_name: str

    def list_facts(self, ticker: str, start_year: int, end_year: int, *, as_of: AsOf = None,
                   version_policy: VersionPolicy = "all") -> list[dict[str, Any]]: ...
    def list_filing_versions(self, ticker: str, start_year: int, end_year: int) -> list[dict[str, Any]]: ...
    def list_restatement_comparisons(self, ticker: str, *, as_of: AsOf = None) -> list[dict[str, Any]]: ...
    def list_summary_observations(self, ticker: str, *, as_of: AsOf = None) -> list[dict[str, Any]]: ...
    def list_disclosed_values(self, ticker: str, *, as_of: AsOf = None) -> list[dict[str, Any]]: ...
    def list_publication_events(self, ticker: str) -> list[dict[str, Any]]: ...


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

    def list_disclosed_values(self, ticker, *, as_of=None):
        return list_disclosed_financial_values(self.repository, ticker, as_of=as_of)

    def list_publication_events(self, ticker):
        return sorted(list_publication_timeline(self.repository, ticker), key=event_order)


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
        disclosed = {d["disclosed_value_id"]: d for d in self._rows("disclosed_values", ticker)}
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
                comparison = (comparisons if best.get("corroborating_kind", "restatement_comparison") == "restatement_comparison"
                              else disclosed).get(best["corroborating_id"], {})
                document = documents.get(comparison.get("source_document_id"), {})
                event = events.get(comparison.get("event_id"), {})
                evidence[fact["fact_id"]] = {
                    "observation_id": fact["fact_id"], "available_at": best["available_at"],
                    "corroborating_id": best["corroborating_id"], "match_detail": best["match_detail"],
                    "corroborating_kind": best.get("corroborating_kind", "restatement_comparison"),
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

    def list_disclosed_values(self, ticker, *, as_of=None):
        """Same rows and order as ``evidence_export.list_disclosed_financial_values`` (parity-tested)."""
        cutoff = as_of_cutoff(as_of) if as_of is not None else None
        documents, events = self._documents(ticker), self._events(ticker)
        dated: dict[str, int] = {}
        for row in self._rows("observation_availability", ticker):
            if row.get("corroborating_kind") == "financial_report_disclosure":
                dated[row["corroborating_id"]] = dated.get(row["corroborating_id"], 0) + 1
        values = sorted(self._rows("disclosed_values", ticker),
                        key=lambda v: (v["fiscal_year"], v["statement_scope"], v["disclosed_at"], v["source_label"]))
        result = []
        for row in values:
            if cutoff is not None and not parse_timestamp(row["disclosed_at"]) < cutoff:
                continue
            document = documents[row["source_document_id"]]
            result.append({
                "ticker": ticker, "evidence_type": "official_disclosed_value", "disclosure_kind": row["disclosure_kind"],
                "period": row["period"], "fiscal_year": row["fiscal_year"], "statement_scope": row["statement_scope"],
                "accounting_framework": row["accounting_framework"], "source_label": row["source_label"],
                "canonical_metric": row["canonical_metric"], "value": row["value_text"],
                "published_unit": row["published_unit"], "normalized_value": row["normalized_value_text"],
                "normalized_unit": row["normalized_unit"], "disclosed_at": row["disclosed_at"],
                "availability_status": row["availability_status"],
                "point_in_time_eligible": row["availability_status"] == "verified",
                "dated_facts": dated.get(row["disclosed_value_id"], 0), "source_url": document["source_url"],
                "announcement_key": events[row["event_id"]]["event_key"], "content_hash": document["content_hash"],
            })
        return result

    def list_publication_events(self, ticker):
        """Same rows and order as ``evidence_export.list_publication_timeline`` (parity-tested)."""
        documents = self._documents(ticker)
        links: dict[str, list[str]] = {}
        for row in sorted(self._rows("evidence_links", ticker), key=lambda r: (r["period"], r.get("target_id") or "")):
            links.setdefault(row["event_id"], []).append(f"{row['period']}:{row['target_id']}:{row['link_status']}")
        result = []
        for event in self._rows("publication_events", ticker):
            document = documents[event["source_document_id"]]
            available_from = availability_instant(event["publication_at"], event["publication_precision"])
            result.append({
                "ticker": ticker, "event_key": event["event_key"], "event_type": event["event_type"],
                "title": event["title"], "announcement_id": event["announcement_id"],
                "publication_at": event["publication_at"], "publication_precision": event["publication_precision"],
                "available_from": available_from.isoformat(), "event_date": event["event_date"],
                "event_date_basis": event["event_date_basis"],
                "affected_periods": ",".join(json.loads(event["affected_periods_json"])),
                "affected_scopes": ",".join(json.loads(event["affected_scopes_json"])),
                "issuer": document["issuer"], "source_url": document["source_url"],
                "content_hash": document["content_hash"], "verification_status": event["verification_status"],
                "linked_filing_versions": ";".join(links.get(event["event_id"], [])),
            })
        return sorted(result, key=event_order)


_VERSION_PUBLIC_FIELDS = (
    "filing_version_id", "ticker", "period", "fiscal_year", "statement_scope", "filing_version_type", "source_kind",
    "source_url", "content_hash", "content_length", "available_at", "availability_status", "availability_basis",
    "source_published_at", "document_dated_at", "retrieved_at", "validation_status", "quarantine_reason",
)


def _public_version(version: dict[str, Any]) -> dict[str, Any]:
    """Backend-neutral view (no local paths, no cloud object names)."""
    return {key: version.get(key) for key in _VERSION_PUBLIC_FIELDS}
