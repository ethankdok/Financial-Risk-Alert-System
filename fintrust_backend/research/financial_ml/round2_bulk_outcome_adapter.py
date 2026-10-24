"""Auditable, bulk issuer-year outcome intake for a *supplied historical archive*.

Expected CSV (one issuer-year, no artificial negatives):
ticker,fiscal_year,annual_core_restatement_event,event_notice_date,
first_annual_filed_at,followup_end_at,full_24m_event_coverage,
source_url,source_archive_sha256,statement_scope,reviewer_status

A source document must support each 1 (specific annual-core correction event);
a 0 must have a >=24-month source search ending at/after first filing +24mo.
A present-day roster NEVER implies 0. All outputs remain SOURCE_REPORTED
until an independent official-vintage audit is completed.

No dataset is bundled; this adapter enables TEJ TT2/licensed or official
historic CSV exports when actually available, without pretending to fetch them.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = (
    "ticker", "fiscal_year", "annual_core_restatement_event",
    "event_notice_date", "first_annual_filed_at", "followup_end_at",
    "full_24m_event_coverage", "source_url", "source_archive_sha256",
    "statement_scope", "reviewer_status",
)
OUT = (
    "ticker", "fiscal_year", "y", "target", "first_annual_filed_at",
    "label_observation_end_at", "event_notice_date", "source_url",
    "source_archive_sha256", "label_evidence_level",
)
TARGET = "ANNUAL_CORE_RESTATEMENT_WITHIN_24M_OF_ORIGINAL_FILING"


def add_24m(d):
    year = d.year + 2
    day = min(d.day, 28) if d.month == 2 else d.day
    return date(year, d.month, day)


def validate_row(r, *, as_of=date(2026, 10, 24)):
    ticker = str(r["ticker"]).strip()
    fy = int(r["fiscal_year"])
    if len(ticker) != 4 or not ticker.isascii() or not ticker.isdecimal():
        raise ValueError("bad_issuer_key")
    if fy < 2013 or fy > 2023:
        raise ValueError("outside_training_fiscal_year_range")
    if ticker == "1785":
        raise ValueError("reserved_case_leakage")
    if r["statement_scope"] != "consolidated_annual":
        raise ValueError("not_comparable_annual_consolidated")
    if (r["reviewer_status"] != "SOURCE_REPORTED_REVIEWABLE" or
            len(r["source_archive_sha256"]) != 64 or
            any(x not in "0123456789abcdef" for x in r["source_archive_sha256"].lower())):
        raise ValueError("insufficient_source_archive_provenance")
    u = urlparse(r["source_url"])
    if u.scheme != "https" or not u.hostname:
        raise ValueError("invalid_source_url")
    filed = date.fromisoformat(r["first_annual_filed_at"])
    if not fy <= filed.year <= fy + 2:
        raise ValueError("first_annual_filing_inconsistent_year")
    if filed > as_of:
        raise ValueError("future_first_filing")
    horizon = add_24m(filed)
    event = r["annual_core_restatement_event"]
    if event == "1":
        if not r["event_notice_date"]:
            raise ValueError("positive_without_event_date")
        announcement = date.fromisoformat(r["event_notice_date"])
        if not filed < announcement <= min(as_of, horizon):
            raise ValueError("positive_outside_24m_or_asof")
        y = "1"
    elif event == "0":
        if r["event_notice_date"]:
            raise ValueError("negative_has_event_date")
        if r["full_24m_event_coverage"] != "true":
            raise ValueError("negative_missing_complete_24m_coverage")
        if not r["followup_end_at"]:
            raise ValueError("negative_missing_followup")
        covered_to = date.fromisoformat(r["followup_end_at"])
        if not horizon <= covered_to <= as_of:
            raise ValueError("negative_censored_or_bad_coverage_date")
        y = "0"
    else:
        raise ValueError("not_a_verified_numeric_outcome")
    return {
        "ticker": ticker, "fiscal_year": str(fy), "y": y,
        "target": TARGET, "first_annual_filed_at": filed.isoformat(),
        "label_observation_end_at": horizon.isoformat(),
        "event_notice_date": r["event_notice_date"], "source_url": r["source_url"],
        "source_archive_sha256": r["source_archive_sha256"].lower(),
        "label_evidence_level": "SOURCE_REPORTED_NEEDS_INDEPENDENT_AUDIT",
    }


def build(input_csv, output, *, as_of=date(2026, 10, 24)):
    blob = Path(input_csv).read_bytes()
    text = blob.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not set(REQUIRED).issubset(reader.fieldnames or []):
        raise ValueError("bulk_outcome_missing_required_columns")
    rows = []
    keys = set()
    for raw in reader:
        if not any(raw.values()):
            continue
        row = validate_row(raw, as_of=as_of)
        key = (row["ticker"], row["fiscal_year"])
        if key in keys:
            raise ValueError("bulk_outcome_duplicate_or_conflicting_issuer_year")
        keys.add(key)
        rows.append(row)
    if not rows:
        raise ValueError("no_source_supported_binary_labels")
    rows.sort(key=lambda x: (x["ticker"], x["fiscal_year"]))
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=OUT, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    payload = stream.getvalue().encode("utf-8")
    report = {
        "source_sha256": hashlib.sha256(blob).hexdigest(),
        "output_sha256": hashlib.sha256(payload).hexdigest(),
        "total_rows": len(rows), "counts": dict(Counter(x["y"] for x in rows)),
        "target": TARGET, "source_reported_labels_only": True,
        "actual_official_archive_independently_reverified": False,
        "no_default_zeros_from_company_roster": True,
    }
    files = {
        out / "round2_bulk_labels.csv": payload,
        out / "round2_bulk_labels_report.json":
            (json.dumps(report, indent=2, sort_keys=True) + "\n").encode(),
    }
    for file, data in files.items():
        if file.exists() and file.read_bytes() != data:
            raise FileExistsError("bulk_outcome_no_silent_overwrite")
        if not file.exists():
            file.write_bytes(data)
    return report


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--input-csv", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    print(json.dumps(build(a.input_csv, a.out), indent=2))


if __name__ == "__main__":
    main()
