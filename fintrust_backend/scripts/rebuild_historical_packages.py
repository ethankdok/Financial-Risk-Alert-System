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
 8. journaled publication of the strict ZIP + audit sidecar pair (see ``publish_release``),
    followed by a fail-closed check of the published pair.

Release pair: a strict ZIP is only a valid release together with its sidecar
``<zip>.audit.json`` whose ``package_sha256``/``content_digest``/``package_file``
bind that exact ZIP. Both artifacts are fully staged before anything is
published; a journal (``<zip>.release.json``) recorded before the first rename
lets ``recover_release`` finish (roll forward) or undo (roll back, using the
journal's staged files or the hash-qualified backups) an interrupted
publication. Every run first recovers/validates the existing pair and refuses to
continue on an unrecoverable mismatch. ``--check-release`` only validates.
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
# Year markers of the modern (generation / retrieval) era. They are a sound leakage check only for cutoffs before
# that era; later cutoffs legitimately contain 2024+ evidence, so the exact retrieval-time scan below applies always.
MODERN_MARKERS = ("2024-", "2025-", "2026-", "2027-")
MODERN_ERA_START = "2024-01-01"
# Columns that must be empty in every model-facing CSV (retrieval / generation metadata).
MODERN_COLUMNS = ("retrieved_at", "created_at", "recorded_at", "generated_at", "listing_retrieved_at")


def retrieval_timestamps(database: Path) -> set[str]:
    """Every retrieval / creation time the research DB recorded, rendered as UTC and as Asia/Taipei (to seconds)."""
    import sqlite3

    from app.services.historical_audit.models import TAIPEI, parse_timestamp

    connection = sqlite3.connect(f"file:{Path(database).as_posix()}?mode=ro", uri=True)
    values: set[str] = set()
    try:
        for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')
                       if row[1] in ("retrieved_at", "created_at", "recorded_at", "listing_retrieved_at", "started_at", "completed_at")]
            for column in columns:
                for (value,) in connection.execute(f'SELECT DISTINCT "{column}" FROM "{table}" WHERE "{column}" IS NOT NULL'):
                    stamp = parse_timestamp(str(value)) if "T" in str(value) or " " in str(value) else None
                    if stamp is not None:
                        values.add(stamp.astimezone(TAIPEI).strftime("%Y-%m-%dT%H:%M:%S"))
                        values.add(stamp.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
    finally:
        connection.close()
    return values
MODEL_FACING_EXEMPT = ("raw_evidence/", "validation/verify_package.py", "validation/checksums.sha256", "manifest.json")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()}


def _rows(files: dict[str, bytes], name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8"))))


def check_strict(path: Path, as_of: str, audit_path: Path, database: Path | None = None) -> dict:
    cutoff = as_of_cutoff(as_of)
    files = _members(path)
    manifest = json.loads(files["manifest.json"])
    assert manifest["mode"] == "strict_point_in_time" and manifest["leakage_check"] == "passed"
    assert set(manifest) <= STRICT_MANIFEST_KEYS and manifest["generated_at"] is None, "modern manifest metadata"
    assert "validation/provenance.csv" not in files, "retrieval provenance inside the strict ZIP"
    model_text = b"".join(data for name, data in files.items()
                          if not name.startswith(MODEL_FACING_EXEMPT)).decode("utf-8", "replace")
    modern_era = cutoff > as_of_cutoff(MODERN_ERA_START)
    markers = (() if modern_era else MODERN_MARKERS) + (FUTURE_MARKERS_20161114 if as_of == "2016-11-14" else ())
    found = [marker for marker in markers if marker in model_text]
    if found:
        raise AssertionError(f"strict package contains post-cutoff or modern markers {found}")
    for name, data in files.items():
        if name.startswith("data/") and name.endswith(".csv"):
            for row in _rows(files, name):
                filled = [column for column in MODERN_COLUMNS if row.get(column)]
                assert not filled, f"{name}: retrieval/generation metadata {filled} in a model input"
    if database is not None:  # exact retrieval / creation times recorded by this archive must never appear
        leaked = sorted(stamp for stamp in retrieval_timestamps(database) if stamp in model_text)
        assert not leaked, f"strict package contains archive retrieval/creation timestamps {leaked[:3]}"
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


# --------------------------------------------------------------------------- release pair
class ReleaseError(RuntimeError):
    """The strict ZIP and its audit sidecar do not form a valid release (fail closed)."""


def _journal_name(target: Path) -> Path:
    return target.with_name(target.name.removesuffix(".zip") + ".release.json")


def _write_atomic(path: Path, payload: dict) -> None:
    staging = path.with_name(path.name + ".tmp")
    staging.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(staging, path)


def verify_release_pair(target: Path, audit_path: Path | None = None) -> dict:
    """Fail-closed check that ``target`` and its sidecar form one release; returns the binding."""
    audit_path = audit_path or _audit_name(target)
    if not target.exists() or not audit_path.exists():
        raise ReleaseError(f"incomplete release pair: {target.name} / {audit_path.name}")
    if _journal_name(target).exists():
        raise ReleaseError(f"publication of {target.name} is in progress or was interrupted (journal present)")
    try:
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ReleaseError(f"unreadable audit sidecar {audit_path.name}: {exc}") from exc
    digest = _sha(target)
    manifest = json.loads(_members(target)["manifest.json"])
    if audit.get("package_sha256") != digest:
        raise ReleaseError(f"audit sidecar binds {str(audit.get('package_sha256'))[:12]}… but {target.name} is {digest[:12]}…")
    if audit.get("package_file") != target.name or audit.get("content_digest") != manifest.get("content_digest"):
        raise ReleaseError("audit sidecar package_file/content_digest do not match the ZIP")
    verify_package(target)
    return {"package": target.name, "package_sha256": digest, "audit": audit_path.name, "audit_sha256": _sha(audit_path)}


def stage_audit(temp_audit: Path, target: Path) -> Path:
    """Rewrite the builder's sidecar for the final file name before anything is published."""
    audit = json.loads(temp_audit.read_text(encoding="utf-8"))
    audit["package_file"] = target.name
    _write_atomic(temp_audit, audit)
    return temp_audit


def publish_release(staged_zip: Path, staged_audit: Path, target: Path, backups: dict[str, str] | None = None) -> dict:
    """Journaled two-step publication of a fully staged (ZIP, sidecar) pair."""
    audit_target = _audit_name(target)
    journal = _journal_name(target)
    if journal.exists():
        raise ReleaseError(f"refusing to publish over an unrecovered journal {journal.name}")
    staged_binding = json.loads(staged_audit.read_text(encoding="utf-8"))
    if staged_binding.get("package_sha256") != _sha(staged_zip) or staged_binding.get("package_file") != target.name:
        raise ReleaseError("staged audit sidecar does not bind the staged ZIP")
    _write_atomic(journal, {
        "target": target.name, "audit": audit_target.name,
        "staged_zip": staged_zip.name, "staged_audit": staged_audit.name,
        "new_zip_sha256": _sha(staged_zip), "new_audit_sha256": _sha(staged_audit),
        "old_zip_sha256": _sha(target) if target.exists() else None,
        "old_audit_sha256": _sha(audit_target) if audit_target.exists() else None,
        "backups": backups or {},
    })
    os.replace(staged_zip, target)          # step 1
    os.replace(staged_audit, audit_target)  # step 2 (a crash between 1 and 2 is recoverable from the journal)
    journal.unlink()
    return verify_release_pair(target)


def recover_release(target: Path) -> dict:
    """Finish or undo an interrupted ``publish_release``; then validate the pair (fail closed)."""
    journal_path = _journal_name(target)
    if not journal_path.exists():
        if not target.exists() and not _audit_name(target).exists():
            return {"action": "none", "status": "no_existing_release"}
        return {"action": "none", **verify_release_pair(target)}  # a lone ZIP or lone sidecar fails closed
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    directory = target.parent
    audit_target = directory / journal["audit"]
    staged_zip, staged_audit = directory / journal["staged_zip"], directory / journal["staged_audit"]
    current = _sha(target) if target.exists() else None
    current_audit = _sha(audit_target) if audit_target.exists() else None
    if current == journal["new_zip_sha256"] and (
            current_audit == journal["new_audit_sha256"]
            or (staged_audit.exists() and _sha(staged_audit) == journal["new_audit_sha256"])):
        if current_audit != journal["new_audit_sha256"]:
            os.replace(staged_audit, audit_target)
        action = "rolled_forward"
    elif current == journal["old_zip_sha256"] and current_audit == journal["old_audit_sha256"]:
        action = "rolled_back"  # nothing was published; the old pair is intact
    else:
        backups = journal.get("backups", {})
        zip_backup, audit_backup = backups.get("zip"), backups.get("audit")
        if not (zip_backup and audit_backup and Path(zip_backup).exists() and Path(audit_backup).exists()
                and _sha(Path(zip_backup)) == journal["old_zip_sha256"]
                and _sha(Path(audit_backup)) == journal["old_audit_sha256"]):
            raise ReleaseError(f"cannot recover {target.name}: state matches neither the old nor the new release "
                               "and no verified hash-qualified backup is recorded")
        shutil.copy2(zip_backup, target.with_name(target.name + ".restore"))
        shutil.copy2(audit_backup, audit_target.with_name(audit_target.name + ".restore"))
        os.replace(target.with_name(target.name + ".restore"), target)
        os.replace(audit_target.with_name(audit_target.name + ".restore"), audit_target)
        action = "restored_from_backup"
    for leftover in (staged_zip, staged_audit):
        leftover.unlink(missing_ok=True)
    journal_path.unlink()
    return {"action": action, **verify_release_pair(target)}


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
    parser.add_argument("--strict-filename", default=None,
                        help="strict ZIP file name (default fintrust_<ticker>_asof_<as-of>.zip); its sidecar follows it")
    parser.add_argument("--check-release", action="store_true",
                        help="only recover/validate the strict ZIP + audit sidecar pair, then exit")
    args = parser.parse_args(argv)

    stem = f"fintrust_{args.ticker}"
    all_targets = {"full": args.packages / f"{stem}_{args.start_year}_{args.end_year}_full.zip",
                   "strict": args.packages / (args.strict_filename or f"{stem}_asof_{args.as_of}.zip")}
    if args.strict_filename and (Path(args.strict_filename).name != args.strict_filename
                                 or not args.strict_filename.endswith(".zip") or ".." in args.strict_filename):
        parser.error("--strict-filename must be a plain *.zip file name inside --packages")
    selected = ("full", "strict") if args.rebuild == "both" else (args.rebuild,)
    targets = {name: all_targets[name] for name in selected}
    started = datetime.now(timezone.utc)
    report: dict = {"started_at": started.isoformat(), "rebuild": list(selected),
                    "targets": {k: str(v) for k, v in targets.items()}}

    # The existing strict release must be a valid pair (or recoverable) before anything else happens.
    try:
        report["existing_release"] = recover_release(all_targets["strict"])
    except (ReleaseError, Exception) as exc:  # noqa: BLE001 - any doubt about the pair fails closed
        print(json.dumps({**report, "status": "failed_existing_release_invalid", "error": f"{type(exc).__name__}: {exc}"},
                         ensure_ascii=False, indent=2, default=str))
        return 1
    if args.check_release:
        if report["existing_release"].get("status") == "no_existing_release":  # nothing to validate is not "valid"
            print(json.dumps({**report, "status": "failed_no_release_found"}, ensure_ascii=False, indent=2, default=str))
            return 1
        print(json.dumps({**report, "status": "release_pair_valid"}, ensure_ascii=False, indent=2, default=str))
        return 0

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
    strict_backups = {}
    if "strict" in targets:
        for kind, source in (("zip", targets["strict"]), ("audit", _audit_name(targets["strict"]))):
            if source.name in report["previous"]:
                strict_backups[kind] = report["previous"][source.name]["path"]

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
            report["strict_checks"] = check_strict(temporary["strict"], args.as_of, temp_audit, args.database)
            stage_audit(temp_audit, targets["strict"])  # fully staged pair before any publication
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
    if "full" in temporary:
        os.replace(temporary["full"], targets["full"])  # single artifact: one atomic rename
    if "strict" in temporary:
        try:
            report["release_pair"] = publish_release(temporary["strict"], temp_audit, targets["strict"], strict_backups)
        except Exception as exc:  # noqa: BLE001
            try:
                report["recovery"] = recover_release(targets["strict"])
            except Exception as recovery_error:  # noqa: BLE001
                report["recovery_error"] = f"{type(recovery_error).__name__}: {recovery_error}"
            report["status"] = "failed_publication"
            report["error"] = f"{type(exc).__name__}: {exc}"
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return 1
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
