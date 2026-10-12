"""Company / period / scope / unit / version / time alignment for the Integrity Workbench.

All arithmetic is Decimal. A value is only comparable with another when currency, period type, consolidation scope
and filing policy agree; otherwise the caller reports ``not_comparable`` with the exact reasons. Point-in-time
admission (``strict_admissible``) needs a timezone-aware publication instant strictly before an exclusive,
timezone-aware cutoff; a missing or naive timestamp is never assumed to have been available.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from app.services.financial_research.input_snapshot import safe_official_url

ALIGNMENT_VERSION = "integrity_alignment_v1"
TAIPEI = timezone(timedelta(hours=8))
PRECISION = 50
# Units the pipeline writes for New Taiwan dollar amounts, with their scale to NT$1.
TWD_SCALES = {
    "新台幣元": Decimal(1), "元": Decimal(1), "TWD": Decimal(1), "NT$": Decimal(1),
    "新台幣仟元": Decimal(1000), "新台幣千元": Decimal(1000), "仟元": Decimal(1000), "千元": Decimal(1000),
    "新台幣百萬元": Decimal(1_000_000), "百萬元": Decimal(1_000_000),
}
ANNUAL_PERIOD = re.compile(r"^(?P<year>\d{4})FY$")
QUARTER_PERIOD = re.compile(r"^(?P<year>\d{4})Q(?P<q>[1-4])$")
# MOPS t164sb01 (IFRS financial report) download links carry the filing identity in the query string.
MOPS_REPORT_SCOPES = {"C": "consolidated"}
FLOAT64_EXACT_INTEGER_LIMIT = Decimal(2) ** 53


def to_decimal(value: Any) -> Decimal | None:
    """Decimal from a stored value. Floats go through ``repr`` (shortest round-trip), never binary expansion."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def text(value: Decimal | None) -> str | None:
    """Plain decimal notation (no exponent), trailing zeros removed."""
    if value is None:
        return None
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return format(normalized.quantize(Decimal(1)), "f")
    return format(normalized, "f")


def ratio(numerator: Decimal, denominator: Decimal, places: int = 6) -> str:
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return text((numerator / denominator).quantize(Decimal(1).scaleb(-places)))


def quantize(value: Decimal, places: int = 6) -> str:
    return text(value.quantize(Decimal(1).scaleb(-places)))


def twd_scale(unit: str | None) -> Decimal | None:
    return TWD_SCALES.get((unit or "").strip())


def to_twd(value: Decimal | None, unit: str | None) -> Decimal | None:
    scale = twd_scale(unit)
    if value is None or scale is None:
        return None
    with localcontext() as ctx:
        ctx.prec = PRECISION
        return value * scale


def parse_period(period: str) -> dict[str, Any]:
    """``2024FY`` → annual (calendar fiscal year); ``2026Q2`` → quarter. Fiscal-year-end is assumed 12-31 and the
    assumption is stated in ``basis`` (true for every company in the reviewed registry)."""
    annual = ANNUAL_PERIOD.match(period or "")
    if annual:
        year = int(annual["year"])
        return {"period_type": "annual", "year": year, "start": f"{year}-01-01", "end": f"{year}-12-31",
                "basis": "calendar_fiscal_year_assumed_dec31"}
    quarter = QUARTER_PERIOD.match(period or "")
    if quarter:
        year, q = int(quarter["year"]), int(quarter["q"])
        start_month, end_month = 3 * q - 2, 3 * q
        end_day = 31 if end_month in (3, 12) else 30
        return {"period_type": "quarter", "year": year, "quarter": q, "start": f"{year}-{start_month:02d}-01",
                "end": f"{year}-{end_month:02d}-{end_day:02d}", "basis": "calendar_quarter"}
    return {"period_type": "unknown", "year": None, "start": None, "end": None, "basis": "unparsed_period"}


def mops_filing_identity(url: str | None) -> dict[str, Any]:
    """Filing year / season / report scope from a MOPS t164sb01 download URL (ROC year + 1911)."""
    if not url:
        return {"recognised": False}
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if "t164sb01" not in (query.get("functionName") or [""])[0]:
        return {"recognised": False}
    try:
        roc_year = int((query.get("year") or [""])[0])
        season = int((query.get("season") or [""])[0])
    except ValueError:
        return {"recognised": False}
    report_id = (query.get("report_id") or [""])[0]
    return {"recognised": True, "filing_fiscal_year": roc_year + 1911, "season": season, "report_id": report_id,
            "scope": MOPS_REPORT_SCOPES.get(report_id, "unknown"),
            "filing_version": f"mops_t164sb01:{roc_year + 1911}:S{season}:{report_id}:as_retrieved"}


def derive_scope(stored_scope: str | None, source_url: str | None) -> tuple[str, str]:
    """(scope, basis). A stored explicit scope wins; otherwise the MOPS report id; never guessed."""
    stored = (stored_scope or "").strip().lower()
    if stored in ("consolidated", "individual"):
        return stored, "stored_statement_scope"
    identity = mops_filing_identity(source_url)
    if identity.get("recognised") and identity["scope"] != "unknown":
        return identity["scope"], f"mops_report_id_{identity['report_id']}"
    return "unknown", "scope_not_recorded"


def filing_policy(period: str, source_url: str | None) -> str | None:
    """``as_filed_own_year`` when an annual value comes from that year's own Q4/annual filing; a value taken from a
    later filing (a comparative column, possibly restated) gets a different policy and is not mixed."""
    identity = mops_filing_identity(source_url)
    parsed = parse_period(period)
    if not identity.get("recognised") or parsed["period_type"] != "annual":
        return None
    if identity["filing_fiscal_year"] == parsed["year"] and identity["season"] == 4:
        return "as_filed_own_year"
    return f"comparative_from_FY{identity['filing_fiscal_year']}_filing"


def comparability_problems(records: Iterable[dict[str, Any]]) -> list[str]:
    """Reasons a set of evidence records cannot be compared (empty list = comparable)."""
    records = list(records)
    problems: list[str] = []
    for record in records:
        if record.get("value_twd") is None:
            problems.append(f"unit_not_a_known_twd_scale:{record['concept']}:{record['fiscal_period']}:{record.get('unit')}")
        if record.get("is_demo"):
            problems.append(f"demo_fixture_value:{record['concept']}:{record['fiscal_period']}")
    period_types = {record["period_type"] for record in records}
    if len(period_types) > 1:
        problems.append("period_type_mismatch:" + ",".join(sorted(period_types)))
    scopes = {record["scope"] for record in records}
    if "unknown" in scopes:
        problems.append("scope_unknown")
    elif len(scopes) > 1:
        problems.append("scope_mismatch:" + ",".join(sorted(scopes)))
    policies = {record.get("filing_policy") for record in records}
    if None in policies:
        problems.append("filing_policy_unknown")
    elif len(policies) > 1:
        problems.append("filing_policy_mismatch:" + ",".join(sorted(policies)))
    return sorted(set(problems))


def parse_instant(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def strict_admissible(record: dict[str, Any], cutoff_at: datetime) -> tuple[bool, str]:
    """Point-in-time admission: available strictly before the exclusive cutoff, both instants timezone-aware.

    A date-only publication is treated as available only at the end of that Taipei calendar day.
    """
    if cutoff_at.tzinfo is None or cutoff_at.utcoffset() is None:
        raise ValueError("cutoff_at must be timezone-aware")
    if str(record.get("filing_policy") or "").startswith("comparative_from_") and not record.get("effective_available_at"):
        return False, "later_filing_version_without_publication_time"
    precision = record.get("effective_available_at_precision") or "unknown"
    raw = record.get("effective_available_at")
    if not raw or precision == "unknown":
        return False, "effective_available_at_unknown"
    if precision == "date":
        try:
            day = date.fromisoformat(str(raw)[:10])
        except ValueError:
            return False, "effective_available_at_unparseable"
        available = datetime.combine(day + timedelta(days=1), time(0), tzinfo=TAIPEI)
    else:
        available = parse_instant(raw)
        if available is None:
            return False, "effective_available_at_unparseable"
        if available.tzinfo is None or available.utcoffset() is None:
            return False, "effective_available_at_timezone_unknown"
    if available >= cutoff_at:
        return False, "available_at_or_after_cutoff"
    return True, "available_before_cutoff"


def official_url(url: Any) -> str | None:
    """Only links to the regulators' official hosts leave the service (shared research allowlist)."""
    return safe_official_url(url)


def is_float64_exact(value: Decimal | None) -> bool:
    return value is None or (value == value.to_integral() and abs(value) < FLOAT64_EXACT_INTEGER_LIMIT)
