"""Archive-wide data-quality audit for the historical audit database."""

from __future__ import annotations

import json
from typing import Any

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.export import coverage_summary
from app.services.historical_audit.repository import HistoricalAuditRepository


def quality_report(
    repository: HistoricalAuditRepository,
    archive: RawEvidenceArchive | None,
    ticker: str,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    with repository.connect() as connection:
        checks["duplicate_fact_identities"] = connection.execute(
            """SELECT COUNT(*) FROM (
                SELECT filing_version_id, metric_code, period, statement_scope, unit, COUNT(*) AS n
                FROM versioned_financial_facts WHERE ticker = ?
                GROUP BY 1, 2, 3, 4, 5 HAVING n > 1)""",
            (ticker,),
        ).fetchone()[0]
        checks["duplicate_versions_same_content"] = connection.execute(
            """SELECT COUNT(*) FROM (
                SELECT period, statement_scope, content_hash, COUNT(*) AS n
                FROM financial_filing_versions WHERE ticker = ?
                GROUP BY 1, 2, 3 HAVING n > 1)""",
            (ticker,),
        ).fetchone()[0]
        checks["facts_without_version"] = connection.execute(
            """SELECT COUNT(*) FROM versioned_financial_facts AS f
            LEFT JOIN financial_filing_versions AS v ON v.filing_version_id = f.filing_version_id
            WHERE f.ticker = ? AND v.filing_version_id IS NULL""",
            (ticker,),
        ).fetchone()[0]
        checks["facts_missing_provenance"] = connection.execute(
            """SELECT COUNT(*) FROM versioned_financial_facts AS f
            JOIN financial_filing_versions AS v ON v.filing_version_id = f.filing_version_id
            WHERE f.ticker = ? AND (v.content_hash IS NULL OR v.content_hash = ''
                OR v.raw_storage_path IS NULL OR v.retrieved_at IS NULL)""",
            (ticker,),
        ).fetchone()[0]
        versions = [
            dict(row) for row in connection.execute(
                """SELECT filing_version_id, period, filing_version_type, statement_scope,
                validation_status, quarantine_reason, availability_status, available_at,
                document_dated_at, content_hash, raw_storage_path, warnings_json
                FROM financial_filing_versions WHERE ticker = ? AND fiscal_year BETWEEN ? AND ?
                ORDER BY fiscal_year, filing_version_id""",
                (ticker, start_year, end_year),
            ).fetchall()
        ]
    hash_failures = []
    if archive is not None:
        for version in versions:
            try:
                archive.read(version["raw_storage_path"])
            except Exception as exc:  # missing file or tampered bytes
                hash_failures.append({"filing_version_id": version["filing_version_id"], "error": str(exc)})
    checks["archive_hash_failures"] = hash_failures
    for version in versions:
        version["warnings"] = json.loads(version.pop("warnings_json") or "[]")
    passed = (
        checks["duplicate_fact_identities"] == 0
        and checks["duplicate_versions_same_content"] == 0
        and checks["facts_without_version"] == 0
        and checks["facts_missing_provenance"] == 0
        and not hash_failures
    )
    return {
        "ticker": ticker,
        "start_year": start_year,
        "end_year": end_year,
        "integrity_passed": passed,
        "checks": checks,
        "versions": versions,
        "coverage": coverage_summary(repository, ticker, start_year, end_year, include_test_fixtures=True),
        "point_in_time_eligible_versions": sum(v["availability_status"] == "verified" for v in versions),
    }
