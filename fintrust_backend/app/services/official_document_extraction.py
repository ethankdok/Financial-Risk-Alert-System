from __future__ import annotations

import io
import json
import re
import ssl
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
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
STRUCTURAL_NOISE_RE = re.compile(
    r"<(nav|header|footer|aside|script|style)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
PARAGRAPH_RE = re.compile(
    r"<(?:p|li|h[1-6]|td|th|div|section|article)\b[^>]*>(.*?)</(?:p|li|h[1-6]|td|th|div|section|article)>",
    re.IGNORECASE | re.DOTALL,
)
TEXTISH_CONTENT_TYPES = ("text/", "json", "xml", "html", "javascript")
DEFAULT_USER_AGENT = "FinTrustAlert-MIS-Project/0.1 (+https://github.com/UnaLu027/fintrust-alert)"
ALLOWED_DOCUMENT_HOST_SUFFIXES = (
    "mediatek.com",
    "tsmc.com",
    "umc.com",
    "aseglobal.com",
    "twse.com.tw",
    "twse.com",
)

Opener = Callable[[Request, float], Any]


def strip_html(value: str) -> str:
    no_scripts = SCRIPT_STYLE_RE.sub(" ", value)
    return SPACE_RE.sub(" ", unescape(TAG_RE.sub(" ", no_scripts))).strip()


def _dedupe_repeated_lines(lines: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    output: list[str] = []
    for line in lines:
        key = line.casefold()
        counts[key] = counts.get(key, 0) + 1
        if counts[key] <= 2:
            output.append(line)
    return output


def extract_meaningful_html_text(value: str) -> tuple[str, list[str]]:
    html = STRUCTURAL_NOISE_RE.sub(" ", value)
    paragraphs = [
        strip_html(match.group(1))
        for match in PARAGRAPH_RE.finditer(html)
    ]
    paragraphs = [paragraph for paragraph in paragraphs if len(paragraph) >= 8]
    if not paragraphs:
        text = strip_html(html)
        paragraphs = [line.strip() for line in re.split(r"[\r\n]+", text) if len(line.strip()) >= 8]
    paragraphs = _dedupe_repeated_lines(paragraphs)
    return "\n".join(paragraphs).strip(), paragraphs


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


def _verified_ssl_context():
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        return None


def _extract_pdf_text(raw: bytes, *, max_chars: int) -> tuple[str | None, str | None, int]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        return None, "PDF parser pypdf 尚未安裝；目前先保留文件連結與 download/debug 狀態。", 0
    try:
        reader = PdfReader(io.BytesIO(raw))
        chunks = []
        pages_extracted = 0
        for page in reader.pages:
            chunks.append(page.extract_text() or "")
            pages_extracted += 1
            if sum(len(chunk) for chunk in chunks) >= max_chars:
                break
        lines = [SPACE_RE.sub(" ", line).strip() for chunk in chunks for line in chunk.splitlines()]
        text = "\n".join(_dedupe_repeated_lines([line for line in lines if line])).strip()
        return (text[:max_chars] if text else None), None, pages_extracted
    except Exception as exc:  # pragma: no cover - PDF parsing varies by document
        return None, f"PDF 下載成功但文字抽取失敗：{exc}", 0


def _source_status_from_error(error: Exception) -> tuple[OfficialEvidenceSourceStatus, str]:
    if isinstance(error, HTTPError) and error.code in {401, 403, 429}:
        return "blocked_by_source", "blocked_by_source"
    return "error", "download_failed"


def _is_allowed_document_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"}:
        return False
    hostname = (parsed.hostname or "").casefold()
    return any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in ALLOWED_DOCUMENT_HOST_SUFFIXES)


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
        return urlopen(request, timeout=self.timeout_seconds, context=_verified_ssl_context())  # noqa: S310 - official URL supplied by backend source registry.

    def extract(self, request_payload: OfficialDocumentExtractionRequest) -> OfficialDocumentExtractionResult:
        company = get_company(request_payload.ticker)
        if company is None:
            raise ValueError("Unsupported company for official document extraction.")

        source_url = request_payload.source_url or request_payload.document_url
        if self.opener is None and not _is_allowed_document_url(request_payload.document_url):
            raise ValueError("Official document URL host is not in the approved public-source allowlist.")
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
        full_text: str | None = None
        limitation: str | None = None
        paragraph_count: int | None = None
        pages_extracted: int | None = None
        if kind == "pdf":
            full_text, limitation, pages_extracted = _extract_pdf_text(raw, max_chars=request_payload.max_full_text_chars)
        elif kind in {"html", "transcript", "unknown"} or (content_type and any(t in content_type.casefold() for t in TEXTISH_CONTENT_TYPES)):
            full_text, paragraphs = extract_meaningful_html_text(_decode_bytes(raw, content_type))
            paragraph_count = len(paragraphs)
            full_text = full_text[: request_payload.max_full_text_chars]
        else:
            limitation = "此文件類型目前不直接抽取全文；保留官方文件連結供下一步下載或人工覆核。"

        text_preview = full_text[: request_payload.max_preview_chars] if full_text else None
        claims = infer_official_claims(full_text or request_payload.document_title or "", source_url=final_url or source_url)
        related_metrics = CONFERENCE_TOPIC_METRICS.get(company.subindustry, [])
        topics = infer_conference_topics(full_text or request_payload.document_title or "", company.subindustry)
        if full_text:
            return OfficialDocumentExtractionResult(
                **base_kwargs,
                document_kind=kind,
                status="available",
                extract_status="text_extracted",
                content_type=content_type,
                final_url=final_url,
                http_status=http_status,
                text_preview=text_preview,
                full_text=full_text,
                text_length=len(text_preview or ""),
                full_text_length=len(full_text),
                paragraph_count=paragraph_count,
                pages_extracted=pages_extracted,
                related_metrics=related_metrics,
                disclosure_claims=claims,
                limitations=[
                    "文件文字抽取已支援官方 PDF / HTML full-text candidate；較複雜表格或影音內容仍保留官方連結供人工覆核。"
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
            paragraph_count=paragraph_count,
            pages_extracted=pages_extracted,
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
                max_full_text_chars=max(1000, min(200000, max_preview_chars * 30)),
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
        if extraction.full_text:
            update["document_full_text"] = extraction.full_text
            update["document_full_text_length"] = extraction.full_text_length
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
