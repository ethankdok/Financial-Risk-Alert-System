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
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPSHandler, HTTPRedirectHandler, HTTPCookieProcessor, Request, build_opener

from app.services.official_ir_pdf_archive import AcquisitionError, MAX_PAGES, _ocr_page

LIST_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
DOWNLOAD_URL = "https://mopsov.twse.com.tw/server-java/FileDownLoad"
REFERER = "https://mops.twse.com.tw/mops/#/web/t100sb02_1"
ALLOWED_HOSTS = frozenset({"mops.twse.com.tw", "mopsov.twse.com.tw"})
FILE_RE = re.compile(r"^[0-9]{4,6}[0-9]{8}[A-Z][0-9]{3}\.pdf$", re.I)
ONCLICK_ASSIGN_RE = re.compile(
    r"\b(?:document\.)?(?:fm_fileDownload|downloadForm|form1)?\.?"
    r"(?P<field>fileName|filePath|functionName|step)\.value\s*=\s*['\"](?P<value>[^'\"]*)['\"]",
    re.I,
)
PAGE_RE = re.compile(r"\b(?:page|goPage|chgPage)\((?P<quote>['\"]?)(?P<page>\d+)(?P=quote)\)", re.I)
MAX_LIST_BYTES = 4 * 1024 * 1024
MAX_PDF_BYTES = 35 * 1024 * 1024
MOPS_ENCODINGS = ("utf-8", "big5", "cp950")


def _allowed(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS


class _MopsRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _allowed(newurl):
            raise AcquisitionError("MOPS response redirected outside the official hosts")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


class MopsTransport(Protocol):
    def listing(self, ticker: str, roc_year: int, market: str, page: int = 1) -> bytes: ...

    def pdf(self, attachment: "ListedAttachment", referer: str) -> bytes: ...


class HttpMopsTransport:
    """Use the same cookie jar for the listing and MOPS's form POST download."""

    def __init__(self, timeout: float = 25) -> None:
        self.timeout = timeout
        self.opener = build_opener(
            HTTPCookieProcessor(CookieJar()),
            _MopsRedirects(),
            HTTPSHandler(context=_mops_ssl_context()),
        )
        self._primed = False

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

    def _prime(self) -> None:
        if self._primed:
            return
        self._read(Request(REFERER, headers={"User-Agent": "FinTrustAlert/0.1"}), MAX_LIST_BYTES)
        self._primed = True

    def listing(self, ticker: str, roc_year: int, market: str, page: int = 1) -> bytes:
        self._prime()
        params = {"step": "1", "firstin": "1", "off": "1", "TYPEK": market,
                  "year": str(roc_year), "co_id": ticker}
        if page > 1:
            params["pg"] = str(page)
        url = f"{LIST_URL}?{urlencode(params)}"
        return self._read(Request(url, headers={"User-Agent": "FinTrustAlert/0.1", "Referer": REFERER}), MAX_LIST_BYTES)

    def pdf(self, attachment: "ListedAttachment", referer: str) -> bytes:
        if not FILE_RE.fullmatch(attachment.filename) or not _allowed(referer):
            raise AcquisitionError("Invalid MOPS attachment name or referer")
        payload = urlencode(attachment.download_fields()).encode()
        req = Request(DOWNLOAD_URL, data=payload, headers={
            "User-Agent": "FinTrustAlert/0.1", "Referer": referer,
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/pdf,*/*",
        }, method="POST")
        return self._read(req, MAX_PDF_BYTES)


def _mops_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    strict = getattr(ssl, "VERIFY_X509_STRICT", 0)
    if strict:
        context.verify_flags &= ~strict
    return context


@dataclass(frozen=True)
class ListedAttachment:
    filename: str
    language: str
    conference_dates: tuple[str, ...]
    file_path: str = ""
    function_name: str = ""
    step: str = ""

    def download_fields(self) -> dict[str, str]:
        return {
            "step": self.step,
            "filePath": self.file_path,
            "fileName": self.filename,
            "functionName": self.function_name,
        }


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_body_row = False
        self.in_cell = False
        self.cell_text: list[str] = []
        self.cells: list[str] = []
        self.cell_attachments: list[list[dict[str, str]]] = []
        self.cell_links: list[int] = []
        self.current_attachments: list[dict[str, str]] = []
        self.current_links = 0
        self.rows: list[tuple[list[str], list[list[dict[str, str]]], list[int]]] = []
        self.page_buttons: set[int] = set()
        self.in_download_form = False
        self.download_defaults = {"step": "", "filePath": "", "fileName": "", "functionName": ""}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form" and (a.get("id") == "fm_fileDownload" or a.get("name") == "fm_fileDownload"):
            self.in_download_form = True
        elif tag == "tr" and a.get("data-type") == "body":
            self.in_body_row, self.cells, self.cell_attachments, self.cell_links = True, [], [], []
        elif self.in_body_row and tag == "td":
            self.in_cell, self.cell_text, self.current_attachments, self.current_links = True, [], [], 0
        elif self.in_cell and tag == "a":
            self.current_links += 1
            onclick_fields = {
                key: value for key, value in _download_fields_from_onclick(a.get("onclick") or "").items()
                if value
            }
            fields = {**self.download_defaults, **onclick_fields}
            if fields.get("fileName"):
                self.current_attachments.append(fields)
        elif self.in_download_form and tag == "input":
            name = a.get("name") or a.get("id") or ""
            if name in self.download_defaults:
                self.download_defaults[name] = a.get("value") or ""
        elif tag == "input" and PAGE_RE.search(a.get("onclick", "")):
            self._record_page(a.get("onclick") or "", a.get("value") or "")

    def handle_data(self, data):
        if self.in_cell:
            self.cell_text.append(data)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag != "input":
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == "form" and self.in_download_form:
            self.in_download_form = False
        elif tag == "td" and self.in_cell:
            self.cells.append(" ".join(" ".join(self.cell_text).split()))
            self.cell_attachments.append(self.current_attachments)
            self.cell_links.append(self.current_links)
            self.in_cell = False
        elif tag == "tr" and self.in_body_row:
            self.rows.append((self.cells, self.cell_attachments, self.cell_links))
            self.in_body_row = False

    def _record_page(self, onclick: str, value: str) -> None:
        match = PAGE_RE.search(onclick)
        if match:
            page = int(match.group("page"))
            if page == 0 and re.fullmatch(r"\d+", value):
                page = int(value)
            self.page_buttons.add(page)
            return
        if re.fullmatch(r"\d+", value):
            self.page_buttons.add(int(value))


def _decode_mops_html(raw: bytes) -> str:
    for encoding in MOPS_ENCODINGS:
        text = raw.decode(encoding, errors="replace")
        if "公司代號" in text or "法人說明會簡報內容" in text:
            return text
    return raw.decode("utf-8", errors="replace")


def _download_fields_from_onclick(onclick: str) -> dict[str, str]:
    fields = {"step": "", "filePath": "", "fileName": "", "functionName": ""}
    for match in ONCLICK_ASSIGN_RE.finditer(onclick):
        fields[match.group("field")] = match.group("value")
    return fields


def parse_listing(raw: bytes, *, ticker: str, roc_year: int) -> tuple[list[ListedAttachment], int]:
    html = _decode_mops_html(raw)
    if "公司代號" not in html or "法人說明會簡報內容" not in html or "FileDownLoad" not in html:
        raise AcquisitionError("Unexpected MOPS response; the listing could not be verified")
    parser = _ListingParser()
    parser.feed(html)
    if not parser.rows:
        raise AcquisitionError("MOPS returned no verifiable company rows")
    documents: dict[str, dict] = {}
    languages: dict[str, str] = {}
    for cells, attachments, links in parser.rows:
        if len(cells) < 8 or cells[0] != ticker:
            raise AcquisitionError("Listing includes a different company or an unexpected table layout")
        if not re.match(rf"^{roc_year}/\d{{2}}/\d{{2}}", cells[2]):
            raise AcquisitionError("Listing includes a different announcement year")
        for cell_no, language in ((6, "zh"), (7, "en")):
            if links[cell_no] != len(attachments[cell_no]):
                raise AcquisitionError("A PDF link could not be resolved from the official listing")
            for fields in attachments[cell_no]:
                filename = fields["fileName"]
                if not FILE_RE.fullmatch(filename) or not filename.startswith(ticker):
                    raise AcquisitionError("Unexpected attachment filename in official listing")
                if filename in languages and languages[filename] != language:
                    raise AcquisitionError("An attachment appears in conflicting language columns")
                languages[filename] = language
                entry = documents.setdefault(filename, {"dates": [], "fields": fields})
                if entry["fields"] != fields:
                    raise AcquisitionError("An attachment appears with conflicting download fields")
                entry["dates"].append(cells[2])
    if not documents:
        raise AcquisitionError("No downloadable PDFs appear in the verified listing")
    return ([ListedAttachment(
        name,
        languages[name],
        tuple(dict.fromkeys(value["dates"])),
        file_path=value["fields"].get("filePath", ""),
        function_name=value["fields"].get("functionName", ""),
        step=value["fields"].get("step", ""),
    ) for name, value in sorted(documents.items())], len(parser.rows))


def listing_pages(raw: bytes) -> set[int]:
    html = _decode_mops_html(raw)
    parser = _ListingParser()
    parser.feed(html)
    return parser.page_buttons or {1}


def merge_attachments(groups: list[list[ListedAttachment]]) -> list[ListedAttachment]:
    by_name: dict[str, ListedAttachment] = {}
    for group in groups:
        for item in group:
            previous = by_name.get(item.filename)
            if previous is None:
                by_name[item.filename] = item
                continue
            if (
                previous.language != item.language
                or previous.file_path != item.file_path
                or previous.function_name != item.function_name
                or previous.step != item.step
            ):
                raise AcquisitionError("An attachment appears with conflicting metadata across pages")
            dates = tuple(dict.fromkeys((*previous.conference_dates, *item.conference_dates)))
            by_name[item.filename] = ListedAttachment(
                item.filename,
                item.language,
                dates,
                file_path=item.file_path,
                function_name=item.function_name,
                step=item.step,
            )
    return [by_name[name] for name in sorted(by_name)]


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(data)
        temporary = Path(tmp.name)
    os.replace(temporary, path)


NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?(?![A-Za-z0-9])")


def _numeric_evidence(filename: str, page_no: int, text: str, method: str) -> list[dict]:
    results: list[dict] = []
    for match in NUMBER_RE.finditer(text):
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 80)
        results.append({
            "kind": "numeric_text",
            "filename": filename,
            "page": page_no,
            "value_text": match.group(0),
            "source_excerpt": " ".join(text[start:end].split()),
            "extraction_method": method,
            "confidence": "medium",
            "verification_status": "needs_context_review",
        })
    return results[:200]


def _table_like_evidence(filename: str, page_no: int, text: str, method: str) -> list[dict]:
    results: list[dict] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        numbers = NUMBER_RE.findall(line)
        if len(numbers) >= 2:
            results.append({
                "kind": "table_or_metric_row",
                "filename": filename,
                "page": page_no,
                "line": line_no,
                "values": numbers,
                "source_excerpt": " ".join(line.split()),
                "extraction_method": method,
                "confidence": "medium",
                "verification_status": "needs_context_review",
            })
    return results[:100]


def extract_pages(raw: bytes, *, filename: str = "document.pdf", ocr: bool = False) -> tuple[list[dict], list[str]]:
    from pypdf import PdfReader

    try:
        pdf = PdfReader(io.BytesIO(raw), strict=True)
        if pdf.is_encrypted or not 1 <= len(pdf.pages) <= MAX_PAGES:
            raise AcquisitionError("PDF is encrypted, empty, or exceeds the page limit")
        selectable_texts = [(page.extract_text() or "").strip() for page in pdf.pages]
        texts = list(selectable_texts)
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
        visuals = [None] * len(texts)
    pages = []
    for i, value in enumerate(texts):
        method = "selectable_text" if selectable_texts[i] else "ocr" if value else "none"
        analysis = _numeric_evidence(filename, i + 1, value, method)
        analysis.extend(_table_like_evidence(filename, i + 1, value, method))
        if visuals[i] is True:
            analysis.append({
                "kind": "chart_or_image_region",
                "filename": filename,
                "page": i + 1,
                "region": "full_page_visual_layer",
                "source_excerpt": None,
                "extraction_method": "pdf_visual_heuristic",
                "confidence": "low",
                "verification_status": "needs_manual_chart_value_verification",
            })
        elif visuals[i] is None:
            analysis.append({
                "kind": "visual_detection_unavailable",
                "filename": filename,
                "page": i + 1,
                "region": "full_page",
                "source_excerpt": None,
                "extraction_method": "pymupdf_unavailable",
                "confidence": "low",
                "verification_status": "needs_visual_parser_or_manual_review",
            })
        pages.append({
            "page": i + 1,
            "text": value,
            "text_length": len(value),
            "text_extraction_method": method,
            "analysis_results": analysis,
            "numeric_candidate_count": sum(1 for item in analysis if item["kind"] == "numeric_text"),
            "table_candidate_count": sum(1 for item in analysis if item["kind"] == "table_or_metric_row"),
            "visual_review_required": visuals[i] is not False,
        })
    problems = [f"page_{p['page']}:low_text" for p in pages if p["text_length"] < 30]
    problems += [f"page_{p['page']}:visual_review_required" for p in pages if p["visual_review_required"]]
    problems += [
        f"page_{p['page']}:chart_values_unverified"
        for p in pages
        if any(item["verification_status"] == "needs_manual_chart_value_verification" for item in p["analysis_results"])
    ]
    problems += [
        f"page_{p['page']}:visual_detection_unavailable"
        for p in pages
        if any(item["verification_status"] == "needs_visual_parser_or_manual_review" for item in p["analysis_results"])
    ]
    return pages, problems


def render_review_pages(raw: bytes, pages: list[dict], directory: Path) -> None:
    """Keep page images alongside unresolved visual evidence for human checking."""
    try:
        import fitz
    except ImportError:
        for item in pages:
            if item["visual_review_required"] or item["text_length"] < 30:
                item["review_image_error"] = "PyMuPDF is unavailable; page image was not rendered."
        return

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
                    "listing_pages": [], "documents": [], "errors": []}
    directory = output_dir / ticker / str(year)
    directory.mkdir(parents=True, exist_ok=True)
    previous = {}
    try:
        previous = {item["filename"]: item.get("sha256") for item in
                    json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["documents"]}
    except (OSError, KeyError, ValueError, TypeError):
        pass
    try:
        first_listing = source.listing(ticker, year - 1911, market, page=1)
        listing_page_numbers = sorted(listing_pages(first_listing))
        if 1 not in listing_page_numbers:
            raise AcquisitionError("PAGINATION_UNVERIFIED: first listing page is missing from pagination controls")
        result["listing_pages"] = listing_page_numbers
        page_payloads: dict[int, bytes] = {1: first_listing}
        page_attachments = []
        for page_no in listing_page_numbers:
            listing_html = page_payloads.get(page_no)
            if listing_html is None:
                listing_html = source.listing(ticker, year - 1911, market, page=page_no)
                page_payloads[page_no] = listing_html
            discovered = listing_pages(listing_html)
            if not set(listing_page_numbers).issuperset(discovered):
                raise AcquisitionError("PAGINATION_CHANGED: MOPS pagination changed during the run")
            attachments_on_page, rows = parse_listing(listing_html, ticker=ticker, roc_year=year - 1911)
            result["rows"] += rows
            page_attachments.append(attachments_on_page)
            result.setdefault("listing_page_sha256", {})[str(page_no)] = hashlib.sha256(listing_html).hexdigest()
            _atomic_bytes(directory / f"listing-page-{page_no}.html", listing_html)
        attachments = merge_attachments(page_attachments)
        result["expected_pdfs"] = len(attachments)
        for attachment in attachments:
            doc = {"filename": attachment.filename, "language": attachment.language,
                   "conference_dates": attachment.conference_dates,
                   "download_fields": attachment.download_fields(), "status": "failed"}
            result["documents"].append(doc)
            try:
                raw = source.pdf(attachment, result["listing_url"])
                if not raw.startswith(b"%PDF-") or len(raw) > MAX_PDF_BYTES:
                    raise AcquisitionError("MOPS attachment is missing or is not a PDF")
                digest = hashlib.sha256(raw).hexdigest()
                pages, problems = extract_pages(raw, filename=attachment.filename, ocr=ocr)
                base = directory / attachment.filename.removesuffix(".pdf")
                _atomic_bytes(base.with_suffix(".pdf"), raw)
                _atomic_bytes(base.with_suffix(".txt"), "\n\n".join(
                    f"[page {p['page']}]\n{p['text']}" for p in pages).encode("utf-8"))
                if problems:
                    render_review_pages(raw, pages, directory / f"{base.name}-review")
                _atomic_bytes(base.with_suffix(".pages.json"), json.dumps(
                    pages, ensure_ascii=False, indent=2).encode("utf-8"))
                analysis_path = base.with_suffix(".analysis.json")
                analysis_results = [
                    {key: value for key, value in item.items() if key != "text"}
                    for page in pages
                    for item in page["analysis_results"]
                ]
                _atomic_bytes(analysis_path, json.dumps(analysis_results, ensure_ascii=False, indent=2).encode("utf-8"))
                doc.update({"status": "complete" if not problems else "needs_review",
                            "sha256": digest, "page_count": len(pages),
                            "change": "new" if attachment.filename not in previous else
                                      "unchanged" if previous[attachment.filename] == digest else "updated",
                            "text_pages": sum(p["text_length"] >= 30 for p in pages),
                            "analysis_results": len(analysis_results),
                            "needs_manual_review_pages": [
                                p["page"] for p in pages if p["visual_review_required"] or p["text_length"] < 30
                            ],
                            "issues": problems, "pdf_path": str(base.with_suffix(".pdf")),
                            "text_path": str(base.with_suffix(".txt")),
                            "pages_path": str(base.with_suffix(".pages.json")),
                            "analysis_path": str(analysis_path)})
            except Exception as exc:
                doc["error"] = str(exc)
                result["errors"].append(f"{attachment.filename}: {exc}")
        result["downloaded_pdfs"] = sum("sha256" in doc for doc in result["documents"])
        missing = [doc["filename"] for doc in result["documents"] if "sha256" not in doc]
        unresolved_pages = sum(len(doc.get("needs_manual_review_pages", [])) for doc in result["documents"])
        unverified_charts = sum(
            sum(1 for issue in doc.get("issues", []) if issue.endswith(":chart_values_unverified"))
            for doc in result["documents"]
        )
        result["integrity"] = {
            "listing_pages_verified": bool(listing_page_numbers) and set(listing_page_numbers) == set(result["listing_pages"]),
            "missing_pdf_count": len(missing),
            "missing_pdfs": missing,
            "total_page_count": sum(int(doc.get("page_count") or 0) for doc in result["documents"]),
            "pages_requiring_manual_review": unresolved_pages,
            "unverified_chart_page_count": unverified_charts,
            "complete_requires_no_missing_pdfs_no_low_text_no_unverified_visuals": True,
        }
        result["status"] = "complete" if result["downloaded_pdfs"] == result["expected_pdfs"] and all(
            doc["status"] == "complete" for doc in result["documents"]) else "failed"
    except Exception as exc:
        result["errors"].append(str(exc))
    manifest = directory / "manifest.json"
    _atomic_bytes(manifest, json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8"))
    result["manifest_path"] = str(manifest)
    return result
