"""Standard-library-only verifier for FinTrust historical research packages.

This exact file is also shipped inside each package as
``validation/verify_package.py`` so researchers can verify a ZIP or an extracted
directory without FinTrust code, a database or cloud credentials::

    python verify_package.py fintrust_historical_research_dataset.zip
    python verify_package.py path/to/extracted/fintrust_historical_research_dataset

Checks: safe member paths (no absolute, drive, ``..``, backslash or symlink
entries, no duplicates, bounded size), the manifest's SHA-256 of
``validation/checksums.sha256``, the SHA-256 and size of every listed file, no
unlisted files, and that content-addressed raw evidence names equal their hash.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

PACKAGE_ROOT = "fintrust_historical_research_dataset"
CHECKSUMS = "validation/checksums.sha256"
MANIFEST = "manifest.json"
MAX_TOTAL_BYTES = 4 * 1024 ** 3
MAX_MEMBERS = 20000
_SAFE_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._()\-]*$")
_CONTENT_ADDRESSED = re.compile(r"^([0-9a-f]{64})\.[a-z0-9]+$")


class PackageVerificationError(ValueError):
    pass


def safe_relative_path(name: str) -> str:
    """Validate a package-relative POSIX path; return it unchanged or raise."""
    if not name or "\\" in name or name.startswith("/") or ":" in name.split("/")[0]:
        raise PackageVerificationError(f"Unsafe path: {name!r}")
    parts = PurePosixPath(name).parts
    if not parts or any(part in {"", ".", ".."} or not _SAFE_PART.fullmatch(part) for part in parts):
        raise PackageVerificationError(f"Unsafe path: {name!r}")
    return "/".join(parts)


def parse_checksums(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise PackageVerificationError(f"Malformed checksum line {line_no}")
        path = safe_relative_path(match.group(2))
        if path in entries:
            raise PackageVerificationError(f"Duplicate checksum entry: {path}")
        entries[path] = match.group(1)
    return entries


def _read_zip(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise PackageVerificationError("Too many archive members")
        total = 0
        for info in members:
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise PackageVerificationError(f"Symlink entry not allowed: {info.filename}")
            if info.is_dir():
                continue
            name = safe_relative_path(info.filename)
            prefix = PACKAGE_ROOT + "/"
            if not name.startswith(prefix):
                raise PackageVerificationError(f"Entry outside {PACKAGE_ROOT}/: {name}")
            relative = name[len(prefix):]
            if relative in files:
                raise PackageVerificationError(f"Duplicate entry: {relative}")
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise PackageVerificationError("Archive exceeds the size limit")
            files[relative] = archive.read(info)
    return files


def _read_directory(path: Path) -> dict[str, bytes]:
    root = path.resolve()
    files: dict[str, bytes] = {}
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise PackageVerificationError(f"Symlink not allowed: {item}")
        if item.is_dir():
            continue
        if item.name == "__pycache__" or "__pycache__" in item.parts:
            continue
        relative = safe_relative_path(item.relative_to(root).as_posix())
        files[relative] = item.read_bytes()
    return files


def verify_package(path: str | Path) -> dict:
    """Verify a package ZIP or extracted package root. Raises PackageVerificationError on failure."""
    target = Path(path)
    return _verify_files(_read_zip(target) if target.is_file() else _read_directory(target))


def _verify_files(files: dict[str, bytes]) -> dict:
    if MANIFEST not in files or CHECKSUMS not in files:
        raise PackageVerificationError("manifest.json or validation/checksums.sha256 missing")
    manifest = json.loads(files[MANIFEST].decode("utf-8"))
    checksum_bytes = files[CHECKSUMS]
    if hashlib.sha256(checksum_bytes).hexdigest() != manifest.get("checksums_sha256"):
        raise PackageVerificationError("checksums.sha256 does not match the manifest")
    expected = parse_checksums(checksum_bytes.decode("utf-8"))
    actual = {name for name in files if name not in {MANIFEST, CHECKSUMS}}
    missing = sorted(set(expected) - actual)
    unlisted = sorted(actual - set(expected))
    if missing or unlisted:
        raise PackageVerificationError(f"Missing files {missing[:5]} / unlisted files {unlisted[:5]}")
    for name, digest in sorted(expected.items()):
        if hashlib.sha256(files[name]).hexdigest() != digest:
            raise PackageVerificationError(f"SHA-256 mismatch: {name}")
        match = _CONTENT_ADDRESSED.fullmatch(PurePosixPath(name).name)
        if name.startswith("raw_evidence/") and match and match.group(1) != digest:
            raise PackageVerificationError(f"Raw evidence name does not match its content hash: {name}")
    listed = {entry["path"]: entry for entry in manifest.get("files", [])}
    for name, digest in expected.items():
        entry = listed.get(name)
        if entry is None or entry.get("sha256") != digest or entry.get("bytes") != len(files[name]):
            raise PackageVerificationError(f"Manifest file entry disagrees with package: {name}")
    return {
        "status": "verified",
        "package_schema_version": manifest.get("package_schema_version"),
        "content_digest": manifest.get("content_digest"),
        "files_verified": len(expected),
    }


def safe_extract(zip_path: str | Path, destination: str | Path) -> Path:
    """Extract only after every member path and checksum has been validated; returns the package root."""
    destination = Path(destination).resolve()
    files = _read_zip(Path(zip_path))
    _verify_files(files)  # nothing is written unless the whole package verifies
    root = destination / PACKAGE_ROOT
    for relative, data in files.items():
        target = (root / relative).resolve()
        if root.resolve() not in target.parents:
            raise PackageVerificationError(f"Extraction escapes destination: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return root


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: python verify_package.py <package.zip | extracted package directory>")
        return 2
    try:
        result = verify_package(args[0])
    except (PackageVerificationError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
