"""Strict point-in-time package assembly (fail closed on unknown availability).

Every dataset in a strict package is derived only from evidence verifiably
public before the cutoff:

- filing artifacts (and their raw bytes) only with a verified ``available_at`` before the cutoff;
- source documents only when they are single-publication official notices
  (TPEx announcements, MOPS material-information detail pages) published before
  the cutoff; listings and summary workbooks are *current snapshots* that contain
  later rows, so their raw bytes are never included;
- financial observations dated by an earlier disclosure are kept, but the later
  filing artifact's identity is withheld (``artifact_reference_status =
  withheld_not_public_at_cutoff``) and the disclosure is named as provenance;
- timeline events only when public before the cutoff, with snapshot-derived
  attributes removed;
- conference documents are excluded unless their availability is verified;
- retrieval timestamps (post-cutoff by nature) live in ``validation/provenance.csv``,
  never in ``data/``. ``leakage_check`` rejects any post-cutoff date in ``data/``.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from app.services.historical_audit.evidence_export import (
    COMPARISON_FIELDS,
    SUMMARY_FIELDS,
    list_publication_timeline,
    list_restatement_comparisons,
    list_summary_observations,
)
from app.services.historical_audit.evidence_import import availability_instant
from app.services.historical_audit.export import EXPORT_FIELDS, build_export_records
from app.services.historical_audit.models import TAIPEI, iso, parse_timestamp

SINGLE_PUBLICATION_PARSERS = ("tpex_announcement", "mops_material_detail")
STRICT_VERSION_FIELDS = (
    "filing_version_id", "ticker", "period", "fiscal_year", "statement_scope", "statement_scope_evidence",
    "filing_version_type", "source_kind", "source_url", "content_hash", "content_length", "detected_format",
    "filing_available_at", "availability_basis", "validation_status", "package_raw_path", "raw_evidence_included",
)
STRICT_INVENTORY_FIELDS = (
    "source_document_id", "source_key", "issuer", "document_type", "source_url", "content_hash",
    "document_available_at", "availability_basis", "package_raw_path", "raw_evidence_included",
)
STRICT_TIMELINE_FIELDS = (
    "ticker", "event_key", "event_type", "title", "announcement_id", "publication_at", "publication_precision",
    "available_from", "event_date", "event_date_basis", "affected_periods", "affected_scopes", "issuer",
    "source_url", "source_document_included", "verification_status", "linked_filing_versions",
)
STRICT_COVERAGE_FIELDS = (
    "fiscal_year", "verified_public_filing_artifacts", "disclosed_observations", "restatement_comparison_rows",
    "summary_observations", "status",
)
PROVENANCE_FIELDS = ("package_path", "sha256", "source_url", "retrieved_at")
WITHHELD_FIELDS = ("filing_version_id", "taxonomy_concept", "source_kind", "source_url", "source_published_at",
                   "available_at", "availability_status", "document_dated_at", "retrieved_at", "content_hash",
                   "validation_status", "quality_status", "filing_available_at")
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?")


def document_availability(repository, ticker: str) -> dict[str, tuple[datetime | None, str]]:
    """Publication instant of single-publication source documents; None for snapshots."""
    with repository.connect() as connection:
        documents = [dict(r) for r in connection.execute(
            "SELECT source_document_id, parser FROM historical_source_documents WHERE ticker = ?", (ticker,))]
        events = [dict(r) for r in connection.execute(
            "SELECT source_document_id, event_type, publication_at, publication_precision FROM historical_publication_events "
            "WHERE ticker = ?", (ticker,))]
    result: dict[str, tuple[datetime | None, str]] = {}
    for document in documents:
        if document["parser"] not in SINGLE_PUBLICATION_PARSERS:
            result[document["source_document_id"]] = (None, "current snapshot (listing/summary); first publication unverified")
            continue
        times = [availability_instant(e["publication_at"], e["publication_precision"])
                 for e in events if e["source_document_id"] == document["source_document_id"]]
        basis = ("TPEx 發文日期 (date only; counted from the next Taipei midnight)" if document["parser"] == "tpex_announcement"
                 else "MOPS material-information 發言日期/發言時間")
        result[document["source_document_id"]] = (min(times) if times else None, basis)
    return result


def leakage_check(files: dict[str, bytes], cutoff: datetime) -> list[str]:
    """Every ISO date/timestamp in data/ must be before the cutoff (dates: on or before the cutoff day)."""
    cutoff_day = (cutoff - timedelta(microseconds=1)).astimezone(TAIPEI).date()
    problems = []
    for path, data in sorted(files.items()):
        if not path.startswith("data/"):
            continue
        for match in _ISO.finditer(data.decode("utf-8", "replace")):
            text = match.group(0)
            if len(text) == 10:
                late = datetime.fromisoformat(text).date() > cutoff_day
            else:
                stamp = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T"))
                late = (stamp.date() > cutoff_day) if stamp.tzinfo is None else stamp >= cutoff
            if late:
                problems.append(f"{path}: {text}")
    return problems


def strict_facts(repository, params, cutoff: datetime, version_public: set[str]) -> list[dict[str, Any]]:
    rows = build_export_records(repository, params.ticker, params.start_year, params.end_year,
                                as_of=params.as_of, version_policy=params.version_policy)
    result = []
    for row in rows:
        row = dict(row)
        if row["filing_version_id"] in version_public:
            row["artifact_reference_status"] = "verified_public_artifact"
        else:
            for name in WITHHELD_FIELDS:
                row[name] = None
            row["artifact_reference_status"] = "withheld_not_public_at_cutoff"
            row["evidence_type"] = "official_disclosed_observation"
            row["completeness"] = "disclosed_value_only"
        row["retrieved_at"] = None  # retrieval metadata lives in validation/provenance.csv
        result.append(row)
    return result


def build_strict(*, add, csv_bytes, json_bytes, repository, archive, params, cutoff: datetime,
                 include_raw: bool) -> dict[str, Any]:
    ticker = params.ticker
    provenance: list[dict[str, Any]] = []
    excluded: dict[str, int] = {}

    versions = repository.list_filing_versions(ticker, params.start_year, params.end_year)
    public_versions, version_rows = set(), []
    for version in versions:
        available = parse_timestamp(version["available_at"]) if version["availability_status"] == "verified" else None
        if available is None or not available < cutoff:
            excluded["filing_versions"] = excluded.get("filing_versions", 0) + 1
            continue
        public_versions.add(version["filing_version_id"])
        raw_path = None
        if include_raw:
            data = archive.read(version["raw_storage_path"])
            suffix = version["raw_storage_path"].rsplit(".", 1)[-1]
            raw_path = f"raw_evidence/financial_filings/{ticker}/{version['period']}/{version['content_hash']}.{suffix}"
            add(raw_path, data, "raw_evidence")
            provenance.append({"package_path": raw_path, "sha256": version["content_hash"],
                               "source_url": version["source_url"], "retrieved_at": version["retrieved_at"]})
        version_rows.append({**{k: version.get(k) for k in STRICT_VERSION_FIELDS},
                             "filing_available_at": available.isoformat(), "package_raw_path": raw_path,
                             "raw_evidence_included": raw_path is not None})
    add("data/filing_versions.csv", csv_bytes(version_rows, STRICT_VERSION_FIELDS), "dataset")

    facts = strict_facts(repository, params, cutoff, public_versions)
    add("data/financial_facts.csv", csv_bytes(facts, EXPORT_FIELDS), "dataset")
    add("data/financial_facts.json", json_bytes({"contract": "fintrust.historical_financial_facts",
                                                 "mode": "strict_point_in_time", "fields": list(EXPORT_FIELDS),
                                                 "record_count": len(facts), "records": facts}), "dataset")

    availability = document_availability(repository, ticker)
    with repository.connect() as connection:
        documents = [dict(r) for r in connection.execute(
            "SELECT * FROM historical_source_documents WHERE ticker = ? ORDER BY source_key, content_hash", (ticker,))]
    version_hashes = {v["content_hash"] for v in versions}
    public_documents, inventory = set(), []
    for document in documents:
        if document["content_hash"] in version_hashes:
            continue  # filing PDFs are governed by filing-version availability
        available, basis = availability.get(document["source_document_id"], (None, ""))
        if available is None or not available < cutoff:
            excluded["source_documents"] = excluded.get("source_documents", 0) + 1
            continue
        public_documents.add(document["source_document_id"])
        raw_path = None
        if include_raw:
            data = archive.read(document["raw_storage_path"])
            suffix = document["raw_storage_path"].rsplit(".", 1)[-1]
            raw_path = f"raw_evidence/regulatory_disclosures/{ticker}/{document['source_key']}/{document['content_hash']}.{suffix}"
            add(raw_path, data, "raw_evidence")
            provenance.append({"package_path": raw_path, "sha256": document["content_hash"],
                               "source_url": document["source_url"], "retrieved_at": document["retrieved_at"]})
        inventory.append({**{k: document.get(k) for k in STRICT_INVENTORY_FIELDS},
                          "document_available_at": available.isoformat(), "availability_basis": basis,
                          "package_raw_path": raw_path, "raw_evidence_included": raw_path is not None})
    add("data/source_inventory.csv", csv_bytes(inventory, STRICT_INVENTORY_FIELDS), "dataset")

    comparisons = [r for r in list_restatement_comparisons(repository, ticker, as_of=params.as_of)
                   if params.start_year <= r["fiscal_year"] <= params.end_year]
    excluded["restatement_comparisons"] = len(list_restatement_comparisons(repository, ticker)) - len(comparisons)
    add("data/restatement_comparisons.csv", csv_bytes(comparisons, COMPARISON_FIELDS), "dataset")
    summaries = [r for r in list_summary_observations(repository, ticker, as_of=params.as_of)
                 if params.start_year <= r["fiscal_year"] <= params.end_year]
    for row in summaries:
        row["retrieved_at"] = None
        row["content_hash"] = None  # the summary file's current bytes are a later snapshot; the value is dated by the notice
    excluded["summary_observations"] = len(list_summary_observations(repository, ticker)) - len(summaries)
    add("data/historical_summaries.csv", csv_bytes(summaries, SUMMARY_FIELDS), "dataset")

    hash_documents = {d["content_hash"]: d["source_document_id"] for d in documents}
    timeline = []
    all_events = list_publication_timeline(repository, ticker)
    for event in all_events:
        if not datetime.fromisoformat(event["available_from"]) < cutoff:
            continue
        links = [item for item in (event["linked_filing_versions"] or "").split(";")
                 if item and item.split(":")[1] in public_versions]
        document_id = hash_documents.get(event["content_hash"])
        timeline.append({**{k: event.get(k) for k in STRICT_TIMELINE_FIELDS},
                         "source_document_included": document_id in public_documents,
                         "linked_filing_versions": ";".join(links)})
    excluded["publication_events"] = len(all_events) - len(timeline)
    add("data/publication_timeline.csv", csv_bytes(timeline, STRICT_TIMELINE_FIELDS), "dataset")

    coverage = []
    for year in range(params.start_year, params.end_year + 1):
        counts = {
            "verified_public_filing_artifacts": sum(1 for r in version_rows if r["fiscal_year"] == year),
            "disclosed_observations": sum(1 for r in facts if r["fiscal_year"] == year),
            "restatement_comparison_rows": sum(1 for r in comparisons if r["fiscal_year"] == year),
            "summary_observations": sum(1 for r in summaries if r["fiscal_year"] == year),
        }
        coverage.append({"fiscal_year": year, **counts,
                         "status": "evidence_available" if any(counts.values()) else "no_verified_public_evidence"})
    add("data/coverage_matrix.csv", csv_bytes(coverage, STRICT_COVERAGE_FIELDS), "dataset")
    add("data/missing_evidence.csv", csv_bytes(
        [{"fiscal_year": None, "evidence_kind": kind, "status": "excluded_by_cutoff_or_unverified_availability",
          "detail": f"{count} item(s) withheld"} for kind, count in sorted(excluded.items()) if count],
        ("fiscal_year", "evidence_kind", "status", "detail")), "dataset")
    add("validation/provenance.csv", csv_bytes(sorted(provenance, key=lambda r: r["package_path"]), PROVENANCE_FIELDS),
        "validation")
    return {
        "facts": facts, "versions": version_rows, "summaries": summaries, "comparisons": comparisons,
        "timeline": timeline, "inventory": inventory, "excluded": excluded,
        "withheld_artifact_facts": sum(1 for r in facts if r["artifact_reference_status"] == "withheld_not_public_at_cutoff"),
    }
