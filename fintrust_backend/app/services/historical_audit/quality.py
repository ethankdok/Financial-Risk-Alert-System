"""Archive-wide data-quality audit for the historical audit database."""

from __future__ import annotations

import json
from typing import Any

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.export import coverage_summary
from app.services.historical_audit.reader import list_historical_facts
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
        # Artifact level: filing versions whose own bytes have a verified availability time.
        "point_in_time_eligible_versions": sum(v["availability_status"] == "verified" for v in versions),
        "artifact_level_verified_versions": sum(v["availability_status"] == "verified" for v in versions),
        # Observation level, using exactly the reader/export definition.
        "point_in_time_eligible_facts": sum(
            fact["point_in_time_eligible"]
            for fact in list_historical_facts(repository, ticker, start_year, end_year, include_test_fixtures=False)
        ),
    }


PRIORITY_CONCEPT_KEYWORDS = {
    "revenue": ("revenue", "sales"),
    "receivables": ("receivable",),
    "inventory": ("inventor",),
    "cost_of_goods_sold": ("cost",),
    "assets": ("assets",),
    "net_income": ("profitloss", "comprehensiveincome"),
    "cash_flow": ("cashflow", "cashequivalent"),
    "equity": ("equity", "retainedearnings", "capital"),
}


def unmapped_concept_report(repository: HistoricalAuditRepository, ticker: str, start_year: int, end_year: int) -> dict[str, Any]:
    """Unmapped current-period concepts grouped by the review priorities; nothing is auto-mapped."""
    report: dict[str, Any] = {"ticker": ticker, "versions": []}
    for version in repository.list_filing_versions(ticker, start_year, end_year):
        diagnostics = json.loads(version["diagnostics_json"] or "{}")
        concepts = diagnostics.get("unmapped_current_period_concepts")
        if concepts is None:
            continue
        groups: dict[str, list[str]] = {name: [] for name in PRIORITY_CONCEPT_KEYWORDS}
        other = []
        for concept in concepts:
            lowered = concept.split(":")[-1].lower()
            group = next((name for name, keys in PRIORITY_CONCEPT_KEYWORDS.items() if any(k in lowered for k in keys)), None)
            (groups[group] if group else other).append(concept)
        report["versions"].append({
            "period": version["period"], "filing_version_id": version["filing_version_id"],
            "unmapped_total": len(concepts), "priority_groups": groups, "other_count": len(other),
        })
    return report


def eps_unit_investigation(repository: HistoricalAuditRepository, archive: RawEvidenceArchive, ticker: str) -> list[dict[str, Any]]:
    """Evidence about EPS facts whose filing tags them with a currency unit instead of TWD/shares."""
    from app.services.historical_audit.xbrl_document import parse_xbrl_document

    results = []
    with repository.connect() as connection:
        facts = [dict(row) for row in connection.execute(
            """SELECT f.fact_id, f.period, f.fiscal_year, f.value_text, f.source_unit_ref, f.quality_status,
                      f.quality_notes_json, f.statement_scope, v.raw_storage_path, v.filing_version_type
            FROM versioned_financial_facts f JOIN financial_filing_versions v USING (filing_version_id)
            WHERE f.ticker = ? AND f.metric_code = 'eps' ORDER BY f.fiscal_year""", (ticker,)).fetchall()]
        summaries = {
            (row["fiscal_year"], row["report_period"]): row["value_text"]
            for row in connection.execute(
                "SELECT fiscal_year, report_period, value_text FROM official_summary_observations "
                "WHERE ticker = ? AND source_metric_code = 'tpex_eps'", (ticker,))
        }
        cited = [row["title"] for row in connection.execute(
            "SELECT title FROM historical_publication_events WHERE ticker = ? AND event_type = 'restated_figure_cited' "
            "AND verification_status = 'verified_official_quote'", (ticker,))]
    for fact in facts:
        document = parse_xbrl_document(archive.read(fact["raw_storage_path"]))
        eps_facts = [f for f in document.numeric_facts if f.local_name == "BasicEarningsLossPerShare"
                     and (c := document.contexts.get(f.context_ref)) is not None and not c.dimensional
                     and c.end is not None and c.end.year == fact["fiscal_year"] and c.start is not None]
        per_share_units = sorted(uid for uid, measure in document.units.items() if measure.lower() == "iso4217:twd/xbrli:shares")
        corroboration = [f"TPEx summary {report}: {value}" for (year, report), value in sorted(summaries.items())
                         if year == fact["fiscal_year"]]
        corroboration += [quote for quote in cited if str(abs(float(fact["value_text"]))) in quote]
        results.append({
            "period": fact["period"], "filing_version_type": fact["filing_version_type"], "value": fact["value_text"],
            "declared_unit_refs": sorted({f.unit_ref for f in eps_facts if f.unit_ref}),
            "document_defines_per_share_units": per_share_units,
            "decimals": sorted({f.decimals for f in eps_facts if f.decimals}),
            "stored_unit": "TWD/share", "quality_status": fact["quality_status"],
            "official_corroboration": corroboration,
            "conclusion": (
                "Concept ifrs:BasicEarningsLossPerShare is a per-share item; the filing declares unit 'TWD' although it "
                "defines a TWD/shares unit. The value is not rescaled. The warning is retained because the source "
                "declaration itself is inconsistent."
            ),
        })
    return results
