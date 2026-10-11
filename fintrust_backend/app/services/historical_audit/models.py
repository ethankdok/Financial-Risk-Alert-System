from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


PARSER_VERSION = "historical-xbrl-1.0"
FILING_VERSION_KEY = "hfv1"
FACT_KEY = "hff1"

# Taiwan has observed UTC+8 without DST since 1979; a fixed offset avoids a
# tzdata dependency on Windows runtimes.
TAIPEI = timezone(timedelta(hours=8), "Asia/Taipei")

Market = Literal["TWSE", "TPEX"]
StatementScope = Literal["consolidated", "individual", "unknown"]
FilingVersionType = Literal["original", "restated", "unknown_revision"]
AvailabilityStatus = Literal["verified", "unverified"]
ValidationStatus = Literal[
    "validated", "validated_with_warnings", "quarantined", "extraction_pending"
]
QualityStatus = Literal["accepted", "warning"]
YearStatus = Literal[
    "available",
    "filing_not_found",
    "source_unavailable",
    "source_invalid_content",
    "parse_failed",
    "quarantined",
    "pending_verification",
    "not_in_manifest",
]
SourceStrategy = Literal["mops_t164sb01", "manifest", "archive"]
VersionPolicy = Literal["all", "latest_available", "earliest_available", "original_only"]

# source_kind describes the evidence format and origin, never its revision status.
SourceKind = Literal[
    "mops_xbrl_instance",
    "mops_inline_xbrl",
    "mops_xbrl_zip",
    "official_pdf",
    "test_fixture",
]

CORE_FIELDS = (
    "revenue",
    "cost_of_goods_sold",
    "gross_profit",
    "operating_income",
    "net_income",
    "accounts_receivable",
    "inventory",
    "current_assets",
    "total_assets",
    "current_liabilities",
    "total_liabilities",
    "equity",
    "operating_cash_flow",
    "investing_cash_flow",
    "capital_expenditure",
    "eps",
    "cash_and_cash_equivalents",
)
SUPPLEMENTARY_FIELDS = ("research_and_development_expense",)
CANONICAL_FIELDS = CORE_FIELDS + SUPPLEMENTARY_FIELDS

INSTANT_FIELDS = frozenset({
    "accounts_receivable",
    "inventory",
    "current_assets",
    "total_assets",
    "current_liabilities",
    "total_liabilities",
    "equity",
    "cash_and_cash_equivalents",
})
STATEMENT_TYPE_BY_FIELD = {
    **{field: "balance_sheet" for field in INSTANT_FIELDS},
    "operating_cash_flow": "cash_flow",
    "investing_cash_flow": "cash_flow",
    "capital_expenditure": "cash_flow",
}


def statement_type_for(field: str) -> str:
    return STATEMENT_TYPE_BY_FIELD.get(field, "income_statement")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Historical timestamps must carry an explicit timezone.")
    return value.astimezone(timezone.utc)


def iso(value: datetime | None) -> str | None:
    return to_utc(value).isoformat() if value is not None else None


def parse_timestamp(value: Any) -> datetime | None:
    """Parse an explicit timestamp. A bare date is not a publication time and is rejected."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return to_utc(value)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return to_utc(parsed)


def as_of_cutoff(value: date | datetime | str) -> datetime:
    """Exclusive UTC cutoff for an as-of query.

    A date means "everything public by the end of that day in Taipei"; a
    datetime is used as given (inclusive) and must carry a timezone.
    """
    if isinstance(value, str):
        text = value.strip()
        if len(text) == 10:
            value = date.fromisoformat(text)
        else:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        return to_utc(value) + timedelta(microseconds=1)
    next_day = datetime.combine(value + timedelta(days=1), time.min, tzinfo=TAIPEI)
    return next_day.astimezone(timezone.utc)


def stable_hash(*parts: object) -> str:
    encoded = json.dumps([str(part) for part in parts], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def filing_version_id(ticker: str, period: str, statement_scope: str, content_hash: str) -> str:
    """Deterministic identity of one immutable source artifact for one filing period.

    Identical bytes always resolve to the same version; any byte difference
    yields a distinct version. A distinct version is not, by itself, evidence
    of an official restatement.
    """
    return f"{FILING_VERSION_KEY}_" + stable_hash(
        FILING_VERSION_KEY, ticker, period, statement_scope, content_hash
    )[:32]


def fact_id(
    version_id: str, metric_code: str, period: str, statement_scope: str, unit: str
) -> str:
    return f"{FACT_KEY}_" + stable_hash(
        FACT_KEY, version_id, metric_code, period, statement_scope, unit
    )[:32]


def decimal_text(value: Any) -> str:
    """Canonical fixed-point text of an exact decimal (never exponent notation).

    ``str(Decimal)`` renders scaled iXBRL values such as ``Decimal("1525265").scaleb(3)`` as ``1.525265E+9``;
    ``format(value, "f")`` gives ``1525265000`` and equals ``str`` for every non-exponent value.
    """
    from decimal import Decimal

    return format(value if isinstance(value, Decimal) else Decimal(str(value)), "f")


def annual_period(fiscal_year: int) -> str:
    return f"{fiscal_year}FY"


class HistoricalAuditCase(BaseModel):
    case_id: str
    ticker: str
    company_name: str
    legal_name: str | None = None
    english_name: str | None = None
    market: Market
    default_start_year: int
    default_end_year: int
    priority_period: str | None = None
    registration_basis: str
    notes: list[str] = Field(default_factory=list)
    # Archived research coverage (may extend beyond the priority event period that the CLI defaults use).
    coverage_start_year: int | None = None
    coverage_end_year: int | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.coverage_start_year is None:
            self.coverage_start_year = self.default_start_year
        if self.coverage_end_year is None:
            self.coverage_end_year = self.default_end_year
        if not self.coverage_start_year <= self.default_start_year <= self.default_end_year <= self.coverage_end_year:
            raise ValueError("the priority event period must lie within the research coverage")


class ManifestDocument(BaseModel):
    """One official document named by a case manifest. Unknown stays None."""

    period: str
    source_kind: SourceKind
    source_url: str | None = None
    local_path: str | None = None
    statement_scope: StatementScope = "unknown"
    filing_version_type: FilingVersionType = "unknown_revision"
    source_published_at: datetime | None = None
    available_at: datetime | None = None
    availability_basis: str | None = None
    verification_evidence: list[str] = Field(default_factory=list)


class CaseManifest(BaseModel):
    manifest_version: Literal[1] = 1
    ticker: str
    case_id: str | None = None
    documents: list[ManifestDocument] = Field(default_factory=list)


class YearOutcome(BaseModel):
    ticker: str
    fiscal_year: int
    period: str
    status: YearStatus
    source_kind: str | None = None
    source_url: str | None = None
    downloaded_at: datetime | None = None
    content_hash: str | None = None
    raw_storage_path: str | None = None
    parser_status: str | None = None
    filing_version_id: str | None = None
    filing_version_type: FilingVersionType | None = None
    new_version: bool = False
    publication_verification_status: AvailabilityStatus | None = None
    document_dated_at: str | None = None
    statement_scope: StatementScope | None = None
    normalized_fact_count: int = 0
    facts_inserted: int = 0
    core_fields_found: list[str] = Field(default_factory=list)
    core_fields_missing: list[str] = Field(default_factory=list)
    persistence_status: Literal["persisted", "unchanged", "not_persisted", "dry_run"] = "not_persisted"
    validation_status: ValidationStatus | None = None
    quarantine_reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None

    @property
    def core_field_coverage(self) -> str:
        return f"{len(self.core_fields_found)}/{len(CORE_FIELDS)}"


class BackfillRunResult(BaseModel):
    run_id: str
    ticker: str
    start_year: int
    end_year: int
    source_strategy: SourceStrategy
    dry_run: bool
    database_path: str
    archive_path: str
    started_at: datetime
    completed_at: datetime | None = None
    status: Literal["running", "completed", "partial", "failed", "dry_run"]
    years: list[YearOutcome] = Field(default_factory=list)
    plan: list[dict[str, Any]] = Field(default_factory=list)
