"""Read-only data baseline of the approved historical research artifacts (Phase 3-5 non-mutation evidence).

Records, without writing to any of them:
- per-table row counts and deterministic row digests of the historical SQLite DB (opened ``mode=ro``);
- SHA-256 of every file in the research package directory (ZIPs and audit sidecars);
- an aggregate digest over every immutable raw-archive file (path + SHA-256) and the conference archive.

    python -m scripts.research_baseline --out before.json
    python -m scripts.research_baseline --out after.json --compare before.json   # exit 1 on any difference
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_DATABASE = Path("data/historical_audit/historical_audit.sqlite3")
DEFAULT_PACKAGES = Path("data/historical_audit/packages")
DEFAULT_RAW = Path("data/historical_audit/raw")
DEFAULT_CONFERENCE = Path("data/historical-conference-pdfs")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def database_digest(path: Path) -> dict[str, dict[str, object]]:
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        tables = {}
        for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"):
            rows = sorted(json.dumps(row, default=str, ensure_ascii=False) for row in connection.execute(f'SELECT * FROM "{table}"'))
            tables[table] = {"rows": len(rows), "sha256": hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()}
        return tables
    finally:
        connection.close()


def tree_digest(root: Path) -> dict[str, object]:
    if not root.is_dir():
        return {"files": 0, "sha256": None, "present": False}
    entries = sorted(f"{p.relative_to(root).as_posix()}\t{file_sha256(p)}" for p in root.rglob("*") if p.is_file())
    return {"files": len(entries), "sha256": hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest(), "present": True}


def baseline(database: Path, packages: Path, raw: Path, conference: Path) -> dict[str, object]:
    return {
        "database": {"path": database.as_posix(), "tables": database_digest(database)},
        "packages": {p.name: {"bytes": p.stat().st_size, "sha256": file_sha256(p)}
                     for p in sorted(packages.glob("*")) if p.is_file()},
        "raw_archive": tree_digest(raw),
        "conference_archive": tree_digest(conference),
    }


def compare(before: dict, after: dict) -> list[str]:
    differences = []
    for table in sorted(set(before["database"]["tables"]) | set(after["database"]["tables"])):
        if before["database"]["tables"].get(table) != after["database"]["tables"].get(table):
            differences.append(f"database table {table}")
    for name, item in before["packages"].items():
        if after["packages"].get(name) != item:
            differences.append(f"package {name}")
    for key in ("raw_archive", "conference_archive"):
        if before[key] != after[key]:
            differences.append(key)
    return differences


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--packages", type=Path, default=DEFAULT_PACKAGES)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--conference", type=Path, default=DEFAULT_CONFERENCE)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--compare", type=Path, help="earlier baseline JSON; exit 1 if anything differs")
    args = parser.parse_args(argv)
    result = baseline(args.database, args.packages, args.raw, args.conference)
    if args.out:
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for table, item in result["database"]["tables"].items():
        print(f"table {table:40s} {item['rows']:6d} {item['sha256'][:16]}")
    for name, item in result["packages"].items():
        print(f"package {name:58s} {item['bytes']:11d} {item['sha256']}")
    for key in ("raw_archive", "conference_archive"):
        print(f"{key} files={result[key]['files']} sha256={result[key]['sha256']}")
    if args.compare:
        differences = compare(json.loads(args.compare.read_text(encoding="utf-8")), result)
        print("compare:", "IDENTICAL" if not differences else "DIFFERENT " + ", ".join(differences))
        return 1 if differences else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
