"""Read-only financial/nonfinancial growth comparison for FinTrust.

Inspired by Brazel, Jones & Zimbelman (2009); descriptive comparison only.
No calibrated fraud threshold, risk tier, database, network, or file access.
An upstream official-document verifier must establish source identity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Literal, Sequence
from urllib.parse import urlsplit

METHOD_VERSION = "fintrust_financial_nonfinancial_growth_v1"
METHOD_APPROVAL = "DRAFT_PENDING_METHOD_OWNER_REVIEW"
_ALLOWED_HOSTS = frozenset({
    "mops.twse.com.tw", "mopsov.twse.com.tw", "emops.twse.com.tw", "doc.twse.com.tw",
    "www.twse.com.tw", "www.tpex.org.tw",
})
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_TICKER = re.compile(r"^[0-9]{4,6}$")


@dataclass(frozen=True)
class GrowthEvidence:
    """Candidate evidence, verified and identified by an upstream adapter.

    published_at is public availability, NOT local download or ingestion.
    """
    ticker: str
    fiscal_year: int
    metric: str
    value: str | int | Decimal
    unit: str
    statement_scope: str
    measurement_policy: str
    period_basis: Literal["annual_flow", "year_end_stock", "annual_average"]
    source_url: str
    source_sha256: str
    filing_version_id: str
    published_at: datetime | None
    source_trust: Literal["verified_official_document", "unverified", "demo"]


@dataclass(frozen=True)
class GrowthComparison:
    ticker: str
    fiscal_year: int
    financial_metric: str
    nonfinancial_metric: str
    status: Literal["computed_descriptive", "not_computable"]
    reasons: tuple[str, ...]
    method_version: str = METHOD_VERSION
    method_approval: str = METHOD_APPROVAL
    financial_growth: Decimal | None = None
    nonfinancial_growth: Decimal | None = None
    growth_gap_percentage_points: Decimal | None = None
    evidence: tuple[GrowthEvidence, ...] = field(default_factory=tuple)
    cut_off_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON-safe: Decimal strings, explicit provenance, no probability."""
        return {
            "ticker": self.ticker,
            "fiscal_year": self.fiscal_year,
            "financial_metric": self.financial_metric,
            "nonfinancial_metric": self.nonfinancial_metric,
            "status": self.status,
            "reasons": list(self.reasons),
            "method_version": self.method_version,
            "method_approval": self.method_approval,
            "financial_growth": str(self.financial_growth) if self.financial_growth is not None else None,
            "nonfinancial_growth": str(self.nonfinancial_growth) if self.nonfinancial_growth is not None else None,
            "growth_gap_percentage_points": (
                str(self.growth_gap_percentage_points)
                if self.growth_gap_percentage_points is not None else None
            ),
            "evidence": [
                {
                    "ticker": e.ticker,
                    "fiscal_year": e.fiscal_year,
                    "metric": e.metric,
                    "value": str(e.value),
                    "unit": e.unit,
                    "statement_scope": e.statement_scope,
                    "measurement_policy": e.measurement_policy,
                    "period_basis": e.period_basis,
                    "source_url": e.source_url,
                    "source_sha256": e.source_sha256,
                    "filing_version_id": e.filing_version_id,
                    "published_at": e.published_at.isoformat() if e.published_at else None,
                    "source_trust": e.source_trust,
                } for e in self.evidence
            ],
            "cut_off_at": self.cut_off_at.isoformat() if self.cut_off_at else None,
            "interpretation": "Growth consistency check only; no calibrated threshold or fraud inference.",
            "independent_corroboration": False,
            "fraud_probability": None,
            "risk_tier": None,
        }


def _official_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
        return bool(
            parts.scheme == "https"
            and parts.hostname in _ALLOWED_HOSTS
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and parts.path.startswith("/")
            and not parts.fragment
        )
    except ValueError:
        return False


def _decimal(value: str | int | Decimal) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (TypeError, InvalidOperation, ValueError):
        return None


def _admissibility(
    e: GrowthEvidence, *, ticker: str, cutoff: datetime | None
) -> str | None:
    if e.ticker != ticker:
        return "ticker_mismatch"
    if e.source_trust != "verified_official_document" or not _official_url(e.source_url):
        return "unverified_or_nonofficial_source"
    if not _SHA256.fullmatch(e.source_sha256) or not e.filing_version_id.strip():
        return "incomplete_source_provenance"
    if not e.statement_scope.strip() or not e.unit.strip() or not e.measurement_policy.strip():
        return "missing_measurement_identity"
    if e.published_at is not None and e.published_at.tzinfo is None:
        return "publication_time_not_timezone_aware"
    if cutoff is not None:
        if e.published_at is None:
            return "publication_time_unknown"
        if e.published_at >= cutoff:
            return "source_unavailable_at_cutoff"
    if _decimal(e.value) is None:
        return "invalid_numeric_value"
    return None


def compare_financial_nonfinancial_growth(
    observations: Sequence[GrowthEvidence],
    *,
    ticker: str,
    fiscal_year: int,
    financial_metric: str = "revenue",
    nonfinancial_metric: str = "employees",
    cutoff_at: datetime | None = None,
) -> GrowthComparison:
    """Compare adjacent FY revenue growth vs a related nonfinancial measure.

    Four source observations required. Duplicate rows with identical identity
    are collapsed; distinct versions fail closed, even with the same value.
    Within each metric, units, period basis, scope and measurement policy must
    match across years. Financial and NFM use their own declared period bases.
    """
    if not _TICKER.fullmatch(ticker):
        raise ValueError("ticker must be a 4–6-digit company code")
    if not 1900 <= fiscal_year <= 2100:
        raise ValueError("invalid fiscal year")
    if not financial_metric or not nonfinancial_metric or financial_metric == nonfinancial_metric:
        raise ValueError("two distinct non-empty metrics are required")
    if cutoff_at is not None and cutoff_at.tzinfo is None:
        raise ValueError("cutoff_at must be timezone-aware")

    def unavailable(reason: str) -> GrowthComparison:
        return GrowthComparison(
            ticker=ticker, fiscal_year=fiscal_year,
            financial_metric=financial_metric, nonfinancial_metric=nonfinancial_metric,
            status="not_computable", reasons=(reason,), cut_off_at=cutoff_at,
        )

    selected: list[GrowthEvidence] = []
    for metric in (financial_metric, nonfinancial_metric):
        for year in (fiscal_year - 1, fiscal_year):
            candidates = [
                e for e in observations
                if e.ticker == ticker and e.metric == metric and e.fiscal_year == year
            ]
            if not candidates:
                return unavailable(f"missing:{metric}:{year}")
            for candidate in candidates:
                reason = _admissibility(candidate, ticker=ticker, cutoff=cutoff_at)
                if reason:
                    return unavailable(f"{reason}:{metric}:{year}")
            unique = {
                (e.source_sha256.lower(), e.filing_version_id, e.statement_scope,
                 e.measurement_policy, e.unit, e.period_basis, str(e.value)): e
                for e in candidates
            }
            if len(unique) != 1:
                return unavailable(f"ambiguous_filing_versions:{metric}:{year}")
            selected.append(next(iter(unique.values())))

    financial_prev, financial_curr, nfm_prev, nfm_curr = selected
    for left, right, metric in (
        (financial_prev, financial_curr, financial_metric),
        (nfm_prev, nfm_curr, nonfinancial_metric),
    ):
        if (
            left.unit != right.unit
            or left.period_basis != right.period_basis
            or left.measurement_policy != right.measurement_policy
            or left.statement_scope != right.statement_scope
        ):
            return unavailable(f"incompatible_measurement_basis:{metric}")
    if len({e.statement_scope for e in selected}) != 1:
        return unavailable("incompatible_company_scope")
    if financial_prev.period_basis != "annual_flow":
        return unavailable("financial_measure_not_annual_flow")
    if nfm_prev.period_basis not in ("year_end_stock", "annual_average"):
        return unavailable("nonfinancial_measure_basis_not_supported")

    values = [_decimal(e.value) for e in selected]
    assert all(v is not None for v in values)
    fp, fc, np, nc = values
    if min(fp, fc, np, nc) <= 0:
        return unavailable("nonpositive_growth_input")
    growth_financial = fc / fp - Decimal(1)
    growth_nonfinancial = nc / np - Decimal(1)
    return GrowthComparison(
        ticker=ticker, fiscal_year=fiscal_year,
        financial_metric=financial_metric, nonfinancial_metric=nonfinancial_metric,
        status="computed_descriptive", reasons=(),
        financial_growth=growth_financial,
        nonfinancial_growth=growth_nonfinancial,
        growth_gap_percentage_points=(growth_financial - growth_nonfinancial) * Decimal(100),
        evidence=tuple(selected), cut_off_at=cutoff_at,
    )
