"""Bounded multi-company conference-PDF processing through the existing pipeline.

For each ticker and announcement year, acquire at most --max-documents official
MOPS PDFs (most recent first, preferring files whose listing states a reported
fiscal quarter) and run the unchanged Phase 1 pipeline on them. Unselected
files are recorded in the manifest. Existing archives are never reprocessed.
Model interpretation, region OCR and write-through are disabled for this run.

Run from fintrust_backend:
  python -m scripts.process_conference_companies --tickers 2454,2303 --year 2025 \\
      --output data/official-ir-pdfs-live-test [--max-documents 8] [--delay 2]
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from app.services.conference_document_identity import claimed_period_from_listing
from app.services.mops_conference_pdf_pipeline import HttpMopsTransport, ListedAttachment, run_mops_pdf_pipeline

DISABLED_FOR_RUN = ("CONFERENCE_PDF_MULTIMODAL_PROVIDER", "CONFERENCE_PDF_OCR_PROVIDER", "CONFERENCE_PDF_ARCHIVE_PUBLISH")


class PoliteTransport:
    """Wraps the official MOPS transport with a fixed delay before every request."""

    def __init__(self, delay: float) -> None:
        self.inner, self.delay = HttpMopsTransport(), delay

    def listing(self, *args, **kwargs):
        time.sleep(self.delay)
        return self.inner.listing(*args, **kwargs)

    def pdf(self, *args, **kwargs):
        time.sleep(self.delay)
        return self.inner.pdf(*args, **kwargs)


def _latest_date(item: ListedAttachment) -> str:
    return max((date[:9] for date in item.conference_dates), default="")


def select_recent(max_documents: int):
    def select(attachments: list[ListedAttachment]) -> list[ListedAttachment]:
        ordered = sorted(attachments, key=lambda item: (_latest_date(item), item.filename), reverse=True)
        claimed = [item for item in ordered if claimed_period_from_listing(item.summaries)[0]]
        others = [item for item in ordered if item not in claimed]
        return (claimed + others)[:max_documents]
    return select


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", required=True)
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--output", type=Path, default=Path("data/official-ir-pdfs"))
    parser.add_argument("--market", default="sii")
    parser.add_argument("--max-documents", type=int, default=8)
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    for name in DISABLED_FOR_RUN:
        os.environ.pop(name, None)
    summary = []
    for ticker in [item.strip() for item in args.tickers.split(",") if item.strip()]:
        if (args.output / ticker / str(args.year) / "manifest.json").is_file():
            summary.append({"ticker": ticker, "status": "skipped_existing_archive"})
            continue
        result = run_mops_pdf_pipeline(ticker=ticker, year=args.year, market=args.market, output_dir=args.output,
                                       transport=PoliteTransport(args.delay),
                                       select_documents=select_recent(args.max_documents))
        documents = [doc for doc in result["documents"] if "sha256" in doc]
        summary.append({
            "ticker": ticker, "status": result["status"], "errors": result["errors"][:3],
            "listed": (result.get("selection") or {}).get("listed_documents"),
            "downloaded": result["downloaded_pdfs"], "expected": result["expected_pdfs"],
            "periods": sorted({doc.get("period") for doc in documents if doc.get("period")}),
            "types": sorted({doc.get("document_type") for doc in documents}),
            "quarantined": [doc["filename"] for doc in documents if doc.get("quarantined")],
        })
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
    print(json.dumps({"processed": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
