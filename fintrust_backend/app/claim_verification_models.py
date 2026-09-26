"""Canonical contract of POST /api/v1/financial/claims/verify.

The user-facing verdict has exactly three values. Official evidence is always a
list, and every item keeps its own provenance. The detailed legacy verifier
outcome is kept separately in ``verification_detail``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CanonicalVerdict = Literal["supported", "conflicting", "insufficient_evidence"]
ClaimType = Literal[
    "numeric_metric", "percentage_mix", "trend", "company_statement", "operational_metric", "unsupported",
]
EvidenceRelation = Literal["supports", "conflicts", "context"]
EvidenceSourceType = Literal[
    "financial_fact", "financial_metric", "conference_table", "conference_chart",
    "conference_text", "official_announcement",
]

LEGACY_VERDICT_MAP: dict[str, CanonicalVerdict] = {
    "supported": "supported",
    "contradicted": "conflicting",
    "partially_supported": "insufficient_evidence",
    "not_applicable": "insufficient_evidence",
    "insufficient_evidence": "insufficient_evidence",
}


class ClaimVerifyRequest(BaseModel):
    """Accepts the Phase 2 names (company_code, claim) and the legacy aliases (ticker, text)."""

    model_config = ConfigDict(extra="ignore")

    company_code: str | None = Field(default=None, max_length=12)
    claim: str = Field(min_length=2, max_length=5000)
    period: str | None = None
    comparison_period: str | None = None
    tolerance_percentage_points: float = Field(default=2.0, ge=0.0, le=20.0)

    @model_validator(mode="before")
    @classmethod
    def _normalize_aliases(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        if not payload.get("claim") and payload.get("text"):
            payload["claim"] = payload["text"]
        if not payload.get("company_code") and payload.get("ticker"):
            payload["company_code"] = payload["ticker"]
        if isinstance(payload.get("company_code"), str):
            payload["company_code"] = payload["company_code"].strip() or None
        if isinstance(payload.get("claim"), str):
            payload["claim"] = payload["claim"].strip()
        return payload


class StructuredClaim(BaseModel):
    raw_claim: str
    company_code: str | None = None
    company_name: str | None = None
    claim_type: ClaimType
    metric_or_topic: str | None = None
    period: str | None = None
    comparison_period: str | None = None
    value: float | None = None
    value_text: str | None = None
    unit: str | None = None
    direction: str | None = None
    comparator: str | None = None
    keywords: list[str] = Field(default_factory=list)
    extraction_method: Literal["deterministic", "deterministic+gemini"] = "deterministic"
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)
    requires_review: bool = False


class EvidenceComparison(BaseModel):
    claimed_value: float | None = None
    official_value: float | None = None
    difference: float | None = None
    tolerance: float | None = None
    formula: str | None = None


class EvidenceProvenance(BaseModel):
    extraction_method: str | None = None
    source_kind: str | None = None
    supported_by: list[str] = Field(default_factory=list)
    semantic_provider: str | None = None
    mapping_status: str | None = None
    is_demo: bool = False


class ClaimEvidenceItem(BaseModel):
    evidence_id: str
    relation: EvidenceRelation = "context"
    decisive: bool = False
    source_type: EvidenceSourceType
    source_title: str | None = None
    source_date: str | None = None
    document: str | None = None
    source_reference: str | None = None
    page: int | None = None
    region_id: str | None = None
    period: str | None = None
    metric: str | None = None
    label: str | None = None
    value: str | None = None
    unit: str | None = None
    source_text: str | None = None
    verification_status: str
    document_sha256: str | None = None
    comparison: EvidenceComparison | None = None
    provenance: EvidenceProvenance = Field(default_factory=EvidenceProvenance)
    note: str | None = None


class VerificationDetail(BaseModel):
    legacy_verdict: str | None = None
    difference: float | None = None
    tolerance: float | None = None
    calculation: str | None = None
    decisive_supporting: int = 0
    decisive_conflicting: int = 0
    llm_calls: int = 0


class ClaimVerifyResponse(BaseModel):
    request: dict[str, Any]
    structured_claim: StructuredClaim
    verdict: CanonicalVerdict
    reason_code: str
    summary: str
    evidence: list[ClaimEvidenceItem] = Field(default_factory=list)
    verification_detail: VerificationDetail = Field(default_factory=VerificationDetail)
    limitations: list[str] = Field(default_factory=list)
    requires_review: bool = False
