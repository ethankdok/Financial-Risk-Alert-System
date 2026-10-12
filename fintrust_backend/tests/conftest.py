"""Session guard: no test run may change an approved local data store (Phase 1.1 incident follow-up).

The existing SQLite analysis repository commits its schema script on open, so any test that reaches the default
``get_analysis_repository`` dependency without isolation rewrites ``data/financial_pipeline.sqlite3``. This guard
hashes every approved store at session start and fails the session if any of them changed, naming the file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parents[1] / "data"
PROTECTED_STORES = (
    DATA / "financial_pipeline.sqlite3",
    DATA / "literature_models" / "literature_inputs.sqlite3",
    DATA / "historical_audit" / "historical_audit.sqlite3",
    DATA / "historical_audit" / "research_results.sqlite3",
)


def _digests() -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in PROTECTED_STORES if p.is_file()}


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[_KEY] = _digests()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.config.stash.get(_KEY, {})
    after = _digests()
    changed = sorted(path for path in before if after.get(path) != before[path])
    if changed:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        message = "PROTECTED DATA STORE CHANGED DURING TESTS: " + ", ".join(changed)
        if reporter is not None:
            reporter.write_line(message, red=True, bold=True)
        else:
            print(message)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


_KEY = pytest.StashKey[dict]()
