"""PORT-01 … PORT-06 and package failure injection (SYNTHETIC fixtures, local only)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.services.conference_document_identity import IDENTITY_VERSION
from app.services.historical_audit.package_verify import (
    PACKAGE_ROOT,
    PackageVerificationError,
    safe_extract,
    verify_package,
)
from app.services.historical_audit.reader import list_historical_facts
from app.services.historical_audit.research_package import PackageParameters, ResearchPackageBuilder
from tests.test_historical_evidence import EvidenceTestCase


FIXED = datetime(2026, 10, 10, tzinfo=timezone.utc)


class FakeConferenceRepository:
    """Minimal ConferencePdfArchiveRepository with one validated document (synthetic)."""

    backend_name = "file"

    def __init__(self, root: Path, ticker: str, pdf: bytes) -> None:
        self.ticker, self.pdf = ticker, pdf
        directory = root / ticker / "2016"
        directory.mkdir(parents=True)
        (directory / "conf_2016Q3.pdf").write_bytes(pdf)

    def available_years(self, ticker):
        return [2016] if ticker == self.ticker else []

    def latest_manifest(self, ticker, year):
        return {"listing_url": "https://mopsov.twse.com.tw/mops/web/t100sb07_1", "retrieved_at": "2026-10-01T00:00:00+00:00",
                "documents": [{"filename": "conf_2016Q3.pdf", "sha256": hashlib.sha256(self.pdf).hexdigest(),
                               "identity_version": IDENTITY_VERSION, "period": "2016Q3",
                               "period_validation_status": "verified", "document_type": "earnings_presentation",
                               "document_language": "en", "quarantined": False, "quarantine_reasons": [],
                               "download_fields": {"step": "9", "filePath": "/x", "fileName": "conf_2016Q3.pdf"}}]}

    def pages(self, ticker, year, filename):
        return [{"page": 1, "text": "3Q16 results synthetic text"}]


class PackageTestCase(EvidenceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_all()
        self.builder = ResearchPackageBuilder(self.repository, self.archive)
        self.params = PackageParameters("1785", 2013, 2014)

    def build(self, name: str = "pkg.zip", params: PackageParameters | None = None, builder=None) -> tuple[Path, dict]:
        path = self.root / name
        result = (builder or self.builder).build(params or self.params, path, generated_at=FIXED)
        return path, result

    def read(self, zip_path: Path, member: str) -> bytes:
        with zipfile.ZipFile(zip_path) as archive:
            return archive.read(f"{PACKAGE_ROOT}/{member}")

    def csv_rows(self, zip_path: Path, member: str) -> list[dict]:
        return list(csv.DictReader(io.StringIO(self.read(zip_path, member).decode("utf-8"))))


class Port01To03Tests(PackageTestCase):
    def test_port01_complete_package_from_local_evidence(self) -> None:
        path, result = self.build()
        with zipfile.ZipFile(path) as archive:
            names = {n[len(PACKAGE_ROOT) + 1:] for n in archive.namelist()}
        for required in ("README.md", "manifest.json", "data/financial_facts.csv", "data/financial_facts.json",
                         "data/filing_versions.csv", "data/historical_summaries.csv", "data/restatement_comparisons.csv",
                         "data/publication_timeline.csv", "data/source_inventory.csv", "data/coverage_matrix.csv",
                         "data/missing_evidence.csv", "validation/quality_report.json", "validation/checksums.sha256",
                         "validation/verify_package.py", "contracts/HISTORICAL_FINANCIAL_FACTS_CONTRACT.md",
                         "contracts/HISTORICAL_RESEARCH_PACKAGE_CONTRACT.md"):
            self.assertIn(required, names)
        versions = self.csv_rows(path, "data/filing_versions.csv")
        self.assertTrue(all(row["raw_evidence_included"] == "true" for row in versions))
        self.assertTrue(any(n.startswith("raw_evidence/financial_filings/1785/2013FY/") for n in names))
        self.assertTrue(any(n.startswith("raw_evidence/regulatory_disclosures/") for n in names))
        self.assertTrue(any(n.startswith("raw_evidence/official_summaries/") for n in names))
        self.assertEqual(result["counts"]["filing_versions_raw_included"], len(versions))
        self.assertTrue(all(not Path(n).is_absolute() and ".." not in n for n in names))

    def test_port02_manifest_checksums_and_reproducibility(self) -> None:
        path, result = self.build("a.zip")
        manifest = json.loads(self.read(path, "manifest.json"))
        self.assertEqual(manifest["package_schema_version"], "1.0")
        self.assertEqual(manifest["parameters"], {"ticker": "1785", "start_year": 2013, "end_year": 2014, "as_of": None,
                                                  "version_policy": "all", "include_raw_evidence": True,
                                                  "include_conference": False})
        self.assertEqual(manifest["checksums_sha256"], hashlib.sha256(self.read(path, "validation/checksums.sha256")).hexdigest())
        self.assertEqual(verify_package(path)["status"], "verified")
        again, _ = self.build("b.zip")
        self.assertEqual(path.read_bytes(), again.read_bytes())  # byte-identical with fixed generated_at
        later = self.root / "c.zip"
        later_result = self.builder.build(self.params, later)  # different generated_at
        self.assertEqual(later_result["content_digest"], result["content_digest"])

    def test_port03_extracted_package_verifies_outside_repository(self) -> None:
        path, _ = self.build()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as elsewhere:
            shutil.copyfile(path, Path(elsewhere) / "dataset.zip")
            root = safe_extract(Path(elsewhere) / "dataset.zip", Path(elsewhere) / "out")
            for target in (str(Path(elsewhere) / "dataset.zip"), str(root)):
                completed = subprocess.run([sys.executable, "-I", str(root / "validation" / "verify_package.py"), target],
                                           cwd=elsewhere, capture_output=True, text=True, timeout=120)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["status"], "verified")
            facts = list(csv.DictReader((root / "data" / "financial_facts.csv").open(encoding="utf-8")))
            self.assertTrue(facts)


class Port04To06Tests(PackageTestCase):
    def test_port04_missing_and_corrupted_sources_stay_explicitly_missing(self) -> None:
        versions = self.repository.list_filing_versions("1785", 2013, 2014)
        removed = next(v for v in versions if v["source_kind"] == "official_pdf")
        corrupted = next(v for v in versions if v["source_kind"] == "mops_xbrl_instance")
        (self.archive.root / removed["raw_storage_path"]).unlink()
        (self.archive.root / corrupted["raw_storage_path"]).write_bytes(b"tampered bytes")
        path, result = self.build()
        rows = {r["filing_version_id"]: r for r in self.csv_rows(path, "data/filing_versions.csv")}
        self.assertEqual(rows[removed["filing_version_id"]]["raw_evidence_included"], "false")
        self.assertEqual(rows[corrupted["filing_version_id"]]["raw_evidence_included"], "false")
        statuses = {(r["evidence_kind"], r["status"]) for r in self.csv_rows(path, "data/missing_evidence.csv")}
        self.assertIn(("raw_artifact", "missing_locally"), statuses)
        self.assertIn(("raw_artifact", "failed_integrity"), statuses)
        with zipfile.ZipFile(path) as archive:
            self.assertFalse([n for n in archive.namelist() if corrupted["content_hash"] in n])
            self.assertFalse([n for n in archive.namelist() if removed["content_hash"] in n])
        self.assertEqual(result["completeness"]["status"], "partial")
        self.assertEqual(verify_package(path)["status"], "verified")

    def test_port05_financial_facts_and_conference_evidence_stay_distinct(self) -> None:
        unavailable, result = self.build("no_conf.zip", PackageParameters("1785", 2013, 2014, include_conference=True))
        self.assertEqual(result["completeness"]["conference_evidence"], "unavailable_no_archive_configured")
        pdf = b"%PDF-1.4 synthetic conference deck"
        conference_root = self.root / "conference"
        builder = ResearchPackageBuilder(self.repository, self.archive,
                                         conference_repository=FakeConferenceRepository(conference_root, "1785", pdf),
                                         conference_root=conference_root)
        path, result = self.build("conf.zip", PackageParameters("1785", 2013, 2014, include_conference=True), builder)
        self.assertEqual(result["completeness"]["conference_evidence"], "included")
        index = self.csv_rows(path, "conference/conference_documents.csv")
        self.assertEqual([(r["period"], r["raw_evidence_included"]) for r in index], [("2016Q3", "true")])
        self.assertEqual(self.read(path, index[0]["package_raw_path"]), pdf)
        self.assertTrue(self.read(path, "contracts/JSD_INPUT_CONTRACT.md"))
        facts = self.csv_rows(path, "data/financial_facts.csv")
        self.assertEqual({r["evidence_type"] for r in facts}, {"official_filing_fact"})
        self.assertFalse([r for r in facts if r["source_kind"] not in {"mops_xbrl_instance"}])
        self.assertEqual(verify_package(path)["status"], "verified")

    def test_port06_versions_and_pit_metadata_preserved(self) -> None:
        path, _ = self.build("pit.zip", PackageParameters("1785", 2013, 2014, as_of="2016-11-14", version_policy="latest_available"))
        facts = self.csv_rows(path, "data/financial_facts.csv")
        reader = list_historical_facts(self.repository, "1785", 2013, 2014, as_of="2016-11-14",
                                       version_policy="latest_available", include_test_fixtures=False)
        self.assertEqual([(r["filing_version_id"], r["metric_code"]) for r in facts],
                         [(f["filing_version_id"], f["metric_code"]) for f in reader])
        self.assertTrue(all(r["point_in_time_eligible"] == "true" and r["availability_evidence_kind"] for r in facts))
        versions = self.csv_rows(path, "data/filing_versions.csv")
        self.assertEqual({r["filing_version_type"] for r in versions}, {"original", "restated"})
        manifest = json.loads(self.read(path, "manifest.json"))
        self.assertEqual(manifest["parameters"]["as_of"], "2016-11-14")


class PackageFailureInjectionTests(PackageTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.zip_path, _ = self.build()
        self.extracted = safe_extract(self.zip_path, self.root / "extracted")

    def rewrite(self, transform) -> Path:
        out = self.root / "modified.zip"
        with zipfile.ZipFile(self.zip_path) as source, zipfile.ZipFile(out, "w") as target:
            for info in source.infolist():
                result = transform(info, source.read(info))
                if result is not None:
                    target.writestr(*result)
        return out

    def test_invalid_checksum_and_tampered_files_fail(self) -> None:
        (self.extracted / "data" / "financial_facts.csv").write_bytes(b"tampered")
        with self.assertRaises(PackageVerificationError):
            verify_package(self.extracted)
        bad = self.rewrite(lambda info, data: (info, data + b"x" if info.filename.endswith("checksums.sha256") else data))
        with self.assertRaises(PackageVerificationError):
            verify_package(bad)

    def test_unlisted_and_missing_files_fail(self) -> None:
        (self.extracted / "data" / "extra.csv").write_text("x", encoding="utf-8")
        with self.assertRaises(PackageVerificationError):
            verify_package(self.extracted)
        (self.extracted / "data" / "extra.csv").unlink()
        (self.extracted / "data" / "coverage_matrix.csv").unlink()
        with self.assertRaises(PackageVerificationError):
            verify_package(self.extracted)

    def test_malformed_paths_and_symlinks_are_rejected(self) -> None:
        for name in ("../evil.txt", f"{PACKAGE_ROOT}/../evil.txt", "/abs/evil.txt", f"{PACKAGE_ROOT}/a\\b.txt",
                     "C:/evil.txt", f"{PACKAGE_ROOT}/data/.hidden"):
            bad = self.rewrite(lambda info, data: (info, data))
            with zipfile.ZipFile(bad, "a") as archive:
                archive.writestr(name, b"x")
            with self.assertRaises(PackageVerificationError, msg=name):
                verify_package(bad)
            with self.assertRaises(PackageVerificationError, msg=name):
                safe_extract(bad, self.root / "never")
        link = self.rewrite(lambda info, data: (info, data))
        with zipfile.ZipFile(link, "a") as archive:
            info = zipfile.ZipInfo(f"{PACKAGE_ROOT}/data/link")
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "/etc/passwd")
        with self.assertRaises(PackageVerificationError):
            verify_package(link)
        self.assertFalse((self.root / "never").exists())

    def test_package_contains_no_secrets_or_local_paths(self) -> None:
        with zipfile.ZipFile(self.zip_path) as archive:
            blob = b"".join(archive.read(name) for name in archive.namelist())
            names = archive.namelist()
        self.assertFalse([n for n in names if n.endswith((".env", ".sqlite3", ".db", ".json.key")) or "credential" in n.lower()])
        self.assertNotIn(str(self.root).encode(), blob)
        self.assertNotIn(b"GOOGLE_APPLICATION_CREDENTIALS", blob)


if __name__ == "__main__":
    unittest.main()
