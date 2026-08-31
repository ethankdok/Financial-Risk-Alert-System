from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


OfficialEvidenceType = Literal["financial_snapshot", "investor_conference", "material_event"]
OfficialEvidenceSourceStatus = Literal[
    "available",
    "metadata_only",
    "needs_manual_review",
    "missing",
    "blocked_by_source",
    "error",
]
OfficialDocumentExtractStatus = Literal[
    "not_attempted",
    "metadata_only",
    "html_preview",
    "document_link_found",
    "text_extracted",
    "download_failed",
    "blocked_by_source",
    "unsupported",
    "seeded_index",
    "error",
]
OfficialDocumentKind = Literal[
    "html",
    "pdf",
    "presentation",
    "spreadsheet",
    "transcript",
    "video",
    "unknown",
]
MaterialEventCategory = Literal[
    "financial_outlook",
    "capacity_or_capex",
    "revenue_or_orders",
    "inventory_or_demand",
    "financing_or_debt",
    "ma_or_investment",
    "operation_disruption",
    "legal_or_penalty",
    "governance",
    "other",
]
OfficialClaimType = Literal[
    "outlook",
    "capacity_or_capex",
    "inventory_or_demand",
    "revenue_or_orders",
    "rd_or_product",
    "cash_flow_or_financing",
    "other",
]


class OfficialSourceLink(BaseModel):
    source_name: str
    source_url: str
    status: OfficialEvidenceSourceStatus = "metadata_only"
    retrieved_at: datetime | None = None
    limitation: str | None = None


class OfficialDisclosureClaim(BaseModel):
    """A conservative, source-grounded claim extracted from an official disclosure."""

    claim_type: OfficialClaimType = "other"
    text: str
    related_metrics: list[str] = Field(default_factory=list)
    evidence_source: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    limitations: list[str] = Field(default_factory=list)


class OfficialDocumentExtractionRequest(BaseModel):
    ticker: str
    document_url: str
    source_url: str | None = None
    document_title: str | None = None
    source_name: str = "官方揭露文件"
    max_preview_chars: int = Field(default=1800, ge=200, le=6000)


class OfficialDocumentExtractionResult(BaseModel):
    ticker: str
    company_name: str
    subindustry: str
    source_name: str
    source_url: str
    document_url: str
    document_title: str | None = None
    document_kind: OfficialDocumentKind = "unknown"
    status: OfficialEvidenceSourceStatus = "metadata_only"
    extract_status: OfficialDocumentExtractStatus = "not_attempted"
    content_type: str | None = None
    final_url: str | None = None
    http_status: int | None = None
    text_preview: str | None = None
    text_length: int | None = None
    related_metrics: list[str] = Field(default_factory=list)
    disclosure_claims: list[OfficialDisclosureClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None
    debug: dict[str, Any] = Field(default_factory=dict)
    retrieved_at: datetime | None = None


class InvestorConferenceRecord(BaseModel):
    ticker: str
    company_name: str
    subindustry: str
    fiscal_year: int | None = None
    quarter: int | None = None
    conference_date: str | None = None
    title: str
    source_name: str = "公開資訊觀測站 法說會"
    source_url: str
    document_url: str | None = None
    video_url: str | None = None
    status: OfficialEvidenceSourceStatus = "metadata_only"
    document_extract_status: OfficialDocumentExtractStatus = "metadata_only"
    document_title: str | None = None
    document_text_preview: str | None = None
    document_text_length: int | None = None
    source_evidence: list[str] = Field(default_factory=list)
    extracted_topics: list[str] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)
    disclosure_claims: list[OfficialDisclosureClaim] = Field(default_factory=list)
    document_extractions: list[OfficialDocumentExtractionResult] = Field(default_factory=list)
    summary: str | None = None
    limitations: list[str] = Field(default_factory=list)


class MaterialEventRecord(BaseModel):
    ticker: str
    company_name: str
    subindustry: str
    event_date: str | None = None
    title: str
    category: MaterialEventCategory = "other"
    source_name: str = "公開資訊觀測站 重大訊息"
    source_url: str
    status: OfficialEvidenceSourceStatus = "metadata_only"
    raw_text: str | None = None
    related_metrics: list[str] = Field(default_factory=list)
    risk_related: bool = False
    summary: str | None = None
    disclosure_claims: list[OfficialDisclosureClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class OfficialEvidenceSummary(BaseModel):
    ticker: str
    company_name: str
    subindustry: str
    generated_at: datetime
    evidence_layers: list[OfficialEvidenceType]
    financial_snapshot: dict | None = None
    investor_conferences: list[InvestorConferenceRecord] = Field(default_factory=list)
    material_events: list[MaterialEventRecord] = Field(default_factory=list)
    official_evidence_summary: str
    readiness: Literal[
        "financial_only",
        "financial_plus_event_metadata",
        "ready_for_frontend_integration",
        "needs_refresh",
    ]
    limitations: list[str] = Field(default_factory=list)
    sources: list[OfficialSourceLink] = Field(default_factory=list)


class OfficialEvidenceCardResponse(BaseModel):
    schema_version: str = "frontend-official-evidence-card-1.0.0"
    ticker: str
    company_name: str
    subindustry: str
    generated_at: datetime
    evidence_readiness: str
    overall_severity: str | None = None
    headline: str
    summary: str
    financial_snapshot: dict | None = None
    key_metrics: list[dict[str, Any]] = Field(default_factory=list)
    rule_cards: list[dict[str, Any]] = Field(default_factory=list)
    investor_conferences: list[dict[str, Any]] = Field(default_factory=list)
    material_events: list[dict[str, Any]] = Field(default_factory=list)
    disclosure_claims: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    source_status: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)
    frontend_hints: dict[str, Any] = Field(default_factory=dict)
