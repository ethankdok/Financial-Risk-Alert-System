"""Rebuild the 1785 research ZIPs in place, replacing them only after full verification.

Run from fintrust_backend/:

    python -m scripts.rebuild_historical_packages --as-of 2016-11-14 --rebuild strict

``--rebuild`` selects ``strict`` (default), ``full`` or ``both``; a package that is
not rebuilt is never touched, and its SHA-256 is recorded (and compared with
``--expect-full-sha256`` when given).

Steps (any failure leaves the current packages untouched):
 1. copy each package being rebuilt to packages/previous/ under a hash-qualified
    name (an existing backup is never overwritten);
 2. build new packages under temporary names;
 3. manifest/checksum and full semantic verification;
 4. SHA-256 binding of the reviewer-only audit sidecar to the new strict ZIP;
 5. run the shipped verifier with ``python -I`` from outside the repository;
 6. safe extraction outside the repository and verification of the folder;
 7. strict point-in-time and modern-metadata checks; conference provenance (full);
 8. atomic replacement (ZIP, then its audit sidecar).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.models import as_of_cutoff
from app.services.historical_audit.package_verify import STRICT_MANIFEST_KEYS, safe_extract, verify_package
from app.services.historical_audit.repository import HistoricalAuditRepository
from app.services.historical_audit.research_package import PackageParameters, ResearchPackageBuilder
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository

# Literal markers of information that only became public after 2016-11-14 (checked for that cutoff only).
FUTURE_MARKERS_20161114 = ("2017-", "106年", "105/12", "2016-12-", "2016-11-15", "2016-11-16", "2016-11-17")
# Markers of modern (generation / retrieval era) metadata that must never reach a strict model input.
MODERN_MARKERS = ("2024-", "2025-", "2026-", "2027-")
MODEL_FACING_EXEMPT = ("raw_evidence/", "validation/verify_package.py", "validation/checksums.sha256", "manifest.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()}


def _rows(files: dict[str, bytes], name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8"))))


def check_strict(path: Path, as_of: str, audit_path: Path) -> dict:
    cutoff = as_of_cutoff(as_of)
    files = _members(path)
    manifest = json.loads(files["manifest.json"])
    assert manifest["mode"] == "strict_point_in_time" and manifest["leakage_check"] == "passed"
    assert set(manifest) <= STRICT_MANIFEST_KEYS and manifest["generated_at"] is None, "modern manifest metadata"
    assert "validation/provenance.csv" not in files, "retrieval provenance inside the strict ZIP"
    model_text = b"".join(data for name, data in files.items()
                          if not name.startswith(MODEL_FACING_EXEMPT)).decode("utf-8", "replace")
    markers = MODERN_MARKERS + (FUTURE_MARKERS_20161114 if as_of == "2016-11-14" else ())
    found = [marker for marker in markers if marker in model_text]
    if found:
        raise AssertionError(f"strict package contains post-cutoff or modern markers {found}")
    for name, column in (("data/filing_versions.csv", "filing_available_at"), ("data/source_inventory.csv", "document_available_at"),
                         ("data/publication_timeline.csv", "available_from"), ("data/restatement_comparisons.csv", "disclosed_at"),
                         ("data/financial_facts.csv", "effective_available_at"),
                         ("data/historical_summaries.csv", "effective_available_at")):
        for row in _rows(files, name):
            stamp = datetime.fromisoformat(row[column])
            assert stamp < cutoff, (name, row[column])
            assert stamp.utcoffset().total_seconds() == 8 * 3600, (name, "not Asia/Taipei", row[column])
    for row in _rows(files, "data/historical_summaries.csv"):
        assert row["evidence_type"] == "official_disclosed_observation" and not row["source_url"] and not row["content_hash"]
        assert row["side_consistency"] == "consistent" and row["pit_evidence_hash"], row
    assert not [n for n in files if n.startswith(("conference/", "data/conference"))]
    assert not [n for n in files if n.endswith((".xml", ".xls"))]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["package_sha256"] == _sha(path), "audit sidecar is not bound to this package"
    return {"raw_evidence_files": sum(1 for n in files if n.startswith("raw_evidence/")),
            "facts": len(_rows(files, "data/financial_facts.csv")),
            "filing_versions": len(_rows(files, "data/filing_versions.csv")),
            "historical_summaries": len(_rows(files, "data/historical_summaries.csv")),
            "restatement_comparisons": len(_rows(files, "data/restatement_comparisons.csv")),
            "publication_events": len(_rows(files, "data/publication_timeline.csv")),
            "summary_decisions": {d["decision"]: sum(1 for x in audit["summary_observation_review"] if x["decision"] == d["decision"])
                                  for d in audit["summary_observation_review"]}}


def check_conference(path: Path, conference_root: Path, ticker: str) -> dict:
    files = _members(path)
    documents = _rows(files, "data/conference_documents.csv")
    for document in documents:
        archived = conference_root / ticker / document["announcement_year"] / document["filename"]
        assert _sha(archived) == document["sha256"], document["filename"]
        assert hashlib.sha256(files[document["package_raw_path"]]).hexdigest() == document["sha256"]
        assert files[f"conference/text/{document['sha256']}.txt"].strip()
        pages = json.loads(files[f"conference/pages/{document['sha256']}.pages.json"])
        assert len(pages) == int(document["page_count"]) and not any("review_image_path" in p for p in pages)
    return {"documents": len(documents), "pages": sum(int(d["page_count"]) for d in documents)}


def _audit_name(path: Path) -> Path:
    return path.with_name(path.name.removesuffix(".zip") + ".audit.json")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ticker", default="1785")
    parser.add_argument("--start-year", type=int, default=2011)
    parser.add_argument("--end-year", type=int, default=2016)
    parser.add_argument("--as-of", default="2016-11-14")
    parser.add_argument("--rebuild", choices=("strict", "full", "both"), default="strict")
    parser.add_argument("--expect-full-sha256", default=None, help="fail unless the untouched full ZIP has this hash")
    parser.add_argument("--database", type=Path, default=Path("data/historical_audit/historical_audit.sqlite3"))
    parser.add_argument("--archive", type=Path, default=Path("data/historical_audit/raw"))
    parser.add_argument("--conference-root", type=Path, default=Path("data/historical-conference-pdfs"))
    parser.add_argument("--packages", type=Path, default=Path("data/historical_audit/packages"))
    args = parser.parse_args(argv)

    stem = f"fintrust_{args.ticker}"
    all_targets = {"full": args.packages / f"{stem}_{args.start_year}_{args.end_year}_full.zip",
                   "strict": args.packages / f"{stem}_asof_{args.as_of}.zip"}
    selected = ("full", "strict") if args.rebuild == "both" else (args.rebuild,)
    targets = {name: all_targets[name] for name in selected}
    started = datetime.now(timezone.utc)
    report: dict = {"started_at": started.isoformat(), "rebuild": list(selected),
                    "targets": {k: str(v) for k, v in targets.items()}}

    untouched = {name: path for name, path in all_targets.items() if name not in targets and path.exists()}
    report["untouched"] = {name: {"path": str(path), "sha256": _sha(path), "bytes": path.stat().st_size}
                           for name, path in untouched.items()}
    if args.expect_full_sha256 and "full" in untouched and report["untouched"]["full"]["sha256"] != args.expect_full_sha256:
        print(json.dumps({**report, "status": "failed_full_package_hash_mismatch"}, indent=2))
        return 1

    previous = args.packages / "previous"
    previous.mkdir(parents=True, exist_ok=True)
    report["previous"] = {}
    for name, target in targets.items():
        for source in (target, _audit_name(target)):
            if not source.exists():
                continue
            digest = _sha(source)
            backup = previous / f"{source.name.removesuffix('.zip').removesuffix('.audit.json')}.{digest[:12]}" \
                f"{'.audit.json' if source.name.endswith('.audit.json') else '.zip'}"
            if not backup.exists():
                shutil.copy2(source, backup)
            if _sha(backup) != digest:
                raise SystemExit(f"backup {backup} does not match {source}")
            report["previous"][source.name] = {"path": str(backup), "sha256": digest, "bytes": backup.stat().st_size}

    builder = ResearchPackageBuilder(HistoricalAuditRepository(str(args.database)), RawEvidenceArchive(args.archive),
                                     conference_repository=FileConferencePdfArchiveRepository(args.conference_root),
                                     conference_root=args.conference_root)
    temporary = {name: target.with_name(target.stem + ".new.zip") for name, target in targets.items()}
    temp_audit = _audit_name(temporary["strict"]) if "strict" in temporary else None
    try:
        report["build"] = {}
        if "full" in temporary:
            report["build"]["full"] = builder.build(
                PackageParameters(args.ticker, args.start_year, args.end_year, include_conference=True), temporary["full"])
        if "strict" in temporary:
            report["build"]["strict"] = builder.build(
                PackageParameters(args.ticker, args.start_year, args.end_year, as_of=args.as_of,
                                  version_policy="latest_available", include_conference=True),
                temporary["strict"], audit_path=temp_audit)
        report["verify_zip"] = {name: verify_package(path) for name, path in temporary.items()}
        report["sha256_new"] = {name: _sha(path) for name, path in temporary.items()}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as outside:
            report["standalone"], report["extracted"] = {}, {}
            for name, path in temporary.items():
                copy = Path(outside) / f"{name}.zip"
                shutil.copyfile(path, copy)
                assert _sha(copy) == report["sha256_new"][name]
                root = safe_extract(copy, Path(outside) / name)
                for label, target in (("zip", copy), ("folder", root)):
                    completed = subprocess.run([sys.executable, "-I", str(root / "validation" / "verify_package.py"), str(target)],
                                               cwd=outside, capture_output=True, text=True, timeout=600)
                    if completed.returncode != 0:
                        raise AssertionError(f"standalone verification failed for {name}/{label}: {completed.stdout}")
                    report["standalone" if label == "zip" else "extracted"][name] = json.loads(completed.stdout)
        if "strict" in temporary:
            report["strict_checks"] = check_strict(temporary["strict"], args.as_of, temp_audit)
        if "full" in temporary:
            report["conference_provenance"] = check_conference(temporary["full"], args.conference_root, args.ticker)
        for name, path in untouched.items():  # the package not being rebuilt must not have changed meanwhile
            assert _sha(path) == report["untouched"][name]["sha256"], f"{name} package changed during the rebuild"
    except Exception as exc:
        for path in [*temporary.values(), temp_audit]:
            if path is not None:
                path.unlink(missing_ok=True)
        report["status"] = "failed_previous_packages_untouched"
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1
    for name, path in temporary.items():
        os.replace(path, targets[name])
    if temp_audit is not None:
        audit = json.loads(temp_audit.read_text(encoding="utf-8"))
        audit["package_file"] = targets["strict"].name
        _audit_name(targets["strict"]).write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                                   encoding="utf-8")
        temp_audit.unlink()
    report["final"] = {name: {"path": str(target.resolve()), "sha256": _sha(target), "bytes": target.stat().st_size}
                       for name, target in all_targets.items() if target.exists()}
    report["status"] = "replaced"
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    (previous / f"REPLACEMENT_REPORT.{stamp}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
