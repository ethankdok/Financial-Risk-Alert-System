"""Readers and research exports for Phase 1B evidence types.

Each evidence type has its own dataset so unlike evidence is never merged:
filing facts (export.py), official summary observations, restatement
comparisons, publication timeline, source inventory and the year coverage matrix.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.services.historical_audit.evidence_import import availability_instant
from app.services.historical_audit.models import TAIPEI, as_of_cutoff, iso, parse_timestamp, utc_now
from app.services.historical_audit.reader import list_historical_facts
from app.services.historical_audit.repository import HistoricalAuditRepository


EVIDENCE_CONTRACT_VERSION = "1.0"

SUMMARY_FIELDS = (
    "ticker", "evidence_type", "completeness", "period", "fiscal_year", "report_period", "observation_role",
    "accounting_framework", "source_label", "source_metric_code", "canonical_metric", "mapping_status",
    "value", "published_unit", "normalized_value", "normalized_unit", "statement_scope", "statement_scope_basis",
    "availability_status", "effective_available_at", "point_in_time_eligible", "source_url", "content_hash",
    "retrieved_at", "quality_notes",
    # summary contract 1.1 (appended): metric-specific point-in-time evidence and source semantics.
    "observation_origin", "scope_inference_basis", "pit_evidence_kind", "pit_evidence_ref", "pit_evidence_url",
    "pit_evidence_hash", "pit_evidence_side", "pit_evidence_label", "side_consistency", "source_reference_status",
)
SUMMARY_CONTRACT_VERSION = "1.1"
COMPARISON_FIELDS = (
    "ticker", "evidence_type", "period", "fiscal_year", "statement_scope", "accounting_framework", "statement_type",
    "pre_label", "post_label", "canonical_metric", "sign_factor", "pre_restatement_value", "post_restatement_value",
    "difference", "published_unit", "disclosed_at", "availability_status", "point_in_time_eligible",
    "pre_value_semantics", "source_url", "announcement_key", "content_hash",
)
TIMELINE_FIELDS = (
    "ticker", "event_key", "event_type", "title", "announcement_id", "publication_at", "publication_precision",
    "available_from", "event_date", "event_date_basis", "affected_periods", "affected_scopes", "issuer",
    "source_url", "content_hash", "verification_status", "linked_filing_versions",
)
INVENTORY_FIELDS = (
    "ticker", "source_key", "source_category", "issuer", "document_type", "source_url", "request_method",
    "retrieved_at", "content_hash", "content_length", "http_last_modified", "accounting_framework",
    "statement_scope", "fiscal_periods", "version_classification", "contains_full_statements",
    "contains_summary_values", "contains_comparison_values", "parser", "parser_status",
    "publication_evidence", "verification_status", "missing_evidence",
)
COVERAGE_FIELDS = (
    "fiscal_year", "original_evidence", "restated_evidence", "summary_evidence", "comparison_evidence",
    "verified_availability", "pit_ready_facts", "pit_ready", "remaining_gaps",
)
PRE_VALUE_SEMANTICS = (
    "as previously reported according to the company's 2016-11-13 restatement notice "
    "(may differ from the first-published figure)"
)


def _cutoff(as_of: date | datetime | str | None) -> datetime | None:
    return as_of_cutoff(as_of) if as_of is not None else None


def list_restatement_comparisons(
    repository: HistoricalAuditRepository, ticker: str, *, as_of: date | datetime | str | None = None
) -> list[dict[str, Any]]:
    with repository.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """SELECT c.*, d.source_url, d.content_hash, e.event_key FROM restatement_comparisons c
            JOIN historical_source_documents d USING (source_document_id)
            JOIN historical_publication_events e ON e.event_id = c.event_id
            WHERE c.ticker = ? ORDER BY c.fiscal_year, c.statement_scope, c.statement_type, COALESCE(c.pre_label, c.post_label)""",
            (ticker,),
        ).fetchall()]
    return finalize_comparisons(rows, ticker, as_of=as_of)


def finalize_comparisons(rows: list[dict[str, Any]], ticker: str, *,
                         as_of: date | datetime | str | None = None) -> list[dict[str, Any]]:
    """Backend-independent; ``rows`` are comparison rows joined with source_url, content_hash, event_key."""
    cutoff = _cutoff(as_of)
    rows = sorted(rows, key=lambda r: (r["fiscal_year"], r["statement_scope"], r["statement_type"],
                                       r["pre_label"] or r["post_label"] or ""))
    result = []
    for row in rows:
        disclosed = parse_timestamp(row["disclosed_at"])
        if cutoff is not None and not disclosed < cutoff:
            continue
        result.append({
            "ticker": ticker, "evidence_type": "official_restatement_comparison", "period": row["period"],
            "fiscal_year": row["fiscal_year"], "statement_scope": row["statement_scope"],
            "accounting_framework": row["accounting_framework"], "statement_type": row["statement_type"],
            "pre_label": row["pre_label"], "post_label": row["post_label"], "canonical_metric": row["canonical_metric"],
            "sign_factor": row["sign_factor"], "pre_restatement_value": row["pre_value_text"],
            "post_restatement_value": row["post_value_text"], "difference": row["difference_text"],
            "published_unit": row["published_unit"], "disclosed_at": disclosed.isoformat(),
            "availability_status": row["availability_status"], "point_in_time_eligible": True,
            "pre_value_semantics": PRE_VALUE_SEMANTICS, "source_url": row["source_url"],
            "announcement_key": row["event_key"], "content_hash": row["content_hash"],
        })
    return result


def list_summary_observations(
    repository: HistoricalAuditRepository, ticker: str, *, as_of: date | datetime | str | None = None
) -> list[dict[str, Any]]:
    with repository.connect() as connection:
        rows = [dict(row) for row in connection.execute(
            """SELECT o.*, d.source_url, d.content_hash, d.retrieved_at
            FROM official_summary_observations o JOIN historical_source_documents d USING (source_document_id)
            WHERE o.ticker = ?
            ORDER BY o.fiscal_year, o.report_period, o.observation_role, o.source_metric_code""",
            (ticker,),
        ).fetchall()]
        availability = [dict(r) for r in connection.execute(
            "SELECT * FROM observation_availability WHERE observation_kind = 'summary_observation'")]
        comparisons = {r["comparison_id"]: dict(r) for r in connection.execute(
            "SELECT * FROM restatement_comparisons WHERE ticker = ?", (ticker,))}
        documents = {r["source_document_id"]: dict(r) for r in connection.execute(
            "SELECT source_document_id, source_url, content_hash FROM historical_source_documents WHERE ticker = ?", (ticker,))}
        events = {r["event_id"]: dict(r) for r in connection.execute(
            "SELECT event_id, event_key FROM historical_publication_events WHERE ticker = ?", (ticker,))}
    return finalize_summaries(rows, ticker, as_of=as_of,
                              evidence=summary_evidence_map(availability, comparisons, documents, events))


def expected_side(report_period: str, disclosed_at: str) -> str:
    """A report whose fiscal year ended before a restatement disclosure carries 'as previously reported' (pre)
    values; a report for a later fiscal year can only carry post-restatement figures."""
    report_end = datetime(int(report_period[:4]) + 1, 1, 1, tzinfo=TAIPEI)
    return "pre" if report_end <= parse_timestamp(disclosed_at) else "post"


def summary_evidence_map(availability: list[dict[str, Any]], comparisons: dict[str, dict[str, Any]],
                         documents: dict[str, dict[str, Any]], events: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """observation_id -> candidate disclosure evidence (backend-independent)."""
    result: dict[str, list[dict[str, Any]]] = {}
    for item in availability:
        comparison = comparisons.get(item["corroborating_id"])
        if comparison is None:
            continue
        sides = item["match_detail"].split("(", 1)[1].split(" side", 1)[0].split("+")
        document = documents.get(comparison["source_document_id"], {})
        result.setdefault(item["observation_id"], []).append({
            "available_at": item["available_at"], "sides": sides, "comparison_id": comparison["comparison_id"],
            "label": comparison["pre_label"] if sides == ["pre"] else (comparison["post_label"] or comparison["pre_label"]),
            "event_key": events.get(comparison["event_id"], {}).get("event_key"),
            "source_url": document.get("source_url"), "content_hash": document.get("content_hash"),
            "statement_scope": comparison["statement_scope"], "canonical_metric": comparison["canonical_metric"],
            "fiscal_year": comparison["fiscal_year"], "accounting_framework": comparison["accounting_framework"],
        })
    return result


def admissible_summary_evidence(row: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str]:
    """Earliest disclosure matching metric, period, scope, framework and the expected restatement side."""
    admissible, inconsistent = [], False
    for item in candidates:
        key = (item["canonical_metric"], item["fiscal_year"], item["statement_scope"], item["accounting_framework"])
        if key != (row["canonical_metric"], row["fiscal_year"], row["statement_scope"], row["accounting_framework"]):
            continue
        if expected_side(row["report_period"], item["available_at"]) in item["sides"]:
            admissible.append(item)
        else:
            inconsistent = True
    if admissible:
        return min(admissible, key=lambda i: (parse_timestamp(i["available_at"]), i["comparison_id"])), "consistent"
    return None, ("inconsistent_side" if inconsistent else "no_disclosure_match")


def finalize_summaries(rows: list[dict[str, Any]], ticker: str, *, as_of: date | datetime | str | None = None,
                       evidence: dict[str, list[dict[str, Any]]] | None = None) -> list[dict[str, Any]]:
    """Backend-independent; ``rows`` are summary rows joined with their workbook document fields."""
    cutoff = _cutoff(as_of)
    evidence = evidence or {}
    rows = sorted(rows, key=lambda r: (r["fiscal_year"], r["report_period"], r["observation_role"], r["source_metric_code"]))
    result = []
    for row in rows:
        pit, consistency = admissible_summary_evidence(row, evidence.get(row["observation_id"], []))
        effective = parse_timestamp(row["available_at"]) if row["availability_status"] == "verified" else None
        if pit is not None:
            observed = parse_timestamp(pit["available_at"])
            effective = observed if effective is None else min(effective, observed)
        if cutoff is not None and (effective is None or not effective < cutoff):
            continue
        result.append({
            "ticker": ticker, "evidence_type": "official_historical_summary", "completeness": "summary_values_only",
            "period": row["period"], "fiscal_year": row["fiscal_year"], "report_period": row["report_period"],
            "observation_role": row["observation_role"], "accounting_framework": row["accounting_framework"],
            "source_label": row["source_label"], "source_metric_code": row["source_metric_code"],
            "canonical_metric": row["canonical_metric"], "mapping_status": row["mapping_status"],
            "value": row["value_text"], "published_unit": row["published_unit"],
            "normalized_value": row["normalized_value_text"], "normalized_unit": row["normalized_unit"],
            # The archived basis text records the *revenue* match that fixed the scope of the whole report row;
            # contract 1.1 states that explicitly so non-revenue rows are not read as revenue matches.
            "statement_scope": row["statement_scope"],
            "statement_scope_basis": (
                f"scope of the whole {row['report_period']} report row, inferred from that row's revenue "
                f"(not from this {row['canonical_metric'] or row['source_metric_code']} value): {row['statement_scope_basis']}"
                if row["statement_scope"] != "unknown" else row["statement_scope_basis"]),
            "availability_status": "verified_by_corroboration" if pit else row["availability_status"],
            "effective_available_at": effective.isoformat() if effective else None,
            "point_in_time_eligible": effective is not None, "source_url": row["source_url"],
            "content_hash": row["content_hash"], "retrieved_at": row["retrieved_at"],
            "quality_notes": "; ".join(json.loads(row["quality_notes_json"])),
            "observation_origin": "tpex_quarterly_summary_value",
            "scope_inference_basis": "report_row_revenue_match" if row["statement_scope"] != "unknown" else "not_inferred",
            "pit_evidence_kind": "restatement_disclosure" if pit else None,
            "pit_evidence_ref": pit["event_key"] if pit else None,
            "pit_evidence_url": pit["source_url"] if pit else None,
            "pit_evidence_hash": pit["content_hash"] if pit else None,
            "pit_evidence_side": "+".join(pit["sides"]) if pit else None,
            "pit_evidence_label": pit["label"] if pit else None,
            "side_consistency": consistency,
            "source_reference_status": "retrospective_workbook_reference",
        })
    return result


def list_publication_timeline(repository: HistoricalAuditRepository, ticker: str) -> list[dict[str, Any]]:
    with repository.connect() as connection:
        events = [dict(row) for row in connection.execute(
            """SELECT e.*, d.issuer, d.source_url, d.content_hash FROM historical_publication_events e
            JOIN historical_source_documents d USING (source_document_id) WHERE e.ticker = ?""", (ticker,)).fetchall()]
        links: dict[str, list[str]] = {}
        for row in connection.execute(
            "SELECT event_id, target_id, link_status, period FROM publication_evidence_links ORDER BY period, target_id"
        ):
            links.setdefault(row["event_id"], []).append(f"{row['period']}:{row['target_id']}:{row['link_status']}")
    result = []
    for event in events:
        available_from = availability_instant(event["publication_at"], event["publication_precision"])
        result.append({
            "ticker": ticker, "event_key": event["event_key"], "event_type": event["event_type"], "title": event["title"],
            "announcement_id": event["announcement_id"], "publication_at": event["publication_at"],
            "publication_precision": event["publication_precision"], "available_from": available_from.isoformat(),
            "event_date": event["event_date"], "event_date_basis": event["event_date_basis"],
            "affected_periods": ",".join(json.loads(event["affected_periods_json"])),
            "affected_scopes": ",".join(json.loads(event["affected_scopes_json"])),
            "issuer": event["issuer"], "source_url": event["source_url"], "content_hash": event["content_hash"],
            "verification_status": event["verification_status"],
            "linked_filing_versions": ";".join(links.get(event["event_id"], [])),
        })
    return sorted(result, key=lambda row: (row["available_from"], row["event_key"]))


def source_inventory(repository: HistoricalAuditRepository, ticker: str) -> list[dict[str, Any]]:
    """Machine-readable inventory of every archived source artifact (evidence documents and filing XBRL/PDFs)."""
    with repository.connect() as connection:
        documents = [dict(row) for row in connection.execute(
            "SELECT * FROM historical_source_documents WHERE ticker = ? ORDER BY source_key, retrieved_at", (ticker,)).fetchall()]
        versions = {row["content_hash"]: dict(row) for row in connection.execute(
            "SELECT * FROM financial_filing_versions WHERE ticker = ?", (ticker,)).fetchall()}
        counts = {
            table: {row[0]: row[1] for row in connection.execute(
                f"SELECT source_document_id, COUNT(*) FROM {table} GROUP BY source_document_id")}
            for table in ("historical_publication_events", "official_summary_observations", "restatement_comparisons")
        }
        quote_failures = {row[0] for row in connection.execute(
            "SELECT source_document_id FROM historical_publication_events WHERE verification_status = 'quote_not_found'")}
    inventory = []
    for document in documents:
        document_id = document["source_document_id"]
        version = versions.get(document["content_hash"])
        summaries = counts["official_summary_observations"].get(document_id, 0)
        comparisons = counts["restatement_comparisons"].get(document_id, 0)
        events = counts["historical_publication_events"].get(document_id, 0)
        category = document["source_category"]
        if version is not None:
            category = {"original": "official_original_filing", "restated": "official_restated_filing"}.get(
                version["filing_version_type"], "official_filing_unknown_revision")
        parsed = bool(version or summaries or comparisons or events)
        missing = []
        if version is not None:
            if version["availability_status"] != "verified":
                missing.append("verified public-availability time of these exact bytes")
            missing.append("numeric extraction (scanned statements; no OCR)")
        if summaries:
            missing.append("verified first-publication time of the summary file")
        inventory.append({
            "ticker": ticker, "source_key": document["source_key"], "source_category": category,
            "issuer": document["issuer"], "document_type": document["document_type"],
            "source_url": (version or {}).get("source_url") or document["source_url"],
            "request_method": json.loads(document["request_json"]).get("method"),
            "retrieved_at": document["retrieved_at"], "content_hash": document["content_hash"],
            "content_length": document["content_length"], "http_last_modified": document["http_last_modified"],
            "accounting_framework": (json.loads(version["diagnostics_json"]).get("ebook_listing", {}).get("accounting_framework")
                                     if version else None),
            "statement_scope": version["statement_scope"] if version else None,
            "fiscal_periods": version["period"] if version else None,
            "version_classification": version["filing_version_type"] if version else None,
            "contains_full_statements": version is not None,
            "contains_summary_values": summaries > 0,
            "contains_comparison_values": comparisons > 0,
            "parser": document["parser"], "parser_status": "parsed" if parsed else "not_parsed",
            "publication_evidence": (version["available_at"] if version and version["available_at"] else
                                     f"{events} timeline events" if events else None),
            "verification_status": "quote_not_found" if document_id in quote_failures else
                                   ("verified_official_source" if parsed else "pending_verification"),
            "missing_evidence": "; ".join(missing),
        })
    for version in versions.values():
        if version["source_kind"] in {"mops_xbrl_instance", "mops_inline_xbrl", "mops_xbrl_zip"}:
            inventory.append({
                "ticker": ticker, "source_key": f"mops-t164sb01-{version['period']}",
                "source_category": {"original": "official_original_filing", "restated": "official_restated_filing"}.get(
                    version["filing_version_type"], "official_filing_unknown_revision"),
                "issuer": "MOPS (company filing)", "document_type": "annual consolidated XBRL instance (t164sb01)",
                "source_url": version["source_url"], "request_method": "GET", "retrieved_at": version["retrieved_at"],
                "content_hash": version["content_hash"], "content_length": version["content_length"],
                "http_last_modified": None, "accounting_framework": "TIFRS", "statement_scope": version["statement_scope"],
                "fiscal_periods": version["period"], "version_classification": version["filing_version_type"],
                "contains_full_statements": True, "contains_summary_values": False, "contains_comparison_values": False,
                "parser": "historical-xbrl", "parser_status": version["validation_status"],
                "publication_evidence": version["available_at"], "verification_status": "verified_official_source",
                "missing_evidence": "" if version["available_at"] else "verified public-availability time of these exact bytes",
            })
    return sorted(inventory, key=lambda row: (row["source_category"], row["source_key"]))


def coverage_matrix(repository: HistoricalAuditRepository, ticker: str, start_year: int, end_year: int) -> list[dict[str, Any]]:
    with repository.connect() as connection:
        versions = [dict(row) for row in connection.execute(
            "SELECT * FROM financial_filing_versions WHERE ticker = ? AND fiscal_year BETWEEN ? AND ?",
            (ticker, start_year, end_year)).fetchall()]
        summary_years = {row[0] for row in connection.execute(
            "SELECT DISTINCT fiscal_year FROM official_summary_observations WHERE ticker = ? AND observation_role != 'prior_year_comparative'",
            (ticker,))}
        corroborated_summary = {row[0]: row[1] for row in connection.execute(
            """SELECT o.fiscal_year, COUNT(DISTINCT o.observation_id) FROM official_summary_observations o
            JOIN observation_availability a ON a.observation_id = o.observation_id AND a.observation_kind = 'summary_observation'
            WHERE o.ticker = ? AND o.observation_role = 'current_period' GROUP BY o.fiscal_year""", (ticker,))}
        first_disclosure = {row[0]: row[1] for row in connection.execute(
            "SELECT fiscal_year, MIN(disclosed_at) FROM restatement_comparisons WHERE ticker = ? GROUP BY fiscal_year", (ticker,))}
        comparison_years = {row[0] for row in connection.execute(
            "SELECT DISTINCT fiscal_year FROM restatement_comparisons WHERE ticker = ?", (ticker,))}
    facts = list_historical_facts(repository, ticker, start_year, end_year, include_test_fixtures=False)
    matrix = []
    for year in range(start_year, end_year + 1):
        year_versions = [v for v in versions if v["fiscal_year"] == year]

        def describe(kind: str) -> str:
            found = [f"{v['source_kind']}/{v['statement_scope']}" for v in year_versions if v["filing_version_type"] == kind]
            return ", ".join(sorted(found)) or "none"

        verified = [f"{v['source_kind']}/{v['statement_scope']}@{v['available_at']}" for v in year_versions
                    if v["availability_status"] == "verified"]
        pit_facts = [fact for fact in facts if fact["fiscal_year"] == year and fact["point_in_time_eligible"]]
        gaps = []
        originals = [v for v in year_versions if v["filing_version_type"] == "original"]
        if originals and all(v["source_kind"] == "official_pdf" for v in originals):
            gaps.append("original filing only as scanned PDF (no machine-readable original values)")
            gaps.append("original first-publication time unverified (archive re-upload time used as conservative bound)")
        if not originals and not any(v["filing_version_type"] == "restated" for v in year_versions):
            gaps.append("revision status unknown (no restatement evidence, original status unproven)")
        if any(v["filing_version_type"] == "restated" and v["availability_status"] != "verified" for v in year_versions):
            gaps.append("restated artifact bytes not linked to a verified upload time")
        if any(v["source_kind"] != "official_pdf" and v["availability_status"] != "verified" for v in year_versions):
            gaps.append("XBRL bytes not linked to a verified publication time")
        matrix.append({
            "fiscal_year": year, "original_evidence": describe("original"), "restated_evidence": describe("restated"),
            "summary_evidence": (
                f"TPEx summary ({corroborated_summary.get(year, 0)} current-period values corroborated by verified disclosure; rest unverified)"
                if year in summary_years else "none"),
            "comparison_evidence": "MOPS 2016-11-13 before/after disclosure" if year in comparison_years else "none",
            "verified_availability": "; ".join(verified) or "none",
            "pit_ready_facts": len(pit_facts),
            "pit_ready": (
                f"partial: {len(pit_facts)} filing facts (observation-level) + before/after disclosure from {first_disclosure[year]}"
                if pit_facts else
                f"disclosure-only: before/after values from {first_disclosure[year]}; no filing facts" if year in first_disclosure else "no"),
            "remaining_gaps": "; ".join(gaps),
        })
    return matrix


def _render(rows: list[dict[str, Any]], fields: tuple[str, ...], output_format: str, *, name: str,
            filters: dict[str, Any], generated_at: datetime | None = None) -> str:
    if output_format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow(["" if row[f] is None else ("true" if row[f] is True else "false" if row[f] is False else row[f])
                             for f in fields])
        return buffer.getvalue()
    if output_format == "json":
        return json.dumps({
            "contract": f"fintrust.historical_{name}",
            "contract_version": SUMMARY_CONTRACT_VERSION if name == "summary_observations" else EVIDENCE_CONTRACT_VERSION,
            "generated_at": iso(generated_at or utc_now()), "filters": filters, "fields": list(fields),
            "record_count": len(rows), "records": [{f: row[f] for f in fields} for row in rows],
        }, ensure_ascii=False, indent=2)
    raise ValueError("output_format must be 'csv' or 'json'.")


DATASETS = {
    "summary_observations": (list_summary_observations, SUMMARY_FIELDS, True),
    "restatement_comparisons": (list_restatement_comparisons, COMPARISON_FIELDS, True),
    "publication_timeline": (list_publication_timeline, TIMELINE_FIELDS, False),
    "source_inventory": (source_inventory, INVENTORY_FIELDS, False),
}


def export_evidence_dataset(
    repository: HistoricalAuditRepository, ticker: str, dataset: str, *, output_path: str | Path,
    output_format: str = "csv", as_of: date | datetime | str | None = None, generated_at: datetime | None = None,
    start_year: int | None = None, end_year: int | None = None,
) -> int:
    if dataset == "coverage_matrix":
        rows, fields = coverage_matrix(repository, ticker, start_year or 2011, end_year or 2016), COVERAGE_FIELDS
    else:
        reader, fields, supports_as_of = DATASETS[dataset]
        if as_of is not None and not supports_as_of:
            raise ValueError(f"{dataset} does not support as_of filtering.")
        rows = reader(repository, ticker, as_of=as_of) if supports_as_of else reader(repository, ticker)
    text = _render(rows, fields, output_format, name=dataset,
                   filters={"ticker": ticker, "as_of": str(as_of) if as_of is not None else None}, generated_at=generated_at)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return len(rows)
