"""Reviewer-attested *positive-only* FinLab/MOPS event ledger gate.

Never issues Y=0. A reviewer's entered URLs/dates are checked for consistency;
this module does not download external MOPS evidence and therefore does not
claim it independently verified a source. Positive labels have REVIEWER_ATTESTED
provenance and are not automatically considered gold.

Make a PRIVATE copy of the review CSV and add columns:
  reviewer_evidence_checked, verified_event_kind, core_line_item,
  verified_old_value, verified_new_value
Then fill existing evidence columns and adjudication=APPROVE_SOURCE_REVIEW.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

from research.financial_ml.round2_finlab_evidence import _write_immutable

DOC_FIELDS = (
    "mops_notice_url", "original_financial_filing_url",
    "first_report_public_date", "verified_correction_date", "scope_verified",
    "reviewer_evidence_checked", "verified_event_kind", "adjudication",
)
RESULT_COLS = (
    "case_id", "ticker", "fiscal_year", "y_event_restatement_or_core_24m",
    "y_core_change_24m", "first_report_public_date", "verified_correction_date",
    "observation_end_date", "review_provenance", "mops_notice_url",
    "original_financial_filing_url", "reviewed_core_line_item",
    "source_input_sha256",
)
FAILED_COLS = ("case_id", "reason")
OFFICIAL_SUFFIXES = ("mops.twse.com.tw", "doc.twse.com.tw")


def _official_url(raw):
    try:
        url = urlparse(raw)
    except ValueError:
        return False
    return (
        url.scheme == "https" and
        (url.hostname or "").lower() in OFFICIAL_SUFFIXES and bool(url.path)
    )


def _shift_months(d, months):
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _date(v):
    return date.fromisoformat(v)


def _csv(fields, records):
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(records)
    return buf.getvalue().encode("utf-8-sig")


def _money(v):
    x = Decimal(v.replace(",", "").strip())
    return x if x.is_finite() else None


def _check_one(r):
    if r.get("holdout", "").lower() == "true" or r.get("ticker") == "1785":
        return "RESERVED_HOLDOUT"
    fy = int(r.get("fiscal_year") or 0)
    if fy not in range(2013, 2024):
        return "UNSUPPORTED_FISCAL_YEAR"
    if (r.get("reviewer_evidence_checked") or "").lower() not in ("yes", "true"):
        return "MISSING_REVIEWER_ATTESTATION"
    if not _official_url(r.get("mops_notice_url") or ""):
        return "MISSING_OFFICIAL_MOPS_EVENT_URL"
    if not _official_url(r.get("original_financial_filing_url") or ""):
        return "MISSING_OFFICIAL_ORIGINAL_FINANCIAL_FILING_URL"
    if (r.get("scope_verified") or "").lower() not in ("consolidated", "合併"):
        return "SCOPE_NOT_CONFIRMED_CONSOLIDATED"
    try:
        original = _date(r["first_report_public_date"])
        corrective = _date(r["verified_correction_date"])
    except (ValueError, KeyError, TypeError):
        return "INVALID_PUBLIC_FILING_DATES"
    if original.year < fy or corrective < original:
        return "CHRONOLOGICALLY_IMPOSSIBLE"
    if corrective > date(2026, 10, 24):
        return "EVENT_AFTER_CUTOFF"
    if corrective > _shift_months(original, 24):
        return "EVENT_OUTSIDE_24_MONTH_WINDOW"
    kind = r.get("verified_event_kind") or ""
    if kind not in ("RESTATEMENT", "CORE_AMOUNT_CORRECTION"):
        return "EVENT_KIND_NOT_IN_RESEARCH_TARGET"
    if kind == "CORE_AMOUNT_CORRECTION":
        if (r.get("line_items_old_new_verified") or "").lower() != "true":
            return "CORE_OLD_NEW_NOT_REVIEWED"
        if not (r.get("core_line_item") or "").strip():
            return "CORE_LINE_ITEM_NOT_IDENTIFIED"
        try:
            before = _money(r.get("verified_old_value") or "")
            after = _money(r.get("verified_new_value") or "")
        except InvalidOperation:
            return "INVALID_OLD_NEW_AMOUNTS"
        if before is None or after is None or before == after:
            return "CORE_OLD_NEW_NOT_DIFFERENT"
    return ""


def build(reviewed_csv, out):
    path = Path(reviewed_csv)
    raw = path.read_bytes()
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        decoded = raw.decode("cp950")
    reader = csv.DictReader(io.StringIO(decoded))
    fields = set(reader.fieldnames or [])
    if not set(DOC_FIELDS).issubset(fields):
        raise ValueError("missing_review_source_columns")
    if not {
        "case_id", "ticker", "fiscal_year", "holdout", "line_items_old_new_verified"
    }.issubset(fields):
        raise ValueError("missing_original_case_columns")
    approved = []
    rejected = []
    seen = set()
    for row in reader:
        if (row.get("adjudication") or "") != "APPROVE_SOURCE_REVIEW":
            continue
        cid = row["case_id"]
        if cid in seen:
            rejected.append({"case_id": cid, "reason": "DUPLICATE_CASE_APPROVAL"})
            continue
        seen.add(cid)
        error = _check_one(row)
        if error:
            rejected.append({"case_id": cid, "reason": error})
            continue
        original = date.fromisoformat(row["first_report_public_date"])
        kind = row["verified_event_kind"]
        approved.append({
            "case_id": cid, "ticker": row["ticker"], "fiscal_year": row["fiscal_year"],
            "y_event_restatement_or_core_24m": "1",
            "y_core_change_24m": "1" if kind == "CORE_AMOUNT_CORRECTION" else "",
            "first_report_public_date": row["first_report_public_date"],
            "verified_correction_date": row["verified_correction_date"],
            "observation_end_date": _shift_months(original, 24).isoformat(),
            "review_provenance": "REVIEWER_ATTESTED_NOT_AUTO_VERIFIED",
            "mops_notice_url": row["mops_notice_url"],
            "original_financial_filing_url": row["original_financial_filing_url"],
            "reviewed_core_line_item": row.get("core_line_item") or "",
            "source_input_sha256": hashlib.sha256(raw).hexdigest(),
        })
    out = Path(out)
    good = _csv(RESULT_COLS, approved)
    bad = _csv(FAILED_COLS, rejected)
    summary = {
        "schema": "fintrust_round2_review_gate_v1",
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "reviewer_attested_positive_event_count": len(approved),
        "reviewer_attested_positive_core_count": sum(
            r["y_core_change_24m"] == "1" for r in approved
        ),
        "reject_count": len(rejected),
        "reject_reasons": dict(sorted(Counter(r["reason"] for r in rejected).items())),
        "negative_0_issued": 0,
        "warning": (
            "Manual reviewer attestation is NOT independently verified by code; "
            "MOPS links are syntactically checked only. Confirm original versions "
            "and document hashes before academic gold-label claims."
        ),
    }
    _write_immutable(out / "reviewer_attested_positives_private.csv", good)
    _write_immutable(out / "review_gate_rejected_private.csv", bad)
    _write_immutable(
        out / "review_gate_summary.json",
        (json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reviewed-csv", required=True)
    p.add_argument("--out", required=True)
    a = p.parse_args()
    print(json.dumps(build(a.reviewed_csv, a.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
