"""Read-only candidates from archived MOPS annual-report page text.

Candidate extraction is *not* official verification. It does not prove the
PDF's issuer, reporting period, page-text correspondence, company scope,
headcount measurement method or publication time. Never feed its output
directly to check_revenue_nfm_strict as verified_source.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re
from typing import Any, Sequence

EXTRACTOR_VERSION = "fintrust_nfm_employees_candidate_v1"
_MAX_PAGES = 2000
_MAX_CHARS = 500_000
_PATTERN = re.compile(
    r"(?:員工(?:總)?人數|期末員工(?:人數)?|年底員工(?:人數)?|"
    r"number\s+of\s+employees|total\s+employees|employees\s+at\s+year[ -]?end)"
    r"\s*(?:[:：=]|為|共|合計)?\s*"
    r"(?P<count>[0-9][0-9,]{0,14})\s*(?:人|名|persons|people|employees)?",
    re.IGNORECASE,
)
_TICKER = re.compile(r"^[0-9]{4,6}$")
_SHA = re.compile(r"^[a-fA-F0-9]{64}$")
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?:\s*年|\s*FY)?(?!\d)")
_MAX_MATCHES_PER_PAGE = 20


def scan_employee_candidates(
    pages: Sequence[dict[str, Any]],
    *,
    ticker: str,
    expected_fiscal_year: int,
    source_sha256: str,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Produce review candidates with literal page excerpts and no attestations."""
    if not _TICKER.fullmatch(ticker) or not 1990 <= expected_fiscal_year <= 2100:
        raise ValueError("invalid company / fiscal year")
    if not _SHA.fullmatch(source_sha256):
        raise ValueError("a SHA-256 of preserved original bytes is required")
    if len(pages) > _MAX_PAGES:
        raise ValueError("page count exceeds bounded extraction limit")

    out: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    used: set[int] = set()
    for row in pages:
        if not isinstance(row, dict):
            rejected.append({"page": None, "reason": "malformed_page_record"})
            continue
        raw_page = row.get("page_number", row.get("page"))
        if isinstance(raw_page, bool) or not isinstance(raw_page, int) or raw_page < 1:
            rejected.append({"page": raw_page, "reason": "invalid_page_number"})
            continue
        if raw_page in used:
            rejected.append({"page": raw_page, "reason": "duplicate_page_number"})
            continue
        used.add(raw_page)
        text = row.get("text")
        if not isinstance(text, str) or len(text) > _MAX_CHARS:
            rejected.append({"page": raw_page, "reason": "invalid_or_oversized_text"})
            continue

        for m in list(_PATTERN.finditer(text))[:_MAX_MATCHES_PER_PAGE]:
            raw_number = m.group("count")
            # English tokens and Chinese 人／名 are accepted, but bare numbers
            # next to misleading headings must be reviewed before use.
            if not re.fullmatch(r"\d{1,3}(?:,\d{3})+|\d+", raw_number):
                rejected.append({"page": raw_page, "reason": "invalid_digit_grouping"})
                continue
            try:
                count = Decimal(raw_number.replace(",", ""))
            except InvalidOperation:
                continue
            if count <= 0 or count > Decimal("100000000"):
                rejected.append({"page": raw_page, "reason": "implausible_employee_count"})
                continue
            line_begin = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            if line_end < 0:
                line_end = len(text)
            quote = text[line_begin:line_end].strip()[:320]
            years = sorted({int(v) for v in _YEAR.findall(quote)})
            out.append({
                "ticker": ticker,
                "expected_fiscal_year": expected_fiscal_year,
                "metric": "employees",
                "candidate_value": str(count),
                "unit": "persons",
                "page_number": raw_page,
                "verbatim": quote,
                "year_mentions_in_excerpt": years,
                "source_sha256": source_sha256.lower(),
                "source_url": source_url,
                "status": "candidate_requires_document_period_scope_review",
                "source_document_verified": False,
                "document_identity_verified": False,
                "measurement_policy_verified": False,
                "publication_time_verified": False,
                "eligible_as_f4_input": False,
            })
    return {
        "method_version": EXTRACTOR_VERSION,
        "ticker": ticker,
        "expected_fiscal_year": expected_fiscal_year,
        "page_records": len(pages),
        "candidate_count": len(out),
        "candidates": out,
        "rejected": rejected,
        "verified_official_employee_observations": 0,
        "warning": "Candidates require manual review of page text against original PDF and issuer, scope, fiscal period, definition and official publication.",
    }
