"""Range-based historical backfill: acquisition → archive → versioning → QA → persistence.

This path never calls FinancialIngestionPipeline.refresh_company(), the latest
TWSE services, the AI/LLM layer or any snapshot writer.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.services.historical_audit.archive import RawEvidenceArchive, sha256_hex
from app.services.historical_audit.case_registry import CASES_DIR, get_case
from app.services.historical_audit.models import (
    CORE_FIELDS,
    BackfillRunResult,
    ManifestDocument,
    SourceStrategy,
    YearOutcome,
    annual_period,
    decimal_text,
    fact_id,
    filing_version_id,
    iso,
    utc_now,
)
from app.services.historical_audit.normalization import normalize_annual_filing
from app.services.historical_audit.repository import FilingVersionRecord, HistoricalAuditRepository
from app.services.historical_audit.sources import (
    FetchResult,
    OfficialSourceFetcher,
    load_manifest,
    mops_annual_url,
)
from app.services.historical_audit.xbrl_document import XbrlDocumentError, detect_format, parse_xbrl_document


MAX_YEAR_SPAN = 30
_XBRL_FORMATS = ("xbrl_instance", "inline_xbrl", "zip")
_SOURCE_KIND_BY_FORMAT = {
    "xbrl_instance": "mops_xbrl_instance",
    "inline_xbrl": "mops_inline_xbrl",
    "zip": "mops_xbrl_zip",
    "pdf": "official_pdf",
}


@dataclass
class SourceDocument:
    """Acquired bytes plus the provenance claims that accompany them."""

    period: str
    fiscal_year: int
    content: bytes
    source_kind: str
    source_url: str | None
    retrieved_at: str
    retrieval_metadata: dict[str, Any]
    declared_scope: str = "unknown"
    declared_version_type: str = "unknown_revision"
    source_published_at: str | None = None
    available_at: str | None = None
    availability_basis: str | None = None
    verification_evidence: list[str] = field(default_factory=list)
    annotation_source: str = "mops_t164sb01"


def validate_year_range(start_year: int, end_year: int) -> list[int]:
    if start_year > end_year:
        raise ValueError("start_year must not be after end_year.")
    if start_year < 1990 or end_year > date.today().year:
        raise ValueError("Year range is outside the supported historical window.")
    if end_year - start_year + 1 > MAX_YEAR_SPAN:
        raise ValueError(f"A single backfill is bounded to {MAX_YEAR_SPAN} fiscal years.")
    return list(range(start_year, end_year + 1))


def classify_version(document, fiscal_year: int) -> tuple[str, list[str], list[str]]:
    """Revision status from evidence inside the filing itself.

    `restated` requires both an explicit restated-statements phrase in the audit
    report and an audit report date after the normal annual filing window.
    Nothing here can establish `original`; absent markers stay unknown.
    """
    markers = document.restatement_evidence()
    audit_date = document.audit_report_date()
    warnings: list[str] = []
    if markers and audit_date and audit_date > date(fiscal_year + 1, 6, 30):
        evidence = [
            f"audit report date {audit_date.isoformat()} is after the annual filing window for {fiscal_year}FY",
            *markers,
        ]
        return "restated", evidence, warnings
    if markers:
        warnings.append("restatement wording present but audit report date is within the normal filing window; revision status left unknown")
    return "unknown_revision", [], warnings


class HistoricalBackfillService:
    def __init__(
        self,
        *,
        repository: HistoricalAuditRepository,
        archive: RawEvidenceArchive,
        fetcher: OfficialSourceFetcher | None = None,
        cases_directory: Path = CASES_DIR,
        concurrency: int = 1,
    ) -> None:
        if not 1 <= concurrency <= 3:
            raise ValueError("concurrency must be between 1 and 3 for official sources.")
        self.repository = repository
        self.archive = archive
        self.fetcher = fetcher
        self.cases_directory = cases_directory
        self.concurrency = concurrency

    # ------------------------------------------------------------------ run
    async def run(
        self,
        ticker: str,
        start_year: int,
        end_year: int,
        *,
        source_strategy: SourceStrategy = "mops_t164sb01",
        manifest_path: str | Path | None = None,
        dry_run: bool = False,
    ) -> BackfillRunResult:
        years = validate_year_range(start_year, end_year)
        case = get_case(ticker, self.cases_directory)
        manifest_documents: dict[int, list[ManifestDocument]] = {}
        manifest_root: Path | None = None
        if source_strategy == "manifest":
            if manifest_path is None:
                raise ValueError("source_strategy=manifest requires a manifest path.")
            manifest, manifest_root = load_manifest(manifest_path)
            if manifest.ticker != case.ticker:
                raise ValueError("Manifest ticker does not match the requested case.")
            for document in manifest.documents:
                if document.period.endswith("FY") and document.period[:4].isdigit():
                    manifest_documents.setdefault(int(document.period[:4]), []).append(document)

        result = BackfillRunResult(
            run_id=uuid4().hex,
            ticker=case.ticker,
            start_year=start_year,
            end_year=end_year,
            source_strategy=source_strategy,
            dry_run=dry_run,
            database_path=str(self.repository.database_path),
            archive_path=str(self.archive.root),
            started_at=utc_now(),
            status="dry_run" if dry_run else "running",
        )
        if dry_run:
            result.plan = [self._plan_year(case.ticker, year, source_strategy, manifest_documents) for year in years]
            result.completed_at = utc_now()
            return result

        if source_strategy == "mops_t164sb01" and self.fetcher is None:
            self.fetcher = OfficialSourceFetcher()
        self.repository.register_case(case)
        self.repository.save_run(self._run_row(result))

        semaphore = asyncio.Semaphore(self.concurrency)

        async def one_year(year: int) -> list[YearOutcome]:
            async with semaphore:
                try:
                    return await self._process_year(
                        result.run_id, case.ticker, year, source_strategy,
                        manifest_documents.get(year, []), manifest_root,
                    )
                except Exception as exc:  # per-year isolation
                    outcome = YearOutcome(
                        ticker=case.ticker, fiscal_year=year, period=annual_period(year),
                        status="parse_failed", error=f"{type(exc).__name__}: {exc}",
                    )
                    self._record(result.run_id, outcome)
                    return [outcome]

        for outcomes in await asyncio.gather(*(one_year(year) for year in years)):
            result.years.extend(outcomes)
        result.years.sort(key=lambda outcome: (outcome.fiscal_year, outcome.filing_version_id or ""))
        available_years = {outcome.fiscal_year for outcome in result.years if outcome.status == "available"}
        result.status = (
            "completed" if available_years == set(years)
            else "partial" if available_years
            else "failed"
        )
        result.completed_at = utc_now()
        self.repository.save_run(self._run_row(result))
        return result

    @staticmethod
    def _run_row(result: BackfillRunResult) -> dict[str, Any]:
        return {
            "run_id": result.run_id,
            "ticker": result.ticker,
            "start_year": result.start_year,
            "end_year": result.end_year,
            "source_strategy": result.source_strategy,
            "status": result.status,
            "started_at": iso(result.started_at),
            "completed_at": iso(result.completed_at),
            "summary": {
                "years": [
                    {"fiscal_year": y.fiscal_year, "status": y.status, "filing_version_id": y.filing_version_id,
                     "facts_inserted": y.facts_inserted, "new_version": y.new_version}
                    for y in result.years
                ],
            },
        }

    def _plan_year(self, ticker: str, year: int, strategy: str, manifest_documents: dict[int, list[ManifestDocument]]) -> dict[str, Any]:
        period = annual_period(year)
        existing = []
        if self.repository.is_initialized():
            existing = [row["filing_version_id"] for row in self.repository.list_filing_versions(ticker, year, year)]
        plan: dict[str, Any] = {"fiscal_year": year, "roc_year": year - 1911, "period": period, "existing_versions": existing}
        if strategy == "mops_t164sb01":
            plan["source_url"] = mops_annual_url(ticker, year)
        elif strategy == "manifest":
            plan["documents"] = [doc.model_dump(mode="json") for doc in manifest_documents.get(year, [])]
        else:
            plan["reprocess_versions"] = existing
        return plan

    # ------------------------------------------------------------ per year
    async def _process_year(
        self,
        run_id: str,
        ticker: str,
        year: int,
        strategy: str,
        manifest_documents: list[ManifestDocument],
        manifest_root: Path | None,
    ) -> list[YearOutcome]:
        period = annual_period(year)
        if strategy == "mops_t164sb01":
            assert self.fetcher is not None
            url = mops_annual_url(ticker, year)
            fetched = await self.fetcher.fetch(url, expect=_XBRL_FORMATS)
            if fetched.status != "ok":
                return [self._fetch_failure(run_id, ticker, year, fetched)]
            assert fetched.content is not None and fetched.retrieved_at is not None
            document = SourceDocument(
                period=period, fiscal_year=year, content=fetched.content,
                source_kind=_SOURCE_KIND_BY_FORMAT[fetched.detected_format or ""],
                source_url=url, retrieved_at=iso(fetched.retrieved_at) or "",
                retrieval_metadata=fetched.metadata(),
            )
            return [self._process_document(run_id, ticker, document)]

        if strategy == "manifest":
            if not manifest_documents:
                outcome = YearOutcome(
                    ticker=ticker, fiscal_year=year, period=period, status="not_in_manifest",
                    error="The case manifest names no document for this fiscal year; this is not evidence that no filing exists.",
                )
                self._record(run_id, outcome)
                return [outcome]
            outcomes = []
            for item in manifest_documents:
                outcomes.append(await self._process_manifest_document(run_id, ticker, year, item, manifest_root))
            return outcomes

        # strategy == "archive": re-verify and reprocess archived bytes; no network.
        outcomes = []
        for row in self.repository.list_filing_versions(ticker, year, year):
            content = self.archive.read(row["raw_storage_path"])
            document = SourceDocument(
                period=row["period"], fiscal_year=year, content=content,
                source_kind=row["source_kind"], source_url=row["source_url"],
                retrieved_at=row["retrieved_at"],
                retrieval_metadata={"reprocessed_from_archive": row["raw_storage_path"]},
                declared_scope=row["statement_scope"],
                annotation_source="archive_reprocess",
            )
            outcomes.append(self._process_document(run_id, ticker, document, archive_existing=False))
        if not outcomes:
            outcome = YearOutcome(ticker=ticker, fiscal_year=year, period=period, status="filing_not_found",
                                  error="No archived artifact for this fiscal year.")
            self._record(run_id, outcome)
            outcomes.append(outcome)
        return outcomes

    async def _process_manifest_document(
        self, run_id: str, ticker: str, year: int, item: ManifestDocument, root: Path | None
    ) -> YearOutcome:
        period = annual_period(year)
        if item.local_path:
            path = (root or Path(".")) / item.local_path
            content = path.read_bytes()
            retrieval = {"imported_from": item.local_path, "source_url": item.source_url}
            retrieved_at = iso(utc_now()) or ""
        elif item.source_url:
            if self.fetcher is None:
                self.fetcher = OfficialSourceFetcher()
            expect = ("pdf",) if item.source_kind == "official_pdf" else _XBRL_FORMATS
            fetched = await self.fetcher.fetch(item.source_url, expect=expect)
            if fetched.status != "ok":
                return self._fetch_failure(run_id, ticker, year, fetched)
            content = fetched.content or b""
            retrieval = fetched.metadata()
            retrieved_at = iso(fetched.retrieved_at) or ""
        else:
            raise ValueError(f"{item.period}: manifest document needs local_path or source_url.")
        document = SourceDocument(
            period=period, fiscal_year=year, content=content, source_kind=item.source_kind,
            source_url=item.source_url, retrieved_at=retrieved_at, retrieval_metadata=retrieval,
            declared_scope=item.statement_scope, declared_version_type=item.filing_version_type,
            source_published_at=iso(item.source_published_at),
            available_at=iso(item.available_at), availability_basis=item.availability_basis,
            verification_evidence=list(item.verification_evidence), annotation_source="case_manifest",
        )
        return self._process_document(run_id, ticker, document)

    def _fetch_failure(self, run_id: str, ticker: str, year: int, fetched: FetchResult) -> YearOutcome:
        raw_path = content_hash = None
        if fetched.content:
            # The failure body is kept as evidence of what the source actually returned.
            stored = self.archive.store(
                ticker=ticker, period=f"{annual_period(year)}/source_responses",
                content=fetched.content, detected_format=None, retrieval=fetched.metadata(),
            )
            raw_path, content_hash = stored.relative_path, stored.content_hash
        outcome = YearOutcome(
            ticker=ticker, fiscal_year=year, period=annual_period(year), status=fetched.status,
            source_url=fetched.url, downloaded_at=fetched.retrieved_at, content_hash=content_hash,
            raw_storage_path=raw_path, error=fetched.error,
        )
        self._record(run_id, outcome)
        return outcome

    def _process_document(
        self, run_id: str, ticker: str, source: SourceDocument, *, archive_existing: bool = True
    ) -> YearOutcome:
        detected = detect_format(source.content)
        content_hash = sha256_hex(source.content)
        if archive_existing:
            stored = self.archive.store(
                ticker=ticker, period=source.period, content=source.content,
                detected_format=detected, retrieval=source.retrieval_metadata,
            )
            raw_path = stored.relative_path
        else:
            raw_path = self.archive.path_for(ticker, source.period, content_hash, detected).relative_to(self.archive.root).as_posix()

        outcome = YearOutcome(
            ticker=ticker, fiscal_year=source.fiscal_year, period=source.period, status="available",
            source_kind=source.source_kind, source_url=source.source_url,
            downloaded_at=source.retrieved_at or None, content_hash=content_hash, raw_storage_path=raw_path,
        )
        warnings: list[str] = []
        version_type, type_evidence = source.declared_version_type, list(source.verification_evidence)
        scope, scope_evidence = source.declared_scope, ("declared by case manifest" if source.declared_scope != "unknown" else None)
        validation_status, quarantine_reason = "validated", None
        facts = []
        diagnostics: dict[str, Any] = {"retrieval": source.retrieval_metadata}
        document_dated_at = None

        if source.source_kind == "official_pdf" or detected == "pdf":
            if detected != "pdf":
                validation_status, quarantine_reason = "quarantined", "declared_pdf_is_not_pdf"
                outcome.status = "quarantined"
            else:
                validation_status = "extraction_pending"
                outcome.status = "pending_verification"
                warnings.append("Official PDF archived; financial fact extraction is pending and no values were derived.")
            outcome.parser_status = "not_parsed_pdf"
        else:
            try:
                parsed = parse_xbrl_document(source.content)
            except XbrlDocumentError as exc:
                parsed = None
                validation_status, quarantine_reason = "quarantined", f"parse_failed:{exc}"
                outcome.status, outcome.parser_status = "parse_failed", "failed"
            if parsed is not None:
                outcome.parser_status = f"parsed:{parsed.document_format}"
                audit_date = parsed.audit_report_date()
                document_dated_at = audit_date.isoformat() if audit_date else None
                doc_scope, doc_scope_evidence = parsed.statement_scope()
                if doc_scope != "unknown":
                    if scope not in ("unknown", doc_scope):
                        validation_status, quarantine_reason = "quarantined", f"statement_scope_conflict:declared={scope},document={doc_scope}"
                    scope, scope_evidence = doc_scope, doc_scope_evidence
                auto_type, auto_evidence, type_warnings = classify_version(parsed, source.fiscal_year)
                warnings.extend(type_warnings)
                if auto_type != "unknown_revision":
                    if version_type not in ("unknown_revision", auto_type):
                        validation_status, quarantine_reason = "quarantined", f"version_type_conflict:declared={version_type},document={auto_type}"
                    version_type, type_evidence = auto_type, auto_evidence + type_evidence
                if quarantine_reason is None:
                    normalized = normalize_annual_filing(parsed, ticker=ticker, fiscal_year=source.fiscal_year)
                    diagnostics.update(normalized.diagnostics)
                    warnings.extend(normalized.warnings)
                    validation_status, quarantine_reason = normalized.validation_status, normalized.quarantine_reason
                    outcome.core_fields_found = [name for name in CORE_FIELDS if name in normalized.fields_found]
                    outcome.core_fields_missing = [name for name in CORE_FIELDS if name not in normalized.fields_found]
                    if quarantine_reason is None:
                        facts = normalized.facts
                if quarantine_reason is not None:
                    outcome.status = "quarantined"

        version_id = filing_version_id(ticker, source.period, scope, content_hash)
        availability_status = "verified" if source.available_at and source.availability_basis and source.verification_evidence else "unverified"
        record = FilingVersionRecord(
            filing_version_id=version_id, ticker=ticker, period=source.period,
            fiscal_year=source.fiscal_year, statement_scope=scope,
            statement_scope_evidence=scope_evidence, filing_version_type=version_type,
            version_type_evidence=type_evidence, source_kind=source.source_kind,
            source_url=source.source_url, source_published_at=source.source_published_at,
            available_at=source.available_at if availability_status == "verified" else None,
            availability_status=availability_status, availability_basis=source.availability_basis,
            verification_evidence=list(source.verification_evidence),
            document_dated_at=document_dated_at, retrieved_at=source.retrieved_at,
            content_hash=content_hash, content_length=len(source.content), detected_format=detected,
            raw_storage_path=raw_path, validation_status=validation_status,
            quarantine_reason=quarantine_reason, warnings=warnings, diagnostics=diagnostics,
        )
        rows = [
            {
                "fact_id": fact_id(version_id, fact.metric_code, fact.period, scope, fact.unit),
                "filing_version_id": version_id, "ticker": ticker, "period": fact.period,
                "fiscal_year": source.fiscal_year, "metric_code": fact.metric_code,
                "value": float(fact.value), "value_text": decimal_text(fact.value), "unit": fact.unit,
                "source_unit_ref": fact.source_unit_ref, "decimals": fact.decimals,
                "statement_type": fact.statement_type, "statement_scope": scope,
                "taxonomy_concept": fact.taxonomy_concept, "context_ref": fact.context_ref,
                "mapping_method": fact.mapping_method, "source_kind": source.source_kind,
                "source_url": source.source_url, "available_at": record.available_at,
                "quality_status": fact.quality_status, "quality_notes": fact.quality_notes,
            }
            for fact in facts
        ]
        with self.repository.connect() as connection:
            upsert = self.repository.upsert_filing_version(connection, record, annotation_source=source.annotation_source)
            if not upsert.created and upsert.stored_parser_version != record.parser_version:
                warnings.append(
                    f"stored version parsed by {upsert.stored_parser_version}; facts were not rewritten by {record.parser_version}"
                )
            inserted = self.repository.insert_facts(connection, rows) if upsert.created else 0
            stored = connection.execute(
                "SELECT filing_version_type, available_at, availability_status, validation_status, quarantine_reason "
                "FROM financial_filing_versions WHERE filing_version_id = ?", (version_id,),
            ).fetchone()
            outcome.filing_version_id = version_id
            outcome.new_version = upsert.created
            outcome.filing_version_type = stored["filing_version_type"]
            outcome.publication_verification_status = stored["availability_status"]
            outcome.statement_scope = scope
            outcome.document_dated_at = document_dated_at
            outcome.validation_status = stored["validation_status"]
            outcome.quarantine_reason = stored["quarantine_reason"]
            outcome.normalized_fact_count = len(rows)
            outcome.facts_inserted = inserted
            outcome.persistence_status = "persisted" if upsert.created or upsert.annotations else "unchanged"
            outcome.warnings = warnings + [f"classification_conflict: {item}" for item in upsert.conflicts]
            self.repository.record_attempt(connection, run_id, outcome.model_dump(mode="json"))
        return outcome

    def _record(self, run_id: str, outcome: YearOutcome) -> None:
        with self.repository.connect() as connection:
            self.repository.record_attempt(connection, run_id, outcome.model_dump(mode="json"))
