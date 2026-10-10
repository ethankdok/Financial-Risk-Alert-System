"""Rebuild the 1785 research ZIPs in place, replacing them only after full verification.

Run from fintrust_backend/:

    python -m scripts.rebuild_historical_packages --as-of 2016-11-14

Steps (any failure leaves the current packages untouched):
 1. copy current packages to packages/previous/ (with a hash record);
 2. build new packages under temporary names;
 3. verify manifests/checksums; 4. run the shipped verifier with ``python -I`` from
    outside the repository; 5. extract both outside the repository and verify again;
 6. strict leakage checks; 7. conference provenance checks (PDF hashes vs the
    conference archive, text/page files present); 8. atomic replacement.
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
from app.services.historical_audit.package_verify import PACKAGE_ROOT, safe_extract, verify_package
from app.services.historical_audit.repository import HistoricalAuditRepository
from app.services.historical_audit.research_package import PackageParameters, ResearchPackageBuilder
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository

FUTURE_MARKERS = ("2017-", "106年", "105/12", "2016-12-", "2016-11-15", "2016-11-16", "2016-11-17")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()}


def _rows(files: dict[str, bytes], name: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(files[name].decode("utf-8"))))


def check_strict(path: Path, cutoff: datetime) -> dict:
    files = _members(path)
    manifest = json.loads(files["manifest.json"])
    assert manifest["mode"] == "strict_point_in_time" and manifest["leakage_check"] == "passed"
    text = b"".join(data for name, data in files.items() if not name.startswith("raw_evidence/")
                    and name != "validation/provenance.csv" and name != "manifest.json").decode("utf-8", "replace")
    found = [marker for marker in FUTURE_MARKERS if marker in text]
    if found:
        raise AssertionError(f"strict package contains post-cutoff markers {found}")
    for name, column in (("data/filing_versions.csv", "filing_available_at"), ("data/source_inventory.csv", "document_available_at")):
        for row in _rows(files, name):
            assert datetime.fromisoformat(row[column]) < cutoff, (name, row[column])
    for row in _rows(files, "data/publication_timeline.csv"):
        assert datetime.fromisoformat(row["available_from"]) < cutoff
    assert not [n for n in files if n.startswith(("conference/", "data/conference"))]
    assert not [n for n in files if n.endswith((".xml", ".xls"))]
    return {"raw_evidence_files": sum(1 for n in files if n.startswith("raw_evidence/")),
            "facts": len(_rows(files, "data/financial_facts.csv")),
            "filing_versions": len(_rows(files, "data/filing_versions.csv")),
            "publication_events": len(_rows(files, "data/publication_timeline.csv"))}


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", default="1785")
    parser.add_argument("--start-year", type=int, default=2011)
    parser.add_argument("--end-year", type=int, default=2016)
    parser.add_argument("--as-of", default="2016-11-14")
    parser.add_argument("--database", type=Path, default=Path("data/historical_audit/historical_audit.sqlite3"))
    parser.add_argument("--archive", type=Path, default=Path("data/historical_audit/raw"))
    parser.add_argument("--conference-root", type=Path, default=Path("data/historical-conference-pdfs"))
    parser.add_argument("--packages", type=Path, default=Path("data/historical_audit/packages"))
    args = parser.parse_args(argv)

    stem = f"fintrust_{args.ticker}"
    targets = {"full": args.packages / f"{stem}_{args.start_year}_{args.end_year}_full.zip",
               "strict": args.packages / f"{stem}_asof_{args.as_of}.zip"}
    report: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "targets": {k: str(v) for k, v in targets.items()}}

    previous = args.packages / "previous"
    previous.mkdir(parents=True, exist_ok=True)
    report["previous"] = {}
    for name, target in targets.items():
        if target.exists():
            backup = previous / target.name
            if not backup.exists():
                shutil.copy2(target, backup)
            assert _sha(backup) == _sha(target) or backup.exists()
            report["previous"][name] = {"path": str(backup), "sha256": _sha(backup), "bytes": backup.stat().st_size}

    builder = ResearchPackageBuilder(HistoricalAuditRepository(str(args.database)), RawEvidenceArchive(args.archive),
                                     conference_repository=FileConferencePdfArchiveRepository(args.conference_root),
                                     conference_root=args.conference_root)
    temporary = {name: target.with_name(target.stem + ".new.zip") for name, target in targets.items()}
    try:
        report["build"] = {
            "full": builder.build(PackageParameters(args.ticker, args.start_year, args.end_year, include_conference=True),
                                  temporary["full"]),
            "strict": builder.build(PackageParameters(args.ticker, args.start_year, args.end_year, as_of=args.as_of,
                                                      version_policy="latest_available", include_conference=True),
                                    temporary["strict"]),
        }
        report["verify_zip"] = {name: verify_package(path) for name, path in temporary.items()}
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as outside:
            report["standalone"], report["extracted"] = {}, {}
            for name, path in temporary.items():
                copy = Path(outside) / f"{name}.zip"
                shutil.copyfile(path, copy)
                root = safe_extract(copy, Path(outside) / name)
                for label, target in (("zip", copy), ("folder", root)):
                    completed = subprocess.run([sys.executable, "-I", str(root / "validation" / "verify_package.py"), str(target)],
                                               cwd=outside, capture_output=True, text=True, timeout=600)
                    if completed.returncode != 0:
                        raise AssertionError(f"standalone verification failed for {name}/{label}: {completed.stdout}")
                    report["standalone" if label == "zip" else "extracted"][name] = json.loads(completed.stdout)
        from app.services.historical_audit.models import as_of_cutoff

        report["strict_leakage"] = check_strict(temporary["strict"], as_of_cutoff(args.as_of))
        report["conference_provenance"] = check_conference(temporary["full"], args.conference_root, args.ticker)
    except Exception as exc:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        report["status"] = "failed_previous_packages_untouched"
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1
    for name, path in temporary.items():
        os.replace(path, targets[name])
    report["final"] = {name: {"path": str(target.resolve()), "sha256": _sha(target), "bytes": target.stat().st_size}
                       for name, target in targets.items()}
    report["status"] = "replaced"
    (args.packages / "previous" / "REPLACEMENT_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
