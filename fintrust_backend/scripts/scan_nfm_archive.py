"""Stage employee-count candidates from a local archived official-document bundle.

No network/DB writes; stdout is unapproved review material. The PDF digest
check does not authenticate the extracted page JSON or official issuer.
From fintrust_backend:
python -m scripts.scan_nfm_archive --root <archive_dir> --pdf company.pdf \
  --pdf-sha256 <actual sha> --pages company.pages.json \
  --pages-sha256 <actual sha> --ticker 2454 --fiscal-year 2025
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from app.services.integrity.nfm_candidate_extraction import scan_employee_candidates
from app.services.integrity.official_archive_integrity import verify_pdf_archive

_SHA = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_JSON = 25 * 1024 * 1024


def _archive_path(root: Path, name: str) -> Path:
    if (
        not name or "\\" in name or ":" in name or Path(name).is_absolute()
        or any(part in ("", ".", "..") for part in name.split("/"))
    ):
        raise ValueError("invalid archive relative path")
    current = root
    for part in name.split("/"):
        current = current / part
        if current.is_symlink():
            raise ValueError("symlinks are not accepted")
    resolved_root = root.resolve(strict=True)
    full = current.resolve(strict=True)
    if not full.is_relative_to(resolved_root) or not full.is_file():
        raise ValueError("path is not a regular file inside archive root")
    return full


def stage(
    root: Path, *, pdf_name: str, pdf_sha256: str,
    pages_name: str, pages_sha256: str, ticker: str, fiscal_year: int
) -> dict:
    pdf = verify_pdf_archive(root, pdf_name, expected_sha256=pdf_sha256)
    if not pdf["file_bytes_match"]:
        return {"status": "blocked", "reason": pdf["reason"], "candidates": []}
    if not _SHA.fullmatch(pages_sha256):
        return {"status": "blocked", "reason": "pages_digest_invalid", "candidates": []}
    path = _archive_path(root, pages_name)
    if path.stat().st_size > _MAX_JSON:
        return {"status": "blocked", "reason": "pages_json_too_large", "candidates": []}
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest().lower() != pages_sha256.lower():
        return {"status": "blocked", "reason": "pages_digest_mismatch", "candidates": []}
    document = json.loads(raw.decode("utf-8"))
    pages = document.get("pages") if isinstance(document, dict) else document
    if not isinstance(pages, list):
        return {"status": "blocked", "reason": "invalid_pages_schema", "candidates": []}
    result = scan_employee_candidates(
        pages, ticker=ticker, expected_fiscal_year=fiscal_year,
        source_sha256=pdf_sha256,
    )
    return {
        **result,
        "status": "review_candidates_only",
        "pdf_bytes_match": True,
        "pages_json_bytes_match": True,
        "pdf_sha256": pdf_sha256.lower(),
        "pages_sha256": pages_sha256.lower(),
        "pdf_page_text_correspondence_verified": False,
        "official_issuer_and_publication_verified": False,
        "eligible_as_f4_input": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only NFM candidate extraction from archived PDF/page JSON")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--pdf-sha256", required=True)
    parser.add_argument("--pages", required=True)
    parser.add_argument("--pages-sha256", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--fiscal-year", required=True, type=int)
    args = parser.parse_args()
    try:
        result = stage(
            args.root, pdf_name=args.pdf, pdf_sha256=args.pdf_sha256,
            pages_name=args.pages, pages_sha256=args.pages_sha256,
            ticker=args.ticker, fiscal_year=args.fiscal_year,
        )
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        result = {"status": "blocked", "reason": type(exc).__name__, "candidates": []}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "review_candidates_only" else 2


if __name__ == "__main__":
    raise SystemExit(main())
