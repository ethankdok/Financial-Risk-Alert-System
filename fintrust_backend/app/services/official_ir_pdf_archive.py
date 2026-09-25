"""Archive PDF evidence linked from an approved official investor-relations page.

This is an acquisition boundary, not a risk model. It preserves the original PDF,
full extracted text, hashes and source metadata for later, separately calibrated
document comparisons. No scraped page is treated as proof of its publication date.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
MAX_DOCUMENTS = 8
MAX_PAGES = 250
MAX_OCR_PAGES = 20
USER_AGENT = "FinTrustAlert-MIS-Project/0.1 (+https://github.com/UnaLu027/fintrust-alert)"
OFFICIAL_HOST_SUFFIXES = ("mediatek.com", "tsmc.com", "umc.com", "aseglobal.com", "twse.com.tw", "twse.com")
Fetch = Callable[[str], tuple[str, str, bytes]]


class AcquisitionError(Exception):
    """An official document could not be acquired or safely interpreted."""


def _is_allowed_document_url(url: str) -> bool:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").casefold()
    return parsed.scheme == "https" and any(
        hostname == suffix or hostname.endswith(f".{suffix}") for suffix in OFFICIAL_HOST_SUFFIXES
    )


class _OfficialRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _is_allowed_document_url(newurl):
            raise AcquisitionError("Redirected URL is outside the approved official-host allowlist.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


@dataclass(frozen=True)
class Candidate:
    url: str
    title: str


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.label = []

    def handle_data(self, data: str) -> None:
        if self.href is not None:
            self.label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.label).strip()))
            self.href = None
            self.label = []


def discover_pdfs(html: str, page_url: str) -> list[Candidate]:
    parser = _Links()
    parser.feed(html)
    candidates: dict[str, Candidate] = {}
    for href, title in parser.links:
        url = urljoin(page_url, href)
        if urlparse(url).path.casefold().endswith(".pdf") and _is_allowed_document_url(url):
            candidates.setdefault(url, Candidate(url=url, title=title or "Official PDF"))
    return list(candidates.values())


def _fetch(url: str) -> tuple[str, str, bytes]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8"})
    with build_opener(_OfficialRedirects()).open(request, timeout=20) as response:
        raw = response.read(MAX_DOWNLOAD_BYTES + 1)
        if len(raw) > MAX_DOWNLOAD_BYTES:
            raise AcquisitionError("Document exceeds the 20 MiB download limit.")
        return response.geturl(), response.headers.get("Content-Type", ""), raw


def _read(url: str, fetch: Fetch) -> tuple[str, str, bytes]:
    if not _is_allowed_document_url(url):
        raise AcquisitionError("Source URL is outside the approved official-host allowlist.")
    final_url, content_type, data = fetch(url)
    if not _is_allowed_document_url(final_url):
        raise AcquisitionError("Redirected URL is outside the approved official-host allowlist.")
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise AcquisitionError("Document exceeds the 20 MiB download limit.")
    return final_url, content_type, data


def _ocr_page(page: object, language: str) -> str:
    import fitz  # type: ignore

    if shutil.which("tesseract") is None:
        raise AcquisitionError("OCR_UNAVAILABLE: tesseract executable is missing.")
    langs = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10, check=False)
    installed = set(langs.stdout.splitlines()) | set(langs.stderr.splitlines())
    missing = set(language.split("+")) - installed
    if missing:
        raise AcquisitionError(f"OCR_UNAVAILABLE: language data missing: {', '.join(sorted(missing))}.")
    # 150 dpi is enough for a first pass and bounds CPU and memory use.
    image = page.get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72)).tobytes("png")
    result = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", language],
        input=image, capture_output=True, timeout=45, check=False,
    )
    if result.returncode:
        raise AcquisitionError(f"OCR_FAILED: tesseract exit code {result.returncode}.")
    return result.stdout.decode("utf-8", errors="replace")


def extract_pdf(raw: bytes, *, ocr: bool = False, ocr_language: str = "chi_tra+eng") -> tuple[str, int, int, list[str]]:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise AcquisitionError("Encrypted PDF requires manual review.")
        if len(reader.pages) > MAX_PAGES:
            raise AcquisitionError(f"PDF exceeds the {MAX_PAGES}-page parsing limit.")
        page_texts = [(page.extract_text() or "").strip() for page in reader.pages]
    except AcquisitionError:
        raise
    except Exception as exc:
        raise AcquisitionError(f"Invalid or unreadable PDF: {type(exc).__name__}") from exc
    warnings: list[str] = []
    scanned = [i for i, value in enumerate(page_texts) if len(value) < 30]
    if scanned and ocr:
        try:
            import fitz  # type: ignore

            document = fitz.open(stream=raw, filetype="pdf")
            for i in scanned[:MAX_OCR_PAGES]:
                page_texts[i] = _ocr_page(document[i], ocr_language).strip()
            if len(scanned) > MAX_OCR_PAGES:
                warnings.append(f"OCR limited to the first {MAX_OCR_PAGES} low-text pages.")
        except (ImportError, AcquisitionError) as exc:
            warnings.append(str(exc))
    elif scanned:
        warnings.append(f"{len(scanned)} pages have little selectable text; OCR was not requested.")
    text = "\n\n".join(f"[page {i + 1}]\n{value}" for i, value in enumerate(page_texts) if value)
    return text, len(page_texts), len(scanned), warnings


def acquire_page(
    *, ticker: str, company_name: str, page_url: str, output_dir: Path,
    as_of: str | None = None, max_documents: int = 3, ocr: bool = False,
    fetch: Fetch = _fetch,
) -> dict:
    """Discover and archive PDF links on one approved page; never crawl other pages."""
    if not re.fullmatch(r"\d{4,6}", ticker):
        raise ValueError("ticker must be a 4–6 digit TWSE/TPEx company code")
    if not 1 <= max_documents <= MAX_DOCUMENTS:
        raise ValueError(f"max_documents must be between 1 and {MAX_DOCUMENTS}")
    if as_of is not None:
        datetime.fromisoformat(as_of).date()  # syntax only; publication date needs independent verification
    final_page, content_type, page_data = _read(page_url, fetch)
    if "pdf" in content_type.casefold() or page_data.startswith(b"%PDF-"):
        candidates = [Candidate(final_page, "Official PDF")]
    elif "html" in content_type.casefold() or page_data.lstrip().startswith(b"<"):
        candidates = discover_pdfs(page_data.decode("utf-8", errors="replace"), final_page)
    else:
        raise AcquisitionError("Source page was neither HTML nor PDF.")
    result = {
        "ticker": ticker, "company_name": company_name,
        "source_page": page_url, "resolved_source_page": final_page,
        "as_of": as_of, "as_of_verified": False,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "candidates_found": len(candidates), "documents": [],
    }
    target = output_dir / ticker
    target.mkdir(parents=True, exist_ok=True)
    for candidate in candidates[:max_documents]:
        item: dict = {"title": candidate.title, "document_url": candidate.url}
        try:
            final_url, pdf_type, pdf_bytes = _read(candidate.url, fetch)
            if not pdf_bytes.startswith(b"%PDF-"):
                raise AcquisitionError("Downloaded response is not a PDF (PDF magic missing).")
            digest = hashlib.sha256(pdf_bytes).hexdigest()
            pdf_file = target / f"{digest}.pdf"
            txt_file = target / f"{digest}.txt"
            pdf_file.write_bytes(pdf_bytes)
            text, pages, low_text_pages, warnings = extract_pdf(pdf_bytes, ocr=ocr)
            if text.strip():
                txt_file.write_text(text, encoding="utf-8")
            item.update({
                "status": "text_extracted" if text.strip() else "needs_manual_review",
                "resolved_document_url": final_url, "content_type": pdf_type,
                "sha256": digest, "pdf_path": str(pdf_file),
                "text_path": str(txt_file) if text.strip() else None,
                "page_count": pages, "low_text_page_count": low_text_pages,
                "text_length": len(text), "warnings": warnings,
            })
        except Exception as exc:  # continue with other independently linked documents
            item.update({"status": "acquisition_failed", "error": str(exc)})
        result["documents"].append(item)
    manifest = target / f"acquisition-{hashlib.sha256(page_url.encode()).hexdigest()[:16]}.json"
    manifest.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["manifest_path"] = str(manifest)
    return result
