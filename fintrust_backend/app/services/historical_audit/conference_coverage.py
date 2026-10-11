"""Year-by-year official conference coverage for a historical case.

Reuses the existing MOPS t100sb02_1 conference pipeline: its archive
(``<root>/<ticker>/<year>/manifest.json``), its listing transport and its
listing parser. This module only *records* coverage and preserves the official
listing response that justifies each status; acquisition, text extraction and
document identity stay in ``mops_conference_pdf_pipeline``.

Statuses: ``conference_found``, ``no_official_record_found`` (MOPS answered
查無資料), ``official_listing_unavailable``, ``document_missing``,
``unsupported_attachment``, ``download_failed``, ``pending_verification``.
A MOPS 查無資料 answer is not proof that no conference took place.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.evidence_store import to_json
from app.services.historical_audit.models import iso, utc_now
from app.services.historical_audit.repository import HistoricalAuditRepository
from app.services.mops_conference_pdf_pipeline import LIST_URL, AcquisitionError, parse_listing


COVERAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_conference_coverage (
    ticker TEXT NOT NULL,
    year INTEGER NOT NULL,
    research_role TEXT NOT NULL,
    status TEXT NOT NULL,
    listing_url TEXT NOT NULL,
    listing_sha256 TEXT,
    listing_raw_path TEXT,
    listing_retrieved_at TEXT,
    conference_rows INTEGER NOT NULL DEFAULT 0,
    meeting_dates_json TEXT NOT NULL DEFAULT '[]',
    expected_documents INTEGER NOT NULL DEFAULT 0,
    downloaded_documents INTEGER NOT NULL DEFAULT 0,
    non_pdf_attachments INTEGER NOT NULL DEFAULT 0,
    missing_documents INTEGER NOT NULL DEFAULT 0,
    errors_json TEXT NOT NULL DEFAULT '[]',
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (ticker, year, listing_sha256)
);
"""


def listing_url(ticker: str, year: int, market: str) -> str:
    from urllib.parse import urlencode

    return f"{LIST_URL}?{urlencode({'step': '1', 'firstin': '1', 'off': '1', 'TYPEK': market, 'year': year - 1911, 'co_id': ticker})}"


def classify_listing(raw: bytes, *, ticker: str, year: int) -> tuple[str, str | None]:
    """Classify an official listing response with the pipeline's own parser."""
    try:
        attachments, _ = parse_listing(raw, ticker=ticker, roc_year=year - 1911, non_pdf=[])
        return ("conference_found" if attachments else "unsupported_attachment"), None
    except AcquisitionError as exc:
        if "查無資料" in str(exc):
            return "no_official_record_found", str(exc)
        return "official_listing_unavailable", str(exc)


def research_role(year: int, start_year: int, end_year: int) -> str:
    if year < start_year:
        return "pre_period_context"
    if year > end_year:
        return "post_period_context"
    return "core"


class ConferenceCoverageRecorder:
    def __init__(self, repository: HistoricalAuditRepository, archive: RawEvidenceArchive,
                 conference_root: Path, *, transport: Any | None = None, delay_seconds: float = 2.0,
                 sleep=None) -> None:
        self.repository = repository
        self.archive = archive
        self.root = Path(conference_root)
        self.transport = transport
        self.delay_seconds = delay_seconds
        self.sleep = sleep or __import__("time").sleep
        self._fetched = 0
        with self.repository.connect() as connection:
            connection.executescript(COVERAGE_SCHEMA)

    def record(self, ticker: str, years: list[int], *, market: str, start_year: int, end_year: int) -> list[dict[str, Any]]:
        rows = []
        for year in years:
            manifest_path = self.root / ticker / str(year) / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
            saved = self.root / ticker / str(year) / "listing-page-1.html"
            url = listing_url(ticker, year, market)
            retrieved_at = manifest.get("retrieved_at")
            raw: bytes | None = None
            if saved.is_file():
                raw = saved.read_bytes()  # preserved by the conference pipeline; no new request
            else:
                if self.transport is None:
                    from app.services.mops_conference_pdf_pipeline import HttpMopsTransport

                    self.transport = HttpMopsTransport()
                if self._fetched:
                    self.sleep(self.delay_seconds)  # polite spacing between official requests
                self._fetched += 1
                try:
                    raw = self.transport.listing(ticker, year - 1911, market, page=1)
                    retrieved_at = iso(utc_now())
                except Exception as exc:  # transport failure is not evidence of absence
                    rows.append(self._save(ticker, year, start_year, end_year, "official_listing_unavailable", url,
                                           None, None, None, manifest, [f"{type(exc).__name__}: {exc}"]))
                    continue
            status, error = classify_listing(raw, ticker=ticker, year=year)
            stored = self.archive.store(ticker=ticker, period=f"evidence/mops-conference-listing-{year}", content=raw,
                                        detected_format="html", retrieval={"source_url": url, "retrieved_at": retrieved_at})
            listed, listing_rows = (parse_listing(raw, ticker=ticker, roc_year=year - 1911, non_pdf=[])
                                    if status == "conference_found" else ([], 0))
            documents = manifest.get("documents", [])
            downloaded = sum(1 for d in documents if d.get("sha256"))
            # The official listing, not only a pipeline manifest, defines what exists: listed documents that were
            # never archived are missing evidence even when no manifest was written for the year.
            if status == "conference_found" and downloaded < max(len(documents), len(listed)):
                status = "document_missing" if not manifest.get("errors") else "download_failed"
            errors = list(manifest.get("errors", [])) + ([error] if error else [])
            rows.append(self._save(ticker, year, start_year, end_year, status, url, stored.content_hash,
                                   stored.relative_path, retrieved_at, manifest, errors, listed, listing_rows))
        return rows

    def _save(self, ticker, year, start_year, end_year, status, url, digest, raw_path, retrieved_at, manifest, errors,
              listed=(), listing_rows=0):
        documents = manifest.get("documents", [])
        dates = sorted({date for d in documents for date in d.get("conference_dates", [])}
                       | {date for attachment in listed for date in attachment.conference_dates})
        row = {
            "ticker": ticker, "year": year, "research_role": research_role(year, start_year, end_year),
            "status": status, "listing_url": url, "listing_sha256": digest, "listing_raw_path": raw_path,
            "listing_retrieved_at": retrieved_at, "conference_rows": int(manifest.get("rows") or listing_rows or 0),
            "meeting_dates_json": to_json(dates),
            "expected_documents": max(int(manifest.get("expected_pdfs") or 0), len(listed)),
            "downloaded_documents": sum(1 for d in documents if d.get("sha256")),
            "non_pdf_attachments": len(manifest.get("non_pdf_attachments") or []),
            "missing_documents": len((manifest.get("integrity") or {}).get("missing_pdfs") or []),
            "errors_json": to_json(errors), "recorded_at": iso(utc_now()),
        }
        with self.repository.connect() as connection:
            connection.execute(
                f"INSERT OR IGNORE INTO historical_conference_coverage ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                tuple(row.values()))
        return row


def latest_coverage(repository: HistoricalAuditRepository, ticker: str) -> list[dict[str, Any]]:
    with repository.connect() as connection:
        connection.executescript(COVERAGE_SCHEMA)
        rows = [dict(r) for r in connection.execute(
            "SELECT * FROM historical_conference_coverage WHERE ticker = ? ORDER BY year, recorded_at DESC", (ticker,))]
    latest: dict[int, dict[str, Any]] = {}
    for row in rows:
        latest.setdefault(row["year"], row)
    return [latest[year] for year in sorted(latest)]


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
