"""Read-only text/JSD readiness bridge for a historical case (no JSD is computed here).

Readiness comes from the unchanged ``conference_jsd_corpus_adapter.build_records`` (``docs/data/JSD_INPUT_CONTRACT.md``):
a record is JSD-ready only with a document-verified ``YYYYQn`` period, known type, language, official text and SHA,
not quarantined and not a duplicate. Ethan's JSD algorithm, tokenizer, thresholds and calibration are neither called
nor modified. With zero ready records the drift result is NOT_APPLICABLE — never a numeric zero.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from app.services.financial_research.modes import AnalysisContext, AnalysisMode

BRIDGE_VERSION = "text_evidence_bridge_v1"


def text_readiness(conference_repository: Any, ticker: str, context: AnalysisContext, *, start_year: int,
                   end_year: int, coverage_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from app.services.conference_jsd_corpus_adapter import build_records
    from app.services.historical_audit.conference_package import page_text_status

    if context.mode is AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
        from app.services.financial_research.modes import ModeNotSupportedError
        raise ModeNotSupportedError("analysis_mode_not_supported",
                                    "Text readiness supports RETROSPECTIVE_FORENSIC and STRICT_AS_OF.")
    if conference_repository is None:
        return {"bridge_version": BRIDGE_VERSION, **context.as_dict(), "ticker": ticker,
                "status": "EVIDENCE_UNVERIFIED", "archive_status": "conference_archive_unavailable_in_this_deployment",
                "jsd": {"status": "NOT_APPLICABLE", "value": None}}
    years = [y for y in conference_repository.available_years(ticker) if start_year <= y <= end_year]
    records = build_records(conference_repository, ticker, years) if years else []
    pages = text_pages = 0
    documents = []
    for record in sorted(records, key=lambda r: (r.provenance["announcement_year"], r.provenance["filename"])):
        year, filename = record.provenance["announcement_year"], record.provenance["filename"]
        page_rows = conference_repository.pages(ticker, year, filename)
        statuses = [page_text_status(p) for p in page_rows]
        pages += len(page_rows)
        text_pages += statuses.count("text_extracted")
        documents.append({
            "announcement_year": year, "filename": filename, "sha256": record.record["sha256"],
            "document_type": record.record["document_type"], "language": record.record["language"],
            "period": record.record["period"], "period_validation_status": record.provenance.get("period_validation_status"),
            "page_count": len(page_rows), "text_pages": statuses.count("text_extracted"),
            "duplicate_of": record.provenance.get("duplicate_of"), "jsd_ready": record.jsd_ready,
            "readiness_issues": list(record.readiness_issues), "publication_availability_status": "unverified"})
    coverage = sorted((r for r in coverage_rows or [] if start_year <= r["year"] <= end_year), key=lambda r: r["year"])
    ready = sum(record.jsd_ready for record in records)
    issues = Counter(issue for record in records for issue in record.readiness_issues)
    issues["publication_unverified"] = len(records)
    strict_eligible = 0  # no archived conference document has a verified first-publication time
    jsd_status = "NOT_APPLICABLE" if ready == 0 else "AVAILABLE_FROM_TEAMMATE_PIPELINE_ONLY"
    return {
        "bridge_version": BRIDGE_VERSION, **context.as_dict(), "ticker": ticker,
        "years": {"start": start_year, "end": end_year, "with_documents": sorted({d["announcement_year"] for d in documents})},
        "status": "NOT_READY" if ready == 0 else "PARTIAL",
        "archive": {"file_records": len(records), "unique_sha256": len({r.record["sha256"] for r in records}),
                    "pages": pages, "text_pages": text_pages,
                    "listing_meeting_rows": sum(int(r.get("conference_rows") or 0) for r in coverage),
                    "coverage_years": [{"year": r["year"], "status": r["status"], "listing_meeting_rows": r.get("conference_rows"),
                                        "expected_documents": r.get("expected_documents"),
                                        "downloaded_documents": r.get("downloaded_documents"),
                                        "listing_sha256": r.get("listing_sha256")} for r in coverage]},
        "jsd_ready_records": ready,
        "strict_eligible_documents": strict_eligible if context.mode is AnalysisMode.STRICT_AS_OF else None,
        "readiness_issue_counts": dict(sorted(issues.items())),
        "data_quality_states": ["archived", "text_extracted", "period_unconfirmed", "publication_unverified", "jsd_not_ready"],
        "jsd": {"status": jsd_status, "value": None,
                "explanation": ("0 records satisfy the JSD input contract (period not verified from the document, "
                                "publication time unverified); no drift score is computed or implied.")
                if ready == 0 else "Ready records exist; drift values come only from the teammate JSD pipeline."},
        "contract": "docs/data/JSD_INPUT_CONTRACT.md",
        "ownership": "JSD algorithm, tokenizer, thresholds and calibration are owned by the teammate pipeline; read-only here.",
        "documents": documents,
    }


def build_conference_repository(root: str | Path) -> Any | None:
    from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository

    path = Path(root)
    return FileConferencePdfArchiveRepository(path) if path.is_dir() else None
