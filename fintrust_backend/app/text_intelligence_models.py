from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


CanonicalTopic = Literal[
    "outlook",
    "capacity_capex",
    "demand_inventory",
    "revenue_orders",
    "rd_product",
    "cash_financing",
    "ma_investment",
    "operation_disruption",
    "legal_regulatory",
    "governance",
    "other",
]

SourceType = Literal[
    "investor_conference",
    "material_event",
    "official_ir",
    "financial_snapshot",
    "uploaded_text",
    "synthetic_fixture",
    "other",
]


class OfficialTextDocumentInput(BaseModel):
    ticker: str
    company_name: str | None = None
    source_type: SourceType = "uploaded_text"
    source_name: str = "research_input"
    source_url: str = ""
    document_url: str | None = None
    document_id: str | None = None
    period: str | None = None
    event_date: str | None = None
    section: str = "other"
    text: str
    document_kind: str = "unknown"
    extraction_status: str = "text_provided"
    retrieved_at: datetime | None = None
    limitations: list[str] = Field(default_factory=list)


class TopicDecision(BaseModel):
    topic: CanonicalTopic
    score: float
    evidence_terms: list[str] = Field(default_factory=list)


class TextEvidenceSentence(BaseModel):
    evidence_id: str
    ticker: str
    company_name: str | None = None
    source_type: SourceType
    source_name: str
    source_url: str
    document_url: str | None = None
    document_id: str
    document_hash: str
    event_date: str | None = None
    period: str | None = None
    retrieved_at: datetime
    document_kind: str = "unknown"
    extraction_status: str
    parser_version: str
    section: str
    sentence_id: str
    original_text: str
    cleaned_text: str
    text_hash: str
    relevant: bool
    relevance_score: float
    relevance_model_name: str
    relevance_model_version: str
    semantic_relevance_score: float | None = None
    semantic_provider: str | None = None
    topics: list[CanonicalTopic] = Field(default_factory=list)
    topic_scores: list[TopicDecision] = Field(default_factory=list)
    related_metrics: list[str] = Field(default_factory=list)
    explanation: str
    limitations: list[str] = Field(default_factory=list)


class TextMiningTerm(BaseModel):
    term: str
    count: int
    rate: float


class TfidfTerm(BaseModel):
    term: str
    score: float


class TextMiningDocumentResult(BaseModel):
    document_id: str
    ticker: str
    company_name: str | None = None
    source_type: SourceType
    source_name: str
    source_url: str
    document_url: str | None = None
    period: str | None = None
    event_date: str | None = None
    candidate_sentence_count: int
    relevant_sentence_count: int
    coverage_ratio: float
    topic_counts: dict[CanonicalTopic, int] = Field(default_factory=dict)
    topic_proportions: dict[CanonicalTopic, float] = Field(default_factory=dict)
    top_terms: list[TextMiningTerm] = Field(default_factory=list)
    tfidf_terms: list[TfidfTerm] = Field(default_factory=list)
    sentences: list[TextEvidenceSentence] = Field(default_factory=list)
    semantic_summary: dict[str, Any] = Field(default_factory=dict)


class TextMiningAnalysisRequest(BaseModel):
    documents: list[OfficialTextDocumentInput]
    include_irrelevant_sentences: bool = False


class TextMiningAnalysisResponse(BaseModel):
    schema_version: str = "text-intelligence-v2.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_summary: dict[str, Any]
    documents: list[TextMiningDocumentResult]
    semantic_analysis: dict[str, Any] = Field(default_factory=dict)


class NarrativeShiftRequest(BaseModel):
    document_1: OfficialTextDocumentInput
    document_2: OfficialTextDocumentInput


class TermChange(BaseModel):
    term: str
    period_1_rate: float
    period_2_rate: float
    change: float
    period_1_count: int
    period_2_count: int


class TopicChange(BaseModel):
    topic: CanonicalTopic
    period_1_rate: float
    period_2_rate: float
    change: float
    period_1_count: int
    period_2_count: int


class NarrativeShiftResponse(BaseModel):
    schema_version: str = "narrative-shift-v2.0"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ticker: str
    period_1: str | None = None
    period_2: str | None = None
    metrics: dict[str, float]
    data_quality: dict[str, Any]
    topic_changes: list[TopicChange]
    emerging_terms: list[TermChange]
    disappearing_terms: list[TermChange]
    supporting_sentences: list[TextEvidenceSentence]
    method: dict[str, Any]
    limitations: list[str] = Field(default_factory=list)


class AnnotationCandidateExportRow(BaseModel):
    sample_id: str
    ticker: str
    company_name: str | None = None
    source_type: SourceType
    source_name: str
    source_url: str
    document_url: str | None = None
    document_id: str
    period: str | None = None
    event_date: str | None = None
    section: str
    sentence_id: str
    original_text: str
    relevant_label: str = ""
    primary_topic: str = ""
    secondary_topics: str = ""
    forward_looking: str = ""
    risk_relevant: str = ""
    annotator_id: str = ""
    annotation_round: str = ""
    annotation_notes: str = ""
