"""Audit runtime datastore dependencies before Cloud Run deployment.

This is intentionally a lightweight static guard. It reports known SQLite usage
and distinguishes production blockers from explicitly allowed local/test
fallbacks. Exit status is non-zero only when a new, unclassified runtime SQLite
reference is introduced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]

SQLITE_PATTERN = re.compile(
    r"\bsqlite3\b|FINANCIAL_DATABASE_PATH|financial_risk\.db|\.sqlite3\b|DATASTORE_BACKEND"
)

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "tests",
    "scripts",
}


@dataclass(frozen=True)
class Classification:
    prefix: str
    status: str
    reason: str


CLASSIFICATIONS = (
    Classification(
        "flask_data_repository.py",
        "ALLOWED_FALLBACK",
        "Flask repository supports Firestore in production and retains SQLite only for local/test compatibility.",
    ),
    Classification(
        "fintrust_backend/app/dependencies.py",
        "CONFIG",
        "Fact repository is selected by DATASTORE_BACKEND; no production SQLite is forced.",
    ),
    Classification(
        "fintrust_backend/app/services/fact_repository.py",
        "ALLOWED_FALLBACK",
        "Fact ingest supports Firestore in production and retains SQLite for local/test compatibility.",
    ),
    Classification(
        "fintrust_backend/app/services/analysis_repository.py",
        "ALLOWED_FALLBACK",
        "SQLite analysis repository may remain for local/test use when production selects Firestore.",
    ),
    Classification(
        "fintrust_backend/app/main.py",
        "CONFIG",
        "Reports the configured persistence backend; not itself a SQLite persistence implementation.",
    ),
)


def classify(relative: str) -> Classification | None:
    for item in CLASSIFICATIONS:
        if relative == item.prefix or relative.startswith(item.prefix.rstrip("/") + "/"):
            return item
    return None


def iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*.py"):
        relative_parts = path.relative_to(ROOT).parts
        if any(part in EXCLUDED_PARTS for part in relative_parts):
            continue
        # The audit script itself contains the search terms by design.
        if path.resolve() == Path(__file__).resolve():
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    findings: list[tuple[str, int, str, Classification | None]] = []
    for path in iter_python_files():
        relative = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if SQLITE_PATTERN.search(line):
                findings.append((relative, number, line.strip(), classify(relative)))

    unknown = [finding for finding in findings if finding[3] is None]
    blockers = [finding for finding in findings if finding[3] and finding[3].status == "BLOCKER"]

    print("Runtime datastore audit")
    print(f"root={ROOT}")
    print(f"findings={len(findings)} blockers={len(blockers)} unknown={len(unknown)}")
    print()

    grouped: dict[str, list[tuple[int, str, Classification | None]]] = {}
    for relative, number, line, classification in findings:
        grouped.setdefault(relative, []).append((number, line, classification))

    for relative, rows in grouped.items():
        classification = rows[0][2]
        label = classification.status if classification else "UNCLASSIFIED"
        reason = classification.reason if classification else "New runtime SQLite/config reference requires review."
        print(f"[{label}] {relative}")
        print(f"  {reason}")
        for number, line, _ in rows:
            print(f"  L{number}: {line}")
        print()

    if unknown:
        print("FAIL: unclassified runtime datastore references were found.", file=sys.stderr)
        return 1

    print("PASS: every runtime datastore reference is explicitly classified.")
    if blockers:
        print("NOTE: known blockers remain by design until the Firestore migration phases are implemented.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
