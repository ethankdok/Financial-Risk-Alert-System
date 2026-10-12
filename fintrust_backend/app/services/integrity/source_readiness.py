"""Phase 2–6 source-readiness dashboard data, built from read-only Workbench facts.

This is coverage, not a fraud risk rating and never treats official URL
identity as proof of archived bytes or verified public availability.
"""
from __future__ import annotations

from typing import Any

from app.services.integrity.nfm_evidence_bridge import check_revenue_nfm_strict

VERSION = "fintrust_source_readiness_v1"


def summarize_source_readiness(
    facts: dict[str, Any], *,
    ticker: str,
    frozen_literature_observations: int | None = None,
    frozen_store_reason: str | None = None,
    nfm_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    index = facts.get("index") or {}
    years = sorted({y for (_, y) in index})
    latest = years[-1] if years else None
    needed = [] if latest is None else [latest - 1, latest]
    required_revenue = []
    for year in needed:
        row = index.get(("revenue", year))
        reasons: list[str] = []
        if row is None:
            reasons.append("revenue_fiscal_year_missing")
        else:
            if row.get("source_trust") != "validated_mops_filing":
                reasons.append("official_filing_url_not_validated")
            if not row.get("source_sha256"):
                reasons.append("source_artifact_sha256_missing")
            if row.get("source_document_verified") is not True:
                reasons.append("original_document_bytes_not_verified")
            if not row.get("effective_available_at"):
                reasons.append("official_publication_instant_not_known")
        required_revenue.append({
            "year": year,
            "evidence_id": row.get("evidence_id") if row else None,
            "present": row is not None,
            "source_url_allowlisted": bool(row and row.get("source_trust") == "validated_mops_filing"),
            "official_document_sha256_present": bool(row and row.get("source_sha256")),
            "file_bytes_verified": bool(row and row.get("source_document_verified") is True),
            "publication_instant_available": bool(row and row.get("effective_available_at")),
            "reasons": reasons,
        })
    nfm = [r for r in (nfm_records or []) if r.get("ticker") == ticker]
    nfm_verified = [r for r in nfm
                    if r.get("source_document_verified") is True
                    and r.get("document_identity_verified") is True
                    and r.get("verified_source") is True]
    if latest is None:
        required_revenue.append({
            "year": None, "evidence_id": None, "present": False,
            "source_url_allowlisted": False, "official_document_sha256_present": False,
            "file_bytes_verified": False, "publication_instant_available": False,
            "reasons": ["no_annual_financial_evidence"],
        })
    missing = sorted({
        code for row in required_revenue for code in row["reasons"]
    } | ({"two_years_of_verified_nfm_missing"} if len({
        r.get("fiscal_year") for r in nfm_verified if r.get("fiscal_year") in needed
    }) < 2 else set()) | ({"data_quality_ambiguity_requires_review"} if facts.get("quality") else set()))
    strict = check_revenue_nfm_strict(index, nfm_records or [], ticker=ticker)
    return {
        "method_version": VERSION,
        "ticker": ticker,
        "latest_fiscal_year": latest,
        "annual_fact_years": years,
        "f4_required_revenue_years": required_revenue,
        "unverified_nfm_candidates": len(nfm) - len(nfm_verified),
        "nfm_years_with_attested_documents": sorted({
            r.get("fiscal_year") for r in nfm_verified if isinstance(r.get("fiscal_year"), int)
        }),
        "frozen_literature_observations": frozen_literature_observations,
        "frozen_literature_store_reason": frozen_store_reason,
        "data_quality_findings_count": len(facts.get("quality") or []),
        "excluded_fact_rows": len(facts.get("excluded") or []),
        "f4_data_ready": strict["status"] == "descriptive_gap" and not missing,
        "f4_verification_status": strict["status"],
        "blockers": sorted(set(missing + strict["reasons"])) or (
            [] if needed else ["no_annual_financial_evidence"]
        ),
        "fraud_probability": None,
        "note": "This is a gap checklist, not risk, independent evidence, or approval of a new model. Reported NFM flags require upstream archive audit.",
    }
