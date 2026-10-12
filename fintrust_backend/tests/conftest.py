"""Test-session protection of approved local data stores (Phase 1.1 incident closure).

1. Before any test module is imported, default database paths point at a temporary directory and the write-capable
   SQLite repositories (analysis, company master, ingestion runs) refuse any path inside ``fintrust_backend/data``
   *before* they touch the file (``tests/protected_stores.py``).
2. At session start every present approved store must equal its explicitly approved SHA-256
   (``tests/approved_data_baseline.json``); otherwise the session stops before running tests.
3. At session end the stores must equal both their start-of-session digests and the approved baseline; any change
   fails the session and names the file.
"""

from __future__ import annotations

import pytest

from tests import protected_stores as guard

GUARDED = guard.install()
SCRATCH = guard.isolate_environment()
_KEY = pytest.StashKey[dict]()


def _report(session: pytest.Session, message: str) -> None:
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(message, red=True, bold=True)
    else:
        print(message)


def pytest_sessionstart(session: pytest.Session) -> None:
    mismatches = guard.baseline_mismatches()
    if mismatches:
        pytest.exit("APPROVED DATA STORE DOES NOT MATCH ITS APPROVED SHA-256 (tests not run): " + "; ".join(mismatches),
                    returncode=pytest.ExitCode.USAGE_ERROR)
    session.config.stash[_KEY] = guard.current_digests()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    before = session.config.stash.get(_KEY, {})
    after = guard.current_digests()
    changed = sorted(path for path in before if after.get(path) != before[path])
    changed += [f"{m} (approved baseline)" for m in guard.baseline_mismatches()]
    if changed:
        _report(session, "PROTECTED DATA STORE CHANGED DURING TESTS: " + ", ".join(changed))
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
