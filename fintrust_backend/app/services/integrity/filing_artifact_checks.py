"""Read-only checksum gate for archived official XBRL/HTML/PDF filing artifacts.

Checks bytes, path containment and file signature only. Source URL identity,
statement line identity and issuer are independently reviewed elsewhere.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any

VERSION = "fintrust_filing_artifact_checksum_v1"
_SHA = re.compile(r"^[0-9a-fA-F]{64}$")
_EXTENSIONS = frozenset({".html", ".htm", ".xhtml", ".xml", ".xbrl", ".pdf", ".zip"})
_MAX_FILE_BYTES = 80 * 1024 * 1024


def verify_filing_artifact(root: str | Path, filename: str, *, expected_sha256: str) -> dict[str, Any]:
    base = {"method_version": VERSION, "verified_bytes": False, "sha256": None,
            "reason": None, "official_source_identity_verified": False}
    if (not isinstance(filename, str) or not filename or Path(filename).is_absolute()
            or ":" in filename or "\\" in filename
            or any(p in ("", ".", "..") for p in filename.split("/"))):
        return {**base, "reason": "invalid_relative_archive_path"}
    if not isinstance(expected_sha256, str) or not _SHA.fullmatch(expected_sha256):
        return {**base, "reason": "invalid_expected_source_sha"}
    if Path(filename).suffix.lower() not in _EXTENSIONS:
        return {**base, "reason": "unsupported_filing_artifact_type"}
    try:
        rootpath = Path(root).resolve(strict=True)
        if not rootpath.is_dir():
            return {**base, "reason": "archive_root_not_directory"}
        current = Path(root)
        for part in filename.split("/"):
            current = current / part
            if current.is_symlink():
                return {**base, "reason": "symlink_in_archive_path"}
        path = current.resolve(strict=True)
        if not path.is_relative_to(rootpath) or not path.is_file():
            return {**base, "reason": "archive_path_outside_root"}
        size = path.stat().st_size
        if not 20 <= size <= _MAX_FILE_BYTES:
            return {**base, "reason": "invalid_archive_file_size"}
        digest = hashlib.sha256()
        with path.open("rb") as src:
            head = src.read(1024).lstrip(b"\xef\xbb\xbf \t\r\n").lower()
            ext = path.suffix.lower()
            if ext == ".pdf":
                valid = head.startswith(b"%pdf-")
            elif ext == ".zip":
                valid = head.startswith(b"pk\x03\x04")
            else:
                valid = any(tag in head[:500] for tag in (b"<html", b"<?xml", b"<xbrl", b"<!doctype"))
            if not valid:
                return {**base, "reason": "unsupported_or_invalid_filing_signature"}
            src.seek(0)
            for chunk in iter(lambda: src.read(65536), b""):
                digest.update(chunk)
        sha = digest.hexdigest()
        if sha != expected_sha256.lower():
            return {**base, "reason": "source_artifact_digest_mismatch", "sha256": sha}
        return {**base, "verified_bytes": True, "sha256": sha, "reason": "source_identity_still_requires_review"}
    except (OSError, ValueError, RuntimeError):
        return {**base, "reason": "archive_file_unavailable"}
