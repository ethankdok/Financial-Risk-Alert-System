"""Conference evidence for research packages (reuses the existing conference archive and JSD adapter).

Files produced in a *retrospective* package (all under the existing package root):

- ``data/conference_documents.csv``      one row per recovered official document (identity, hashes, availability)
- ``data/conference_text_corpus.csv``    archival page-order text of every recovered document (not the JSD contract)
- ``data/conference_jsd_corpus.csv``     rows the unchanged JSD adapter marks ``jsd_ready`` (JSD_INPUT_CONTRACT)
- ``data/conference_page_index.csv``     per page: text status, extraction method, review flags
- ``data/conference_quality_report.csv`` per document quality summary
- ``data/conference_coverage.csv``       year-by-year official listing status and evidence hash
- ``conference/pages/<sha256>.pages.json`` sanitized per-page JSON (local paths removed)
- ``conference/text/<sha256>.txt``       page-order text
- ``raw_evidence/conference_pdfs/<ticker>/<year>/<sha256>.pdf`` original PDFs (SHA-256 checked)
- ``raw_evidence/regulatory_disclosures/<ticker>/mops-conference-listing-<year>/<sha256>.html``

A *strict point-in-time* package contains no conference document, text or listing
status unless the document's public availability is verified before the cutoff
(none is in Phase 1C): presentation cover dates and MOPS meeting dates are not
publication evidence, and even listing a document could reveal a later upload.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

CONFERENCE_DOCUMENT_FIELDS = (
    "ticker", "research_role", "announcement_year", "meeting_dates", "filename", "listing_language",
    "document_language", "document_type", "document_type_confidence", "period", "period_validation_status",
    "page_count", "text_pages", "low_text_pages", "image_or_scanned_pages", "sha256", "source_page", "source_pdf",
    "download_method", "publication_availability_status", "availability_note", "jsd_ready", "readiness_issues",
    "package_raw_path", "raw_evidence_included",
)
CONFERENCE_TEXT_FIELDS = (
    "ticker", "research_role", "filename", "meeting_dates", "document_language", "document_type", "period",
    "sha256", "page_count", "text_length", "archival_only", "jsd_ready", "text",
)
CONFERENCE_PAGE_FIELDS = (
    "ticker", "filename", "sha256", "page", "text_length", "text_extraction_method", "text_status",
    "contains_images", "contains_drawings", "visual_review_required",
)
CONFERENCE_QUALITY_FIELDS = (
    "ticker", "filename", "sha256", "page_count", "text_extracted_pages", "low_text_pages", "image_or_scanned_pages",
    "failed_or_empty_pages", "visual_review_required_pages", "issue_count", "document_type_confidence",
    "period_validation_status", "quarantined",
)
CONFERENCE_COVERAGE_FIELDS = (
    "ticker", "year", "research_role", "status", "conference_rows", "meeting_dates", "expected_documents",
    "downloaded_documents", "non_pdf_attachments", "missing_documents", "listing_url", "listing_sha256",
    "package_raw_path", "errors",
)
TEXT_THRESHOLD = 30  # same threshold the conference pipeline uses for text pages
AVAILABILITY_NOTE = ("MOPS gives the meeting date only; the presentation's first public availability is not verified "
                     "(cover/meeting dates are not publication evidence). Excluded from strict point-in-time packages.")


def page_text_status(page: dict[str, Any]) -> str:
    length = int(page.get("text_length") or 0)
    if length >= TEXT_THRESHOLD:
        return "text_extracted"
    if length > 0:
        return "low_text_coverage"
    if page.get("contains_images"):
        return "image_or_scanned"
    return "failed_or_empty"


def _sanitized_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in page.items() if key != "review_image_path"} for page in pages]


def _role(year: int, start_year: int, end_year: int) -> str:
    return "core" if start_year <= year <= end_year else ("pre_period_context" if year < start_year else "post_period_context")


def build_conference_datasets(
    *, add: Callable[[str, bytes, str], None], csv_bytes: Callable[[list[dict], tuple[str, ...]], bytes],
    repository: Any, root: Path | None, ticker: str, start_year: int, end_year: int,
    include_context: bool, include_raw: bool, coverage_rows: list[dict[str, Any]], archive: Any,
    missing: list[dict[str, Any]],
) -> dict[str, Any]:
    from app.services.conference_jsd_corpus_adapter import (
        CORPUS_FIELDS,
        build_records,
        document_text,
        to_corpus_rows,
    )

    stats = {"status": "included", "documents": 0, "pages": 0, "text_pages": 0, "jsd_ready": 0,
             "awaiting_identity_verification": 0, "out_of_range_excluded": 0, "years_with_documents": []}
    available = repository.available_years(ticker) if repository is not None else []
    in_scope = [y for y in available if include_context or start_year <= y <= end_year]
    stats["out_of_range_excluded"] = sum(
        len((repository.latest_manifest(ticker, y) or {}).get("documents", []))
        for y in available if y not in in_scope)
    records = build_records(repository, ticker, in_scope) if in_scope else []
    doc_rows, text_rows, page_rows, quality_rows = [], [], [], []
    for record in sorted(records, key=lambda r: (r.provenance["announcement_year"], r.provenance["filename"])):
        year, filename = record.provenance["announcement_year"], record.provenance["filename"]
        manifest_doc = next((d for d in (repository.latest_manifest(ticker, year) or {}).get("documents", [])
                             if d.get("filename") == filename), {})
        sha = record.record["sha256"]
        pages = repository.pages(ticker, year, filename)
        statuses = [page_text_status(p) for p in pages]
        raw_path = None
        source = root / ticker / str(year) / filename if root else None
        if include_raw and source is not None and source.is_file():
            data = source.read_bytes()
            if hashlib.sha256(data).hexdigest() == sha:
                raw_path = f"raw_evidence/conference_pdfs/{ticker}/{year}/{sha}.pdf"
                add(raw_path, data, "conference_raw_evidence")
            else:
                missing.append({"fiscal_year": year, "evidence_kind": "conference_pdf", "status": "failed_integrity",
                                "detail": filename})
        elif include_raw:
            missing.append({"fiscal_year": year, "evidence_kind": "conference_pdf", "status": "missing_locally",
                            "detail": filename})
        add(f"conference/pages/{sha}.pages.json",
            (json.dumps(_sanitized_pages(pages), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "conference_derived")
        text = document_text(pages)
        add(f"conference/text/{sha}.txt", text.encode("utf-8"), "conference_derived")
        role = _role(year, start_year, end_year)
        identity_pending = record.provenance.get("period_validation_status") != "verified"
        doc_rows.append({
            "ticker": ticker, "research_role": role, "announcement_year": year,
            "meeting_dates": ";".join(record.provenance.get("conference_dates") or []), "filename": filename,
            "listing_language": manifest_doc.get("language"), "document_language": record.record["language"],
            "document_type": record.record["document_type"],
            "document_type_confidence": manifest_doc.get("document_type_confidence"),
            "period": record.record["period"], "period_validation_status": record.provenance.get("period_validation_status"),
            "page_count": len(pages), "text_pages": statuses.count("text_extracted"),
            "low_text_pages": statuses.count("low_text_coverage"), "image_or_scanned_pages": statuses.count("image_or_scanned"),
            "sha256": sha, "source_page": record.record["source_page"], "source_pdf": record.record["source_pdf"],
            "download_method": record.provenance.get("source_pdf_access"),
            "publication_availability_status": "unverified", "availability_note": AVAILABILITY_NOTE,
            "jsd_ready": record.jsd_ready, "readiness_issues": ";".join(record.readiness_issues),
            "package_raw_path": raw_path, "raw_evidence_included": raw_path is not None,
        })
        text_rows.append({
            "ticker": ticker, "research_role": role, "filename": filename,
            "meeting_dates": ";".join(record.provenance.get("conference_dates") or []),
            "document_language": record.record["language"], "document_type": record.record["document_type"],
            "period": record.record["period"], "sha256": sha, "page_count": len(pages), "text_length": len(text),
            "archival_only": not record.jsd_ready, "jsd_ready": record.jsd_ready, "text": text,
        })
        for page, status in zip(pages, statuses):
            page_rows.append({
                "ticker": ticker, "filename": filename, "sha256": sha, "page": page.get("page"),
                "text_length": page.get("text_length"), "text_extraction_method": page.get("text_extraction_method"),
                "text_status": status, "contains_images": bool(page.get("contains_images")),
                "contains_drawings": bool(page.get("contains_drawings")),
                "visual_review_required": bool(page.get("visual_review_required")),
            })
        quality_rows.append({
            "ticker": ticker, "filename": filename, "sha256": sha, "page_count": len(pages),
            "text_extracted_pages": statuses.count("text_extracted"), "low_text_pages": statuses.count("low_text_coverage"),
            "image_or_scanned_pages": statuses.count("image_or_scanned"),
            "failed_or_empty_pages": statuses.count("failed_or_empty"),
            "visual_review_required_pages": sum(1 for p in pages if p.get("visual_review_required")),
            "issue_count": len(manifest_doc.get("issues") or []),
            "document_type_confidence": manifest_doc.get("document_type_confidence"),
            "period_validation_status": record.provenance.get("period_validation_status"),
            "quarantined": bool(record.provenance.get("quarantined")),
        })
        stats["documents"] += 1
        stats["pages"] += len(pages)
        stats["text_pages"] += statuses.count("text_extracted")
        stats["jsd_ready"] += int(record.jsd_ready)
        stats["awaiting_identity_verification"] += int(identity_pending)
        if year not in stats["years_with_documents"]:
            stats["years_with_documents"].append(year)
    add("data/conference_documents.csv", csv_bytes(doc_rows, CONFERENCE_DOCUMENT_FIELDS), "conference")
    add("data/conference_text_corpus.csv", csv_bytes(text_rows, CONFERENCE_TEXT_FIELDS), "conference")
    corpus = sorted(to_corpus_rows(records), key=lambda row: (row["period"] or "", row["sha256"]))
    add("data/conference_jsd_corpus.csv", csv_bytes(corpus, tuple(CORPUS_FIELDS)), "conference")
    add("data/conference_page_index.csv", csv_bytes(page_rows, CONFERENCE_PAGE_FIELDS), "conference")
    add("data/conference_quality_report.csv", csv_bytes(quality_rows, CONFERENCE_QUALITY_FIELDS), "conference")

    coverage_out = []
    for row in coverage_rows:
        # The role is relative to this package's fiscal-year range (as for documents), not the range in force when the
        # listing was recorded, so a 2011-2019 package treats 2017 coverage as core.
        row = {**row, "research_role": _role(row["year"], start_year, end_year)}
        if not include_context and row["research_role"] != "core":
            continue
        raw_path = None
        if include_raw and row.get("listing_raw_path"):
            try:
                data = archive.read(row["listing_raw_path"])
                raw_path = (f"raw_evidence/regulatory_disclosures/{ticker}/mops-conference-listing-{row['year']}/"
                            f"{row['listing_sha256']}.html")
                add(raw_path, data, "raw_evidence")
            except Exception:
                missing.append({"fiscal_year": row["year"], "evidence_kind": "conference_listing",
                                "status": "failed_integrity", "detail": row["listing_raw_path"]})
        coverage_out.append({**row, "meeting_dates": ";".join(json.loads(row["meeting_dates_json"])),
                             "errors": ";".join(json.loads(row["errors_json"])), "package_raw_path": raw_path})
        if row["research_role"] == "core" and row["status"] != "conference_found":
            detail = ("official MOPS t100sb02_1 listing; absence of a record is not proof that no conference took place"
                      if row["status"] in ("no_official_record_found", "official_listing_unavailable") else
                      f"official MOPS t100sb02_1 listing names {row['expected_documents']} document(s); "
                      f"{row['downloaded_documents']} archived")
            missing.append({"fiscal_year": row["year"], "evidence_kind": "conference_listing", "status": row["status"],
                            "detail": detail})
    add("data/conference_coverage.csv", csv_bytes(coverage_out, CONFERENCE_COVERAGE_FIELDS), "conference")
    if not records:
        stats["status"] = "no_documents_in_scope"
    stats["corpus_rows_jsd_ready"] = len(corpus)
    return stats
