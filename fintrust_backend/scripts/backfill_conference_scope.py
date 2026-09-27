"""Backfill one metadata-feasible MOPS conference scope through the existing pipeline.

Staged by design: ``--periods`` downloads only the listed potential periods (for
PDF identity sampling). A full scope run (``--all-periods``) additionally needs a
``--validated-sample`` report whose status is ``passed`` for the same scope.
Only filenames selected by the metadata discovery report are downloaded, and
Gemini, OCR and production publish/write-through stay disabled.

Run from fintrust_backend:
  python -m scripts.backfill_conference_scope --discovery ../docs/data/conference-pdf-discovery-2017-2025.json \\
      --feasibility ../docs/data/conference-pdf-feasibility-2017-2025.json --ticker 2330 \\
      --metadata-class quarterly_results_candidate --language en --periods 2017Q1 \\
      --output data/historical-conference-pdfs
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.services.mops_conference_pdf_pipeline import HttpMopsTransport, ListedAttachment, run_mops_pdf_pipeline
from scripts.build_conference_feasibility import classify_listing_document, language_scope

DISABLED_FOR_RUN = ("CONFERENCE_PDF_MULTIMODAL_PROVIDER", "CONFERENCE_PDF_OCR_PROVIDER", "CONFERENCE_PDF_ARCHIVE_PUBLISH")


class PoliteTransport:
    def __init__(self, delay: float) -> None:
        self.inner = HttpMopsTransport()
        self.delay = delay

    def listing(self, *args, **kwargs):
        time.sleep(self.delay)
        return self.inner.listing(*args, **kwargs)

    def pdf(self, *args, **kwargs):
        time.sleep(self.delay)
        return self.inner.pdf(*args, **kwargs)


def selected_documents(discovery: dict[str, Any], *, ticker: str, metadata_class: str, language: str,
                       periods: set[str] | None = None) -> dict[int, dict[str, str]]:
    """{announcement year: {filename: potential period}} for one exact metadata scope."""
    company = next((item for item in discovery.get("companies", []) if item.get("ticker") == ticker), None)
    if not company:
        raise ValueError(f"Ticker {ticker} is not present in discovery")
    by_year: dict[int, dict[str, str]] = defaultdict(dict)
    for document in company.get("documents", []):
        identity = classify_listing_document(document)
        if identity["metadata_class"] != metadata_class or language_scope(document.get("language")) != language:
            continue
        period = identity["period"]
        if not period or (periods is not None and period not in periods):
            continue
        dates = document.get("conference_dates") or []
        if not dates:
            continue
        year = int(str(dates[0]).split("/", 1)[0]) + 1911
        by_year[year][document["filename"]] = period
    return dict(sorted(by_year.items()))


def eligible_scope(feasibility: dict[str, Any], *, ticker: str, metadata_class: str, language: str) -> dict[str, Any]:
    for scope in feasibility.get("scopes", []):
        if (
            scope.get("ticker") == ticker
            and scope.get("metadata_class") == metadata_class
            and scope.get("language") == language
        ):
            if not scope.get("staged_identity_validation_eligible"):
                raise ValueError(f"Scope is not eligible for staged validation: "
                                 f"{scope.get('staged_identity_validation_blockers')}")
            return scope
    raise ValueError("Scope is not present in feasibility matrix")


def require_validated_sample(report_path: Path | None, *, ticker: str, metadata_class: str, language: str) -> None:
    if report_path is None:
        raise ValueError("--all-periods requires --validated-sample from a passed staged identity validation")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    scope = (report.get("ticker"), report.get("metadata_class"), report.get("language"))
    if scope != (ticker, metadata_class, language) or report.get("status") != "passed":
        raise ValueError(f"Validated sample does not pass for this scope: {scope} status={report.get('status')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--feasibility", type=Path, required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--metadata-class", required=True)
    parser.add_argument("--language", required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--periods", help="Comma-separated potential periods to download (staged sample)")
    selection.add_argument("--all-periods", action="store_true")
    parser.add_argument("--validated-sample", type=Path)
    parser.add_argument("--output", type=Path, default=Path("data/historical-conference-pdfs"))
    parser.add_argument("--market", default="sii")
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    if args.delay < 1.0:
        raise ValueError("Use --delay >= 1.0 for live MOPS backfill")
    for name in DISABLED_FOR_RUN:
        os.environ.pop(name, None)
    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    feasibility = json.loads(args.feasibility.read_text(encoding="utf-8"))
    scope = eligible_scope(feasibility, ticker=args.ticker, metadata_class=args.metadata_class, language=args.language)
    periods = None
    if args.all_periods:
        require_validated_sample(args.validated_sample, ticker=args.ticker, metadata_class=args.metadata_class,
                                 language=args.language)
    else:
        periods = {item.strip().upper() for item in args.periods.split(",") if item.strip()}
    by_year = selected_documents(discovery, ticker=args.ticker, metadata_class=args.metadata_class,
                                 language=args.language, periods=periods)
    summary = {
        "ticker": args.ticker,
        "metadata_class": args.metadata_class,
        "language": args.language,
        "mode": "all_periods" if args.all_periods else "staged_sample",
        "requested_periods": sorted(periods) if periods is not None else None,
        "potential_historical_pairs": scope["potential_historical_adjacent_pairs_before_target"],
        "selected_pdf_count": sum(len(items) for items in by_year.values()),
        "years": {},
        "status": "completed",
    }
    transport = PoliteTransport(args.delay)
    for year, wanted in by_year.items():
        def select(attachments: list[ListedAttachment], names=frozenset(wanted)) -> list[ListedAttachment]:
            return [item for item in attachments if item.filename in names]

        result = run_mops_pdf_pipeline(
            ticker=args.ticker,
            year=year,
            market=args.market,
            output_dir=args.output,
            transport=transport,
            select_documents=select,
        )
        downloaded = [doc for doc in result.get("documents", []) if "sha256" in doc]
        summary["years"][str(year)] = {
            "status": result.get("status"),
            "selected": wanted,
            "downloaded": len(downloaded),
            "expected": result.get("expected_pdfs"),
            "errors": result.get("errors", [])[:5],
            "documents": [
                {"filename": doc["filename"], "potential_period": wanted.get(doc["filename"]),
                 "period": doc.get("period"), "period_validation_status": doc.get("period_validation_status"),
                 "document_type": doc.get("document_type"),
                 "language": doc.get("document_language") or doc.get("language"),
                 "sha256": doc.get("sha256"), "quarantined": bool(doc.get("quarantined")),
                 "quarantine_reasons": doc.get("quarantine_reasons") or []}
                for doc in downloaded
            ],
        }
        print(json.dumps({"year": year, **summary["years"][str(year)]}, ensure_ascii=False), flush=True)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("ticker", "metadata_class", "language", "mode",
                                                     "selected_pdf_count", "status")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
