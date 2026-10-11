"""Build the single literature-model (Beneish 1999 / Dechow 2011) independent-review ZIP (run from fintrust_backend/).

    python -m scripts.build_literature_review_bundle --commit HEAD --artifacts <handoff dir> --output <zip>

- ``source/``: every file added/changed since the approved Phase 3-5 commit plus the reused dependencies the new code
  reads, taken from the commit with ``git show`` (tracked content only; no databases, archives, paper PDFs, caches or
  environment files);
- ``diff/``: full ``git diff`` approved..commit, name-status, commit log;
- ``handoff/``: generated evidence (report, test log, coverage matrices, case-study JSON, ledger, OpenAPI, UI evidence,
  baseline proofs);
- ``MANIFEST.json`` / ``PROVENANCE.json``. The ZIP is re-extracted, every hash re-verified and every Python file parsed
  with ``ast``; a secret-pattern scan runs over all members. Any failure exits 1.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from scripts.build_phase3_5_review_bundle import EXCLUDED_SUFFIXES, SECRET_PATTERNS, git, sha256

APPROVED = "db7ee699244244e0a5f6fa636a867e4390e7ec17"
ARCHIVE_BASELINE = "506b64cb62f9a31353d87444f0080fa6540cf759"
CONTEXT_FILES = (
    "fintrust_backend/app/services/financial_research/__init__.py",
    "fintrust_backend/app/services/financial_research/decimal_math.py",
    "fintrust_backend/app/services/financial_research/modes.py",
    "fintrust_backend/app/services/financial_research/literature_models.py",
    "fintrust_backend/app/services/financial_research/case_knowledge.py",
    "fintrust_backend/app/services/financial_research/restatement_bridge.py",
    "fintrust_backend/app/services/financial_research/pdf_evidence.py",
    "fintrust_backend/app/services/financial_research/result_sync.py",
    "fintrust_backend/app/services/historical_audit/xbrl_document.py",
    "fintrust_backend/app/services/historical_audit/normalization.py",
    "fintrust_backend/app/services/historical_audit/archive.py",
    "fintrust_backend/app/services/historical_audit/research_access.py",
    "fintrust_backend/app/services/historical_audit/reader.py",
    "fintrust_backend/app/services/historical_audit/repository.py",
    "fintrust_backend/app/services/historical_audit/models.py",
    "fintrust_backend/app/routers/financial.py",
    "fintrust_backend/scripts/build_phase3_5_review_bundle.py",
    "fintrust_backend/scripts/research_baseline.py",
    "fintrust_backend/tests/historical_cloud_fakes.py",
    "fintrust_backend/tests/test_research_ui_chain.py",
    "fintrust_backend/tests/test_financial_research_real.py",
    "fintrust_backend/requirements.txt", "requirements.txt", "app.py", ".gitignore",
    "docs/data/JSD_INPUT_CONTRACT.md", "docs/data/HISTORICAL_1785_RESEARCH_HANDOFF.md",
    "docs/development/PHASE3_5_DEBUG_PASS_VALIDATION.md", "docs/development/PHASE3_5_DEBUG_PASS_FINAL_REPORT.md",
)


def build(commit: str, artifacts: Path | None, output: Path) -> dict:
    resolved = git("rev-parse", commit).decode().strip()
    changed = [p for p in git("diff", "--name-only", f"{APPROVED}..{resolved}").decode("utf-8").splitlines() if p]
    present = set(git("ls-tree", "-r", "--name-only", resolved).decode("utf-8").splitlines())
    members: dict[str, bytes] = {}
    for path in sorted({p for p in changed if p in present} | {p for p in CONTEXT_FILES if p in present}):
        if path.endswith(EXCLUDED_SUFFIXES) or "__pycache__" in path:
            continue
        members[f"source/{path}"] = git("show", f"{resolved}:{path}")
    members["diff/literature_pass_full.diff"] = git("diff", "--binary", f"{APPROVED}..{resolved}")
    members["diff/changed_files.txt"] = git("diff", "--name-status", f"{APPROVED}..{resolved}")
    members["diff/commits.txt"] = git("log", "--format=%H %ad %s", "--date=iso", f"{APPROVED}..{resolved}")
    members["diff/stat_since_archive_baseline.txt"] = git("diff", "--stat", f"{ARCHIVE_BASELINE}..{resolved}")
    if artifacts is not None:
        for path in sorted(p for p in artifacts.rglob("*") if p.is_file()):
            relative = path.relative_to(artifacts).as_posix()
            if not relative.endswith(EXCLUDED_SUFFIXES):
                members[f"handoff/{relative}"] = path.read_bytes()
    leaks = [name for name, data in members.items()
             if not name.endswith(".png") and any(pattern.search(data) for pattern in SECRET_PATTERNS)]
    if leaks:
        raise SystemExit(f"secret-like content found in {leaks}")
    manifest = {"bundle": "literature_models_independent_review", "commit": resolved, "approved_parent": APPROVED,
                "archive_baseline": ARCHIVE_BASELINE, "source_files": sum(n.startswith("source/") for n in members),
                "changed_files_since_approved": len(changed),
                "files": {name: {"bytes": len(data), "sha256": sha256(data)} for name, data in sorted(members.items())}}
    provenance = {"commit": resolved, "approved_parent": APPROVED, "archive_baseline": ARCHIVE_BASELINE,
                  "branch": git("rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
                  "excluded_suffixes": EXCLUDED_SUFFIXES,
                  "not_included": ["paper PDFs (copyright; SHA-256 recorded in the method lock)",
                                   "historical / literature / result SQLite stores", "raw official archives",
                                   "the 220 MB Full research ZIP"],
                  "note": "source/ is read from the commit with git show; handoff/ artifacts are generated evidence."}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(members.items()):
            archive.writestr(name, data)
        archive.writestr("MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        archive.writestr("PROVENANCE.json", json.dumps(provenance, ensure_ascii=False, indent=2) + "\n")
    with tempfile.TemporaryDirectory() as directory, zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise SystemExit("ZIP CRC check failed")
        archive.extractall(directory)
        extracted = json.loads(Path(directory, "MANIFEST.json").read_text(encoding="utf-8"))
        bad = [name for name, item in extracted["files"].items()
               if sha256(Path(directory, name).read_bytes()) != item["sha256"]
               or Path(directory, name).stat().st_size != item["bytes"]]
        if bad:
            raise SystemExit(f"manifest verification failed for {bad}")
        python_files = list(Path(directory, "source").rglob("*.py"))
        for path in python_files:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    data = output.read_bytes()
    return {"output": str(output.resolve()), "bytes": len(data), "sha256": sha256(data), "entries": len(members) + 2,
            "manifest_files": len(members), "source_files": manifest["source_files"],
            "python_files_ast_parsed": len(python_files), "changed_files_since_approved": len(changed),
            "commit": resolved, "manifest_verified": True, "secret_scan": "clean"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--commit", default="HEAD")
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.commit, args.artifacts, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
