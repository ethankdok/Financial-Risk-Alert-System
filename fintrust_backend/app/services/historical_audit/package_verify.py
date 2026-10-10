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

import csv
import hashlib
import io
import json
import re
import stat
import sys
import zipfile
from datetime import datetime, timedelta, timezone
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
    if manifest.get("mode") == "strict_point_in_time":
        _verify_strict(files, manifest)
    return {
        "status": "verified",
        "mode": manifest.get("mode", "retrospective"),
        "package_schema_version": manifest.get("package_schema_version"),
        "content_digest": manifest.get("content_digest"),
        "files_verified": len(expected),
    }


_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?")
_TAIPEI = timezone(timedelta(hours=8))


STRICT_MANIFEST_KEYS = {
    "package", "package_schema_version", "mode", "suitable_for_historical_backtest", "cutoff_utc", "cutoff_taipei", "generator",
    "generated_at", "parameters", "case", "contracts", "counts", "completeness", "leakage_check", "integrity",
    "checksums_sha256", "content_digest", "files",
}
_MODEL_FACING_EXEMPT = ("raw_evidence/", "validation/verify_package.py", "validation/checksums.sha256", "manifest.json")
_HEX64 = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")
WITHHELD_ARTIFACT_FIELDS = ("filing_version_id", "content_hash", "source_url", "taxonomy_concept", "document_dated_at",
                            "retrieved_at", "available_at", "filing_available_at")


def _csv(files: dict[str, bytes], name: str) -> list[dict]:
    if name not in files:
        raise PackageVerificationError(f"Strict package is missing {name}")
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8"))))


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _verify_strict(files: dict[str, bytes], manifest: dict) -> None:
    """Independent semantic re-check of a strict point-in-time package (fails closed)."""
    def fail(message: str) -> None:
        raise PackageVerificationError(message)

    cutoff = _ts(str(manifest["cutoff_utc"]))
    if "cutoff_taipei" in manifest and _ts(str(manifest["cutoff_taipei"])) != cutoff:
        fail("Manifest cutoff_taipei and cutoff_utc disagree")
    cutoff_day = (cutoff - timedelta(microseconds=1)).astimezone(_TAIPEI).date()

    # 1. Model-facing metadata: no modern or archive-derived fields in the manifest.
    unexpected = sorted(set(manifest) - STRICT_MANIFEST_KEYS)
    if unexpected or manifest.get("generated_at") is not None:
        fail(f"Strict manifest carries modern/retrospective metadata: {unexpected or 'generated_at'}")

    # 2. No post-cutoff date in any model-facing file.
    for name, data in files.items():
        if name.startswith(_MODEL_FACING_EXEMPT):
            continue
        for match in _ISO.finditer(data.decode("utf-8", "replace")):
            text = match.group(0)
            if len(text) == 10:
                late = datetime.fromisoformat(text).date() > cutoff_day
            else:
                stamp = _ts(text.replace(" ", "T"))
                if stamp.tzinfo is not None and stamp.utcoffset() != timedelta(hours=8):
                    fail(f"Model-facing timestamp {text} in {name} is not expressed in Asia/Taipei")
                late = stamp.date() > cutoff_day if stamp.tzinfo is None else stamp >= cutoff
            if late:
                fail(f"Post-cutoff date {text} in {name}")

    versions = _csv(files, "data/filing_versions.csv")
    inventory = _csv(files, "data/source_inventory.csv")
    raw_hashes = {name.rsplit("/", 1)[1].split(".")[0]: name for name in files if name.startswith("raw_evidence/")}
    documents = {}
    allowed_raw: set[str] = set()
    for row in versions:  # 5. filing artifacts: own verified availability before the cutoff
        if not row.get("filing_available_at") or _ts(row["filing_available_at"]) >= cutoff:
            fail(f"Filing version {row['filing_version_id']} is not verifiably public before the cutoff")
        if row.get("package_raw_path"):
            allowed_raw.add(row["package_raw_path"])
    for row in inventory:  # single-publication notices only
        if not row.get("document_available_at") or _ts(row["document_available_at"]) >= cutoff:
            fail(f"Source document {row['source_key']} is not verifiably public before the cutoff")
        documents[row["content_hash"]] = row
        if row.get("package_raw_path"):
            allowed_raw.add(row["package_raw_path"])

    # 4. Raw evidence only when admissible.
    extra = sorted(name for name in files if name.startswith("raw_evidence/") and name not in allowed_raw)
    if extra:
        fail(f"Raw evidence without verified pre-cutoff availability: {extra[:3]}")
    if any(name.startswith(("conference/", "data/conference")) for name in files):  # 9.
        fail("Strict package contains conference material without verified availability")

    # 7. Every SHA-256 reference in model-facing files resolves to included evidence.
    for name, data in files.items():
        if name.startswith(_MODEL_FACING_EXEMPT):
            continue
        for digest in _HEX64.findall(data.decode("utf-8", "replace")):
            if digest not in raw_hashes:
                fail(f"{name} references {digest[:12]}… which is not included evidence")

    def resolve_disclosure(digest: str, effective: datetime, what: str) -> None:
        document = documents.get(digest)
        if document is None or digest not in raw_hashes:
            fail(f"{what}: eligibility evidence {digest[:12]}… does not resolve to an included disclosure")
        if _ts(document["document_available_at"]) > effective:
            fail(f"{what}: eligibility evidence published after the stated availability")

    # 1 + 2. Facts: eligibility evidence and timestamps.
    facts = _csv(files, "data/financial_facts.csv")
    version_ids = {row["filing_version_id"] for row in versions}
    for row in facts:
        what = f"fact {row['period']}/{row['metric_code']}"
        if row["point_in_time_eligible"] != "true" or not row["effective_available_at"]:
            fail(f"{what}: not point-in-time eligible")
        effective = _ts(row["effective_available_at"])
        if effective >= cutoff:
            fail(f"{what}: effective availability after the cutoff")
        if row["artifact_reference_status"] == "withheld_not_public_at_cutoff":
            if any(row.get(field) for field in WITHHELD_ARTIFACT_FIELDS):
                fail(f"{what}: withheld artifact identity is present")
            if row["availability_evidence_kind"] != "restatement_disclosure" or not row["observation_available_at"]:
                fail(f"{what}: withheld artifact without a disclosure reference")
            if _ts(row["observation_available_at"]) != effective:
                fail(f"{what}: observation and effective availability disagree")
            resolve_disclosure(row["availability_evidence_hash"], effective, what)
        elif row["artifact_reference_status"] == "verified_public_artifact":
            if row["filing_version_id"] not in version_ids:
                fail(f"{what}: references a filing artifact that is not included")
        else:
            fail(f"{what}: unknown artifact_reference_status {row['artifact_reference_status']!r}")

    # 3. Summary observations: contemporaneous disclosure, workbook withheld, report period ended, side consistent.
    for row in _csv(files, "data/historical_summaries.csv"):
        what = f"summary {row['report_period']}/{row['fiscal_year']}/{row['source_metric_code']}"
        if row["evidence_type"] != "official_disclosed_observation" or row["source_url"] or row["content_hash"]:
            fail(f"{what}: later workbook reference not withheld")
        if row["side_consistency"] != "consistent" or row["pit_evidence_kind"] != "restatement_disclosure":
            fail(f"{what}: no consistent contemporaneous disclosure")
        effective = _ts(row["effective_available_at"])
        if effective >= cutoff or datetime(int(row["report_period"][:4]) + 1, 1, 1, tzinfo=_TAIPEI) > cutoff:
            fail(f"{what}: not available before the cutoff")
        resolve_disclosure(row["pit_evidence_hash"], effective, what)

    for row in _csv(files, "data/restatement_comparisons.csv"):
        effective = _ts(row["disclosed_at"])
        if effective >= cutoff:
            fail("restatement comparison disclosed after the cutoff")
        resolve_disclosure(row["content_hash"], effective, f"comparison {row['period']}/{row['canonical_metric']}")

    for row in _csv(files, "data/publication_timeline.csv"):  # 6. events
        if _ts(row["available_from"]) >= cutoff:
            fail(f"event {row['event_key']} public after the cutoff")
        for link in filter(None, (row.get("linked_filing_versions") or "").split(";")):
            if link.split(":")[1] not in version_ids:
                fail(f"event {row['event_key']} links an excluded filing version")

    # 10. CSV / JSON / manifest consistency.
    records = json.loads(files["data/financial_facts.json"].decode("utf-8"))["records"]
    def as_text(value):
        return "" if value is None else ("true" if value is True else "false" if value is False else str(value))
    if [{k: as_text(v) for k, v in r.items()} for r in records] != facts:
        fail("financial_facts.csv and financial_facts.json disagree")
    counts = manifest.get("counts", {})
    for key, name in (("financial_facts", "data/financial_facts.csv"), ("filing_versions", "data/filing_versions.csv"),
                      ("historical_summaries", "data/historical_summaries.csv"),
                      ("restatement_comparisons", "data/restatement_comparisons.csv"),
                      ("publication_events", "data/publication_timeline.csv"), ("source_inventory", "data/source_inventory.csv")):
        if counts.get(key) != len(_csv(files, name)):
            fail(f"manifest count {key} disagrees with {name}")
    if counts.get("raw_evidence_files") != len(raw_hashes):
        fail("manifest raw evidence count disagrees with the package")


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
