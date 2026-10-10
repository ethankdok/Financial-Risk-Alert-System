"""Phase 1B evidence recovery: acquire → archive → parse → link → corroborate.

Acquisition makes bounded requests to the official sources named by a reviewed
evidence plan and reuses archived copies. Import is offline and deterministic:
it re-reads archived bytes (SHA-256 verified) and inserts immutable derived
records. Nothing here rewrites an existing filing version's evidence fields or
assigns a period-level date to an artifact whose identity is not proven.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.case_registry import get_case
from app.services.historical_audit.evidence_parsers import (
    EvidenceParseError,
    flat_text,
    html_to_text,
    decode_html,
    parse_mops_material_detail,
    parse_mops_material_listing,
    parse_restatement_comparison,
    parse_tpex_announcement,
    parse_tpex_summary_xls,
    parse_twse_ebook_listing,
)
from app.services.historical_audit.evidence_store import evidence_id, insert_ignore, to_json
from app.services.historical_audit.models import TAIPEI, filing_version_id, iso, utc_now
from app.services.historical_audit.repository import FilingVersionRecord, HistoricalAuditRepository
from app.services.historical_audit.sources import OfficialSourceFetcher, ensure_official_url


PLANS_DIR = Path(__file__).with_name("evidence_plans")
EXPECTED_FORMAT = {
    "tpex_announcement": ("html",),
    "mops_material_listing": ("html",),
    "mops_material_detail": ("html",),
    "twse_ebook_listing": ("html",),
    "twse_ebook_pdf": ("pdf",),
    "tpex_quarterly_summary_xls": ("xls",),
}
# Events whose announcement proves that *a* filing of the period exists, not which bytes.
PERIOD_LEVEL_EVENTS = {"restated_annual_reports_filed", "restatement_disclosure"}
# Events after which the archived artifact may have been replaced.
CORRECTION_EVENTS = {"auditor_opinion_correction", "financial_report_correction", "restatement_and_corrections_completed"}
SUMMARY_CANONICAL: dict[str, tuple[str | None, str]] = {
    "tpex_operating_revenue": ("revenue", "mapped"),
    "tpex_operating_income": ("operating_income", "mapped"),
    "tpex_eps": ("eps", "mapped"),
    # 稅後純益 equals the consolidated total in O_2013Q4 but the parent-attributable
    # figure in O_2015Q4 (checked against the 2016-11-13 disclosures): not one concept.
    "tpex_net_income_after_tax": (None, "requires_review"),
}
SUMMARY_NOTES = {
    "tpex_net_income_after_tax": "definition differs across files (consolidated total vs attributable to parent); not mapped to net_income",
    "tpex_equity_to_total_assets": "header says (%) but values are fractions in some files and percentages in others",
    "tpex_non_operating_net": "pre-2013 files: net non-operating amount (TW-GAAP); IFRS files: total non-operating income and expenses",
}


class EvidencePlanError(ValueError):
    pass


def load_plan(ticker: str, path: str | Path | None = None) -> dict[str, Any]:
    plan_path = Path(path) if path else PLANS_DIR / f"{ticker}.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("ticker") != ticker:
        raise EvidencePlanError("Evidence plan ticker does not match.")
    keys = [source["source_key"] for source in plan["sources"]]
    if len(keys) != len(set(keys)):
        raise EvidencePlanError("Duplicate source_key in evidence plan.")
    for source in plan["sources"]:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", source["source_key"]) or ".." in source["source_key"]:
            raise EvidencePlanError(f"Unsafe source_key {source['source_key']!r}")
        ensure_official_url(source["request"]["url"])
        if source["parser"] not in EXPECTED_FORMAT:
            raise EvidencePlanError(f"Unknown parser {source['parser']}")
    return plan


def availability_instant(publication_at: str, precision: str) -> datetime:
    """Earliest instant at which the notice is certainly public.

    Second-precision MOPS/TWSE timestamps are used as given (Asia/Taipei). A
    date-only announcement has no verified intraday time, so it counts as
    public only from the start of the next Taipei day.
    """
    if precision == "date":
        day = date.fromisoformat(publication_at)
        return datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=TAIPEI)
    return datetime.fromisoformat(publication_at)


@dataclass
class AcquireOutcome:
    source_key: str
    status: str
    source_document_id: str | None = None
    content_hash: str | None = None
    reused: bool = False
    error: str | None = None


@dataclass
class ImportReport:
    counts: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, key: str, value: int) -> None:
        self.counts[key] = self.counts.get(key, 0) + value


class HistoricalEvidenceService:
    def __init__(
        self,
        *,
        repository: HistoricalAuditRepository,
        archive: RawEvidenceArchive,
        fetcher: OfficialSourceFetcher | None = None,
    ) -> None:
        self.repository = repository
        self.archive = archive
        self.fetcher = fetcher

    # ------------------------------------------------------------ acquire
    def _existing(self, source_key: str) -> sqlite3.Row | None:
        with self.repository.connect() as connection:
            return connection.execute(
                "SELECT * FROM historical_source_documents WHERE source_key = ? ORDER BY retrieved_at DESC LIMIT 1",
                (source_key,),
            ).fetchone()

    async def acquire(self, plan: dict[str, Any], *, refresh: bool = False, only: set[str] | None = None) -> list[AcquireOutcome]:
        ticker = plan["ticker"]
        get_case(ticker)
        self.repository.register_case(get_case(ticker))
        if self.fetcher is None:
            self.fetcher = OfficialSourceFetcher()
        outcomes: list[AcquireOutcome] = []
        for source in plan["sources"]:
            key = source["source_key"]
            if only and key not in only:
                continue
            existing = self._existing(key)
            if existing is not None and not refresh:
                outcomes.append(AcquireOutcome(key, "archived", existing["source_document_id"], existing["content_hash"], reused=True))
                continue
            try:
                outcomes.append(await self._acquire_one(ticker, source))
            except Exception as exc:  # per-source isolation
                outcomes.append(AcquireOutcome(key, "failed", error=f"{type(exc).__name__}: {exc}"))
        return outcomes

    async def _acquire_one(self, ticker: str, source: dict[str, Any]) -> AcquireOutcome:
        assert self.fetcher is not None
        request = source["request"]
        expect = EXPECTED_FORMAT[source["parser"]]
        if request["method"] == "TWSE_EBOOK":
            step = await self.fetcher.fetch(request["url"], expect=("html",), method="POST", data=request["data"],
                                            referer="https://doc.twse.com.tw/server-java/t57sb01")
            if step.status != "ok" or not step.content:
                return AcquireOutcome(source["source_key"], step.status, error=step.error)
            link = re.search(r"href=['\"]?([^'\" >]+\.pdf)", decode_html(step.content, preferred=("cp950", "utf-8")), re.I)
            if not link:
                return AcquireOutcome(source["source_key"], "source_invalid_content", error="e-document page has no PDF link")
            fetched = await self.fetcher.fetch(ensure_official_url(urljoin(request["url"], link.group(1))), expect=expect)
            fetched.request = {"method": "POST", "url": request["url"], "data": request["data"], "then": "GET resolved PDF link"}
        else:
            fetched = await self.fetcher.fetch(request["url"], expect=expect, method=request["method"],
                                               data=request.get("data"), referer=request.get("referer"))
        if fetched.status != "ok" or fetched.content is None:
            return AcquireOutcome(source["source_key"], fetched.status, error=fetched.error)
        stored = self.archive.store(
            ticker=ticker, period=f"evidence/{source['source_key']}", content=fetched.content,
            detected_format=fetched.detected_format, retrieval=fetched.metadata(),
        )
        document_id = evidence_id("hsd1", ticker, source["source_key"], stored.content_hash)
        with self.repository.connect() as connection:
            insert_ignore(connection, "historical_source_documents", {
                "source_document_id": document_id,
                "ticker": ticker,
                "source_key": source["source_key"],
                "source_category": source["category"],
                "issuer": source["issuer"],
                "document_type": source["document_type"],
                "parser": source["parser"],
                "request_json": to_json(request),
                "source_url": request["url"],
                "final_url": fetched.final_url,
                "retrieved_at": iso(fetched.retrieved_at),
                "content_hash": stored.content_hash,
                "content_length": len(fetched.content),
                "detected_format": fetched.detected_format,
                "raw_storage_path": stored.relative_path,
                "http_last_modified": fetched.response_headers.get("last-modified"),
                "response_metadata_json": to_json(fetched.metadata()),
                "created_at": iso(utc_now()),
            })
        return AcquireOutcome(source["source_key"], "acquired", document_id, stored.content_hash)

    # ------------------------------------------------------------- import
    def import_evidence(self, plan: dict[str, Any]) -> ImportReport:
        ticker = plan["ticker"]
        case = get_case(ticker)
        report = ImportReport()
        sources = {source["source_key"]: source for source in plan["sources"]}
        with self.repository.connect() as connection:
            documents = [dict(row) for row in connection.execute(
                "SELECT * FROM historical_source_documents WHERE ticker = ? ORDER BY source_key, retrieved_at", (ticker,)
            ).fetchall()]
        order = ["tpex_announcement", "mops_material_listing", "mops_material_detail", "twse_ebook_listing",
                 "twse_ebook_pdf", "tpex_quarterly_summary_xls"]
        documents.sort(key=lambda doc: (order.index(doc["parser"]), doc["source_key"], doc["retrieved_at"]))
        for document in documents:
            source = sources.get(document["source_key"])
            if source is None:
                report.warnings.append(f"{document['source_key']}: archived but not in the current plan; skipped")
                continue
            try:
                content = self.archive.read(document["raw_storage_path"])
                handler = getattr(self, f"_import_{document['parser']}")
                with self.repository.connect() as connection:
                    handler(connection, ticker, case.company_name, source, document, content, report)
            except (EvidenceParseError, EvidencePlanError, RuntimeError, ValueError) as exc:
                report.errors.append(f"{document['source_key']}: {exc}")
        with self.repository.connect() as connection:
            self._link(connection, ticker, plan, report)
            self._corroborate(connection, ticker, report)
        return report

    @staticmethod
    def _event(connection: sqlite3.Connection, report: ImportReport, *, ticker: str, document: dict[str, Any],
               event_key: str, event_type: str, title: str, publication_at: str, precision: str,
               evidence_text: str, verification_status: str, announcement_id: str | None = None,
               event_date: str | None = None, event_date_basis: str | None = None,
               periods: list[str] | None = None, scopes: list[str] | None = None) -> str:
        event_id = evidence_id("hpe1", ticker, event_key, document["source_document_id"])
        report.add("events_inserted", insert_ignore(connection, "historical_publication_events", {
            "event_id": event_id, "ticker": ticker, "event_key": event_key, "event_type": event_type,
            "title": title, "announcement_id": announcement_id, "publication_at": publication_at,
            "publication_precision": precision, "event_date": event_date, "event_date_basis": event_date_basis,
            "affected_periods_json": to_json(periods or []), "affected_scopes_json": to_json(scopes or []),
            "source_document_id": document["source_document_id"], "evidence_text": evidence_text,
            "verification_status": verification_status, "created_at": iso(utc_now()),
        }))
        return event_id

    def _claims(self, connection, report, ticker, document, source, text, *, publication_at, precision,
                announcement_id=None, default_event_date=None, default_basis=None) -> dict[str, str]:
        flat = flat_text(text)
        ids: dict[str, str] = {}
        for claim in source.get("events", []):
            found = flat_text(claim["quote"]) in flat
            if not found:
                report.errors.append(f"{source['source_key']}: quote not found for {claim['event_key']}")
            ids[claim["event_key"]] = self._event(
                connection, report, ticker=ticker, document=document, event_key=claim["event_key"],
                event_type=claim["event_type"], title=claim["quote"], publication_at=publication_at,
                precision=precision, evidence_text=claim["quote"],
                verification_status="verified_official_quote" if found else "quote_not_found",
                announcement_id=announcement_id,
                event_date=claim.get("event_date") or default_event_date,
                event_date_basis="stated in the notice" if claim.get("event_date") else default_basis,
                periods=claim.get("affected_periods", []), scopes=claim.get("affected_scopes", []),
            )
        return ids

    def _import_tpex_announcement(self, connection, ticker, company, source, document, content, report) -> None:
        notice = parse_tpex_announcement(content)
        if ticker not in notice.text:
            raise EvidenceParseError("Announcement does not mention the case ticker.")
        publication = notice.issued_on.isoformat()
        self._event(connection, report, ticker=ticker, document=document, event_key=f"tpex:{notice.announcement_no}",
                    event_type="regulatory_announcement", title=notice.subject, publication_at=publication,
                    precision="date", evidence_text=notice.subject, verification_status="verified_official",
                    announcement_id=notice.announcement_no)
        self._claims(connection, report, ticker, document, source, notice.text, publication_at=publication,
                     precision="date", announcement_id=notice.announcement_no)

    def _import_mops_material_listing(self, connection, ticker, company, source, document, content, report) -> None:
        for row in parse_mops_material_listing(content, ticker=ticker):
            self._event(connection, report, ticker=ticker, document=document,
                        event_key=f"mops:{row.spoke_date:%Y%m%d}:{row.spoke_time}:{row.seq_no}",
                        event_type="material_information_listing", title=row.title,
                        publication_at=row.published_at.isoformat(), precision="second",
                        evidence_text=row.title, verification_status="official_listing")

    def _import_mops_material_detail(self, connection, ticker, company, source, document, content, report) -> None:
        detail = parse_mops_material_detail(content, ticker=ticker)
        data = source["request"]["data"]
        if detail.published_at.strftime("%Y%m%d%H%M%S") != data["spoke_date"] + data["spoke_time"]:
            raise EvidenceParseError("Detail page timestamp does not match the requested notice.")
        ids = self._claims(connection, report, ticker, document, source, detail.text,
                           publication_at=detail.published_at.isoformat(), precision="second",
                           default_event_date=detail.fact_date.isoformat() if detail.fact_date else None,
                           default_basis="事實發生日")
        scope = source.get("comparison_scope")
        if not scope:
            return
        expected = "合併" if scope == "consolidated" else "個體"
        if expected not in detail.subject:
            raise EvidenceParseError(f"Comparison scope {scope} not stated in subject {detail.subject!r}.")
        verified_events = [
            row[0] for row in connection.execute(
                "SELECT event_id FROM historical_publication_events WHERE source_document_id = ? "
                "AND verification_status = 'verified_official_quote' ORDER BY event_id",
                (document["source_document_id"],),
            )
        ]
        if not verified_events:
            raise EvidenceParseError("Comparison notice has no verified claim; before/after rows are not imported.")
        event_id = verified_events[0]
        for row in parse_restatement_comparison(detail.body):
            report.add("comparisons_inserted", insert_ignore(connection, "restatement_comparisons", {
                "comparison_id": evidence_id("hrc1", document["source_document_id"], row.statement, row.fiscal_year,
                                             row.pre_label, row.post_label, scope),
                "source_document_id": document["source_document_id"], "event_id": event_id, "ticker": ticker,
                "period": f"{row.fiscal_year}FY", "fiscal_year": row.fiscal_year, "statement_scope": scope,
                "accounting_framework": "TIFRS" if row.fiscal_year >= 2013 else "TW_GAAP",
                "statement_type": row.statement, "pre_label": row.pre_label, "post_label": row.post_label,
                "canonical_metric": row.canonical_metric, "sign_factor": row.sign_factor,
                "pre_value_text": str(row.pre_value) if row.pre_value is not None else None,
                "post_value_text": str(row.post_value) if row.post_value is not None else None,
                "difference_text": str(row.difference) if row.difference is not None else None,
                "published_unit": row.unit, "disclosed_at": detail.published_at.isoformat(),
                "availability_status": "verified",
                "availability_basis": "MOPS material-information 發言日期/發言時間 of the disclosing notice",
                "verification_status": "verified_official_disclosure", "created_at": iso(utc_now()),
            }))

    def _import_twse_ebook_listing(self, connection, ticker, company, source, document, content, report) -> None:
        for row in parse_twse_ebook_listing(content, ticker=ticker):
            period = f"{row.fiscal_year}FY" if row.quarter == 4 else f"{row.fiscal_year}Q{row.quarter}"
            self._event(connection, report, ticker=ticker, document=document, event_key=f"ebook:{row.filename}",
                        event_type="ebook_upload", title=f"{row.data_year_label} {row.detail} {row.filename}",
                        publication_at=row.uploaded_at.isoformat(), precision="second",
                        evidence_text=to_json({"detail": row.detail, "remark": row.remark, "file_size": row.file_size,
                                               "correction": row.correction, "version_label": row.version_label}),
                        verification_status="official_listing", periods=[period], scopes=[row.statement_scope])

    def _listing_row(self, ticker: str, listing_key: str, filename: str):
        listing = self._existing(listing_key)
        if listing is None:
            raise EvidencePlanError(f"Listing {listing_key} has not been acquired.")
        rows = parse_twse_ebook_listing(self.archive.read(listing["raw_storage_path"]), ticker=ticker)
        match = [row for row in rows if row.filename == filename]
        if len(match) != 1:
            raise EvidenceParseError(f"{filename} not listed exactly once in {listing_key}.")
        return match[0]

    def _import_twse_ebook_pdf(self, connection, ticker, company, source, document, content, report) -> None:
        filename = source["request"]["data"]["filename"]
        row = self._listing_row(ticker, source["listing_source_key"], filename)
        if content[:5] != b"%PDF-" or row.quarter != 4:
            raise EvidenceParseError(f"{filename}: not an annual PDF report.")
        period = f"{row.fiscal_year}FY"
        size_match = len(content) == row.file_size
        later_corrections = connection.execute(
            """SELECT event_key, publication_at, publication_precision FROM historical_publication_events
            WHERE ticker = ? AND event_type IN ({})""".format(",".join("?" * len(CORRECTION_EVENTS))),
            (ticker, *sorted(CORRECTION_EVENTS)),
        ).fetchall()
        affected = [
            event["event_key"] for event in later_corrections
            if row.version_label == "restated"
            and availability_instant(event["publication_at"], event["publication_precision"]) > row.uploaded_at
        ]
        verified = size_match and row.correction == "無" and not affected
        evidence = [
            f"TWSE e-document archive label: {row.detail} / {row.remark or '(no remark)'}",
            f"archive 上傳日期 {row.uploaded_at.isoformat()}; archive file size {row.file_size} bytes; "
            f"downloaded {len(content)} bytes ({'match' if size_match else 'MISMATCH'})",
            f"archive 財務報告更(補)正 column: {row.correction or '(blank)'}",
        ]
        if affected:
            evidence.append("later correction notices may have replaced this file: " + ", ".join(affected))
        record = FilingVersionRecord(
            filing_version_id=filing_version_id(ticker, period, row.statement_scope, document["content_hash"]),
            ticker=ticker, period=period, fiscal_year=row.fiscal_year, statement_scope=row.statement_scope,
            statement_scope_evidence=f"TWSE e-document archive 資料細節說明: {row.detail}",
            filing_version_type=row.version_label,
            version_type_evidence=[evidence[0]] if row.version_label != "unknown_revision" else [],
            source_kind="official_pdf", source_url=f"{source['request']['url']}?step=9&kind=A&co_id={ticker}&filename={filename}",
            source_published_at=None,
            available_at=iso(row.uploaded_at) if verified else None,
            availability_status="verified" if verified else "unverified",
            availability_basis=(
                "TWSE e-document archive 上傳日期 of this exact file (size-matched; no 更(補)正 recorded). "
                "Conservative: the report may have been public earlier." if verified else None
            ),
            verification_evidence=evidence, document_dated_at=None,
            retrieved_at=document["retrieved_at"], content_hash=document["content_hash"],
            content_length=len(content), detected_format="pdf", raw_storage_path=document["raw_storage_path"],
            validation_status="extraction_pending", quarantine_reason=None,
            warnings=["Primary statements are scanned images; no values are extracted (no OCR in Phase 1B)."],
            diagnostics={"ebook_listing": {"filename": filename, "detail": row.detail, "remark": row.remark,
                                           "uploaded_at": row.uploaded_at.isoformat(), "file_size": row.file_size,
                                           "correction": row.correction, "accounting_framework": row.accounting_framework}},
        )
        upsert = self.repository.upsert_filing_version(connection, record, annotation_source="twse_ebook_archive")
        report.add("pdf_versions_created", int(upsert.created))
        for conflict in upsert.conflicts:
            report.warnings.append(f"{filename}: {conflict}")

    def _infer_scope(self, connection, ticker: str, fiscal_year: int, revenue_thousand: Decimal | None) -> tuple[str, str]:
        if revenue_thousand is None:
            return "unknown", "no revenue value to cross-check"
        matches: set[str] = set()
        notes: list[str] = []
        for row in connection.execute(
            "SELECT statement_scope, pre_value_text, post_value_text, source_document_id FROM restatement_comparisons "
            "WHERE ticker = ? AND fiscal_year = ? AND canonical_metric = 'revenue'", (ticker, fiscal_year),
        ):
            for side in ("pre_value_text", "post_value_text"):
                if row[side] is not None and Decimal(row[side]) == revenue_thousand:
                    matches.add(row["statement_scope"])
                    notes.append(f"equals {row['statement_scope']} {side[:-11]}-restatement revenue in MOPS 2016-11-13 notice")
        for row in connection.execute(
            "SELECT statement_scope, value_text FROM versioned_financial_facts WHERE ticker = ? AND fiscal_year = ? AND metric_code = 'revenue'",
            (ticker, fiscal_year),
        ):
            if Decimal(row["value_text"]) == revenue_thousand * 1000:
                matches.add(row["statement_scope"])
                notes.append(f"equals {row['statement_scope']} XBRL revenue")
        matches.discard("unknown")
        if len(matches) == 1:
            return matches.pop(), "; ".join(sorted(set(notes)))
        return "unknown", ("ambiguous: " + "; ".join(sorted(set(notes)))) if matches else "no exact official match"

    def _import_tpex_quarterly_summary_xls(self, connection, ticker, company, source, document, content, report) -> None:
        summary = parse_tpex_summary_xls(content, ticker=ticker)
        if summary.company != company:
            raise EvidenceParseError(f"Company name {summary.company!r} does not match case {company!r}.")
        if summary.report_quarter != 4:
            raise EvidenceParseError("Only annual (1-12月) TPEx summaries are imported in Phase 1B.")
        for item in summary.unreadable:
            report.warnings.append(f"{source['source_key']}: {item}")
        groups: dict[tuple[int, str], list] = {}
        for value in summary.values:
            # Period-end columns (股本, 每股淨值, ratios) belong to the current-period row.
            role = "current_period" if value.role == "period_end" else value.role
            groups.setdefault((value.fiscal_year, role), []).append(value)
        for (fiscal_year, role), values in groups.items():
            revenue = next((v.value for v in values if v.source_metric_code == "tpex_operating_revenue"), None)
            scope, scope_basis = self._infer_scope(connection, ticker, fiscal_year, revenue)
            for value in values:
                canonical, mapping_status = SUMMARY_CANONICAL.get(value.source_metric_code, (None, "unmapped"))
                if value.published_unit == "TWD_thousand":
                    normalized, normalized_unit = value.value * 1000, "TWD"
                else:
                    normalized, normalized_unit = value.value, value.published_unit
                notes = [SUMMARY_NOTES[value.source_metric_code]] if value.source_metric_code in SUMMARY_NOTES else []
                if value.role == "prior_year_comparative":
                    notes.append(f"prior-year comparative as presented in the {summary.report_fiscal_year}FY summary")
                report.add("summary_observations_inserted", insert_ignore(connection, "official_summary_observations", {
                    "observation_id": evidence_id("hso1", document["source_document_id"], f"{fiscal_year}FY", value.role, value.source_metric_code),
                    "source_document_id": document["source_document_id"], "ticker": ticker,
                    "period": f"{fiscal_year}FY" if value.role != "period_end" else f"{summary.report_fiscal_year}FY",
                    "fiscal_year": fiscal_year, "report_period": f"{summary.report_fiscal_year}FY",
                    "observation_role": value.role, "accounting_framework": summary.accounting_framework,
                    "source_label": value.source_label, "source_metric_code": value.source_metric_code,
                    "canonical_metric": canonical, "mapping_status": mapping_status,
                    "value_text": str(value.value), "published_unit": value.published_unit,
                    "normalized_value_text": str(normalized), "normalized_unit": normalized_unit,
                    "statement_scope": scope, "statement_scope_basis": scope_basis,
                    "available_at": None, "availability_status": "unverified",
                    "availability_basis": (
                        f"Not verified. HTTP Last-Modified {document['http_last_modified']} is server metadata of the current file, "
                        "not first-publication evidence; TPEx states the summary is not rebuilt after restatements."
                    ),
                    "quality_notes_json": to_json(notes), "created_at": iso(utc_now()),
                }))

    # ------------------------------------------------------------ linking
    def _link(self, connection: sqlite3.Connection, ticker: str, plan: dict[str, Any], report: ImportReport) -> None:
        versions = [dict(row) for row in connection.execute(
            "SELECT * FROM financial_filing_versions WHERE ticker = ?", (ticker,)).fetchall()]
        events = connection.execute(
            "SELECT * FROM historical_publication_events WHERE ticker = ? AND verification_status != 'quote_not_found' "
            "ORDER BY publication_at, event_id", (ticker,)
        ).fetchall()
        affects = {
            claim["event_key"]: set(claim["affects_version_types"])
            for source in plan["sources"] for claim in source.get("events", []) if claim.get("affects_version_types")
        }
        for event in events:
            periods = json.loads(event["affected_periods_json"])
            scopes = json.loads(event["affected_scopes_json"])
            event_type = event["event_type"]
            if event_type == "ebook_upload":
                filename = event["event_key"].split(":", 1)[1]
                for version in versions:
                    if version["period"] not in periods or version["statement_scope"] not in scopes:
                        continue
                    if version["source_kind"] == "official_pdf" and version["source_url"].endswith(f"filename={filename}"):
                        status = "verified_linkage" if version["availability_status"] == "verified" else "period_level_only"
                        rationale = ("archive upload record names this exact file and the archived bytes match its size; no correction recorded"
                                     if status == "verified_linkage" else
                                     "archive upload record names this file, but later corrections may have replaced it")
                    elif version["source_kind"] != "official_pdf" and version["filing_version_type"] == json.loads(event["evidence_text"])["version_label"]:
                        status, rationale = "period_level_only", "same period, scope and revision as an archived PDF upload; a different artifact (XBRL), so its own publication time is unproven"
                    else:
                        continue
                    self._insert_link(connection, report, event, version, status, rationale)
                continue
            if event_type not in PERIOD_LEVEL_EVENTS | CORRECTION_EVENTS:
                continue
            for version in versions:
                if version["period"] not in periods or (scopes and version["statement_scope"] not in scopes):
                    continue
                if version["filing_version_type"] not in affects.get(event["event_key"], {version["filing_version_type"]}):
                    continue
                if event_type in PERIOD_LEVEL_EVENTS:
                    status = "period_level_only"
                    rationale = "the notice proves a restated report for this period/scope was filed, not which bytes"
                    if event_type == "restated_annual_reports_filed" and version["document_dated_at"] and event["event_date"] \
                            and version["document_dated_at"] > event["event_date"]:
                        status = "conflicting_evidence"
                        rationale = "artifact's audit-report date is later than the stated filing date"
                else:
                    status = "unverified_linkage"
                    rationale = "a correction of this period's report was announced; the archived artifact may be the corrected or the earlier upload"
                    if event_type == "auditor_opinion_correction" and version["source_kind"] != "official_pdf":
                        has_emphasis = "EmphasizeCertainImportantItem" in self.archive.read(version["raw_storage_path"]).decode("utf-8", "ignore")
                        rationale += ("; this artifact contains the emphasis-of-matter flag the correction added, so it is not the uncorrected upload"
                                      if has_emphasis else "; this artifact lacks the emphasis-of-matter flag")
                self._insert_link(connection, report, event, version, status, rationale)

    @staticmethod
    def _insert_link(connection, report, event, version, status, rationale) -> None:
        report.add("links_inserted", insert_ignore(connection, "publication_evidence_links", {
            "link_id": evidence_id("hpl1", event["event_id"], version["filing_version_id"]),
            "event_id": event["event_id"], "target_kind": "filing_version", "target_id": version["filing_version_id"],
            "period": version["period"], "statement_scope": version["statement_scope"], "link_status": status,
            "rationale": rationale, "created_at": iso(utc_now()),
        }))

    # ------------------------------------------------------- corroboration
    # Which side of a 重編前/重編後 table may vouch for a filing fact: a restated
    # filing's value is only ever dated by the restated (post) disclosure and an
    # original filing's value only by the previously-reported (pre) one.
    FACT_SIDES = {"restated": ("post",), "original": ("pre",)}
    SUMMARY_SIDES = ("pre", "post")

    def _corroborate(self, connection: sqlite3.Connection, ticker: str, report: ImportReport) -> None:
        """Deterministically rebuild value-level availability (derived data, never raw evidence)."""
        comparisons = [dict(row) for row in connection.execute(
            "SELECT * FROM restatement_comparisons WHERE ticker = ? AND canonical_metric IS NOT NULL "
            "AND verification_status = 'verified_official_disclosure'", (ticker,)).fetchall()]
        facts = [dict(row) for row in connection.execute(
            """SELECT f.fact_id, f.fiscal_year, f.metric_code, f.statement_scope, f.value_text,
                      v.statement_scope_evidence, v.filing_version_type
            FROM versioned_financial_facts f JOIN financial_filing_versions v USING (filing_version_id)
            WHERE f.ticker = ?""", (ticker,)).fetchall()]
        summaries = [dict(row) for row in connection.execute(
            "SELECT * FROM official_summary_observations WHERE ticker = ? AND mapping_status = 'mapped' AND statement_scope != 'unknown'",
            (ticker,)).fetchall()]
        rows: dict[str, dict[str, Any]] = {}
        for comparison in comparisons:
            key = (comparison["fiscal_year"], comparison["canonical_metric"], comparison["statement_scope"],
                   comparison["accounting_framework"])
            values = {
                side: Decimal(comparison[f"{side}_value_text"]) * 1000 * comparison["sign_factor"]
                for side in ("pre", "post") if comparison[f"{side}_value_text"] is not None
            }
            for fact in facts:
                framework = "TIFRS" if "tifrs" in (fact["statement_scope_evidence"] or "") else "unknown"
                if (fact["fiscal_year"], fact["metric_code"], fact["statement_scope"], framework) != key:
                    continue
                sides = [side for side in self.FACT_SIDES.get(fact["filing_version_type"], ())
                         if side in values and Decimal(fact["value_text"]) == values[side]]
                if sides:
                    self._availability_row(rows, "versioned_fact", fact["fact_id"], comparison, sides)
            for summary in summaries:
                if (summary["fiscal_year"], summary["canonical_metric"], summary["statement_scope"],
                        summary["accounting_framework"]) != key:
                    continue
                sides = [side for side in self.SUMMARY_SIDES
                         if side in values and Decimal(summary["normalized_value_text"]) == values[side]]
                if sides:
                    self._availability_row(rows, "summary_observation", summary["observation_id"], comparison, sides)
        fact_ids = [f["fact_id"] for f in facts] + [s["observation_id"] for s in summaries]
        existing_for_ticker = {
            row[0] for row in connection.execute(
                f"SELECT availability_id FROM observation_availability WHERE corroborating_kind = 'restatement_comparison' "
                f"AND observation_id IN ({','.join('?' * len(fact_ids))})", fact_ids)
        } if fact_ids else set()
        stale = existing_for_ticker - set(rows)
        if stale:
            connection.executemany("DELETE FROM observation_availability WHERE availability_id = ?", [(i,) for i in sorted(stale)])
        added = 0
        for availability_id, row in sorted(rows.items()):
            if availability_id not in existing_for_ticker:
                added += insert_ignore(connection, "observation_availability", row)
        report.add("corroborations_added", added)
        report.add("corroborations_removed", len(stale))

    @staticmethod
    def _availability_row(rows, kind, observation_id, comparison, sides) -> None:
        side_text = "+".join(sides)
        availability_id = evidence_id("hoa2", kind, observation_id, comparison["comparison_id"], side_text)
        rows[availability_id] = {
            "availability_id": availability_id, "observation_kind": kind, "observation_id": observation_id,
            "available_at": comparison["disclosed_at"],
            "basis": (f"value disclosed in the {side_text}-restatement column of the MOPS notice published "
                      f"{comparison['disclosed_at']} ({comparison['pre_label'] or comparison['post_label']})"),
            "corroborating_kind": "restatement_comparison", "corroborating_id": comparison["comparison_id"],
            "match_detail": f"exact value match ({side_text} side, sign factor {comparison['sign_factor']})",
            "created_at": iso(utc_now()),
        }
