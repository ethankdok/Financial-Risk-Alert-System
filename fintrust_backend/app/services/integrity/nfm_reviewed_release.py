"""Operator-pinned, read-only official nonfinancial evidence release.

A manifest SHA-256 pin protects an operator-reviewed release from silent edits;
it is not, by itself, independent proof of document origin. The operator must
have checked source origin, issuer, scope, period, original PDF and quoted page.
This loader never writes the manifest, PDFs, DB, cloud or working directory.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from app.services.integrity.official_archive_integrity import verify_pdf_archive

VERSION = "fintrust_nfm_reviewed_release_v1"
_SHA = re.compile(r"^[a-fA-F0-9]{64}$")
_TICKER = re.compile(r"^[0-9]{4,6}$")
_HOSTS = frozenset({"mops.twse.com.tw", "mopsov.twse.com.tw", "www.twse.com.tw",
                    "www.tpex.org.tw", "doc.twse.com.tw", "emops.twse.com.tw"})
_MAX_MANIFEST_BYTES = 1024 * 1024
_MAX_RECORDS = 80


def _instant(value: Any) -> bool:
    if not isinstance(value, str) or "T" not in value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _official_url(raw: Any) -> bool:
    try:
        if not isinstance(raw, str) or len(raw) > 2048:
            return False
        link = urlsplit(raw)
        return (link.scheme == "https" and link.hostname in _HOSTS
                and link.username is None and link.password is None
                and link.port in (None, 443) and link.path.startswith("/")
                and not link.fragment)
    except ValueError:
        return False


def _positive_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        return False
    try:
        n = Decimal(str(value))
    except (ValueError, InvalidOperation):
        return False
    return n.is_finite() and n > 0


def load_approved_nfm_release(
    manifest_path: str | Path, *, approved_manifest_sha256: str,
    pdf_archive_root: str | Path,
) -> dict[str, Any]:
    """Load only operator-pinned and byte-checked archive observations.

    Malformed or unapproved rows reject the WHOLE release, never a subset.
    A matching digest records approval of these exact bytes, not their origin.
    """
    path = Path(manifest_path)
    if not _SHA.fullmatch(approved_manifest_sha256):
        raise ValueError("approved manifest digest is required")
    if path.is_symlink() or not path.is_file():
        raise ValueError("review manifest unavailable or symlink")
    if not 1 <= path.stat().st_size <= _MAX_MANIFEST_BYTES:
        raise ValueError("manifest exceeds bounded size")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != approved_manifest_sha256.lower():
        raise ValueError("manifest differs from operator-approved SHA-256")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("review manifest JSON invalid") from exc
    if not isinstance(manifest, dict) or manifest.get("release_version") != VERSION:
        raise ValueError("unsupported NFM release version")
    rows = manifest.get("records")
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_RECORDS:
        raise ValueError("reviewed release must contain 1-80 rows")
    prepared = []
    seen = set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("invalid NFM record")
        ticker = str(item.get("ticker") or "")
        year = item.get("fiscal_year")
        metric = str(item.get("measure") or "")
        value = item.get("value")
        scope = item.get("scope")
        policy = item.get("measurement_policy")
        basis = item.get("period_basis")
        pdf_sha = item.get("source_sha256")
        url = item.get("source_url")
        version_id = item.get("filing_version_id")
        review = item.get("review") or {}
        if (not _TICKER.fullmatch(ticker) or isinstance(year, bool)
                or not isinstance(year, int) or not 1990 <= year <= 2100):
            raise ValueError("invalid company or fiscal year")
        if (metric != "employees" or not _positive_number(value)
                or item.get("unit") != "persons" or scope not in ("consolidated", "individual")
                or basis not in ("year_end_stock", "annual_average")
                or not isinstance(policy, str) or not policy.strip()
                or not isinstance(version_id, str) or not version_id.strip()):
            raise ValueError("invalid NFM measurement identity")
        if not isinstance(pdf_sha, str) or not _SHA.fullmatch(pdf_sha) or not _official_url(url):
            raise ValueError("missing source checksum or official link")
        if not isinstance(review, dict):
            raise ValueError("invalid review attestation")
        if (review.get("status") != "approved"
                or review.get("ticker") != ticker or review.get("fiscal_year") != year
                or review.get("pdf_sha256", "").lower() != pdf_sha.lower()
                or review.get("scope") != scope
                or not _instant(review.get("reviewed_at"))
                or not all(review.get(k) is True for k in (
                    "source_origin_confirmed", "pdf_page_quote_confirmed",
                    "fiscal_period_confirmed", "metric_definition_confirmed",
                    "statement_scope_confirmed", "positively_scale_related"
                ))
                or isinstance(review.get("pdf_page"), bool)
                or not isinstance(review.get("pdf_page"), int)
                or review["pdf_page"] < 1):
            raise ValueError("operator source identity or page attestation incomplete")
        filename = item.get("archive_pdf_relative_path")
        if not isinstance(filename, str):
            raise ValueError("archive PDF relative path missing")
        result = verify_pdf_archive(
            pdf_archive_root, filename, expected_sha256=pdf_sha
        )
        if result.get("status") != "archive_bytes_verified":
            raise ValueError("reviewed PDF bytes do not match approved artifact")
        published = item.get("published_at")
        if published is not None and not _instant(published):
            raise ValueError("publication instant cannot be inferred from a date")
        key = (ticker, year, metric, version_id)
        if key in seen:
            raise ValueError("duplicate company/year/filing version")
        seen.add(key)
        prepared.append({
            "ticker": ticker, "fiscal_year": year,
            "measure": metric, "value": str(value), "unit": "persons",
            "scope": scope, "period_basis": basis,
            "measurement_policy": policy,
            "source_url": url, "source_sha256": pdf_sha.lower(),
            "filing_version_id": version_id,
            "published_at": published,
            "verified_source": True,
            "source_document_verified": True,
            "document_identity_verified": True,
            "scale_related": True,
            "review_method": "operator_pinned_manual_source_and_page_review",
        })
    return {
        "release_version": VERSION,
        "status": "operator_approved_artifact_release",
        "manifest_sha256": digest,
        "records": prepared,
        "independent_third_party_verified": False,
        "historical_pit_supported": all(r["published_at"] is not None for r in prepared),
        "note": "Approval is an operator source review, not cryptographic attestation by MOPS or independent third-party proof.",
    }
