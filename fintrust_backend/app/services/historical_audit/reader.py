"""Version-aware, point-in-time reader for the historical audit archive.

Fiscal year is never used as a proxy for publication time. With ``as_of`` set,
a fact is visible only if its filing version has a *verified* ``available_at``
strictly before the cutoff; versions with unknown availability are excluded
from point-in-time views and remain visible only to unrestricted queries.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from app.services.historical_audit.models import VersionPolicy, as_of_cutoff, parse_timestamp
from app.services.historical_audit.repository import HistoricalAuditRepository


VERSION_POLICIES: tuple[str, ...] = ("all", "latest_available", "earliest_available", "original_only")

_SELECT = """
SELECT f.fact_id, f.filing_version_id, f.ticker, f.period, f.fiscal_year, f.metric_code,
       f.value, f.value_text, f.unit, f.statement_type, f.statement_scope,
       f.taxonomy_concept, f.context_ref, f.mapping_method, f.quality_status,
       f.quality_notes_json, f.source_kind, f.source_url,
       v.filing_version_type, v.version_type_evidence_json, v.source_published_at,
       v.available_at, v.availability_status, v.availability_basis,
       v.verification_evidence_json, v.document_dated_at, v.retrieved_at,
       v.content_hash, v.raw_storage_path, v.parser_version, v.validation_status,
       v.statement_scope_evidence, oa.observation_available_at, oa.observation_basis
FROM versioned_financial_facts AS f
JOIN financial_filing_versions AS v ON v.filing_version_id = f.filing_version_id
LEFT JOIN (
    SELECT observation_id, MIN(available_at) AS observation_available_at,
           GROUP_CONCAT(basis, ' | ') AS observation_basis
    FROM observation_availability WHERE observation_kind = 'versioned_fact' GROUP BY observation_id
) AS oa ON oa.observation_id = f.fact_id
WHERE f.ticker = ? AND f.fiscal_year BETWEEN ? AND ?
  AND v.validation_status IN ('validated', 'validated_with_warnings')
"""


def version_availability_verified(row: dict[str, Any]) -> bool:
    return row.get("availability_status") == "verified" and row.get("available_at") is not None


def effective_availability(row: dict[str, Any]) -> tuple[datetime | None, str | None]:
    """Earliest verified time: the filing version's own, or a verified disclosure of this exact value."""
    candidates = []
    if version_availability_verified(row):
        candidates.append((parse_timestamp(row["available_at"]), "filing_version"))
    if row.get("observation_available_at"):
        candidates.append((parse_timestamp(row["observation_available_at"]), "observation"))
    if not candidates:
        return None, None
    return min(candidates, key=lambda item: item[0])


_OBSERVATION_EVIDENCE = """
SELECT o.observation_id, o.available_at, o.corroborating_id, o.match_detail, d.source_url, d.content_hash, e.event_key
FROM observation_availability o
JOIN restatement_comparisons c ON c.comparison_id = o.corroborating_id
JOIN historical_source_documents d ON d.source_document_id = c.source_document_id
JOIN historical_publication_events e ON e.event_id = c.event_id
WHERE o.observation_kind = 'versioned_fact' AND o.observation_id IN ({placeholders})
"""


def _observation_evidence(connection, fact_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Earliest corroborating disclosure per fact (the document that actually dates the value)."""
    best: dict[str, dict[str, Any]] = {}
    for start in range(0, len(fact_ids), 500):
        chunk = fact_ids[start:start + 500]
        for row in connection.execute(_OBSERVATION_EVIDENCE.format(placeholders=",".join("?" * len(chunk))), chunk):
            item = dict(row)
            current = best.get(item["observation_id"])
            key = (parse_timestamp(item["available_at"]), item["corroborating_id"])
            if current is None or key < (parse_timestamp(current["available_at"]), current["corroborating_id"]):
                best[item["observation_id"]] = item
    return best


def availability_evidence(row: dict[str, Any], scope: str | None) -> dict[str, Any]:
    """Identity of the evidence that establishes ``effective_available_at``.

    For ``filing_version`` it is the artifact itself; for ``observation`` it is the
    official disclosure stating the value, never the filing artifact.
    """
    if scope == "filing_version":
        return {"availability_evidence_kind": "filing_artifact", "availability_evidence_ref": row["filing_version_id"],
                "availability_evidence_url": row["source_url"], "availability_evidence_hash": row["content_hash"]}
    evidence = row.get("_observation_evidence")
    if scope == "observation" and evidence:
        return {"availability_evidence_kind": "restatement_disclosure", "availability_evidence_ref": evidence["event_key"],
                "availability_evidence_url": evidence["source_url"], "availability_evidence_hash": evidence["content_hash"]}
    return {"availability_evidence_kind": None, "availability_evidence_ref": None,
            "availability_evidence_url": None, "availability_evidence_hash": None}


def point_in_time_eligible(row: dict[str, Any]) -> bool:
    return effective_availability(row)[0] is not None


def _version_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    available = parse_timestamp(row.get("effective_available_at") or row.get("available_at"))
    published = parse_timestamp(row.get("source_published_at"))
    return (
        available is not None,
        available.timestamp() if available else 0.0,
        published.timestamp() if published else 0.0,
        row.get("retrieved_at") or "",
        row["filing_version_id"],
    )


def _earliest_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    available = parse_timestamp(row.get("effective_available_at") or row.get("available_at"))
    published = parse_timestamp(row.get("source_published_at"))
    return (
        available is None,
        available.timestamp() if available else 0.0,
        published is None,
        published.timestamp() if published else 0.0,
        row.get("retrieved_at") or "",
        row["filing_version_id"],
    )


def list_historical_facts(
    repository: HistoricalAuditRepository,
    ticker: str,
    start_year: int,
    end_year: int,
    *,
    as_of: date | datetime | str | None = None,
    version_policy: VersionPolicy = "all",
    metrics: list[str] | tuple[str, ...] | None = None,
    periods: list[str] | tuple[str, ...] | None = None,
    statement_scope: str | None = None,
    include_test_fixtures: bool = True,
) -> list[dict[str, Any]]:
    if version_policy not in VERSION_POLICIES:
        raise ValueError(f"Unsupported version_policy: {version_policy}")
    query = _SELECT
    params: list[Any] = [ticker, start_year, end_year]
    if metrics:
        query += f" AND f.metric_code IN ({','.join('?' * len(metrics))})"
        params.extend(metrics)
    if periods:
        query += f" AND f.period IN ({','.join('?' * len(periods))})"
        params.extend(periods)
    if statement_scope:
        query += " AND f.statement_scope = ?"
        params.append(statement_scope)
    if not include_test_fixtures:
        query += " AND f.source_kind != 'test_fixture'"
    with repository.connect() as connection:
        rows = [dict(row) for row in connection.execute(query, params).fetchall()]
        evidence = _observation_evidence(connection, [row["fact_id"] for row in rows])

    for row in rows:
        row["quality_notes"] = json.loads(row.pop("quality_notes_json") or "[]")
        row["version_type_evidence"] = json.loads(row.pop("version_type_evidence_json") or "[]")
        row["verification_evidence"] = json.loads(row.pop("verification_evidence_json") or "[]")
        row["_observation_evidence"] = evidence.get(row["fact_id"])
        effective, scope = effective_availability(row)
        row["effective_available_at"] = effective.isoformat() if effective else None
        row["availability_scope"] = scope
        row.update(availability_evidence(row, scope))
        row.pop("_observation_evidence")
        row["accounting_framework"] = "TIFRS" if "tifrs" in (row.pop("statement_scope_evidence") or "") else "unknown"
        row["point_in_time_eligible"] = effective is not None

    if as_of is not None:
        cutoff = as_of_cutoff(as_of)
        rows = [
            row for row in rows
            if row["point_in_time_eligible"] and parse_timestamp(row["effective_available_at"]) < cutoff
        ]
    if version_policy == "original_only":
        rows = [row for row in rows if row["filing_version_type"] == "original"]
    elif version_policy in {"latest_available", "earliest_available"}:
        groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            # Scope and unit are part of the key, so they can never be merged.
            groups.setdefault((row["period"], row["metric_code"], row["statement_scope"], row["unit"]), []).append(row)
        if version_policy == "latest_available":
            rows = [max(group, key=_version_sort_key) for group in groups.values()]
        else:
            # Versions with unknown availability sort last, never "earliest".
            rows = [min(group, key=_earliest_sort_key) for group in groups.values()]

    return sorted(
        rows,
        key=lambda row: (row["fiscal_year"], row["period"], row["metric_code"], row["statement_scope"],
                         row["unit"], _version_sort_key(row)),
    )


def list_filing_versions_as_of(
    repository: HistoricalAuditRepository,
    ticker: str,
    *,
    as_of: date | datetime | str,
    start_year: int | None = None,
    end_year: int | None = None,
) -> list[dict[str, Any]]:
    """Filing artifacts (XBRL or PDF) whose own verified availability precedes the cutoff."""
    cutoff = as_of_cutoff(as_of)
    return [
        version for version in repository.list_filing_versions(ticker, start_year, end_year)
        if version_availability_verified(version) and parse_timestamp(version["available_at"]) < cutoff
    ]
