"""Bounded, resumable recovery of official MOPS investor-conference PDFs for a historical case.

Run from fintrust_backend/:

    python -m scripts.recover_historical_conference_pdfs --ticker 1785 --years 2018 2019 2020 2021 2022 --market otc

This is a thin runner around the existing ``mops_conference_pdf_pipeline`` (no second pipeline):

- one announcement year per batch; the pipeline reuses every PDF already archived in the year's manifest
  (by SHA-256), so re-running the same command resumes and never duplicates;
- polite pacing between official requests (``--delay``), one retry with backoff for transient failures,
  and a stop condition: HTTP 403/429 (access restriction) or ``--max-consecutive-failures`` consecutive failed
  requests stop the run; remaining years are reported as ``not_attempted``;
- text-only extraction: ``semantic_analysis=False``, no OCR, and the multimodal (paid LLM) provider is disabled
  for this process, so no external model is called;
- after each year the official listing status is recorded with ``ConferenceCoverageRecorder`` (from the saved
  listing, no extra request).

Per-year outcome (``acquisition_status``, from the listing and the archived files, never from review status):
``complete`` (every listed PDF archived and hash-verified), ``no_official_record`` (MOPS 查無資料),
``no_documents_listed``, ``partial`` (some listed PDFs missing), ``failed`` (listing unavailable, nothing archived,
or an unexpected error) and ``stopped``. ``review_status`` separately reports pages still awaiting visual/semantic
review (expected while LLM/OCR analysis is disabled) and never fails the run.

Exit status: 0 = every year complete / no record / nothing listed; 1 = any year partial or failed; 2 = stopped.
The pipeline catches per-document exceptions, so a stop condition is tracked on the transport itself and short-
circuits every later request.

A meeting date is not a publication time; nothing here asserts public availability of a document.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.case_registry import get_case
from app.services.historical_audit.conference_coverage import ConferenceCoverageRecorder
from app.services.historical_audit.repository import HistoricalAuditRepository
from app.services.mops_conference_pdf_pipeline import AcquisitionError, HttpMopsTransport, run_mops_pdf_pipeline

ACCESS_RESTRICTED = ("HTTP Error 403", "HTTP Error 429")


class StopRecovery(RuntimeError):
    pass


class PacedTransport:
    """Wraps the pipeline transport: spacing, one backoff retry, and a fail-safe stop condition."""

    def __init__(self, inner, *, delay: float, max_consecutive_failures: int, sleep=time.sleep) -> None:
        self.inner, self.delay, self.cap, self.sleep = inner, delay, max_consecutive_failures, sleep
        self.requests = self.failures_in_row = 0
        self.log: list[dict] = []
        self.stopped: str | None = None

    def _stop(self, reason: str) -> StopRecovery:
        self.stopped = reason
        return StopRecovery(reason)

    def _call(self, kind: str, label: str, function):
        if self.stopped:  # the pipeline swallows exceptions; never issue another request once stopped
            raise StopRecovery(self.stopped)
        for attempt in (1, 2):
            if self.requests:
                self.sleep(self.delay if attempt == 1 else self.delay * 4)
            self.requests += 1
            try:
                result = function()
                self.failures_in_row = 0
                self.log.append({"request": kind, "target": label, "attempt": attempt, "status": "ok"})
                return result
            except AcquisitionError as exc:
                message = str(exc)
                self.failures_in_row += 1
                self.log.append({"request": kind, "target": label, "attempt": attempt, "status": "failed", "error": message})
                if any(code in message for code in ACCESS_RESTRICTED):
                    raise self._stop(f"access restricted by the official source: {message}") from exc
                if self.failures_in_row >= self.cap:
                    raise self._stop(f"{self.failures_in_row} consecutive failed requests; stopping") from exc
                if attempt == 2:
                    raise

    def listing(self, ticker, roc_year, market, page=1):
        return self._call("listing", f"{ticker}/{roc_year}/p{page}", lambda: self.inner.listing(ticker, roc_year, market, page=page))

    def pdf(self, attachment, referer):
        return self._call("pdf", attachment.filename, lambda: self.inner.pdf(attachment, referer))


ACQUISITION_OK = ("complete", "no_official_record", "no_documents_listed")


def classify_year(result: dict) -> tuple[str, str]:
    """(acquisition_status, review_status) for one pipeline result; review never decides acquisition."""
    documents = result.get("documents", [])
    errors = " ".join(str(e) for e in result.get("errors", []) or []) + " " + str(result.get("error") or "")
    listed = {d.get("filename") for d in documents if d.get("filename")}
    archived = {d.get("filename") for d in documents if d.get("sha256")}
    if not result.get("listing_pages"):
        acquisition = "no_official_record" if "查無資料" in errors or result.get("status") == "no_listing" else "failed"
    elif not listed:
        acquisition = "no_documents_listed"
    elif archived >= listed:
        acquisition = "complete"
    else:
        acquisition = "partial" if archived else "failed"
    pending = [d for d in documents if d.get("sha256") and d.get("status") != "complete"]
    review = "not_applicable" if not archived else ("visual_review_pending" if pending else "complete")
    return acquisition, review


def exit_code(years: dict) -> int:
    statuses = [summary.get("acquisition_status") for summary in years.values()]
    if "stopped" in statuses or "not_attempted" in statuses:
        return 2
    return 0 if all(status in ACQUISITION_OK for status in statuses) else 1


def year_summary(result: dict) -> dict:
    documents = result.get("documents", [])
    integrity = result.get("integrity", {})
    acquisition, review = classify_year(result)
    return {
        "acquisition_status": acquisition, "review_status": review, "pipeline_status": result.get("status"),
        "rows": result.get("rows"), "expected_pdfs": result.get("expected_pdfs"),
        "downloaded_pdfs": result.get("downloaded_pdfs"),
        "hash_verified": sum(1 for d in documents if d.get("sha256")),
        "missing": [d["filename"] for d in documents if not d.get("sha256")],
        "non_pdf_attachments": [a.get("filename") for a in result.get("non_pdf_attachments") or []],
        "pages": sum(int(d.get("page_count") or 0) for d in documents),
        "text_pages": sum(int(d.get("text_pages") or 0) for d in documents),
        "errors": result.get("errors", []), "manifest_path": result.get("manifest_path"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--years", type=int, nargs="+", required=True)
    parser.add_argument("--market", required=True, choices=("sii", "otc", "rotc", "pub"))
    parser.add_argument("--output", type=Path, default=Path("data/historical-conference-pdfs"))
    parser.add_argument("--database", type=Path, default=Path("data/historical_audit/historical_audit.sqlite3"))
    parser.add_argument("--archive", type=Path, default=Path("data/historical_audit/raw"))
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--max-consecutive-failures", type=int, default=3)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args(argv)

    # No paid/external model in this run, whatever the shell environment holds.
    os.environ["CONFERENCE_PDF_MULTIMODAL_PROVIDER"] = ""
    os.environ["CONFERENCE_PDF_OCR_PROVIDER"] = ""
    from app.services.conference_pdf_multimodal import build_region_interpreter_from_env

    assert build_region_interpreter_from_env() is None

    case = get_case(args.ticker)
    transport = PacedTransport(HttpMopsTransport(), delay=args.delay, max_consecutive_failures=args.max_consecutive_failures)
    recorder = ConferenceCoverageRecorder(HistoricalAuditRepository(str(args.database)), RawEvidenceArchive(args.archive),
                                          args.output)
    report, code = run_recovery(case, args.years, market=args.market, output=args.output, transport=transport,
                                recorder=recorder)
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.report_json:
        args.report_json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return code


def run_recovery(case, years, *, market: str, output: Path, transport: PacedTransport, recorder,
                 pipeline=run_mops_pdf_pipeline) -> tuple[dict, int]:
    """One year per batch; returns the per-year report and the exit status (see the module docstring)."""
    report: dict = {"ticker": case.ticker, "market": market, "years": {}}
    for year in years:
        if transport.stopped:
            report["years"][year] = {"acquisition_status": "not_attempted", "reason": transport.stopped}
            continue
        try:
            result = pipeline(ticker=case.ticker, year=year, market=market, output_dir=output,
                              ocr=False, transport=transport, semantic_analysis=False)
            summary = year_summary(result)
        except StopRecovery:
            summary = {"acquisition_status": "stopped"}
        except Exception as exc:  # noqa: BLE001 - one year's failure is reported, the next year still runs
            summary = {"acquisition_status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        if transport.stopped and summary.get("acquisition_status") != "complete":
            summary.update(acquisition_status="stopped", reason=transport.stopped)
        try:
            coverage = recorder.record(case.ticker, [year], market=market, start_year=case.default_start_year,
                                       end_year=case.default_end_year)[0]
            summary["coverage"] = {key: coverage[key] for key in (
                "status", "conference_rows", "meeting_dates_json", "expected_documents", "downloaded_documents",
                "non_pdf_attachments", "missing_documents")}
        except Exception as exc:  # noqa: BLE001 - coverage recording failure must not hide the acquisition result
            summary["coverage_error"] = f"{type(exc).__name__}: {exc}"
        report["years"][year] = summary
    report["requests"] = transport.requests
    report["request_log"] = transport.log
    report["stopped"] = transport.stopped
    code = exit_code(report["years"])
    report["exit_code"] = code
    return report, code


if __name__ == "__main__":
    raise SystemExit(main())
