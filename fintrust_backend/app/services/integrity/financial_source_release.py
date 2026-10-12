"""Operator-pinned provenance overlays for already stored financial revenue facts.

No amount is recalculated or persisted. Every overlay must match an existing
fact's company, annual period, selected evidence ID, exact TWD number and
validated MOPS report URL. Original artifact bytes and manual page/line
review are required before a source SHA can be attached to a read-only copy.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.services.integrity.alignment import mops_filing_identity
from app.services.integrity.filing_artifact_checks import verify_filing_artifact

VERSION = "fintrust_financial_source_release_v1"
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
TICKER = re.compile(r"^[0-9]{4,6}$")


def _iso_instant(value: Any) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return instant.tzinfo is not None and instant.utcoffset() is not None


def _num(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return None
    try:
        n = Decimal(str(value))
    except (ValueError, InvalidOperation):
        return None
    return n if n.is_finite() else None


def load_approved_financial_source_release(
    release_path: str | Path, *, approved_manifest_sha256: str, archive_root: str | Path
) -> dict[str, Any]:
    path = Path(release_path)
    if not SHA256.fullmatch(str(approved_manifest_sha256 or "")):
        raise ValueError("operator-approved source manifest SHA required")
    if path.is_symlink() or not path.is_file() or not 1 <= path.stat().st_size <= 1024 * 1024:
        raise ValueError("source manifest unavailable or oversized")
    raw = path.read_bytes()
    computed = hashlib.sha256(raw).hexdigest()
    if computed != approved_manifest_sha256.lower():
        raise ValueError("source manifest not pinned to approved bytes")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("source release JSON invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("release_version") != VERSION:
        raise ValueError("unsupported financial source release")
    rows = manifest.get("records")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("financial source release must have 1-100 records")
    verified = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("source release record invalid")
        ticker = str(row.get("ticker") or "")
        year = row.get("fiscal_year")
        source_sha = str(row.get("source_sha256") or "")
        url = row.get("source_url")
        filename = row.get("archive_relative_path")
        review = row.get("review")
        version = row.get("filing_version")
        amount = row.get("value_twd")
        if (not TICKER.fullmatch(ticker) or isinstance(year, bool) or not isinstance(year, int)
                or not 1990 <= year <= 2100 or _num(amount) is None
                or not SHA256.fullmatch(source_sha)
                or not isinstance(filename, str) or not isinstance(review, dict)
                or not isinstance(version, str) or not isinstance(row.get("evidence_id"), str)):
            raise ValueError("incomplete financial source identity")
        identity = mops_filing_identity(url, ticker=ticker)
        if not (identity["recognised"] and identity["filing_fiscal_year"] == year
                and identity["season"] == 4 and identity["scope"] == "consolidated"
                and identity["filing_version"] == version):
            raise ValueError("official MOPS company or filing identity mismatch")
        if (review.get("status") != "approved"
                or review.get("ticker") != ticker or review.get("fiscal_year") != year
                or review.get("evidence_id") != row["evidence_id"]
                or str(review.get("source_sha256") or "").lower() != source_sha.lower()
                or not isinstance(review.get("review_id"), str)
                or not review["review_id"].strip()
                or not isinstance(review.get("verbatim_line"), str)
                or not 8 <= len(review["verbatim_line"].strip()) <= 600
                or _num(review.get("reviewed_value_twd")) != _num(amount)
                or not _iso_instant(review.get("reviewed_at"))
                or not all(review.get(k) is True for k in (
                    "official_download_confirmed", "company_identity_confirmed",
                    "filing_year_confirmed", "revenue_statement_line_confirmed",
                    "consolidated_scope_confirmed", "amount_and_unit_confirmed"
                ))):
            raise ValueError("operator filing/line verification incomplete")
        bytes_check = verify_filing_artifact(archive_root, filename, expected_sha256=source_sha)
        if not bytes_check["verified_bytes"]:
            raise ValueError("approved financial artifact bytes did not match")
        published = row.get("published_at")
        if published is not None and not _iso_instant(published):
            raise ValueError("date-only time is not a verified publication instant")
        key = (ticker, year)
        if key in seen:
            raise ValueError("ambiguous approved revenue filing per year")
        seen.add(key)
        verified.append({
            "ticker": ticker, "fiscal_year": year, "evidence_id": row["evidence_id"],
            "filing_version": version, "source_url": url, "source_sha256": source_sha.lower(),
            "value_twd": str(amount), "published_at": published,
            "review_method": "operator_pinned_manual_original_filing_review",
        })
    return {
        "status": "operator_approved_source_overlays", "release_version": VERSION,
        "manifest_sha256": computed, "records": verified,
        "independent_third_party_verified": False,
    }


def overlay_approved_revenue(
    index: dict[tuple[str, int], dict[str, Any]],
    verified_records: list[dict[str, Any]],
    *, ticker: str,
) -> dict[tuple[str, int], dict[str, Any]]:
    """Return a new index; fail on any attestation mismatch, never change facts."""
    out = {key: dict(value) for key, value in index.items()}
    for overlay in verified_records:
        if overlay.get("ticker") != ticker:
            continue
        year = overlay["fiscal_year"]
        row = out.get(("revenue", year))
        if (row is None or row.get("ticker") != ticker
                or row.get("fiscal_period") != f"{year}FY"
                or row.get("period_type") != "annual"
                or row.get("scope") != "consolidated"
                or row.get("source_trust") != "validated_mops_filing"
                or row.get("filing_policy") != "as_filed_own_year"
                or row.get("filing_version") != overlay["filing_version"]
                or row.get("source_url") != overlay["source_url"]
                or row.get("evidence_id") != overlay["evidence_id"]
                or _num(row.get("value_twd")) != _num(overlay["value_twd"])):
            raise ValueError("approved original filing does not match persisted selected revenue fact")
        row["source_sha256"] = overlay["source_sha256"]
        row["source_document_verified"] = True
        row["effective_available_at"] = overlay["published_at"]
        row["effective_available_at_precision"] = (
            "exact_instant" if overlay["published_at"] is not None else "unknown"
        )
        if overlay["published_at"] is not None:
            row["published_at"] = overlay["published_at"]
        row["pit_eligible"] = overlay["published_at"] is not None
        row["pit_reason"] = ("source_publication_instant_verified" if overlay["published_at"] is not None
                             else "official_publication_time_unknown")
        row["missing_fields"] = [
            field for field in row.get("missing_fields", [])
            if field != "source_sha256"
            and not (overlay["published_at"] is not None
                     and field in ("published_at", "effective_available_at"))
        ]
    return out
