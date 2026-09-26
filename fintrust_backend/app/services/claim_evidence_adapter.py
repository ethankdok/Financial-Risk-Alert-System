"""Official evidence adapter for claim verification.

Reads evidence the system already stores; it never downloads, parses PDFs,
runs OCR, or calls a model. Each candidate records whether its claim-relevant
value/label pair is *source-confirmed* by deterministic PDF or filing evidence.
Only source-confirmed candidates can later become decisive.

Sources:
* financial facts and calculated metrics (PipelineEvidenceRepository);
* conference-PDF semantic evidence (tables, charts, text) from the archive;
* official material-event metadata (context only unless official text exists).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.claim_verification_models import (
    ClaimEvidenceItem,
    EvidenceComparison,
    EvidenceProvenance,
    StructuredClaim,
)
from app.models import FinancialFact
from app.services.periods import normalize_period

# Row / chart labels → canonical metric. Labels are compared after dropping
# parenthetical qualifiers ("Net Revenue (US$ billions)") and footnote marks.
METRIC_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "gross_margin": ("gross margin", "gross profit margin", "營業毛利率", "毛利率"),
    "operating_margin": ("operating margin", "營業淨利率", "營業利益率", "營益率"),
    "net_margin": ("net profit margin", "net margin", "純益率", "淨利率", "稅後純益率"),
    "revenue": ("net revenue", "revenue", "營業收入淨額", "營業收入", "營收"),
    "eps": ("eps", "eps - diluted", "每股盈餘"),
    "roe": ("roe", "股東權益報酬率"),
    "current_ratio": ("current ratio", "流動比率"),
    "debt_ratio": ("debt ratio", "負債比率"),
    "free_cash_flow": ("free cash flow", "free cash flow (fcf)", "自由現金流量"),
    "operating_cash_flow": ("cash from operating activities", "operating cash flow", "營運活動之現金流入"),
    "capital_expenditure": ("capital expenditures", "資本支出"),
    "inventory": ("inventories", "存貨"),
    "net_income": ("net income attributable to shareholders of the parent company", "歸屬予母公司業主之本期淨利"),
    "wafer_shipment": ("shipment", "晶圓出貨量"),
}
_GUIDANCE_RE = re.compile(r"guidance|outlook|業績展望|展望|財測|指引", re.I)
_CHANGE_RE = re.compile(r"(?<![A-Za-z])over(?![A-Za-z])|yoy|qoq|變化|增減|change|vs\.?", re.I)
_PERIOD_TOKEN_RE = re.compile(r"^(?:[1-4]Q\d{2}|[1-4]Q20\d{2}|20\d{2}Q[1-4]|Q[1-4]'?\d{2}|20\d{2})$", re.I)
_ACTUAL_QUALIFIERS = {"", "amount", "金額"}
_NUMBER_RE = re.compile(r"^[-+]?\(?[-+]?\d[\d,]*(?:\.\d+)?\)?%?$")


def _base_label(label: str) -> str:
    text = re.sub(r"\([^)]*\)|（[^）]*）|\*", "", label or "")
    return re.sub(r"\s+", " ", text).strip().casefold()


def label_metric(label: str | None) -> str | None:
    base = _base_label(label or "")
    for metric, aliases in METRIC_LABEL_ALIASES.items():
        if base in aliases:
            return metric
    return None


def label_unit(label: str | None, value_text: str | None) -> str | None:
    if value_text and value_text.strip().endswith("%"):
        return "%"
    text = label or ""
    if re.search(r"US\$\s*billions|美金十億元", text, re.I):
        return "US$ billions"
    if re.search(r"NT\$|新台幣", text):
        return "NT$"
    return None


def classify_column(header: str | None) -> tuple[str, str | None]:
    """Return (kind, period). kind: actual | share | guidance | change | unknown."""
    text = (header or "").strip()
    if not text:
        return "unknown", None
    if _GUIDANCE_RE.search(text):
        return "guidance", _first_period(text)
    if _CHANGE_RE.search(text):
        return "change", _first_period(text)
    tokens = text.split()
    if not _PERIOD_TOKEN_RE.match(tokens[0]):
        return "unknown", None
    period = _token_period(tokens[0])
    qualifier = " ".join(tokens[1:]).casefold()
    if qualifier in _ACTUAL_QUALIFIERS:
        return "actual", period
    if qualifier == "%":
        return "share", period
    return "unknown", period


def _token_period(token: str) -> str | None:
    if re.fullmatch(r"20\d{2}", token):
        return f"{token}FY"
    return normalize_period(token)


def _first_period(text: str) -> str | None:
    for token in text.split():
        if _PERIOD_TOKEN_RE.match(token):
            return _token_period(token)
    return None


def parse_official_number(value_text: str | None) -> tuple[float | None, int]:
    """Parse one printed number; ranges and annotated values return None. Also returns decimals."""
    text = (value_text or "").strip().replace(" ", "")
    if not _NUMBER_RE.match(text):
        return None, 0
    negative = text.startswith("(") and text.endswith(")")
    cleaned = text.strip("()").replace(",", "").rstrip("%").lstrip("+")
    try:
        value = float(cleaned)
    except ValueError:
        return None, 0
    decimals = len(cleaned.split(".")[1]) if "." in cleaned else 0
    return (-abs(value) if negative else value), decimals


def _roc_date(text: str | None) -> str | None:
    match = re.match(r"\s*(1\d{2})/(\d{2})/(\d{2})", text or "")
    if not match:
        return None
    return f"{int(match.group(1)) + 1911}-{match.group(2)}-{match.group(3)}"


@dataclass
class Candidate:
    """An evidence item plus the facts the aggregator needs (not serialized)."""

    item: ClaimEvidenceItem
    source_confirmed: bool
    kind: str = "actual"  # actual | share | guidance | change | unknown | text | event
    numeric_value: float | None = None
    decimals: int = 0
    group: str | None = None  # same table row / chart, for in-source trend recomputation
    score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class ClaimEvidenceAdapter:
    def __init__(self, *, fact_repository: Any | None, conference_repository: Any | None,
                 event_repository: Any | None = None, max_conference_documents: int = 40) -> None:
        self.fact_repository = fact_repository
        self.conference_repository = conference_repository
        self.event_repository = event_repository
        self.max_conference_documents = max_conference_documents

    # --- financial facts ---------------------------------------------------------

    def fact(self, ticker: str, metric: str, period: str) -> FinancialFact | None:
        if self.fact_repository is None:
            return None
        try:
            return self.fact_repository.get_fact(ticker, metric, period)
        except Exception:
            return None

    @staticmethod
    def fact_item(fact: FinancialFact, *, relation: str = "context",
                  comparison: EvidenceComparison | None = None) -> ClaimEvidenceItem:
        verified = fact.source_kind in {"mops_xbrl", "twse_openapi"} and not fact.is_demo
        return ClaimEvidenceItem(
            evidence_id=f"fact:{fact.ticker}:{fact.metric}:{fact.period}",
            relation=relation,
            source_type="financial_fact" if fact.taxonomy_concept else "financial_metric",
            source_title=("公開資訊觀測站 財務報告（XBRL）" if fact.source_kind == "mops_xbrl"
                          else "臺灣證券交易所 OpenAPI" if fact.source_kind == "twse_openapi"
                          else "示範資料（非官方）"),
            source_date=fact.filed_at.date().isoformat() if fact.filed_at else None,
            source_reference=fact.source_url,
            period=fact.period,
            metric=fact.metric,
            value=f"{fact.value:g}",
            unit=fact.unit,
            source_text=f"{fact.metric} {fact.period} = {fact.value:g} {fact.unit}",
            verification_status="verified" if verified else "needs_review",
            comparison=comparison,
            provenance=EvidenceProvenance(
                extraction_method="official_financial_statement",
                source_kind=fact.source_kind,
                supported_by=["official_filing"] if verified else [],
                is_demo=fact.is_demo,
            ),
        )

    # --- conference PDFs -------------------------------------------------------------

    def conference_candidates(self, claim: StructuredClaim) -> list[Candidate]:
        repo = self.conference_repository
        if repo is None or not claim.company_code:
            return []
        try:
            years = repo.available_years(claim.company_code)
        except Exception:
            return []
        candidates: list[Candidate] = []
        documents = 0
        for year in years:
            manifest = repo.latest_manifest(claim.company_code, year) or {}
            for document in manifest.get("documents", []):
                if "sha256" not in document or documents >= self.max_conference_documents:
                    continue
                documents += 1
                try:
                    records = repo.semantic(claim.company_code, year, document["filename"])
                except Exception:
                    continue
                context = {
                    "document": document["filename"],
                    "sha256": document.get("sha256"),
                    "language": document.get("language"),
                    "source_date": _roc_date((document.get("conference_dates") or [None])[0]),
                    "reference": manifest.get("listing_url"),
                    "company": claim.company_name or claim.company_code,
                }
                context["page_titles"] = {
                    record.get("page"): record.get("title")
                    for record in records if record.get("evidence_type") == "text" and record.get("title")
                }
                for record in records:
                    candidates.extend(self._from_record(record, claim, context))
        return candidates

    def _base_item(self, record: dict[str, Any], context: dict[str, Any], *, evidence_id: str,
                   source_type: str) -> dict[str, Any]:
        language = "英文" if context["language"] == "en" else "中文"
        date = context["source_date"]
        return dict(
            evidence_id=evidence_id,
            source_type=source_type,
            source_title=f"{context['company']} 法人說明會簡報（{language}{'，' + date if date else ''}）",
            source_date=date,
            document=context["document"],
            source_reference=context["reference"],
            page=record.get("page"),
            region_id=record.get("region_id"),
            verification_status=record.get("verification_status") or "needs_review",
            document_sha256=context["sha256"],
        )

    def _from_record(self, record: dict[str, Any], claim: StructuredClaim,
                     context: dict[str, Any]) -> list[Candidate]:
        kind = record.get("evidence_type")
        if kind == "table":
            return self._table_candidates(record, claim, context)
        if kind == "chart":
            return self._chart_candidates(record, claim, context)
        if kind == "text" and claim.claim_type == "company_statement":
            return self._text_candidates(record, claim, context)
        return []

    def _wanted(self, claim: StructuredClaim, metric: str | None, label: str | None) -> bool:
        if claim.claim_type == "percentage_mix":
            topic = (claim.metric_or_topic or "").split(":", 1)[-1].casefold()
            return bool(topic) and re.sub(r"\s+", "", (label or "")).casefold() == topic
        return metric is not None and metric == claim.metric_or_topic

    def _table_candidates(self, record: dict[str, Any], claim: StructuredClaim,
                          context: dict[str, Any]) -> list[Candidate]:
        out = []
        row_confirmed = (
            record.get("mapping_status") == "aligned"
            and str(record.get("extraction_method", "")).startswith("pdf_text_layout")
            and record.get("verification_status") in {"verified", "partially_verified"}
        )
        for row_index, row in enumerate(record.get("values") or []):
            if not isinstance(row, dict) or not row.get("cells"):
                continue
            label = row.get("row_label")
            metric = label_metric(label)
            if not self._wanted(claim, metric, label):
                continue
            for cell in row["cells"]:
                column_kind, period = classify_column(cell.get("column"))
                value_text = cell.get("value_text")
                number, decimals = parse_official_number(value_text)
                note = {
                    "guidance": "業績展望欄位：為預測值，不是實際公布數字。",
                    "change": "變化欄位：為期間差異，不是該期間的數值。",
                    "share": "占比欄位：為占總額比例，不是該指標本身的數值。",
                    "unknown": "欄位無法可靠對應到單一期間。",
                }.get(column_kind)
                item = ClaimEvidenceItem(
                    **self._base_item(record, context,
                                      evidence_id=f"{record.get('region_id')}:row{row_index}:{cell.get('column')}",
                                      source_type="conference_table"),
                    period=period,
                    metric=metric or claim.metric_or_topic,
                    label=label,
                    value=value_text,
                    unit=label_unit(label, value_text),
                    source_text=f"{label}｜{cell.get('column')}：{value_text}",
                    provenance=EvidenceProvenance(
                        extraction_method=record.get("extraction_method"),
                        source_kind="mops_conference_pdf",
                        supported_by=["pdf_text"],
                        semantic_provider=record.get("semantic_provider"),
                        mapping_status=record.get("mapping_status"),
                    ),
                    note=note,
                )
                out.append(Candidate(
                    item=item,
                    source_confirmed=row_confirmed and column_kind == "actual" and number is not None,
                    kind=column_kind,
                    numeric_value=number,
                    decimals=decimals,
                    group=f"{record.get('region_id')}:row{row_index}",
                ))
        return out

    def _chart_candidates(self, record: dict[str, Any], claim: StructuredClaim,
                          context: dict[str, Any]) -> list[Candidate]:
        out = []
        title = " ".join(filter(None, [record.get("title"), record.get("source_text")]))
        title_metric = label_metric(record.get("title"))
        page_title = (context.get("page_titles") or {}).get(record.get("page")) or ""
        chart_period = _first_period(record.get("title") or "") or _first_period(page_title) or next(
            (_token_period(p) for p in record.get("period_candidates") or [] if _PERIOD_TOKEN_RE.match(p)), None,
        )
        validations = (record.get("validation") or {}).get("values") or []
        deterministic = record.get("semantic_provider") == "deterministic" and record.get("mapping_status") == "aligned"
        for index, value in enumerate(record.get("values") or []):
            if not isinstance(value, dict) or not value.get("value_text"):
                continue
            label = value.get("label")
            label_period = _token_period(label) if label and _PERIOD_TOKEN_RE.match(label) else None
            metric = title_metric if label_period else None
            if claim.claim_type != "percentage_mix" and not self._wanted(claim, metric, None):
                continue
            if claim.claim_type == "percentage_mix" and not self._wanted(claim, None, label):
                continue
            check = validations[index] if index < len(validations) else {}
            pdf_mapped = "pdf_text" in (check.get("mapping_supported_by") or []) and "pdf_text" in (
                value.get("supported_by") or [])
            confirmed = (
                record.get("verification_status") in {"verified", "partially_verified"}
                and (deterministic or pdf_mapped)
            )
            number, decimals = parse_official_number(value.get("value_text"))
            supported_by = value.get("supported_by") or (["pdf_text"] if deterministic else [])
            item = ClaimEvidenceItem(
                **self._base_item(record, context, evidence_id=f"{record.get('region_id')}:v{index}",
                                  source_type="conference_chart"),
                period=label_period or chart_period,
                metric=metric or claim.metric_or_topic,
                label=label,
                value=value.get("value_text"),
                unit=label_unit(None, value.get("value_text")) or record.get("unit"),
                source_text=f"{title[:160]}｜{label or ''}：{value.get('value_text')}",
                provenance=EvidenceProvenance(
                    extraction_method=record.get("extraction_method"),
                    source_kind="mops_conference_pdf",
                    supported_by=list(supported_by),
                    semantic_provider=record.get("semantic_provider"),
                    mapping_status=record.get("mapping_status"),
                ),
                note=None if confirmed else "此圖表數值的標籤對應未由 PDF 文字層確認（可能僅來自影像判讀或 OCR），僅供參考。",
            )
            out.append(Candidate(item=item, source_confirmed=confirmed and number is not None,
                                 numeric_value=number, decimals=decimals, group=record.get("region_id"),
                                 extra={"trend": record.get("trend"), "trend_source": record.get("trend_source"),
                                        "trend_supported": record.get("trend_supported")}))
        return out

    def _text_candidates(self, record: dict[str, Any], claim: StructuredClaim,
                         context: dict[str, Any]) -> list[Candidate]:
        text = record.get("source_text") or ""
        overlap = sum(1 for keyword in claim.keywords if keyword and keyword in text)
        if not overlap:
            return []
        item = ClaimEvidenceItem(
            **self._base_item(record, context, evidence_id=f"{record.get('region_id')}:text",
                              source_type="conference_text"),
            source_text=text[:600],
            provenance=EvidenceProvenance(extraction_method=record.get("extraction_method"),
                                          source_kind="mops_conference_pdf", supported_by=["pdf_text"]),
        )
        return [Candidate(item=item, source_confirmed=record.get("verification_status") == "verified",
                          kind="text", score=float(overlap))]

    # --- official events ---------------------------------------------------------------

    def event_candidates(self, claim: StructuredClaim, limit: int = 50) -> list[Candidate]:
        if self.event_repository is None or not claim.company_code:
            return []
        try:
            events = self.event_repository.list_material_events(claim.company_code, limit=limit)
        except Exception:
            return []
        out = []
        for event in events:
            text = " ".join(filter(None, [event.title, event.raw_text]))
            overlap = sum(1 for keyword in claim.keywords if keyword and keyword in text)
            if not overlap:
                continue
            has_text = bool(event.raw_text)
            item = ClaimEvidenceItem(
                evidence_id=f"event:{event.event_id or event.title[:40]}",
                source_type="official_announcement",
                source_title=event.source_name,
                source_date=event.event_date,
                source_reference=event.detail_url or event.source_url,
                source_text=(event.raw_text or event.title)[:600],
                verification_status="verified" if has_text else "metadata_only",
                provenance=EvidenceProvenance(extraction_method="mops_material_event",
                                              source_kind="mops_material_event",
                                              supported_by=["official_announcement"] if has_text else []),
                note=None if has_text else "僅有公告標題（metadata），尚未取得公告全文。",
            )
            out.append(Candidate(item=item, source_confirmed=has_text, kind="event", score=float(overlap)))
        return out
