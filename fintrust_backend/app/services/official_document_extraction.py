from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.official_event_models import (
    InvestorConferenceRecord,
    OfficialDocumentExtractionRequest,
    OfficialDocumentExtractionResult,
    OfficialDocumentKind,
    OfficialEvidenceSourceStatus,
)
from app.services.company_registry import get_company
from app.services.official_event_sources import (
    CONFERENCE_TOPIC_METRICS,
    infer_conference_topics,
    infer_official_claims,
)

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TEXTISH_CONTENT_TYPES = ("text/", "json", "xml", "html", "javascript")
DEFAULT_USER_AGENT = "FinTrustAlert-MIS-Project/0.1 (+https://github.com/UnaLu027/fintrust-alert)"

Opener = Callable[[Request, float], Any]


def strip_html(value: str) -> str:
    no_scripts = SCRIPT_STYLE_RE.sub(" ", value)
    return SPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", no_scripts))).strip()


def infer_document_kind(url: str, title: str | None = None, content_type: str | None = None) -> OfficialDocumentKind:
    text = f"{url} {title or ''} {content_type or ''}".casefold()
    if "pdf" in text or text.endswith(".pdf"):
        return "pdf"
    if any(token in text for token in ("ppt", "pptx", "presentation", "簡報")):
        return "presentation"
    if any(token in text for token in ("transcript", "逐字", "議事", "call details")):
        return "transcript"
    if any(token in text for token in ("webcast", "video", "影音", "replay", "youtube")):
        return "video"
    if any(token in text for token in ("xls", "xlsx", "csv")):
        return "spreadsheet"
    if content_type and any(token in content_type.casefold() for token in TEXTISH_CONTENT_TYPES):
        return "html"
    return "unknown"


def _decode_bytes(raw: bytes, content_type: str | None = None) -> str:
    encodings = ["utf-8", "big5", "cp950"]
    if content_type and "charset=" in content_type.casefold():
        encodings.insert(0, content_type.split("charset=", 1)[-1].split(";", 1)[0].strip())
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


def _extract_pdf_text(raw: bytes, *, max_chars: int) -> tuple[str | None, str | None]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return None, "PDF parser pypdf 尚未安裝；目前先保留文件連結與 download/debug 狀態。"
    try:
        reader = PdfReader(io.BytesIO(raw))
        chunks = []
        for page in reader.pages[:8]:
            chunks.append(page.extract_text() or "")
            if sum(len(chunk) for chunk in chunks) >= max_chars:
                break
        text = SPACE_RE.sub(" ", " ".join(chunks)).strip()
        return (text[:max_chars] if text else None), None
    except Exception as exc:  # pragma: no cover - PDF parsing varies by document
        return None, f"PDF 下載成功但文字抽取失敗：{exc}"


def _source_status_from_error(error: Exception) -> tuple[OfficialEvidenceSourceStatus, str]:
    if isinstance(error, HTTPError) and error.code in {401, 403, 429}:
        return "blocked_by_source", "blocked_by_source"
    return "error", "download_failed"


class OfficialDocumentExtractionService:
    """Download/preview official documents with explicit fallback/debug status.

    The service never claims a PDF/transcript was parsed unless text is actually
    extracted. When official sources block Codespaces or server-side requests, it
    returns blocked_by_source and keeps the document URL for manual/frontend use.
    """

    def __init__(self, *, timeout_seconds: float = 15.0, opener: Opener | None = None) -> None:
        self.timeout_seconds = timeout_seconds
        self.opener = opener

    def _open(self, request: Request) -> Any:
        if self.opener is not None:
            return self.opener(request, self.timeout_seconds)
        return urlopen(request, timeout=self.timeout_seconds)  # noqa: S310 - official URL supplied by backend source registry.

    def extract(self, request_payload: OfficialDocumentExtractionRequest) -> OfficialDocumentExtractionResult:
        company = get_company(request_payload.ticker)
        if company is None:
            raise ValueError("Unsupported company for official document extraction.")

        source_url = request_payload.source_url or request_payload.document_url
        initial_kind = infer_document_kind(request_payload.document_url, request_payload.document_title)
        now = datetime.now(timezone.utc)
        base_kwargs = {
            "ticker": company.ticker,
            "company_name": company.name,
            "subindustry": company.subindustry,
            "source_name": request_payload.source_name,
            "source_url": source_url,
            "document_url": request_payload.document_url,
            "document_title": request_payload.document_title,
            "retrieved_at": now,
        }
        req = Request(
            request_payload.document_url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/pdf,application/xml;q=0.9,*/*;q=0.8",
                "Referer": source_url,
            },
        )
        try:
            with self._open(req) as response:
                raw = response.read()
                content_type = response.headers.get("Content-Type") if getattr(response, "headers", None) else None
                final_url = getattr(response, "url", request_payload.document_url)
                http_status = getattr(response, "status", None)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            status, extract_status = _source_status_from_error(exc)
            return OfficialDocumentExtractionResult(
                **base_kwargs,
                document_kind=initial_kind,
                status=status,
                extract_status=extract_status,
                http_status=getattr(exc, "code", None),
                error=str(exc),
                limitations=[
                    "官方文件下載未成功；系統保留 document_url、source_url 與錯誤狀態供前端顯示或人工覆核。",
                    "此失敗不會覆蓋 deterministic 財報規則結果。",
                ],
                debug={"exception_type": type(exc).__name__},
            )

        kind = infer_document_kind(final_url, request_payload.document_title, content_type)
        debug = {
            "raw_bytes": len(raw),
            "content_type": content_type,
            "final_url": final_url,
            "http_status": http_status,
        }
        text: str | None = None
        limitation: str | None = None
        if kind == "pdf":
            text, limitation = _extract_pdf_text(raw, max_chars=request_payload.max_preview_chars)
        elif kind in {"html", "transcript", "unknown"} or (content_type and any(t in content_type.casefold() for t in TEXTISH_CONTENT_TYPES)):
            text = strip_html(_decode_bytes(raw, content_type))[: request_payload.max_preview_chars]
        else:
            limitation = "此文件類型目前不直接抽取全文；保留官方文件連結供下一步下載或人工覆核。"

        claims = infer_official_claims(text or request_payload.document_title or "", source_url=final_url or source_url)
        related_metrics = CONFERENCE_TOPIC_METRICS.get(company.subindustry, [])
        topics = infer_conference_topics(text or request_payload.document_title or "", company.subindustry)
        if text:
            return OfficialDocumentExtractionResult(
                **base_kwargs,
                document_kind=kind,
                status="available",
                extract_status="text_extracted",
                content_type=content_type,
                final_url=final_url,
                http_status=http_status,
                text_preview=text,
                text_length=len(text),
                related_metrics=related_metrics,
                disclosure_claims=claims,
                limitations=[
                    "文件文字抽取為 Phase 4 MVP preview；仍需後續加入更完整的 PDF/table parsing 與 Gemini bounded summary。"
                ],
                debug={**debug, "topics": topics},
            )
        return OfficialDocumentExtractionResult(
            **base_kwargs,
            document_kind=kind,
            status="available",
            extract_status="document_link_found" if limitation else "unsupported",
            content_type=content_type,
            final_url=final_url,
            http_status=http_status,
            related_metrics=related_metrics,
            disclosure_claims=claims,
            limitations=[limitation or "文件下載成功，但目前無可用文字 preview；保留官方連結與 debug 資訊。"],
            debug={**debug, "topics": topics},
        )

    def extract_from_conference(self, record: InvestorConferenceRecord, *, max_preview_chars: int = 1800) -> OfficialDocumentExtractionResult | None:
        if not record.document_url:
            return None
        return self.extract(
            OfficialDocumentExtractionRequest(
                ticker=record.ticker,
                document_url=record.document_url,
                source_url=record.source_url,
                document_title=record.document_title or record.title,
                source_name=record.source_name,
                max_preview_chars=max_preview_chars,
            )
        )


def enrich_conferences_with_document_extraction(
    records: list[InvestorConferenceRecord],
    *,
    max_preview_chars: int = 1800,
    debug_dir: str | Path | None = None,
    service: OfficialDocumentExtractionService | None = None,
) -> tuple[list[InvestorConferenceRecord], list[OfficialDocumentExtractionResult], dict[str, Any]]:
    extractor = service or OfficialDocumentExtractionService()
    enriched: list[InvestorConferenceRecord] = []
    results: list[OfficialDocumentExtractionResult] = []
    for record in records:
        extraction = extractor.extract_from_conference(record, max_preview_chars=max_preview_chars)
        if extraction is None:
            enriched.append(record)
            continue
        results.append(extraction)
        limitations = list(dict.fromkeys([*record.limitations, *extraction.limitations]))
        claims = list(record.disclosure_claims)
        for claim in extraction.disclosure_claims:
            if claim.text not in {item.text for item in claims}:
                claims.append(claim)
        update: dict[str, Any] = {
            "document_extractions": [*record.document_extractions, extraction],
            "document_extract_status": extraction.extract_status,
            "status": "available" if extraction.status == "available" else record.status,
            "disclosure_claims": claims,
            "limitations": limitations,
        }
        if extraction.text_preview:
            update["document_text_preview"] = extraction.text_preview
            update["document_text_length"] = extraction.text_length
        enriched.append(record.model_copy(update=update))

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "document_attempt_count": len(results),
        "text_extracted_count": sum(1 for item in results if item.extract_status == "text_extracted"),
        "blocked_count": sum(1 for item in results if item.extract_status == "blocked_by_source"),
        "download_failed_count": sum(1 for item in results if item.extract_status == "download_failed"),
        "results": [item.model_dump(mode="json") for item in results],
    }
    if debug_dir is not None:
        directory = Path(debug_dir)
        directory.mkdir(parents=True, exist_ok=True)
        tickers = "-".join(dict.fromkeys(record.ticker for record in records)) or "unknown"
        path = directory / f"official-document-extraction-{tickers}.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary["debug_summary_file"] = str(path)
    return enriched, results, summary
