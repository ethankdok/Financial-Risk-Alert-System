"""Historical Financial Facts → downstream research export (contract v1.0).

See docs/data/HISTORICAL_FINANCIAL_FACTS_CONTRACT.md. This is a compatibility
boundary only: no JSD, shift or risk computation happens here, and the
conference-PDF → JSD contract is unrelated and unchanged.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services.historical_audit.case_registry import get_case
from app.services.historical_audit.models import CORE_FIELDS, VersionPolicy, iso, parse_timestamp, utc_now
from app.services.historical_audit.reader import list_historical_facts
from app.services.historical_audit.repository import HistoricalAuditRepository


CONTRACT_NAME = "fintrust.historical_financial_facts"
CONTRACT_VERSION = "1.4"
EXPORT_FIELDS: tuple[str, ...] = (
    "ticker",
    "company",
    "market",
    "fiscal_year",
    "period",
    "metric_code",
    "value",
    "unit",
    "statement_type",
    "statement_scope",
    "taxonomy_concept",
    "filing_version_id",
    "filing_version_type",
    "source_kind",
    "source_url",
    "source_published_at",
    "available_at",
    "availability_status",
    "document_dated_at",
    "retrieved_at",
    "content_hash",
    "quality_status",
    "validation_status",
    "point_in_time_eligible",
    # v1.1 (Phase 1B, appended): evidence typing and observation-level availability.
    "evidence_type",
    "accounting_framework",
    "completeness",
    "availability_scope",
    "effective_available_at",
    # v1.2 (pre-Phase 1C review, appended): the evidence that dates the value.
    "availability_evidence_kind",
    "availability_evidence_ref",
    "availability_evidence_url",
    "availability_evidence_hash",
    # v1.3 (Phase 1C follow-up, appended): the three availability times kept apart.
    "observation_available_at",
    "filing_available_at",
    "artifact_reference_status",
)


def build_export_records(
    repository: HistoricalAuditRepository,
    ticker: str,
    start_year: int,
    end_year: int,
    *,
    as_of: date | datetime | str | None = None,
    version_policy: VersionPolicy = "all",
    include_test_fixtures: bool = False,
) -> list[dict[str, Any]]:
    case = repository.get_case(ticker) or get_case(ticker)
    rows = list_historical_facts(
        repository, ticker, start_year, end_year, as_of=as_of,
        version_policy=version_policy, include_test_fixtures=include_test_fixtures,
    )
    return [
        {
            "ticker": row["ticker"],
            "company": case.company_name,
            "market": case.market,
            "fiscal_year": row["fiscal_year"],
            "period": row["period"],
            "metric_code": row["metric_code"],
            # The exact decimal as filed; floats are never re-derived for export.
            "value": row["value_text"],
            "unit": row["unit"],
            "statement_type": row["statement_type"],
            "statement_scope": row["statement_scope"],
            "taxonomy_concept": row["taxonomy_concept"],
            "filing_version_id": row["filing_version_id"],
            "filing_version_type": row["filing_version_type"],
            "source_kind": row["source_kind"],
            "source_url": row["source_url"],
            "source_published_at": row["source_published_at"],
            "available_at": row["available_at"],
            "availability_status": row["availability_status"],
            "document_dated_at": row["document_dated_at"],
            "retrieved_at": row["retrieved_at"],
            "content_hash": row["content_hash"],
            "quality_status": row["quality_status"],
            "validation_status": row["validation_status"],
            "point_in_time_eligible": bool(row["point_in_time_eligible"]),
            "evidence_type": "official_filing_fact",
            "accounting_framework": row["accounting_framework"],
            "completeness": "full_statement_filing",
            "availability_scope": row["availability_scope"],
            "effective_available_at": row["effective_available_at"],
            "availability_evidence_kind": row["availability_evidence_kind"],
            "availability_evidence_ref": row["availability_evidence_ref"],
            "availability_evidence_url": row["availability_evidence_url"],
            "availability_evidence_hash": row["availability_evidence_hash"],
            "observation_available_at": (parse_timestamp(row["observation_available_at"]).isoformat()
                                         if row.get("observation_available_at") else None),
            "filing_available_at": (parse_timestamp(row["available_at"]).isoformat()
                                    if row["availability_status"] == "verified" and row["available_at"] else None),
            # Retrospective exports reference the archived artifact whatever its historical availability;
            # strict point-in-time packages rewrite this per row (see research_package).
            "artifact_reference_status": "retrospective_reference",
        }
        for row in rows
    ]


def coverage_summary(
    repository: HistoricalAuditRepository, ticker: str, start_year: int, end_year: int,
    *, include_test_fixtures: bool = False,
) -> list[dict[str, Any]]:
    """Per filing version: which core fields are present and which are explicitly missing."""
    versions = repository.list_filing_versions(ticker, start_year, end_year)
    with repository.connect() as connection:
        present: dict[str, set[str]] = {}
        for row in connection.execute(
            "SELECT filing_version_id, metric_code FROM versioned_financial_facts WHERE ticker = ?", (ticker,)
        ):
            present.setdefault(row["filing_version_id"], set()).add(row["metric_code"])
    summary = []
    for version in versions:
        if version["source_kind"] == "test_fixture" and not include_test_fixtures:
            continue
        found = present.get(version["filing_version_id"], set())
        summary.append({
            "period": version["period"],
            "filing_version_id": version["filing_version_id"],
            "filing_version_type": version["filing_version_type"],
            "validation_status": version["validation_status"],
            "quarantine_reason": version["quarantine_reason"],
            "availability_status": version["availability_status"],
            "core_fields_present": [name for name in CORE_FIELDS if name in found],
            "core_fields_missing": [name for name in CORE_FIELDS if name not in found],
        })
    return summary


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_csv(records: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(EXPORT_FIELDS)
    for record in records:
        writer.writerow([_csv_value(record[name]) for name in EXPORT_FIELDS])
    return buffer.getvalue()


def render_json(
    records: list[dict[str, Any]],
    *,
    filters: dict[str, Any],
    coverage: list[dict[str, Any]],
    generated_at: datetime | None = None,
) -> str:
    payload = {
        "contract": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "generated_at": iso(generated_at or utc_now()),
        "filters": filters,
        "fields": list(EXPORT_FIELDS),
        "record_count": len(records),
        "records": [{name: record[name] for name in EXPORT_FIELDS} for record in records],
        "coverage": coverage,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def export_historical_facts(
    repository: HistoricalAuditRepository,
    ticker: str,
    start_year: int,
    end_year: int,
    *,
    output_path: str | Path,
    output_format: str = "csv",
    as_of: date | datetime | str | None = None,
    version_policy: VersionPolicy = "all",
    include_test_fixtures: bool = False,
    generated_at: datetime | None = None,
) -> int:
    records = build_export_records(
        repository, ticker, start_year, end_year, as_of=as_of,
        version_policy=version_policy, include_test_fixtures=include_test_fixtures,
    )
    if output_format == "csv":
        text = render_csv(records)
    elif output_format == "json":
        text = render_json(
            records,
            filters={
                "ticker": ticker, "start_year": start_year, "end_year": end_year,
                "as_of": str(as_of) if as_of is not None else None,
                "version_policy": version_policy, "include_test_fixtures": include_test_fixtures,
            },
            coverage=coverage_summary(repository, ticker, start_year, end_year, include_test_fixtures=include_test_fixtures),
            generated_at=generated_at,
        )
    else:
        raise ValueError("output_format must be 'csv' or 'json'.")
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return len(records)
