"""Strict Phase 2+3 bridge between Phase 1.1 facts and NFM growth evidence.

A validated MOPS *URL* is not proof that source bytes were archived. Phase 1.1
pipeline facts have no source SHA, so genuine current data will remain unavailable
until a verified document/archive adapter provides one. No network or persistence.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.financial_nonfinancial_alignment import (
    GrowthEvidence, METHOD_VERSION, compare_financial_nonfinancial_growth,
)
from app.services.integrity import alignment as al
from app.services.integrity import financial_checks as fc
from app.services.integrity.contracts import (
    FindingFamily, FindingStatus, ImplementationTier, ReviewQueue,
)

BRIDGE_VERSION = "integrity_f4_provenance_bridge_v2"
_FAILURE_STATUSES = {"unverified_or_nonofficial_source", "incomplete_source_provenance"}


def _instant(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str) or "T" not in raw:
        return None  # a publication date alone is not a known instant
    return al.parse_instant(raw)


def _financial_fact(ticker: str, year: int, record: dict[str, Any]) -> GrowthEvidence:
    # The caller cannot turn a URL-only row into a verified document.
    identity = al.mops_filing_identity(record.get("source_url"), ticker=ticker)
    verified = (
        record.get("source_trust") == "validated_mops_filing"
        and record.get("source_document_verified") is True
        and record.get("ticker") == ticker
        and record.get("fiscal_period") == f"{year}FY"
        and record.get("period_type") == "annual"
        and record.get("concept") == "revenue"
        and record.get("scope") == "consolidated"
        and record.get("filing_policy") == "as_filed_own_year"
        and identity.get("recognised") is True
        and identity.get("filing_fiscal_year") == year
        and identity.get("season") == 4
        and identity.get("filing_version") == record.get("filing_version")
    )
    return GrowthEvidence(
        ticker=str(record.get("ticker") or ""),
        fiscal_year=year,
        metric="revenue",
        value=str(record.get("value_twd")),
        unit="TWD",
        statement_scope=str(record.get("scope") or ""),
        measurement_policy=str(record.get("filing_policy") or ""),
        period_basis="annual_flow",
        source_url=str(record.get("source_url") or ""),
        source_sha256=str(record.get("source_sha256") or ""),
        filing_version_id=str(record.get("filing_version") or ""),
        published_at=_instant(record.get("effective_available_at")),
        source_trust=("verified_official_document" if verified else "unverified"),
    )


def _nfm_fact(ticker: str, record: dict[str, Any]) -> GrowthEvidence:
    # An upstream archive adapter must verify the source bytes, issuer and
    # document identity. No user-supplied HTTP/API route populates these flags.
    verified = (
        record.get("verified_source") is True
        and record.get("source_document_verified") is True
        and record.get("document_identity_verified") is True
        and record.get("scale_related") is True
        and record.get("ticker") == ticker
    )
    return GrowthEvidence(
        ticker=str(record.get("ticker") or ""),
        fiscal_year=int(record["fiscal_year"]),
        metric=str(record["measure"]),
        value=str(record.get("value")),
        unit=str(record.get("unit") or ""),
        statement_scope=str(record.get("scope") or ""),
        measurement_policy=str(record.get("measurement_policy") or ""),
        period_basis=record.get("period_basis") or "",  # validated below
        source_url=str(record.get("source_url") or ""),
        source_sha256=str(record.get("source_sha256") or ""),
        filing_version_id=str(record.get("filing_version_id") or ""),
        published_at=_instant(record.get("published_at")),
        source_trust=("verified_official_document" if verified else "unverified"),
    )


def check_revenue_nfm_strict(
    index: dict[tuple[str, int], dict[str, Any]],
    nfm_records: list[dict[str, Any]],
    *,
    ticker: str,
    cutoff_at: datetime | None = None,
) -> dict[str, Any]:
    """Phase 2+3 production F4; Phase 1.1's synthetic-only helper is untouched.

    Current-period-only: never revive a last computable year as a current result.
    This is a calculation bridge, not the missing official archive ingestion.
    """
    common = dict(
        title="營收與非財務指標成長差異（F4，來源驗證版）",
        version=BRIDGE_VERSION,
        tier=ImplementationTier.readiness_only,
        evidence_families=["revenue", "nonfinancial_measure"],
        formula="(Revenue_t / Revenue_t-1 − 1) − (NFM_t / NFM_t-1 − 1)",
        literature_basis="Brazel, Jones & Zimbelman (2009), DOI 10.1111/j.1475-679X.2009.00349.x; "
                         "inspiration, not a replication",
        limitations=[
            *fc.F4_LIMITS,
            "財報 URL 通過 MOPS 連結檢查不代表原始財報檔案已完成 SHA-256 封存核對。",
            "F4 僅在官方文件身分、來源檔 SHA、版本、計量政策、公司範圍與年度齊備時提供描述性數值。",
            "同一發行人提供的非財務指標並非第三方獨立佐證。",
        ],
        not_independent_of=["issuer_self_reported_financial_data"],
    )

    def fail(status: FindingStatus, reason: str, year: int | None) -> dict[str, Any]:
        return fc._finding(
            fc.F4_ID, FindingFamily.financial_consistency, status=status,
            period=f"{year}FY" if year else None,
            reasons=[reason], review_queue=ReviewQueue.insufficient_evidence.value,
            latest_fact_fiscal_year=year, latest_period_status=status.value,
            freshness_status="latest_period_not_computable" if year else "no_computable_period",
            **common,
        )

    latest = fc.latest_fact_year(index)
    if not nfm_records:
        return fail(FindingStatus.unavailable, "no_verified_nonfinancial_measure_series", latest)
    if latest is None:
        return fail(FindingStatus.not_computable, "no_annual_financial_facts", latest)

    selected = [record for record in nfm_records if record.get("ticker") == ticker]
    if len(selected) != len(nfm_records):
        return fail(FindingStatus.not_comparable, "nonfinancial_company_identity_mismatch", latest)
    measures = {str(r.get("measure") or "") for r in selected}
    if "" in measures or len(measures) != 1:
        return fail(FindingStatus.not_comparable, "ambiguous_nonfinancial_measure", latest)
    measure = next(iter(measures))
    if any(r.get("period_basis") not in ("year_end_stock", "annual_average") for r in selected):
        return fail(FindingStatus.not_comparable, "unsupported_nonfinancial_period_basis", latest)
    observations: list[GrowthEvidence] = []
    for year in (latest - 1, latest):
        financial = index.get(("revenue", year))
        if financial is not None:
            observations.append(_financial_fact(ticker, year, financial))
    try:
        for record in selected:
            if isinstance(record.get("fiscal_year"), bool):
                raise ValueError("year must be numeric")
            observations.append(_nfm_fact(ticker, record))
    except (ValueError, TypeError, KeyError):
        return fail(FindingStatus.not_computable, "invalid_nonfinancial_observation", latest)

    result = compare_financial_nonfinancial_growth(
        observations, ticker=ticker, fiscal_year=latest,
        financial_metric="revenue", nonfinancial_metric=measure, cutoff_at=cutoff_at,
    )
    if result.status != "computed_descriptive":
        reason = result.reasons[0] if result.reasons else "not_computable"
        is_identity = any(
            reason.startswith(prefix) for prefix in
            ("ticker_mismatch", "incompatible_", "ambiguous_", "unverified_")
        )
        return fail(FindingStatus.not_comparable if is_identity else FindingStatus.not_computable, reason, latest)

    if result.financial_growth is None or result.nonfinancial_growth is None:
        return fail(FindingStatus.not_computable, "calculation_result_missing", latest)
    diff = result.financial_growth - result.nonfinancial_growth
    return fc._finding(
        fc.F4_ID, FindingFamily.financial_consistency,
        status=FindingStatus.descriptive_gap, tier=ImplementationTier.implemented,
        version=BRIDGE_VERSION, title=common["title"], period=f"{latest}FY",
        evidence_families=common["evidence_families"], formula=common["formula"],
        literature_basis=common["literature_basis"], limitations=common["limitations"],
        not_independent_of=common["not_independent_of"],
        review_queue=None,
        evidence_ids=[index[("revenue", y)]["evidence_id"] for y in (latest - 1, latest)],
        inputs={
            "revenue_t": fc._input(index[("revenue", latest)]),
            "revenue_t_minus_1": fc._input(index[("revenue", latest - 1)]),
            "nfm_measure": measure,
            "nfm_sources": [
                {"year": e.fiscal_year, "unit": e.unit, "source_url": e.source_url,
                 "source_sha256": e.source_sha256, "filing_version_id": e.filing_version_id,
                 "published_at": e.published_at.isoformat() if e.published_at else None}
                for e in result.evidence if e.metric == measure
            ],
        },
        computed={
            "revenue_growth": al.quantize(result.financial_growth),
            "nfm_growth": al.quantize(result.nonfinancial_growth),
            "growth_difference": al.quantize(diff),
            "growth_difference_percentage_points": al.quantize(diff * 100, 2),
        },
        heuristic={"version": METHOD_VERSION, "calibrated": False, "threshold": None,
                   "note": "descriptive comparison only; no fraud conclusion"},
        latest_fact_fiscal_year=latest,
        latest_period_status=FindingStatus.descriptive_gap.value,
        freshness_status="current",
    )
