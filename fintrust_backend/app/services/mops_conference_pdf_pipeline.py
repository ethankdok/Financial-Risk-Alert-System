"""Fail-closed, repeatable acquisition of the PDFs listed by MOPS t100sb02_1.

Scope is one listed company and announcement year. A non-empty text layer does
not establish that numbers inside charts were captured; those pages are kept
for visual review and the strict batch remains incomplete.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

from app.services.official_ir_pdf_archive import AcquisitionError, MAX_PAGES, _ocr_page

LIST_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
DOWNLOAD_URL = "https://mopsov.twse.com.tw/server-java/FileDownLoad"
REFERER = "https://mops.twse.com.tw/mops/#/web/t100sb02_1"
ALLOWED_HOSTS = frozenset({"mops.twse.com.tw", "mopsov.twse.com.tw"})
FILE_RE = re.compile(r"^[0-9]{4,6}[0-9]{8}[A-Z][0-9]{3}\.pdf$", re.I)
ONCLICK_FILE_RE = re.compile(r"\bfileName\.value\s*=\s*['\"]([^'\"]+\.pdf)['\"]", re.I)
MAX_LIST_BYTES = 4 * 1024 * 1024
MAX_PDF_BYTES = 35 * 1024 * 1024


def _allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


class _MopsRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise AcquisitionError("MOPS response redirected outside the official hosts")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class MopsTransport(Protocol):
    def listing(self, ticker: str, roc_year: int, market: str) -> bytes: ...

    def pdf(self, filename: str, referer: str) -> bytes: ...


class HttpMopsTransport:
    """Use the same cookie jar for the listing and MOPS's form POST download."""

    def __init__(self, timeout: float = 25) -> None:
        self.timeout = timeout
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()), _MopsRedirects())

    def _read(self, req: Request, maximum: int) -> bytes:
        if not _allowed(req.full_url):
            raise AcquisitionError("Only official MOPS HTTPS URLs are permitted")
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                if not _allowed(response.geturl()):
                    raise AcquisitionError("MOPS response left the official hosts")
                raw = response.read(maximum + 1)
        except (HTTPError, URLError, TimeoutError) as exc:
            raise AcquisitionError(f"MOPS request failed: {type(exc).__name__}: {exc}") from exc
        if len(raw) > maximum:
            raise AcquisitionError("MOPS response exceeds the configured size limit")
        return raw

    def listing(self, ticker: str, roc_year: int, market: str) -> bytes:
        params = {"step": "1", "firstin": "1", "off": "1", "TYPEK": market,
                  "year": str(roc_year), "co_id": ticker}
        url = f"{LIST_URL}?{urlencode(params)}"
        return self._read(Request(url, headers={"User-Agent": "FinTrustAlert/0.1", "Referer": REFERER}), MAX_LIST_BYTES)

    def pdf(self, filename: str, referer: str) -> bytes:
        if not FILE_RE.fullmatch(filename) or not _allowed(referer):
            raise AcquisitionError("Invalid MOPS attachment name or referer")
        payload = urlencode({"step": "", "filePath": "", "fileName": filename, "functionName": ""}).encode()
        req = Request(DOWNLOAD_URL, data=payload, headers={
            "User-Agent": "FinTrustAlert/0.1", "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/pdf,*/*",
        }, method="POST")
        return self._read(req, MAX_PDF_BYTES)


@dataclass(frozen=True)
class ListedAttachment:
    filename: str
    language: str
    conference_dates: tuple[str, ...]


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body_row = False
        self.in_cell = False
        self.cell_text: list[str] = []
        self.cells: list[str] = []
        self.cell_filenames: list[list[str]] = []
        self.cell_links: list[int] = []
        self.current_files: list[str] = []
        self.current_links = 0
        self.rows: list[tuple[list[str], list[list[str]], list[int]]] = []
        self.page_buttons: set[int] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and a.get("data-type") == "body":
            self.in_body_row, self.cells, self.cell_filenames, self.cell_links = True, [], [], []
        elif self.in_body_row and tag == "td":
            self.in_cell, self.cell_text, self.current_files, self.current_links = True, [], [], 0
        elif self.in_cell and tag == "a":
            self.current_links += 1
            match = ONCLICK_FILE_RE.search(a.get("onclick") or "")
            if match:
                self.current_files.append(match.group(1))
        elif tag == "input" and a.get("onclick", "").startswith("page("):
            match = re.fullmatch(r"\d+", a.get("value") or "")
            if match:
                self.page_buttons.add(int(match.group()))

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.in_cell:
            self.cells.append(" ".join(" ".join(self.cell_text).split()))
            self.cell_filenames.append(self.current_files)
            self.cell_links.append(self.current_links)
            self.in_cell = False
        elif tag == "tr" and self.in_body_row:
            self.rows.append((self.cells, self.cell_filenames, self.cell_links))
            self.in_body_row = False


def parse_listing(raw: bytes, *, ticker: str, roc_year: int) -> tuple[list[ListedAttachment], int]:
    html = raw.decode("utf-8", errors="replace")
    if "公司代號" not in html or "法人說明會簡報內容" not in html or "FileDownLoad" not in html:
        raise AcquisitionError("Unexpected MOPS response; the listing could not be verified")
    parser = _ListingParser()
    parser.feed(html)
    if not parser.rows:
        raise AcquisitionError("MOPS returned no verifiable company rows")
    if parser.page_buttons and parser.page_buttons != {1}:
        raise AcquisitionError("PAGINATION_UNVERIFIED: MOPS shows additional result pages")
    documents: dict[str, list[str]] = {}
    languages: dict[str, str] = {}
    for cells, filenames, links in parser.rows:
        if len(cells) < 8 or cells[0] != ticker:
            raise AcquisitionError("Listing includes a different company or an unexpected table layout")
        if not re.match(rf"^{roc_year}/\d{{2}}/\d{{2}}", cells[2]):
            raise AcquisitionError("Listing includes a different announcement year")
        for cell_no, language in ((6, "zh"), (7, "en")):
            if links[cell_no] != len(filenames[cell_no]):
                raise AcquisitionError("A PDF link could not be resolved from the official listing")
            for filename in filenames[cell_no]:
                if not FILE_RE.fullmatch(filename) or not filename.startswith(ticker):
                    raise AcquisitionError("Unexpected attachment filename in official listing")
                if filename in languages and languages[filename] != language:
                    raise AcquisitionError("An attachment appears in conflicting language columns")
                languages[filename] = language
                documents.setdefault(filename, []).append(cells[2])
    if not documents:
        raise AcquisitionError("No downloadable PDFs appear in the verified listing")
    return ([ListedAttachment(name, languages[name], tuple(dict.fromkeys(dates)))
             for name, dates in sorted(documents.items())], len(parser.rows))


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        temporary = Path(tmp.name)
    os.replace(temporary, path)


def extract_pages(raw: bytes, *, ocr: bool = False) -> tuple[list[dict], list[str]]:
    from pypdf import PdfReader

    try:
        pdf = PdfReader(io.BytesIO(raw), strict=True)
        if pdf.is_encrypted or not 1 <= len(pdf.pages) <= MAX_PAGES:
            raise AcquisitionError("PDF is encrypted, empty, or exceeds the page limit")
        texts = [(page.extract_text() or "").strip() for page in pdf.pages]
    except AcquisitionError:
        raise
    except Exception as exc:
        raise AcquisitionError(f"PDF cannot be parsed: {type(exc).__name__}") from exc

    visuals: list[bool | None] = [None] * len(texts)
    try:
        import fitz

        document = fitz.open(stream=raw, filetype="pdf")
        for i, page in enumerate(document):
            if len(texts[i]) < 30 and ocr:
                texts[i] = _ocr_page(page, "chi_tra+eng").strip()
            # Charts, tables made from paths, and figures need visual checking.
            visuals[i] = bool(page.get_drawings() or page.get_images())
    except ImportError:
        pass
    pages = [{"page": i + 1, "text": value, "text_length": len(value),
              "visual_review_required": visuals[i] is not False}
             for i, value in enumerate(texts)]
    problems = [f"page_{p['page']}:low_text" for p in pages if p["text_length"] < 30]
    problems += [f"page_{p['page']}:visual_review_required" for p in pages if p["visual_review_required"]]
    return pages, problems


def render_review_pages(raw: bytes, pages: list[dict], directory: Path) -> None:
    """Keep page images alongside unresolved visual evidence for human checking."""
    import fitz

    document = fitz.open(stream=raw, filetype="pdf")
    directory.mkdir(parents=True, exist_ok=True)
    for item in pages:
        if item["visual_review_required"] or item["text_length"] < 30:
            name = f"page-{item['page']:03}.png"
            png = document[item["page"] - 1].get_pixmap(matrix=fitz.Matrix(120 / 72, 120 / 72)).tobytes("png")
            _atomic_bytes(directory / name, png)
            item["review_image_path"] = str(directory / name)


def run_mops_pdf_pipeline(*, ticker: str, year: int, output_dir: Path,
                          market: str = "sii", ocr: bool = False,
                          transport: MopsTransport | None = None) -> dict:
    if not re.fullmatch(r"\d{4,6}", ticker) or not 1990 <= year <= datetime.now(timezone.utc).year:
        raise ValueError("Specify a valid company code and Gregorian announcement year")
    if market not in {"sii", "otc", "rotc", "pub"}:
        raise ValueError("Specify a supported MOPS market")
    source = transport or HttpMopsTransport()
    result: dict = {"ticker": ticker, "year": year, "market": market,
                    "listing_url": f"{LIST_URL}?{urlencode({'step':'1','firstin':'1','off':'1','TYPEK':market,'year':year-1911,'co_id':ticker})}",
                    "retrieved_at": datetime.now(timezone.utc).isoformat(),
                    "status": "failed", "rows": 0, "expected_pdfs": 0, "downloaded_pdfs": 0,
                    "documents": [], "errors": []}
    directory = output_dir / ticker / str(year)
    directory.mkdir(parents=True, exist_ok=True)
    previous = {}
    try:
        previous = {item["filename"]: item.get("sha256") for item in
                    json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["documents"]}
    except (OSError, KeyError, ValueError, TypeError):
        pass
    try:
        listing_html = source.listing(ticker, year - 1911, market)
        attachments, result["rows"] = parse_listing(listing_html, ticker=ticker, roc_year=year - 1911)
        result["listing_sha256"] = hashlib.sha256(listing_html).hexdigest()
        _atomic_bytes(directory / "listing.html", listing_html)
        result["expected_pdfs"] = len(attachments)
        for attachment in attachments:
            doc = {"filename": attachment.filename, "language": attachment.language,
                   "conference_dates": attachment.conference_dates, "status": "failed"}
            result["documents"].append(doc)
            try:
                raw = source.pdf(attachment.filename, result["listing_url"])
                if not raw.startswith(b"%PDF-") or len(raw) > MAX_PDF_BYTES:
                    raise AcquisitionError("MOPS attachment is missing or is not a PDF")
                digest = hashlib.sha256(raw).hexdigest()
                pages, problems = extract_pages(raw, ocr=ocr)
                base = directory / attachment.filename.removesuffix(".pdf")
                _atomic_bytes(base.with_suffix(".pdf"), raw)
                _atomic_bytes(base.with_suffix(".txt"), "\n\n".join(
                    f"[page {p['page']}]\n{p['text']}" for p in pages).encode("utf-8"))
                if problems:
                    render_review_pages(raw, pages, directory / f"{base.name}-review")
                _atomic_bytes(base.with_suffix(".pages.json"), json.dumps(
                    pages, ensure_ascii=False, indent=2).encode("utf-8"))
                doc.update({"status": "complete" if not problems else "needs_review",
                            "sha256": digest, "page_count": len(pages),
                            "change": "new" if attachment.filename not in previous else
                                      "unchanged" if previous[attachment.filename] == digest else "updated",
                            "text_pages": sum(p["text_length"] >= 30 for p in pages),
                            "issues": problems, "pdf_path": str(base.with_suffix(".pdf")),
                            "text_path": str(base.with_suffix(".txt")),
                            "pages_path": str(base.with_suffix(".pages.json"))})
            except Exception as exc:
                doc["error"] = str(exc)
                result["errors"].append(f"{attachment.filename}: {exc}")
        result["downloaded_pdfs"] = sum("sha256" in doc for doc in result["documents"])
        result["status"] = "complete" if result["downloaded_pdfs"] == result["expected_pdfs"] and all(
            doc["status"] == "complete" for doc in result["documents"]) else "failed"
    except Exception as exc:
        result["errors"].append(str(exc))
    manifest = directory / "manifest.json"
    _atomic_bytes(manifest, json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    result["manifest_path"] = str(manifest)
    return result
