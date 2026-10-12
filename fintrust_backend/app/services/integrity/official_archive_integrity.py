"""Read-only local archive byte-integrity preflight for official financial/NFM sources.

This verifies bytes and a declared digest only. It NEVER sets
verified_official_document, document_identity_verified or published_at.
Those require separate source-identity and public-availability evidence.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

VERSION = "fintrust_source_archive_integrity_v1"
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_BYTES = 80 * 1024 * 1024


def verify_pdf_archive(
    root: str | Path, relative_filename: str, *, expected_sha256: str
) -> dict[str, Any]:
    """Audit bytes under an explicit read-only root; refuse symlinks and traversal."""
    result: dict[str, Any] = {
        "method_version": VERSION,
        "status": "not_verified", "reason": None,
        "sha256": None, "size_bytes": None,
        "file_bytes_match": False,
        "official_identity_verified": False,
        "official_publication_verified": False,
        "eligible_as_model_source": False,
    }
    base = Path(root)
    if (not isinstance(relative_filename, str) or not relative_filename
            or Path(relative_filename).is_absolute() or "\\" in relative_filename
            or ":" in relative_filename
            or any(x in ("", ".", "..") for x in relative_filename.split("/"))):
        return {**result, "reason": "invalid_relative_path"}
    if not SHA256.fullmatch(str(expected_sha256)):
        return {**result, "reason": "missing_or_invalid_expected_digest"}
    try:
        base_resolved = base.resolve(strict=True)
        file_candidate = base.joinpath(*relative_filename.split("/"))
        if not base_resolved.is_dir() or not file_candidate.is_file():
            return {**result, "reason": "file_missing_or_root_unavailable"}
        current = base
        for part in relative_filename.split("/"):
            current = current / part
            if current.is_symlink():
                return {**result, "reason": "symlink_not_allowed"}
        resolved = file_candidate.resolve(strict=True)
        if not resolved.is_relative_to(base_resolved):
            return {**result, "reason": "outside_archive_root"}
        size = resolved.stat().st_size
        if size < 20 or size > MAX_BYTES:
            return {**result, "reason": "invalid_or_oversized_pdf"}
        sha = hashlib.sha256()
        with resolved.open("rb") as src:
            if not src.read(1024).startswith(b"%PDF-"):
                return {**result, "reason": "missing_pdf_signature"}
            src.seek(0)
            for chunk in iter(lambda: src.read(64 * 1024), b""):
                sha.update(chunk)
        digest = sha.hexdigest()
    except (OSError, RuntimeError, ValueError):
        return {**result, "reason": "archive_read_error"}
    if digest.lower() != expected_sha256.lower():
        return {**result, "reason": "digest_mismatch", "size_bytes": size,
                "sha256": digest}
    return {
        **result,
        "status": "archive_bytes_verified",
        "reason": "official_identity_and_publication_still_need_independent_verification",
        "sha256": digest, "size_bytes": size, "file_bytes_match": True,
    }
