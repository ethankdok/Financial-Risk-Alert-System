"""Download official IR PDFs and archive complete extracted text for later analysis.

Run from fintrust_backend: python -m scripts.acquire_official_ir_pdfs --help
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.official_ir_pdf_archive import acquire_page


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True, help="TWSE/TPEx company code")
    parser.add_argument("--company", required=True, help="Company name shown in the evidence manifest")
    parser.add_argument("--page-url", required=True, help="Official MOPS or company IR page (or a direct PDF)")
    parser.add_argument("--as-of", help="Research cutoff date, YYYY-MM-DD; not treated as verified publication date")
    parser.add_argument("--output", type=Path, default=Path("data/official-ir-pdfs"))
    parser.add_argument("--max-documents", type=int, default=3)
    parser.add_argument("--ocr", action="store_true", help="Try Tesseract OCR on pages with little selectable text")
    args = parser.parse_args()
    result = acquire_page(
        ticker=args.ticker, company_name=args.company, page_url=args.page_url,
        output_dir=args.output, as_of=args.as_of, max_documents=args.max_documents,
        ocr=args.ocr,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
