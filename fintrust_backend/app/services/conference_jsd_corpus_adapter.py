"""JSD input-contract adapter for official conference documents.

Turns archived official conference PDFs (local or GCS archive, same repository
contract) into document-level records compatible with the research corpus
used by the teammate's JSD / cosine tooling::

    ticker, company, industry, year, quarter, period, document_type, language,
    text, source_page, source_pdf, sha256, text_length

FinTrust provenance (validation status, archive backend, identity method ...)
travels alongside in ``provenance`` and is never forced into that contract.

Boundaries:
* ``text`` is the page-order text extracted from the original official PDF;
  no semantic labels, OCR duplicates, model output or narrative is added.
* ``jsd_ready`` means only "satisfies the JSD input contract". Calibration
  suitability is a separate structural flag; no JSD, cosine, percentile, or
  drift computation happens here.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

from app.services.company_registry import get_company
from app.services.conference_document_identity import (
    IDENTITY_VERSION,
    assess_document_identity,
    reconcile_documents,
)
from app.services.semiconductor_subindustries import classify_semiconductor_company

ADAPTER_VERSION = "conference-jsd-adapter-v1"
# Measurement identity of adapter text: calibration applies only to the same identity.
SOURCE_FAMILY = "mops_t100sb02_1_conference_pdf"
EXTRACTION_METHOD = "mops_conference_pipeline:pypdf_extract_text_per_page"
PREPROCESSING_VERSION = "fintrust-conference-document-text-v1"
# Field order of the teammate research corpus (tsmc_quarterly_text.csv).
CORPUS_FIELDS = [
    "ticker", "company", "industry", "year", "quarter", "period", "document_type",
    "language", "text", "source_page", "source_pdf", "sha256", "text_length",
]
INDEX_FIELDS = [
    "ticker", "period", "document_type", "language", "sha256", "text_length", "source_page", "source_pdf",
    "jsd_ready", "readiness_issues", "transcript_calibration_compatible", "period_validation_status",
    "period_claimed_by_source", "period_detected_in_document", "document_type_method",
    "quarantined", "quarantine_reasons", "duplicate_of", "archive_backend", "filename", "acquired_at",
]
# Project taxonomy (semiconductor_subindustries) → research-corpus industry codes.
INDUSTRY_CODES = {
    "晶圓代工": "semiconductor_foundry",
    "IC 設計": "semiconductor_fabless",
    "封裝測試": "semiconductor_osat",
    "記憶體製造": "semiconductor_memory",
    "分離元件與功率半導體": "semiconductor_discrete_power",
    "半導體材料與零組件": "semiconductor_materials",
    "半導體設備": "semiconductor_equipment",
    "記憶體模組與儲存": "semiconductor_memory_modules",
    "光電與新型顯示半導體": "semiconductor_optoelectronics",
}
TRANSCRIPT_TYPE = "full_earnings_transcript"
MOPS_DOWNLOAD_URL = "https://mopsov.twse.com.tw/server-java/FileDownLoad"
_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*(?:page\s+)?\d{1,3}(?:\s*(?:/|of)\s*\d{1,3})?\s*$", re.I)


@dataclass
class JsdCorpusRecord:
    record: dict[str, Any]
    provenance: dict[str, Any]
    jsd_ready: bool
    readiness_issues: list[str] = field(default_factory=list)

    @property
    def transcript_calibration_compatible(self) -> bool:
        return self.jsd_ready and self.record["document_type"] == TRANSCRIPT_TYPE

    def index_row(self) -> dict[str, Any]:
        row = {key: self.record.get(key) for key in INDEX_FIELDS if key in self.record}
        row.update({key: self.provenance.get(key) for key in INDEX_FIELDS if key in self.provenance})
        row.update(jsd_ready=self.jsd_ready, readiness_issues=";".join(self.readiness_issues),
                   transcript_calibration_compatible=self.transcript_calibration_compatible)
        for key in ("period_claimed_by_source", "quarantine_reasons"):
            if isinstance(row.get(key), (dict, list)):
                row[key] = str(row[key])
        return row


def document_text(pages: list[dict[str, Any]]) -> str:
    """Page-order official text. Only bare page-number lines are removed."""
    parts = []
    for page in sorted(pages, key=lambda item: int(item.get("page") or 0)):
        text = _PAGE_NUMBER_LINE.sub("", str(page.get("text") or ""))
        text = re.sub(r"[ \t]{2,}", " ", text).strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def official_download_url(download_fields: dict[str, Any] | None, filename: str) -> str | None:
    """Official MOPS FileDownLoad reference (MOPS serves it as a form POST)."""
    fields = dict(download_fields or {})
    if not filename:
        return None
    fields.setdefault("fileName", filename)
    ordered = {key: fields.get(key, "") for key in ("step", "filePath", "fileName", "functionName")}
    return f"{MOPS_DOWNLOAD_URL}?{urlencode(ordered)}"


def company_identity(ticker: str, listed_name: str | None) -> tuple[str, str]:
    registry = get_company(ticker)
    company = listed_name or (registry.name if registry else ticker)
    classification = classify_semiconductor_company(ticker)
    return company, INDUSTRY_CODES.get(classification.subindustry, "semiconductor_unclassified")


def _readiness(record: dict[str, Any], identity: dict[str, Any]) -> list[str]:
    issues = []
    if not re.fullmatch(r"\d{4,6}", str(record.get("ticker") or "")):
        issues.append("invalid_ticker")
    if identity.get("period_validation_status") != "verified" or not record.get("period"):
        issues.append(f"period_{identity.get('period_validation_status') or 'missing'}")
    if record.get("document_type") in {None, "", "unknown"}:
        issues.append("unknown_document_type")
    if not str(record.get("text") or "").strip():
        issues.append("empty_text")
    for key in ("source_page", "source_pdf"):
        if not str(record.get(key) or "").startswith("https://"):
            issues.append(f"missing_official_{key}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256") or "")):
        issues.append("missing_sha256")
    if record.get("language") in {None, "", "unknown"}:
        issues.append("unknown_language")
    if not record.get("text_length"):
        issues.append("missing_text_length")
    if identity.get("quarantined"):
        issues.append("quarantined")
    if identity.get("duplicate_of"):
        issues.append("duplicate_document")
    return issues


def build_records(repository: Any, ticker: str, years: Iterable[int] | None = None) -> list[JsdCorpusRecord]:
    """Records for one company across its archived announcement years."""
    backend = getattr(repository, "backend_name", "unknown")
    selected = list(years) if years is not None else list(repository.available_years(ticker))
    drafts: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for year in sorted(selected):
        manifest = repository.latest_manifest(ticker, year) or {}
        for document in manifest.get("documents", []):
            if "sha256" not in document:
                continue
            pages = repository.pages(ticker, year, document["filename"])
            if document.get("identity_version") == IDENTITY_VERSION:
                identity = {key: document.get(key) for key in (
                    "period", "period_validation_status", "period_claimed_by_source",
                    "period_detected_in_document", "period_validation_method", "period_validation_confidence",
                    "document_type", "document_type_method", "document_type_confidence", "document_type_evidence",
                    "quarantined", "quarantine_reasons")}
                identity["language"] = document.get("document_language") or document.get("language")
                identity["quarantine_reasons"] = list(identity.get("quarantine_reasons") or [])
            else:
                identity = assess_document_identity(pages, language=document.get("language"),
                                                    summaries=document.get("listing_summaries") or [])
            identity.update(ticker=ticker, sha256=document["sha256"], filename=document["filename"])
            company, industry = company_identity(ticker, document.get("company_name"))
            period = identity.get("period")
            text = document_text(pages)
            record = {
                "ticker": ticker,
                "company": company,
                "industry": industry,
                "year": int(period[:4]) if period else None,
                "quarter": int(period[-1]) if period else None,
                "period": period,
                "document_type": identity.get("document_type") or "unknown",
                "language": identity.get("language") or "unknown",
                "text": text,
                "source_page": manifest.get("listing_url"),
                "source_pdf": official_download_url(document.get("download_fields"), document["filename"]),
                "sha256": document["sha256"],
                "text_length": len(text),
            }
            provenance = {
                "adapter_version": ADAPTER_VERSION,
                "source_family": SOURCE_FAMILY,
                "extraction_method": EXTRACTION_METHOD,
                "preprocessing_version": PREPROCESSING_VERSION,
                "archive_backend": backend,
                "announcement_year": year,
                "filename": document["filename"],
                "acquired_at": manifest.get("retrieved_at"),
                "conference_dates": list(document.get("conference_dates") or []),
                "source_pdf_access": "MOPS FileDownLoad form POST",
                "page_count": len(pages),
                **{key: identity.get(key) for key in (
                    "period_validation_status", "period_claimed_by_source", "period_detected_in_document",
                    "period_validation_method", "period_validation_confidence", "document_type_method",
                    "document_type_confidence", "document_type_evidence")},
            }
            drafts.append((record, provenance, identity))
    reconcile_documents([identity for _, _, identity in drafts])
    records = []
    for record, provenance, identity in drafts:
        provenance.update(quarantined=bool(identity.get("quarantined")),
                          quarantine_reasons=list(identity.get("quarantine_reasons") or []),
                          duplicate_of=identity.get("duplicate_of"))
        issues = _readiness(record, identity)
        records.append(JsdCorpusRecord(record=record, provenance=provenance, jsd_ready=not issues,
                                       readiness_issues=issues))
    return records


def _quarter_index(period: str) -> int:
    return int(period[:4]) * 4 + int(period[-1]) - 1


def comparable_pairs(records: list[JsdCorpusRecord]) -> list[dict[str, Any]]:
    """Metadata-only pairing: same ticker, type and language; adjacent fiscal quarters; both ready."""
    groups: dict[tuple, dict[int, JsdCorpusRecord]] = {}
    for item in records:
        if not item.jsd_ready:
            continue
        key = (item.record["ticker"], item.record["document_type"], item.record["language"])
        groups.setdefault(key, {})[_quarter_index(item.record["period"])] = item
    pairs = []
    for (ticker, document_type, language), by_quarter in sorted(groups.items()):
        for quarter in sorted(by_quarter):
            if quarter + 1 in by_quarter:
                first, second = by_quarter[quarter], by_quarter[quarter + 1]
                pairs.append({
                    "ticker": ticker, "document_type": document_type, "language": language,
                    "period_1": first.record["period"], "period_2": second.record["period"],
                    "sha256_1": first.record["sha256"], "sha256_2": second.record["sha256"],
                    "comparable_for_pairwise_shift": True,
                    "transcript_calibration_compatible": (
                        first.transcript_calibration_compatible and second.transcript_calibration_compatible),
                })
    return pairs


def to_corpus_rows(records: list[JsdCorpusRecord], *, only_ready: bool = True) -> list[dict[str, Any]]:
    return [{key: item.record[key] for key in CORPUS_FIELDS}
            for item in records if item.jsd_ready or not only_ready]


def export_corpus(records: list[JsdCorpusRecord], destination: Path, *, name: str = "conference_corpus",
                  parquet: bool = True) -> dict[str, str]:
    """Write the research corpus (full text; keep out of Git) and a text-free index."""
    destination.mkdir(parents=True, exist_ok=True)
    rows = to_corpus_rows(records)
    paths = {"csv": str(destination / f"{name}.csv"), "index": str(destination / f"{name}_index.csv")}
    with open(paths["csv"], "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CORPUS_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    if parquet and rows:
        import pandas as pd

        paths["parquet"] = str(destination / f"{name}.parquet")
        pd.DataFrame(rows, columns=CORPUS_FIELDS).to_parquet(paths["parquet"], index=False)
    with open(paths["index"], "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=INDEX_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(item.index_row() for item in records)
    return paths
