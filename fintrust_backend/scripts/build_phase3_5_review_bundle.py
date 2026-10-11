"""Build the single Phase 3–5 independent-review ZIP from a commit (run from fintrust_backend/).

    python -m scripts.build_phase3_5_review_bundle --commit HEAD --artifacts <handoff dir> --output <zip>

Contents:
- ``source/``: every file changed since the approved baseline plus the reused context files, read from the commit with
  ``git show`` (tracked content only — no local databases, archives, caches or environment files can enter);
- ``diff/``: complete ``git diff`` baseline..commit, name-status list and commit log;
- ``handoff/``: the supplied artifacts (report, test log, fixture, OpenAPI, UI evidence, cloud evidence, matrix);
- ``MANIFEST.json`` (path, bytes, SHA-256 of every member) and ``PROVENANCE.json``.
The ZIP is then extracted to a temporary directory and every manifest hash is re-verified; a secret-pattern scan runs
over every member. Any failure exits 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BASELINE = "506b64cb62f9a31353d87444f0080fa6540cf759"
CONTEXT_FILES = (
    "fintrust_backend/app/services/historical_audit/research_access.py",
    "fintrust_backend/app/services/historical_audit/reader.py",
    "fintrust_backend/app/services/historical_audit/models.py",
    "fintrust_backend/app/services/historical_audit/evidence_export.py",
    "fintrust_backend/app/services/historical_audit/case_registry.py",
    "fintrust_backend/app/services/historical_audit/cloud_config.py",
    "fintrust_backend/app/services/historical_audit/cloud_sync.py",
    "fintrust_backend/app/services/historical_audit/firestore_repository.py",
    "fintrust_backend/app/services/historical_audit/repository.py",
    "fintrust_backend/app/services/historical_audit/conference_package.py",
    "fintrust_backend/app/services/conference_jsd_corpus_adapter.py",
    "fintrust_backend/app/routers/financial.py",
    "fintrust_backend/requirements.txt",
    "fintrust_backend/tests/historical_cloud_fakes.py",
    "fintrust_backend/tests/test_historical_cloud_emulator.py",
    "financial_routes.py", "requirements.txt", "Dockerfile.fastapi", "deploy/cloudbuild-fastapi.yaml",
    "deploy/cloudbuild-flask.yaml", "docs/data/JSD_INPUT_CONTRACT.md", "docs/cloud/CLOUD_ENVIRONMENT_MATRIX.md",
    "docs/cloud/PHASE7_CLOUD_RUN_PRODUCTION.md", ".gitignore",
)
EXCLUDED_SUFFIXES = (".sqlite3", ".sqlite", ".db", ".env", ".zip", ".pdf", ".xls", ".xlsx", ".pyc")
SECRET_PATTERNS = (
    re.compile(rb"AIza[0-9A-Za-z_\-]{35}"), re.compile(rb"sk-ant-[0-9A-Za-z_\-]{20,}"), re.compile(rb"sk-[A-Za-z0-9]{32,}"),
    re.compile(rb"-----BEGIN (RSA |EC )?PRIVATE KEY-----"), re.compile(rb"\"private_key\"\s*:\s*\"-----BEGIN"),
    re.compile(rb"ghp_[0-9A-Za-z]{36}"), re.compile(rb"xox[baprs]-[0-9A-Za-z-]{10,}"),
)


def git(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, check=True, capture_output=True).stdout


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(commit: str, artifacts: Path | None, output: Path) -> dict:
    resolved = git("rev-parse", commit).decode().strip()
    changed = [line for line in git("diff", "--name-only", f"{BASELINE}..{resolved}").decode("utf-8").splitlines() if line]
    present = set(git("ls-tree", "-r", "--name-only", resolved).decode("utf-8").splitlines())
    sources = sorted({p for p in changed if p in present} | {p for p in CONTEXT_FILES if p in present})
    members: dict[str, bytes] = {}
    for path in sources:
        if path.endswith(EXCLUDED_SUFFIXES) or "__pycache__" in path:
            continue
        members[f"source/{path}"] = git("show", f"{resolved}:{path}")
    members["diff/phase3_5_full.diff"] = git("diff", "--binary", f"{BASELINE}..{resolved}")
    members["diff/changed_files.txt"] = git("diff", "--name-status", f"{BASELINE}..{resolved}")
    members["diff/commits.txt"] = git("log", "--format=%H %ad %s", "--date=iso", f"{BASELINE}..{resolved}")
    if artifacts is not None:
        for path in sorted(p for p in artifacts.rglob("*") if p.is_file()):
            relative = path.relative_to(artifacts).as_posix()
            if relative.endswith(EXCLUDED_SUFFIXES):
                continue
            members[f"handoff/{relative}"] = path.read_bytes()
    leaks = [name for name, data in members.items()
             if not name.endswith(".png") and any(pattern.search(data) for pattern in SECRET_PATTERNS)]
    if leaks:
        raise SystemExit(f"secret-like content found in {leaks}")
    manifest = {"bundle": "phase3_5_independent_review", "commit": resolved, "baseline_commit": BASELINE,
                "source_files": sum(n.startswith("source/") for n in members), "changed_files_since_baseline": len(changed),
                "files": {name: {"bytes": len(data), "sha256": sha256(data)} for name, data in sorted(members.items())}}
    provenance = {"commit": resolved, "baseline": BASELINE, "branch": git("rev-parse", "--abbrev-ref", "HEAD").decode().strip(),
                  "excluded_suffixes": EXCLUDED_SUFFIXES,
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
               if sha256(Path(directory, name).read_bytes()) != item["sha256"] or Path(directory, name).stat().st_size != item["bytes"]]
        if bad:
            raise SystemExit(f"manifest verification failed for {bad}")
        python_files = [p for p in Path(directory, "source").rglob("*.py")]
        for path in python_files:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")
    data = output.read_bytes()
    return {"output": str(output.resolve()), "bytes": len(data), "sha256": sha256(data), "entries": len(members) + 2,
            "manifest_files": len(members), "source_files": manifest["source_files"], "python_files_parsed": len(python_files),
            "changed_files_since_baseline": len(changed), "commit": resolved, "manifest_verified": True, "secret_scan": "clean"}


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
