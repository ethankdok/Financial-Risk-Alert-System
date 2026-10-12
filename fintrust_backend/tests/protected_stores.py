"""Approved local data stores: absolute baseline check and fail-before-write protection for tests.

Phase 1.1 incident follow-up. The write-capable SQLite repositories (analysis, company master, ingestion runs) run
their schema scripts and commit in the constructor, so merely constructing one on an approved file changes it.
``install()`` wraps those constructors so that any path inside ``fintrust_backend/data`` is refused *before* the
original constructor runs (no ``mkdir``, no connection, no schema script). ``isolate_environment()`` points every
default database path at a temporary directory. ``baseline_mismatches()`` compares present stores with the tracked,
explicitly approved SHA-256 manifest ``approved_data_baseline.json``.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PROTECTED_DIR = BACKEND / "data"
BASELINE_FILE = Path(__file__).resolve().with_name("approved_data_baseline.json")
DEFAULT_PATH_VARIABLES = ("FINANCIAL_DATABASE_PATH", "FINANCIAL_FACT_DATABASE_PATH")


class ProtectedStoreWriteBlocked(RuntimeError):
    """A write-capable repository was pointed at an approved local data directory."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved_baseline(path: Path = BASELINE_FILE) -> dict[Path, str]:
    stores = json.loads(path.read_text(encoding="utf-8"))["stores"]
    return {(BACKEND / relative).resolve(): entry["sha256"] for relative, entry in stores.items()}


def baseline_mismatches(baseline: dict[Path, str] | None = None) -> list[str]:
    """Present approved stores whose SHA-256 differs from the approved baseline (absent files are not checked)."""
    baseline = approved_baseline() if baseline is None else baseline
    return sorted(f"{path} expected {expected} found {sha256(path)}"
                  for path, expected in baseline.items() if path.is_file() and sha256(path) != expected)


def current_digests(baseline: dict[Path, str] | None = None) -> dict[str, str]:
    baseline = approved_baseline() if baseline is None else baseline
    return {str(path): sha256(path) for path in baseline if path.is_file()}


def is_protected(database_path: object) -> bool:
    text = str(database_path or "")
    if not text or text == ":memory:" or text.startswith("file::memory:"):
        return False
    try:
        resolved = Path(text).resolve()
    except (OSError, ValueError):
        return False
    return resolved == PROTECTED_DIR.resolve() or PROTECTED_DIR.resolve() in resolved.parents


def _guarded(cls: type) -> type:
    original = cls.__init__
    if getattr(original, "_protected_store_guard", False):
        return cls

    @functools.wraps(original)
    def __init__(self, database_path, *args, **kwargs):
        if is_protected(database_path):
            raise ProtectedStoreWriteBlocked(
                f"{cls.__name__} refused {database_path!r}: write-capable repositories may not open approved data "
                f"under {PROTECTED_DIR}; use a temporary database or a SHA-verified scratch copy.")
        return original(self, database_path, *args, **kwargs)

    __init__._protected_store_guard = True
    cls.__init__ = __init__
    return cls


def guarded_classes() -> list[type]:
    from app.services.analysis_repository import SqliteAnalysisRepository
    from app.services.company_master_repository import SqliteCompanyMasterRepository
    from app.services.ingestion_run_repository import SqliteIngestionRunRepository

    return [SqliteAnalysisRepository, SqliteCompanyMasterRepository, SqliteIngestionRunRepository]


def install() -> list[str]:
    """Wrap the write-capable repository constructors (idempotent); returns the guarded class names."""
    return [_guarded(cls).__name__ for cls in guarded_classes()]


def isolate_environment() -> Path:
    """Point every default database path at a fresh temporary directory (explicit test settings still override)."""
    scratch = Path(tempfile.mkdtemp(prefix="fintrust-test-stores-"))
    for variable in DEFAULT_PATH_VARIABLES:
        os.environ[variable] = str(scratch / f"{variable.lower()}.sqlite3")
    return scratch
