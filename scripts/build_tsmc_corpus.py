"""Download TSMC official quarterly earnings-call transcripts for local research.

Run: python3 scripts/build_tsmc_corpus.py --start 2017 --end 2025
Only metadata / source code should be committed. Do not commit transcript PDF/text.
All documents must come from investor.tsmc.com, and missing links are logged, never invented.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

BASE = "https://investor.tsmc.com"
HEADERS = {"User-Agent": "Academic-coursework-source-indexer/1.0 (single-threaded)"}
FIELDS = ["ticker", "company", "industry", "year", "quarter", "period", "document_type",
          "language", "text", "source_page", "source_pdf", "sha256", "text_length"]
INDEX_FIELDS = ["period", "source_page", "source_pdf", "status", "note", "sha256", "text_length"]


def official_pdf(url: str) -> bool:
    p = urlparse(url)
    return p.scheme == "https" and p.hostname == "investor.tsmc.com" and p.path.lower().endswith(".pdf")


def get_pdf_link(html: str, page_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for tag in soup.find_all(["a", "button"]):
        text = tag.get_text(" ", strip=True).lower()
        href = str(tag.get("href") or tag.get("data-href") or "")
        if "transcript" in text or "逐字稿" in text:
            if href and official_pdf(urljoin(page_url, href)):
                return urljoin(page_url, href)
            # Some versions render the hyperlink within a neighboring element.
            parent = tag.parent
            for link in parent.find_all("a", href=True) if parent else []:
                url = urljoin(page_url, link["href"])
                if official_pdf(url) and ("transcript" in url.lower() or "逐字稿" in url):
                    found.append(url)
    # TSMC sometimes embeds JSON-escaped URLs in script tags.
    raw = html.replace("\\/", "/").replace("&amp;", "&")
    for match in re.finditer(r'(?:https?://investor\.tsmc\.com)?/?(?:english/)?encrypt/files/[^"\x27<>\s]+?\.pdf', raw, re.I):
        url = urljoin(BASE + "/", match.group().lstrip("/"))
        if official_pdf(url) and ("transcript" in unquote(url).lower() or "%20transcript" in url.lower()):
            found.append(url)
    return found[0] if found else None


def read_overrides(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = csv.DictReader(file)
        return {r["period"].strip(): r["source_pdf"].strip()
                for r in rows if r.get("period") and r.get("source_pdf")}


def extract_pdf(data: bytes) -> str:
    if not data.startswith(b"%PDF"):
        raise ValueError("來源未回傳 PDF")
    pdf = PdfReader(io.BytesIO(data))
    pages = [(p.extract_text(extraction_mode="layout") or "") for p in pdf.pages]
    text = "\n".join(pages)
    text = re.sub(r"(?m)^\s*(?:Page\s+)?\d+\s+(?:of\s+\d+)?\s*$", "", text, flags=re.I)
    text = re.sub(r"[ \t]{2,}", " ", text)
    if len(text) < 2000:
        raise ValueError("文字抽取長度不足：可能是掃描 PDF 或來源非逐字稿")
    return text


def build(start: int, end: int, dest: Path, overrides: Path, delay: float) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    corpus_file, index_file = dest / "tsmc_quarterly_text.csv", dest / "tsmc_source_index.csv"
    manual = read_overrides(overrides)
    corpus_rows, source_rows = [], []
    sess = requests.Session()
    sess.headers.update(HEADERS)
    for year in range(start, end + 1):
        for quarter in range(1, 5):
            period = f"{year}Q{quarter}"
            page = f"{BASE}/english/quarterly-results/{year}/q{quarter}"
            pdf_url = manual.get(period, "")
            metadata = {"period": period, "source_page": page, "source_pdf": pdf_url,
                        "status": "", "note": "", "sha256": "", "text_length": ""}
            try:
                if not pdf_url:
                    response = sess.get(page, timeout=35)
                    response.raise_for_status()
                    pdf_url = get_pdf_link(response.text, page) or ""
                    time.sleep(delay)
                if not pdf_url:
                    raise ValueError("官方頁未發現可確認的逐字稿 PDF，請人工補充 override")
                if not official_pdf(pdf_url):
                    raise ValueError("來源不是台積電官方 HTTPS PDF")
                metadata["source_pdf"] = pdf_url
                response = sess.get(pdf_url, timeout=80)
                response.raise_for_status()
                data = response.content
                text = extract_pdf(data)
                sha = hashlib.sha256(data).hexdigest()
                metadata.update(status="ok", sha256=sha, text_length=len(text))
                corpus_rows.append({
                    "ticker": "2330", "company": "Taiwan Semiconductor Manufacturing Company",
                    "industry": "semiconductor_foundry", "year": year, "quarter": quarter,
                    "period": period, "document_type": "full_earnings_transcript",
                    "language": "en_may_include_translation", "text": text,
                    "source_page": page, "source_pdf": pdf_url, "sha256": sha,
                    "text_length": len(text),
                })
                print(f"OK {period}: {len(text)} characters")
            except (ValueError, requests.RequestException, Exception) as error:
                metadata["status"] = "needs_manual_review"
                metadata["note"] = f"{type(error).__name__}: {error}"[:350]
                print(f"REVIEW {period}: {metadata['note']}")
            source_rows.append(metadata)
            time.sleep(delay)
    with corpus_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(corpus_rows)
    with index_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(source_rows)
    print(f"Documents: {len(corpus_rows)} / {len(source_rows)}. Local corpus: {corpus_file}")
    print(f"Check every extracted document manually before calibration. Index: {index_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=2017)
    parser.add_argument("--end", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("data/tsmc_corpus"))
    parser.add_argument("--overrides", type=Path, default=Path("research/tsmc_pdf_overrides.csv"))
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()
    if args.end < args.start or args.delay < 0.8:
        parser.error("end must >= start; delay must >= 0.8 seconds")
    build(args.start, args.end, args.out, args.overrides, args.delay)
