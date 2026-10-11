"""Build a source-review bundle of the historical-audit implementation (Phase 1A/1B/1C).

Only *tracked* files at a given commit are included (read via ``git show``), so
local databases, raw archives, credentials, environment files and caches cannot
enter the bundle. Run from fintrust_backend/:

    python -m scripts.build_historical_review_bundle --output data/historical_audit/review_bundles/bundle.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import tempfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INCLUDE_PREFIXES = (
    "fintrust_backend/app/services/historical_audit/",
    "fintrust_backend/scripts/historical_audit_case.py",
    "fintrust_backend/scripts/build_historical_review_bundle.py",
    "fintrust_backend/scripts/rebuild_historical_packages.py",
    "fintrust_backend/scripts/recover_historical_conference_pdfs.py",
    "fintrust_backend/requirements-historical-audit.txt",
    "fintrust_backend/tests/test_historical_",
    "fintrust_backend/tests/historical_",
    "docs/development/HISTORICAL_",
    "docs/development/evidence/historical_audit_",
    "docs/data/HISTORICAL_",
    "docs/data/JSD_INPUT_CONTRACT.md",
)
EXCLUDE_SUFFIXES = (".sqlite3", ".db", ".env", ".zip", ".pdf", ".xls", ".pyc")
BASE_COMMIT = "5db17c195667c9fbf2f3247cdf83a9e3a8541c7e"


def _git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], check=True, capture_output=True).stdout


def tracked_files(commit: str) -> list[str]:
    names = _git("ls-tree", "-r", "--name-only", commit).decode("utf-8").splitlines()
    return sorted(name for name in names
                  if name.startswith(INCLUDE_PREFIXES) and not name.endswith(EXCLUDE_SUFFIXES) and "__pycache__" not in name)


def schema_sql() -> str:
    """Schema of an empty, freshly initialized isolated database (no data)."""
    from app.services.historical_audit.cloud_sync import SYNC_SCHEMA
    from app.services.historical_audit.repository import HistoricalAuditRepository

    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "empty.sqlite3")
        HistoricalAuditRepository(path)
        connection = sqlite3.connect(path)
        try:
            connection.executescript(SYNC_SCHEMA)
            rows = connection.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name").fetchall()
        finally:
            connection.close()
    return ";\n\n".join(row[0] for row in rows) + ";\n"


def build(commit: str, output: Path) -> dict:
    commit = _git("rev-parse", commit).decode().strip()
    files = {name: _git("show", f"{commit}:{name}") for name in tracked_files(commit)}
    files["REVIEW/schema.sql"] = schema_sql().encode("utf-8")
    files["REVIEW/commits.txt"] = _git("log", "--format=%H %ad %s", "--date=iso", f"{BASE_COMMIT}..{commit}")
    files["REVIEW/diffstat.txt"] = _git("diff", "--stat", BASE_COMMIT, commit)
    manifest = {
        "purpose": "Independent source review of the FinTrust historical-audit implementation (Phase 1A/1B/1C)",
        "commit": commit, "base_commit": BASE_COMMIT,
        "excluded": "raw financial archives, databases, research packages, credentials, environment files, caches, unrelated code",
        "files": [{"path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in sorted(files.items())],
    }
    files["REVIEW/MANIFEST.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(f"fintrust_historical_audit_review/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, files[name])
    return {"output": str(output), "commit": commit, "files": len(files),
            "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.commit, args.output), indent=2))


if __name__ == "__main__":
    main()
