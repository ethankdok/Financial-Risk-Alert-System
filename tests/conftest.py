"""Root (Flask) test-session protection of approved local data stores (Phase 1.1 incident closure).

Uses the same tracked manifest as the backend suite (``fintrust_backend/tests/approved_data_baseline.json``):
present stores must equal their approved SHA-256 before the session starts and must be unchanged when it ends.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "fintrust_backend"
MANIFEST = BACKEND / "tests" / "approved_data_baseline.json"
_KEY = pytest.StashKey[dict]()


def _approved() -> dict[Path, str]:
    if not MANIFEST.is_file():
        return {}
    stores = json.loads(MANIFEST.read_text(encoding="utf-8"))["stores"]
    return {(BACKEND / relative).resolve(): entry["sha256"] for relative, entry in stores.items()}


def _digests() -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in _approved() if p.is_file()}


def _mismatches() -> list[str]:
    current = _digests()
    return sorted(f"{p} expected {sha}" for p, sha in _approved().items() if str(p) in current and current[str(p)] != sha)


def pytest_sessionstart(session: pytest.Session) -> None:
    mismatches = _mismatches()
    if mismatches:
        pytest.exit("APPROVED DATA STORE DOES NOT MATCH ITS APPROVED SHA-256 (tests not run): " + "; ".join(mismatches),
                    returncode=pytest.ExitCode.USAGE_ERROR)
    session.config.stash[_KEY] = _digests()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.config.stash.get(_KEY, {})
    after = _digests()
    changed = sorted(p for p in before if after.get(p) != before[p]) + _mismatches()
    if changed:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        message = "PROTECTED DATA STORE CHANGED DURING TESTS: " + ", ".join(changed)
        reporter.write_line(message, red=True, bold=True) if reporter else print(message)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
