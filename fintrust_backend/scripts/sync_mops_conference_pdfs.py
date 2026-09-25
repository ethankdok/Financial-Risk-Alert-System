"""Sync all MOPS conference PDFs for one company and announcement year.

Run from fintrust_backend:
  python -m scripts.sync_mops_conference_pdfs --ticker 2330 --year 2025 --ocr

Exit status 2 means the strict batch is incomplete. Schedule repeated executions
with the same arguments; hashes distinguish new, changed and unchanged files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.mops_conference_pdf_pipeline import run_mops_pdf_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="4 to 6 digit company code")
    parser.add_argument("--year", required=True, type=int, help="Gregorian announcement year")
    parser.add_argument("--market", default="sii", choices=("sii", "otc", "rotc", "pub"))
    parser.add_argument("--output", type=Path, default=Path("data/official-ir-pdfs"))
    parser.add_argument("--ocr", action="store_true", help="OCR pages with insufficient selectable text")
    args = parser.parse_args()
    result = run_mops_pdf_pipeline(ticker=args.ticker, year=args.year, market=args.market,
                                   output_dir=args.output, ocr=args.ocr)
    integrity = result.get("integrity", {})
    print(json.dumps({
        **{key: result[key] for key in
           ("status", "ticker", "year", "rows", "expected_pdfs", "downloaded_pdfs",
            "errors", "manifest_path")},
        "listing_pages": result.get("listing_pages", []),
        "parsed_pages": integrity.get("total_page_count", 0),
        "pages_requiring_manual_review": integrity.get("pages_requiring_manual_review", 0),
        "unverified_chart_page_count": integrity.get("unverified_chart_page_count", 0),
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
