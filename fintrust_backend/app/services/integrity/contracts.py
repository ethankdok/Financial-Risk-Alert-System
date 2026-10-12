"""Typed contracts of the Financial Integrity Workbench (Phase 1).

Every amount leaves the service as a Decimal string. Every enum is closed, so a client can never confuse
"not computable" or "insufficient evidence" with "low risk". Nothing here is a fraud label or probability:
findings are screening / due-diligence items, and ``review_queue`` is a work-queue priority only.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

METHOD_APPROVAL = "DRAFT_PENDING_METHOD_OWNER_REVIEW"
CONTRACT_VERSION = "integrity_workbench_contract_v2"


class ReviewMode(str, Enum):
    CURRENT_REVIEW = "CURRENT_REVIEW"
    STRICT_AS_OF = "STRICT_AS_OF"  # recognised so it can be refused explicitly (409); not served in Phase 1


class Section(str, Enum):
    financial_checks = "financial_checks"
    literature = "literature"
    jsd = "jsd"
    claims = "claims"


ALL_SECTIONS = (Section.financial_checks, Section.literature, Section.jsd, Section.claims)


class FindingStatus(str, Enum):
    descriptive_divergence = "descriptive_divergence"
    within_screening_heuristic = "within_screening_heuristic"
    descriptive_gap = "descriptive_gap"
    supported = "supported"
    conflicting = "conflicting"
    insufficient_evidence = "insufficient_evidence"
    inconclusive = "inconclusive"
    not_computable = "not_computable"
    not_comparable = "not_comparable"
    unavailable = "unavailable"


class FindingFamily(str, Enum):
    model_screening = "model_screening"
    financial_consistency = "financial_consistency"
    source_discrepancy = "source_discrepancy"
    narrative_change = "narrative_change"
    data_quality = "data_quality"


class ReviewQueue(str, Enum):
    requires_verification = "requires_verification"
    monitor = "monitor"
    insufficient_evidence = "insufficient_evidence"
    no_item_triggered = "no_item_triggered"  # NOT "low risk": nothing met a documented work-queue rule


class ImplementationTier(str, Enum):
    implemented = "implemented"
    readiness_only = "readiness_only"
    future = "future"


class Availability(str, Enum):
    available = "available"
    partial = "partial"
    unavailable = "unavailable"
    not_comparable = "not_comparable"
    not_computable = "not_computable"


class Independence(str, Enum):
    """Who stands behind a figure. An issuer's website, presentation and regulatory filing are all the issuer."""

    issuer_self_reported = "issuer_self_reported"
    regulator_published_issuer_data = "regulator_published_issuer_data"
    independent_third_party = "independent_third_party"
    unverified_source = "unverified_source"  # source URL failed validation: no official identity is inferred


class EvidenceRecord(BaseModel):
    """One source-identified input value; missing metadata is listed in ``missing_fields`` instead of guessed."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    ticker: str
    fiscal_period: str
    period_start: str | None
    period_end: str | None
    period_type: Literal["annual", "quarter", "instant", "document", "unknown"]
    document_type: str
    language: str | None
    concept: str
    source_concept: str | None
    value: str | None = Field(description="Decimal string as stored; null for documents")
    unit: str | None
    value_twd: str | None = Field(description="Decimal string normalised to NT$1 when the unit is a known TWD scale")
    scope: Literal["consolidated", "individual", "unknown", "not_applicable"]
    scope_basis: str
    filing_version: str | None
    filing_policy: str | None
    issuer: str | None
    publisher: str | None
    independence: Independence
    source_sha256: str | None
    source_identity: str
    source_url: str | None
    locator: dict[str, Any]
    published_at: str | None
    effective_available_at: str | None
    effective_available_at_precision: Literal["exact_instant", "date", "unknown"]
    ingested_at: str | None
    provenance: str
    evidence_family: str
    method_version: str
    pit_eligible: bool
    pit_reason: str
    missing_fields: list[str]
    source_trust: Literal["validated_mops_filing", "untrusted_source", "archived_issuer_document"] = "untrusted_source"
    candidate_evidence_ids: list[str] = Field(default_factory=list)
    selection_policy: str | None = None


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: str
    check_id: str
    family: FindingFamily
    title: str
    status: FindingStatus
    review_queue: ReviewQueue | None
    implementation_tier: ImplementationTier
    method_version: str
    literature_basis: str | None
    period: str | None
    evidence_families: list[str]
    evidence_ids: list[str]
    inputs: dict[str, Any]
    formula: str | None
    computed: dict[str, Any]
    heuristic: dict[str, Any] | None
    series: list[dict[str, Any]] = Field(default_factory=list)
    reasons: list[str]
    legitimate_explanations: list[str]
    limitations: list[str]
    not_independent_of: list[str] = Field(default_factory=list)
    latest_fact_fiscal_year: int | None = None
    latest_period_status: str | None = None
    freshness_status: Literal["current", "latest_period_not_computable", "no_computable_period",
                              "not_applicable"] = "not_applicable"
    last_computable: dict[str, Any] | None = None


class PaperModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    paper: str
    paper_doi: str
    status: Literal["computed", "not_computable"]
    availability: Availability
    raw_score: str | None
    fiscal_year: int | None
    approval_status: str
    component_coverage: dict[str, int]
    missing_input_count: int
    missing_metrics: list[str]
    missing_reasons: list[str]
    pipeline_fact_availability: list[dict[str, Any]]
    shares_inputs_with: list[str]
    limitations: list[str]


class ClaimCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str
    statement: dict[str, Any]
    source_verification: dict[str, Any]
    normalized_claim: str
    normalization: str
    verdict: FindingStatus
    reason_code: str
    parsed_claim: dict[str, Any] | None
    evidence: list[dict[str, Any]]
    corroboration: dict[str, Any]
    limitations: list[str]
    precision_check: dict[str, Any] | None = None
    quote_extraction: dict[str, Any] | None = None


class DataShift(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["comparable", "not_comparable", "unavailable", "quality_insufficient", "method_unavailable"]
    reason: str | None
    period_1: str | None
    period_2: str | None
    document_type: str | None
    language: str | None
    compatibility_checks: dict[str, bool | None]
    metrics: dict[str, str] | None
    calibration_status: Literal["calibrated", "uncalibrated", "not_evaluated"]
    drift_level: str | None
    calibration: dict[str, Any]
    source_documents: list[dict[str, Any]]
    method: dict[str, Any]
    limitations: list[str]
    warning: str


class AssessmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(..., pattern=r"^\d{4,6}$")
    review_mode: ReviewMode = ReviewMode.CURRENT_REVIEW
    persist: Literal[False] = Field(False, description="Preview only; persisting is not offered (false is the only value)")
    sections: list[Section] = Field(default_factory=lambda: list(ALL_SECTIONS), min_length=1, max_length=4)
