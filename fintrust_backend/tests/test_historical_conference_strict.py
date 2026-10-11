"""Conference evidence (CONF-*) and strict point-in-time packaging (fixture tier).

The conference archive here is SYNTHETIC but laid out exactly like the MOPS
conference pipeline's output and read through the real
FileConferencePdfArchiveRepository and JSD adapter.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.services.conference_document_identity import IDENTITY_VERSION
from app.services.conference_jsd_corpus_adapter import CORPUS_FIELDS
from app.services.historical_audit.conference_coverage import ConferenceCoverageRecorder, classify_listing
from app.services.historical_audit.package_verify import (
    CHECKSUMS,
    MANIFEST,
    PACKAGE_ROOT,
    PackageVerificationError,
    safe_extract,
    verify_package,
)
from app.services.historical_audit.research_package import (
    PackageParameters,
    ResearchPackageBuilder,
    ResearchPackageError,
)
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
from tests.test_historical_evidence import EvidenceTestCase

FIXED = datetime(2026, 10, 10, tzinfo=timezone.utc)
NO_DATA_PAGE = "<html><body><center>查無資料</center></body></html>".encode("utf-8")


def write_conference(root: Path, year: int, filename: str, *, period=None, status="unconfirmed",
                     doc_type="investor_presentation", pages=None) -> bytes:
    pdf = f"%PDF-1.4 synthetic {filename}".encode()
    directory = root / "1785" / str(year)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_bytes(pdf)
    pages = pages or [
        {"page": 1, "text": "2011. 03. 25 Investor Conference", "text_length": 32, "text_extraction_method": "selectable_text",
         "contains_images": True, "contains_drawings": False, "visual_review_required": True,
         "review_image_path": "C:\\local\\page-001.png"},
        {"page": 2, "text": "", "text_length": 0, "text_extraction_method": "selectable_text", "contains_images": True,
         "contains_drawings": True, "visual_review_required": True},
        {"page": 3, "text": "Revenue", "text_length": 7, "text_extraction_method": "selectable_text",
         "contains_images": False, "contains_drawings": False, "visual_review_required": False},
    ]
    stem = filename.removesuffix(".pdf")
    (directory / f"{stem}.pages.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    manifest_path = directory / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {
        "listing_url": "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1?step=1&TYPEK=otc&year=100&co_id=1785",
        "retrieved_at": "2026-10-10T00:00:00+00:00", "rows": 1, "documents": [], "errors": []}
    manifest["documents"].append({
        "filename": filename, "language": "en", "sha256": hashlib.sha256(pdf).hexdigest(), "conference_dates": ["100/03/25"],
        "identity_version": IDENTITY_VERSION, "period": period, "period_validation_status": status,
        "document_type": doc_type, "document_type_confidence": 0.75, "document_language": "en", "quarantined": False,
        "quarantine_reasons": [], "download_fields": {"step": "9", "filePath": "/STR/", "fileName": filename},
        # Same keys the MOPS conference pipeline records (working-directory relative there).
        "pdf_path": f"{stem}.pdf", "pages_path": f"{stem}.pages.json",
        "issues": ["page_1:visual_review_required"]})
    manifest["expected_pdfs"] = len(manifest["documents"])
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return pdf


class ConferenceTestCase(EvidenceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_all()
        self.conference_root = self.root / "conference"
        self.pdf = write_conference(self.conference_root, 2013, "178520130325E001.pdf")
        write_conference(self.conference_root, 2010, "178520100126M001.pdf")  # pre-period context
        self.conference = FileConferencePdfArchiveRepository(self.conference_root)

    def builder(self) -> ResearchPackageBuilder:
        return ResearchPackageBuilder(self.repository, self.archive, conference_repository=self.conference,
                                      conference_root=self.conference_root)

    def build(self, name: str, **params) -> tuple[Path, dict]:
        path = self.root / name
        defaults = {"include_conference": True}
        return path, self.builder().build(PackageParameters("1785", 2013, 2014, **{**defaults, **params}), path,
                                          generated_at=FIXED)

    @staticmethod
    def read(path: Path, member: str) -> bytes:
        with zipfile.ZipFile(path) as archive:
            return archive.read(f"{PACKAGE_ROOT}/{member}")

    def rows(self, path: Path, member: str) -> list[dict]:
        return list(csv.DictReader(io.StringIO(self.read(path, member).decode("utf-8"))))

    def names(self, path: Path) -> list[str]:
        with zipfile.ZipFile(path) as archive:
            return [n[len(PACKAGE_ROOT) + 1:] for n in archive.namelist()]


class ConferenceDuplicateTests(ConferenceTestCase):
    def test_reused_decks_and_language_versions_are_marked(self) -> None:
        """The same deck listed for several meetings is one document; M/E files are one presentation."""
        write_conference(self.conference_root, 2013, "178520130325M001.pdf")
        write_conference(self.conference_root, 2013, "178520130325E002.pdf")
        directory = self.conference_root / "1785" / "2013"
        (directory / "178520130325E002.pdf").write_bytes(self.pdf)  # identical bytes to E001, listed again
        pages = json.loads((directory / "178520130325E002.pages.json").read_text(encoding="utf-8"))
        pages[0]["analysis_results"] = [{"filename": "178520130325E002.pdf"}]  # per-listing metadata, as in real 2018 data
        (directory / "178520130325E002.pages.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        for document in manifest["documents"]:
            if document["filename"] == "178520130325E002.pdf":
                document["sha256"] = hashlib.sha256(self.pdf).hexdigest()
        (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        path, _ = self.build("dup.zip")
        rows = {r["filename"]: r for r in self.rows(path, "data/conference_documents.csv")}
        self.assertEqual(rows["178520130325E002.pdf"]["content_duplicate_of"], "178520130325E001.pdf")
        # One content-addressed raw/pages/text set per SHA-256, shared by both rows (no conflicting duplicate paths).
        self.assertEqual(rows["178520130325E002.pdf"]["package_raw_path"], rows["178520130325E001.pdf"]["package_raw_path"])
        self.assertEqual(verify_package(path)["status"], "verified")
        self.assertEqual(rows["178520130325E001.pdf"]["content_duplicate_of"], "")
        self.assertEqual(rows["178520130325E001.pdf"]["language_pair_key"], rows["178520130325M001.pdf"]["language_pair_key"])
        self.assertNotEqual(rows["178520130325E002.pdf"]["language_pair_key"], rows["178520130325E001.pdf"]["language_pair_key"])


class ConferenceDatasetTests(ConferenceTestCase):
    def test_conference_packaging_refuses_a_cloud_datastore(self) -> None:
        from unittest import mock

        with mock.patch.dict("os.environ", {"DATASTORE_BACKEND": "firestore"}):
            with self.assertRaises(ResearchPackageError):
                self.build("cloud.zip")
        self.assertFalse((self.root / "cloud.zip").exists())

    def test_conf04_05_06_original_pdf_pages_and_identity(self) -> None:
        path, result = self.build("full.zip")
        documents = self.rows(path, "data/conference_documents.csv")
        self.assertEqual([(d["filename"], d["research_role"], d["document_type"]) for d in documents],
                         [("178520130325E001.pdf", "core", "investor_presentation")])  # never relabelled a transcript
        document = documents[0]
        self.assertEqual(self.read(path, document["package_raw_path"]), self.pdf)
        self.assertEqual(document["sha256"], hashlib.sha256(self.pdf).hexdigest())
        self.assertEqual(document["publication_availability_status"], "unverified")
        pages = {(p["page"], p["text_status"]) for p in self.rows(path, "data/conference_page_index.csv")}
        self.assertEqual(pages, {("1", "text_extracted"), ("2", "image_or_scanned"), ("3", "low_text_coverage")})
        page_json = self.read(path, f"conference/pages/{document['sha256']}.pages.json")
        self.assertNotIn(b"review_image_path", page_json)  # local paths never ship
        self.assertIn(b"Investor Conference", self.read(path, f"conference/text/{document['sha256']}.txt"))
        self.assertEqual(result["conference"]["documents"], 1)
        self.assertEqual(result["conference"]["out_of_range_excluded"], 1)  # 2010 context kept out by default

    def test_conf07_jsd_contract_is_not_weakened(self) -> None:
        path, result = self.build("full.zip")
        corpus = self.rows(path, "data/conference_jsd_corpus.csv")
        header = next(csv.reader(io.StringIO(self.read(path, "data/conference_jsd_corpus.csv").decode("utf-8"))))
        self.assertEqual(tuple(header), tuple(CORPUS_FIELDS))
        self.assertEqual(corpus, [])  # unconfirmed period → not JSD-ready
        self.assertEqual(result["conference"]["jsd_ready"], 0)
        archival = self.rows(path, "data/conference_text_corpus.csv")
        self.assertEqual([(r["archival_only"], r["period"]) for r in archival], [("true", "")])
        self.assertIn("readiness_issues", self.rows(path, "data/conference_documents.csv")[0])
        self.assertIn("contracts/JSD_INPUT_CONTRACT.md", self.names(path))

    def test_context_years_only_on_request(self) -> None:
        path, result = self.build("ctx.zip", include_context_years=True)
        roles = {d["research_role"] for d in self.rows(path, "data/conference_documents.csv")}
        self.assertEqual(roles, {"core", "pre_period_context"})
        self.assertEqual(result["conference"]["out_of_range_excluded"], 0)


class ConferenceCoverageTests(ConferenceTestCase):
    class Transport:
        def __init__(self, responses):
            self.responses, self.calls = responses, []

        def listing(self, ticker, roc_year, market, page=1):
            self.calls.append((ticker, roc_year, market))
            response = self.responses[roc_year + 1911]
            if isinstance(response, Exception):
                raise response
            return response

    def test_conf03_08_year_by_year_status_and_missing_years(self) -> None:
        sleeps = []
        transport = self.Transport({2014: NO_DATA_PAGE, 2015: ConnectionError("down"), 2016: b"<html>throttled</html>"})
        recorder = ConferenceCoverageRecorder(self.repository, self.archive, self.conference_root, transport=transport,
                                              sleep=sleeps.append)
        (self.conference_root / "1785" / "2013" / "listing-page-1.html").write_bytes(b"<html>saved listing</html>")
        rows = {r["year"]: r for r in recorder.record("1785", [2013, 2014, 2015, 2016], market="otc",
                                                      start_year=2011, end_year=2016)}
        self.assertEqual(rows[2014]["status"], "no_official_record_found")
        self.assertEqual(rows[2015]["status"], "official_listing_unavailable")  # transport failure ≠ absence
        self.assertEqual(rows[2016]["status"], "official_listing_unavailable")
        self.assertEqual([c[2] for c in transport.calls], ["otc", "otc", "otc"])
        self.assertNotIn(2013, [c[1] + 1911 for c in transport.calls])  # saved listing reused, no request
        self.assertEqual(len(sleeps), 2)  # polite spacing between the three requests
        self.assertEqual(rows[2014]["listing_sha256"], hashlib.sha256(NO_DATA_PAGE).hexdigest())
        path = self.root / "cov.zip"  # package range covers every recorded year (roles are package-relative)
        self.builder().build(PackageParameters("1785", 2013, 2016, include_conference=True), path, generated_at=FIXED)
        coverage = {r["year"]: r["status"] for r in self.rows(path, "data/conference_coverage.csv")}
        self.assertEqual(coverage["2014"], "no_official_record_found")
        missing = {(r["fiscal_year"], r["status"]) for r in self.rows(path, "data/missing_evidence.csv")
                   if r["evidence_kind"] == "conference_listing"}
        self.assertIn(("2014", "no_official_record_found"), missing)
        self.assertIn(("2015", "official_listing_unavailable"), missing)
        self.assertEqual(classify_listing(NO_DATA_PAGE, ticker="1785", year=2014)[0], "no_official_record_found")

    @staticmethod
    def found_listing(roc_year: int, filenames: list[str]) -> bytes:
        def cell(name: str) -> str:
            link = (f'document.fm_fileDownload.fileName.value=&quot;{name}&quot;;'
                    'document.fm_fileDownload.filePath.value=&quot;/home/html/nas/STR/&quot;;'
                    'document.fm_fileDownload.functionName.value=&quot;t100sb02_1&quot;;document.fm_fileDownload.submit();')
            return f'<a onclick="{link}">{name}</a>'
        zh = [n for n in filenames if "M" in n[12:]]
        en = [n for n in filenames if "E" in n[12:]]
        return ('<form action="/server-java/FileDownLoad"></form>'
                '<table><thead><tr><th>公司代號</th><th>法人說明會簡報內容</th></tr></thead><tbody>'
                f'<tr data-type="body"><td>1785</td><td>光洋科</td><td>{roc_year}/05/16</td><td>x</td><td>x</td><td>x</td>'
                f'<td>{"".join(cell(n) for n in zh)}</td><td>{"".join(cell(n) for n in en)}</td></tr></tbody></table>'
                '<input onclick="page(1)" value="1">').encode()

    def record_with_archive(self, year: int, listed: list[str], archived: dict[str, bytes], *, failed=(), manifest_extra=()):
        """Isolated F-2B-02 scenario: an official listing plus a pipeline manifest/archive in a temporary root."""
        directory = self.conference_root / "1785" / str(year)
        directory.mkdir(parents=True, exist_ok=True)
        documents = []
        for name in [*listed, *manifest_extra]:
            document = {"filename": name}
            if name in archived:
                (directory / name).write_bytes(archived[name])
                document["sha256"] = hashlib.sha256(archived[name]).hexdigest()
            if name in failed:
                document["error"] = "MOPS request failed: URLError: timed out"
            documents.append(document)
        (directory / "manifest.json").write_text(json.dumps({"documents": documents, "rows": 1}), encoding="utf-8")
        transport = self.Transport({year: self.found_listing(year - 1911, listed)})
        recorder = ConferenceCoverageRecorder(self.repository, self.archive, self.conference_root, transport=transport,
                                              sleep=lambda _: None)
        return recorder.record("1785", [year], market="otc", start_year=2011, end_year=2022)[0]

    def test_f2b02_missing_counts_follow_listing_and_verified_archive(self) -> None:
        pair = ["178520200910M001.pdf", "178520200910E001.pdf"]

        def counts(row):
            return row["status"], row["expected_documents"], row["downloaded_documents"], row["missing_documents"]

        self.assertEqual(counts(self.record_with_archive(2020, pair, {})), ("document_missing", 2, 0, 2))  # zero downloads
        self.assertEqual(counts(self.record_with_archive(2021, ["178520210910M001.pdf", "178520210910E001.pdf"],
                                                         {"178520210910M001.pdf": b"%PDF-1 zh"})),
                         ("document_missing", 2, 1, 1))  # partial
        self.assertEqual(counts(self.record_with_archive(2022, ["178520220910M001.pdf", "178520220910E001.pdf"],
                                                         {"178520220910M001.pdf": b"%PDF-1 zh", "178520220910E001.pdf": b"%PDF-1 en"})),
                         ("conference_found", 2, 2, 0))  # complete
        self.assertEqual(counts(self.record_with_archive(2019, ["178520190910M001.pdf", "178520190910E001.pdf"],
                                                         {"178520190910M001.pdf": b"%PDF-1 zh"}, failed=("178520190910E001.pdf",))),
                         ("download_failed", 2, 1, 1))  # failed download

    def test_f2b02_duplicates_and_unverified_files_are_not_double_counted(self) -> None:
        # The same attachment listed in two rows and twice in the manifest counts once.
        twice = self.record_with_archive(2018, ["178520180502M001.pdf", "178520180502M001.pdf", "178520180502E001.pdf"],
                                         {"178520180502M001.pdf": b"%PDF-1 deck", "178520180502E001.pdf": b"%PDF-1 deck"})
        self.assertEqual((twice["expected_documents"], twice["downloaded_documents"], twice["missing_documents"]), (2, 2, 0))
        # A manifest hash whose archived bytes no longer match is not an archived attachment.
        row = self.record_with_archive(2017, ["178520170414M001.pdf", "178520170414E001.pdf"],
                                       {"178520170414M001.pdf": b"%PDF-1 zh", "178520170414E001.pdf": b"%PDF-1 en"})
        self.assertEqual(row["missing_documents"], 0)
        (self.conference_root / "1785" / "2017" / "178520170414E001.pdf").write_bytes(b"%PDF-1 tampered")
        listing = self.found_listing(106, ["178520170414M001.pdf", "178520170414E001.pdf"])
        recorder = ConferenceCoverageRecorder(self.repository, self.archive, self.conference_root,
                                              transport=self.Transport({2017: listing}), sleep=lambda _: None)
        again = recorder.record("1785", [2017], market="otc", start_year=2011, end_year=2022)[0]
        self.assertEqual((again["status"], again["downloaded_documents"], again["missing_documents"]), ("document_missing", 1, 1))
        # The package's coverage CSV reports the same totals.
        path = self.root / "f2b02.zip"
        self.builder().build(PackageParameters("1785", 2017, 2022, include_conference=True), path, generated_at=FIXED)
        csv_rows = {r["year"]: r for r in self.rows(path, "data/conference_coverage.csv")}
        self.assertEqual((csv_rows["2017"]["expected_documents"], csv_rows["2017"]["downloaded_documents"],
                          csv_rows["2017"]["missing_documents"]), ("2", "1", "1"))
        self.assertEqual((csv_rows["2018"]["expected_documents"], csv_rows["2018"]["missing_documents"]), ("2", "0"))

    def test_listed_documents_without_an_archive_are_missing_not_found(self) -> None:
        """A listing with documents but no pipeline manifest must not read as fully covered (0 expected, 0 downloaded)."""
        transport = self.Transport({2019: self.found_listing(108, ["178520190516M001.pdf", "178520190516E001.pdf"])})
        recorder = ConferenceCoverageRecorder(self.repository, self.archive, self.conference_root, transport=transport,
                                              sleep=lambda _: None)
        row = recorder.record("1785", [2019], market="otc", start_year=2011, end_year=2019)[0]
        self.assertEqual((row["status"], row["expected_documents"], row["downloaded_documents"], row["conference_rows"]),
                         ("document_missing", 2, 0, 1))
        self.assertEqual(json.loads(row["meeting_dates_json"]), ["108/05/16"])
        path = self.root / "listed.zip"
        self.builder().build(PackageParameters("1785", 2013, 2019, include_conference=True), path, generated_at=FIXED)
        detail = next(r["detail"] for r in self.rows(path, "data/missing_evidence.csv")
                      if r["evidence_kind"] == "conference_listing" and r["fiscal_year"] == "2019")
        self.assertEqual(detail, "official MOPS t100sb02_1 listing names 2 document(s); 0 archived")

    def test_coverage_role_follows_the_package_range(self) -> None:
        """2017 recorded while the case range was 2011-2016 is context there, but core in a 2011-2017 package."""
        transport = self.Transport({2017: NO_DATA_PAGE})
        recorder = ConferenceCoverageRecorder(self.repository, self.archive, self.conference_root, transport=transport,
                                              sleep=lambda _: None)
        stored = recorder.record("1785", [2017], market="otc", start_year=2011, end_year=2016)
        self.assertEqual(stored[0]["research_role"], "post_period_context")
        narrow, _ = self.build("narrow.zip")  # 2013-2014 package: 2017 is context and omitted
        self.assertNotIn("2017", {r["year"] for r in self.rows(narrow, "data/conference_coverage.csv")})
        wide = self.root / "wide.zip"
        self.builder().build(PackageParameters("1785", 2013, 2017, include_conference=True), wide, generated_at=FIXED)
        rows = {r["year"]: r for r in self.rows(wide, "data/conference_coverage.csv")}
        self.assertEqual((rows["2017"]["research_role"], rows["2017"]["status"]), ("core", "no_official_record_found"))
        missing = {(r["fiscal_year"], r["status"]) for r in self.rows(wide, "data/missing_evidence.csv")
                   if r["evidence_kind"] == "conference_listing"}
        self.assertIn(("2017", "no_official_record_found"), missing)


class StrictPointInTimeTests(ConferenceTestCase):
    CUTOFF = "2016-11-14"

    def strict(self, name="strict.zip", **params) -> tuple[Path, dict]:
        return self.build(name, as_of=self.CUTOFF, **params)

    def tamper(self, path: Path, member: str | None, payload: bytes | None = None, *, extra: dict | None = None,
               manifest_update: dict | None = None) -> Path:
        """Rewrite a package consistently (checksums + manifest) so only the semantic verifier can catch it."""
        out = self.root / f"tampered-{len(list(self.root.glob('tampered-*')))}.zip"
        with zipfile.ZipFile(path) as source:
            files = {n[len(PACKAGE_ROOT) + 1:]: source.read(n) for n in source.namelist()}
        if member is not None:
            files[member] = payload
        files.update(extra or {})
        listed = {n: d for n, d in files.items() if n not in {MANIFEST, CHECKSUMS}}
        checksums = "".join(f"{hashlib.sha256(d).hexdigest()}  {n}\n" for n, d in sorted(listed.items())).encode()
        manifest_data = json.loads(files[MANIFEST])
        manifest_data.update(manifest_update or {})
        manifest_data["checksums_sha256"] = hashlib.sha256(checksums).hexdigest()
        manifest_data["files"] = [{"path": n, "sha256": hashlib.sha256(d).hexdigest(), "bytes": len(d)}
                                  for n, d in sorted(listed.items())]
        files[CHECKSUMS], files[MANIFEST] = checksums, json.dumps(manifest_data).encode()
        with zipfile.ZipFile(out, "w") as target:
            for name, data in files.items():
                target.writestr(f"{PACKAGE_ROOT}/{name}", data)
        return out

    def test_mode_validation(self) -> None:
        with self.assertRaises(ResearchPackageError):
            self.build("x.zip", as_of=self.CUTOFF, mode="retrospective")
        with self.assertRaises(ResearchPackageError):
            self.build("x.zip", mode="strict_point_in_time")

    def test_strict_requirements_1_to_8(self) -> None:
        path, result = self.strict()
        names = self.names(path)
        versions = self.rows(path, "data/filing_versions.csv")
        # 1-2: only artifacts verified public before the cutoff; no XBRL, no unverified PDFs.
        self.assertEqual([(v["source_kind"], v["filing_version_type"]) for v in versions], [("official_pdf", "original")])
        self.assertFalse([n for n in names if n.endswith(".xml")])
        # 3: no event after the cutoff.
        cutoff = datetime.fromisoformat("2016-11-15T00:00:00+08:00")
        self.assertTrue(all(datetime.fromisoformat(e["available_from"]) < cutoff
                            for e in self.rows(path, "data/publication_timeline.csv")))
        # 4 + 6: later notices (TPEx 2016-11-15, MOPS 12-05) and snapshot documents (listings, workbooks) excluded.
        inventory = {r["source_key"] for r in self.rows(path, "data/source_inventory.csv")}
        self.assertEqual(inventory, {"mops-material-detail-20161113-212622-3"})
        self.assertFalse([n for n in names if n.endswith((".xls",)) or "listing" in n or "summaries/" in n])
        # 5: conference material with unverified availability is absent.
        self.assertFalse([n for n in names if n.startswith("conference/") or n.startswith("data/conference")])
        self.assertEqual(result["excluded_by_cutoff"]["conference_documents"], 2)
        # 7: the 2016-11-13 disclosure survives.
        self.assertEqual(len(self.rows(path, "data/restatement_comparisons.csv")), 10)
        # 8: facts reference the included disclosure, never the withheld XBRL.
        facts = self.rows(path, "data/financial_facts.csv")
        raw = {n.rsplit("/", 1)[1].split(".")[0] for n in names if n.startswith("raw_evidence/")}
        self.assertTrue(facts)
        for fact in facts:
            self.assertEqual(fact["artifact_reference_status"], "withheld_not_public_at_cutoff")
            self.assertEqual((fact["filing_version_id"], fact["content_hash"], fact["retrieved_at"]), ("", "", ""))
            self.assertIn(fact["availability_evidence_hash"], raw)
        self.assertNotIn(str(self.root).encode(), b"".join(self.read(path, n) for n in names if not n.startswith("raw_")))

    def test_strict_requirement_9_temporal_consistency_is_verified(self) -> None:
        path, _ = self.strict()
        self.assertEqual(verify_package(path)["mode"], "strict_point_in_time")
        manifest = json.loads(self.read(path, MANIFEST))
        report = json.loads(self.read(path, "validation/quality_report.json"))
        self.assertEqual((manifest["leakage_check"], report["leakage_check"]), ("passed", "passed"))
        self.assertTrue(manifest["suitable_for_historical_backtest"])

        tamper = lambda member, payload, **kw: self.tamper(path, member, payload, **kw)  # noqa: E731

        timeline = self.read(path, "data/publication_timeline.csv") + b"1785,x,late,t,,2016-12-05T17:43:16+08:00,second,2016-12-05T17:43:16+08:00,,,,,,,false,,\n"
        with self.assertRaises(PackageVerificationError):
            verify_package(tamper("data/publication_timeline.csv", timeline))
        with self.assertRaises(PackageVerificationError):
            verify_package(tamper("data/financial_facts.csv", self.read(path, "data/financial_facts.csv"),
                                  extra={"raw_evidence/financial_filings/1785/2016FY/" + "a" * 64 + ".pdf": b"%PDF-later"}))

    def test_modern_metadata_lives_only_in_the_reviewer_sidecar(self) -> None:
        path, result = self.strict()
        names = self.names(path)
        manifest = json.loads(self.read(path, MANIFEST))
        self.assertIsNone(manifest["generated_at"])
        self.assertNotIn("excluded_by_cutoff", manifest)
        self.assertEqual(manifest["cutoff_taipei"], "2016-11-15T00:00:00+08:00")
        self.assertNotIn("validation/provenance.csv", names)
        self.assertEqual(self.rows(path, "data/missing_evidence.csv"), [])
        report = json.loads(self.read(path, "validation/quality_report.json"))
        self.assertNotIn("excluded_by_cutoff_or_unverified_availability", report)
        model_facing = b"".join(self.read(path, n) for n in names
                                if not n.startswith("raw_evidence/") and n != "validation/verify_package.py")
        self.assertNotIn(b"2026-", model_facing)
        audit = json.loads(Path(result["audit_path"]).read_text(encoding="utf-8"))
        self.assertEqual(audit["package_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(audit["generated_at"], "2026-10-10T00:00:00+00:00")
        self.assertEqual(audit["excluded_by_cutoff"]["conference_documents"], 2)
        self.assertTrue(audit["raw_evidence_provenance"])
        self.assertNotIn(Path(result["audit_path"]).name, names)
        # Every model-facing timestamp is Asia/Taipei.
        for row in self.rows(path, "data/financial_facts.csv") + self.rows(path, "data/restatement_comparisons.csv"):
            for key in ("effective_available_at", "observation_available_at", "disclosed_at"):
                if row.get(key):
                    self.assertTrue(row[key].endswith("+08:00"), (key, row[key]))

    def test_summaries_are_reclassified_with_metric_specific_disclosures(self) -> None:
        path, result = self.strict()
        audit = json.loads(Path(result["audit_path"]).read_text(encoding="utf-8"))
        decisions = audit["summary_observation_review"]
        retained = [d for d in decisions if d["decision"].startswith("retained")]
        summaries = self.rows(path, "data/historical_summaries.csv")
        self.assertTrue(summaries)
        self.assertEqual(len(summaries), len(retained))
        for row in summaries:
            self.assertEqual(row["evidence_type"], "official_disclosed_observation")
            self.assertEqual((row["source_url"], row["content_hash"], row["retrieved_at"]), ("", "", ""))
            self.assertEqual(row["source_reference_status"], "workbook_withheld_not_public_at_cutoff")
            self.assertEqual(row["side_consistency"], "consistent")
            self.assertEqual(row["pit_evidence_kind"], "restatement_disclosure")
            self.assertEqual(row["scope_inference_basis"], "report_row_revenue_match")
            self.assertIn("inferred from that row's revenue", row["statement_scope_basis"])
            if row["canonical_metric"] != "revenue":
                self.assertIn(f"not from this {row['canonical_metric']} value", row["statement_scope_basis"])
        for decision in decisions:
            if not decision["decision"].startswith("retained"):
                self.assertTrue(decision["decision"].startswith("excluded: "))

    def test_semantic_verifier_fails_closed(self) -> None:
        path, _ = self.strict()
        verify_package(path)
        facts = self.read(path, "data/financial_facts.csv").decode("utf-8")
        evidence_hash = self.rows(path, "data/financial_facts.csv")[0]["availability_evidence_hash"]
        cases = {
            "modern manifest key": self.tamper(path, None, manifest_update={"excluded_by_cutoff": {"versions": 3}}),
            "generated_at": self.tamper(path, None, manifest_update={"generated_at": "2016-11-14T00:00:00+00:00"}),
            "reference to excluded evidence": self.tamper(
                path, "data/missing_evidence.csv", b"fiscal_year,evidence_kind,status,detail\n,x,y," + b"b" * 64 + b"\n"),
            "unresolved disclosure": self.tamper(path, "data/financial_facts.csv", facts.replace(evidence_hash, "", 1).encode()),
            "non-Taipei timestamp": self.tamper(
                path, "data/restatement_comparisons.csv",
                self.read(path, "data/restatement_comparisons.csv").replace(b"+08:00", b"+00:00", 1)),
            "conference material": self.tamper(path, None, extra={"conference/x.pdf": b"%PDF"}),
            "count mismatch": self.tamper(path, None, manifest_update={"counts": {"financial_facts": 0}}),
        }
        for label, tampered in cases.items():
            with self.subTest(label), self.assertRaises(PackageVerificationError):
                verify_package(tampered)

    def test_summary_rows_are_rederived_from_the_raw_notice(self) -> None:
        from tests.historical_evidence_fixtures import mutate_csv, repack_package

        path, _ = self.strict()
        verify_package(path)
        summaries = self.read(path, "data/historical_summaries.csv")
        row = {"report_period": "2013FY", "source_metric_code": "tpex_operating_revenue"}
        cases = {
            "side": ({"pit_evidence_side": "pre"}, "pit_evidence_side 'pre' but the notice states the value on pre\\+post"),
            "value": ({"value": "1000001", "normalized_value": "1000001000"}, "value 1000001 is not stated"),
            "scope": ({"statement_scope": "individual"}, "statement scope individual disagrees"),
            "year": ({"report_period": "2014FY", "fiscal_year": "2014", "period": "2014FY"}, "is not stated for 2014"),
            "unit": ({"normalized_unit": "TWD_thousand"}, "unit or normalized value disagrees"),
            "reference": ({"pit_evidence_ref": "mops:20161113:212622:4"}, "is not the included notice"),
        }
        for label, (changes, reason) in cases.items():
            with self.subTest(label):
                target = repack_package(path, self.root / f"f1-{label}.zip",
                                        {"data/historical_summaries.csv": mutate_csv(summaries, row, changes)})
                with self.assertRaisesRegex(PackageVerificationError, reason):
                    verify_package(target)

    def test_notice_parser_fails_closed(self) -> None:
        from app.services.historical_audit.package_verify import parse_restatement_notice
        from tests.historical_evidence_fixtures import COMPARISON_EXPLANATION, mops_detail

        parsed = parse_restatement_notice(mops_detail("20161113", "212622", "3", "本公司重編合併財務報告說明",
                                                      COMPARISON_EXPLANATION))
        self.assertEqual((parsed["event_key"], parsed["scope"]), ("mops:20161113:212622:3", "consolidated"))
        self.assertEqual(parsed["values"][("pre", "income", "營業收入", 2013)], 1000000)
        self.assertEqual(parsed["values"][("post", "income", "營業成本", 2014)], -900000)
        for label, data in {
            "not a notice": b"<html><body>no disclosure here</body></html>",
            "missing time": mops_detail("20161113", "212622", "3", "x", "y").replace("發言時間".encode(), b"time"),
            "unit not TWD thousand": mops_detail("20161113", "212622", "3", "本公司重編合併財務報告說明",
                                                 COMPARISON_EXPLANATION.replace("單位:仟元", "單位:元")),
        }.items():
            with self.subTest(label), self.assertRaises(PackageVerificationError):
                parse_restatement_notice(data)
        unknown = parse_restatement_notice(mops_detail("20161113", "212622", "3", "財務報告說明", "說明"))
        self.assertEqual((unknown["scope"], unknown["values"]), ("unknown", {}))  # matches no row -> rows fail closed

    def test_disclosure_dated_fact_with_a_verified_artifact_is_still_verified(self) -> None:
        """A disclosure-dated fact relabelled as having a public artifact must still resolve its disclosure, and a
        fact dated by its artifact must carry that artifact's verified time (no bypass via artifact status)."""
        from tests.historical_evidence_fixtures import mutate_csv, repack_package

        path, _ = self.strict()
        facts = self.read(path, "data/financial_facts.csv")
        first = self.rows(path, "data/financial_facts.csv")[0]
        version = self.rows(path, "data/filing_versions.csv")[0]
        row = {"period": first["period"], "metric_code": first["metric_code"]}
        public = {"artifact_reference_status": "verified_public_artifact", "filing_version_id": version["filing_version_id"]}
        cases = {
            "unresolvable disclosure": ({**public, "availability_evidence_hash": version["content_hash"]},  # included, not a notice
                                        "does not resolve to an included disclosure"),
            "disclosure later than stated time": ({**public, "effective_available_at": "2016-11-13T21:26:21+08:00",
                                                   "observation_available_at": "2016-11-13T21:26:21+08:00"},
                                                  "published after the stated availability"),
            "observation time differs": ({**public, "observation_available_at": "2016-11-13T21:26:21+08:00"},
                                         "observation and effective availability disagree"),
            "artifact time not the version's": ({**public, "availability_evidence_kind": "filing_artifact"},
                                                "not the included artifact's verified time"),
            "unknown evidence kind": ({**public, "availability_evidence_kind": "rumour"}, "unknown availability_evidence_kind"),
        }
        envelope = json.loads(self.read(path, "data/financial_facts.json"))

        def typed(value: str):
            return None if value == "" else True if value == "true" else False if value == "false" else value

        for label, (changes, reason) in cases.items():
            with self.subTest(label):
                mutated = mutate_csv(facts, row, changes)  # CSV and JSON stay consistent: only semantics can catch it
                records = [{k: typed(v) for k, v in r.items()} for r in csv.DictReader(io.StringIO(mutated.decode("utf-8")))]
                target = repack_package(path, self.root / f"bypass-{label.replace(' ', '_')}.zip", {
                    "data/financial_facts.csv": mutated,
                    "data/financial_facts.json": json.dumps({**envelope, "records": records}, ensure_ascii=False).encode("utf-8")})
                with self.assertRaisesRegex(PackageVerificationError, reason):
                    verify_package(target)

    def test_cutoff_matrix_fixture(self) -> None:
        previous = None
        for index, cutoff in enumerate(("2016-05-12", "2016-05-13T00:00:00+08:00", "2016-11-13T21:26:21+08:00",
                                        "2016-11-13T21:26:22+08:00", "2016-11-14", "2017-12-31")):
            path, result = self.build(f"cut{index}.zip", as_of=cutoff)
            self.assertEqual(verify_package(path)["status"], "verified", cutoff)
            if previous:
                self.assertTrue(all(result["counts"][k] >= previous[k] for k in result["counts"]), cutoff)
            previous = result["counts"]
            if index == 2:
                self.assertEqual(self.rows(path, "data/financial_facts.csv"), [])
            if index == 3:
                self.assertTrue(self.rows(path, "data/financial_facts.csv"))

    def test_strict_requirement_10_verifies_after_clean_extraction(self) -> None:
        path, _ = self.strict()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as elsewhere:
            shutil.copyfile(path, Path(elsewhere) / "strict.zip")
            root = safe_extract(Path(elsewhere) / "strict.zip", Path(elsewhere) / "out")
            completed = subprocess.run([sys.executable, "-I", str(root / "validation" / "verify_package.py"), str(root)],
                                       cwd=elsewhere, capture_output=True, text=True, timeout=120)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["mode"], "strict_point_in_time")

    def test_earlier_cutoff_excludes_everything_later(self) -> None:
        path, _ = self.build("early.zip", as_of="2016-05-31")
        self.assertEqual(self.rows(path, "data/financial_facts.csv"), [])
        self.assertEqual(self.rows(path, "data/filing_versions.csv"), [])
        self.assertEqual(self.rows(path, "data/restatement_comparisons.csv"), [])
        self.assertFalse([n for n in self.names(path) if n.startswith("raw_evidence/")])
        self.assertEqual(verify_package(path)["status"], "verified")


if __name__ == "__main__":
    unittest.main()


class ConferenceRecoveryRunnerTests(unittest.TestCase):
    """Bounded recovery runner: pacing, one backoff retry, and fail-safe stop conditions (no network)."""

    class Inner:
        def __init__(self, outcomes):
            self.outcomes = list(outcomes)

        def listing(self, ticker, roc_year, market, page=1):
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def pdf(self, attachment, referer):
            return self.listing("", 0, "")

    def transport(self, outcomes, cap=3):
        from scripts.recover_historical_conference_pdfs import PacedTransport

        sleeps = []
        return PacedTransport(self.Inner(outcomes), delay=2.0, max_consecutive_failures=cap, sleep=sleeps.append), sleeps

    def test_transient_failure_is_retried_once_with_backoff(self) -> None:
        from app.services.mops_conference_pdf_pipeline import AcquisitionError

        paced, sleeps = self.transport([b"first", AcquisitionError("MOPS request failed: URLError: timed out"), b"ok"])
        self.assertEqual(paced.listing("1785", 107, "otc"), b"first")
        self.assertEqual(paced.listing("1785", 107, "otc"), b"ok")
        self.assertEqual(sleeps, [2.0, 8.0])  # spacing, then backoff for the retry

    def test_access_restriction_stops_immediately(self) -> None:
        from app.services.mops_conference_pdf_pipeline import AcquisitionError
        from scripts.recover_historical_conference_pdfs import StopRecovery

        paced, _ = self.transport([AcquisitionError("MOPS request failed: HTTPError: HTTP Error 429: Too Many Requests")])
        with self.assertRaisesRegex(StopRecovery, "access restricted"):
            paced.listing("1785", 107, "otc")

    def test_consecutive_failures_stop_the_run(self) -> None:
        from app.services.mops_conference_pdf_pipeline import AcquisitionError
        from scripts.recover_historical_conference_pdfs import StopRecovery

        error = AcquisitionError("MOPS request failed: URLError: unreachable")
        paced, _ = self.transport([error, error, error, error], cap=3)
        with self.assertRaises(AcquisitionError):
            paced.listing("1785", 107, "otc")  # 2 failures: retried once, then reported
        with self.assertRaisesRegex(StopRecovery, "3 consecutive failed requests"):
            paced.listing("1785", 108, "otc")


class ConferenceRecoveryExitStatusTests(unittest.TestCase):
    """F-2B-01: per-year acquisition outcome and CLI exit status (offline; fake pipeline, transport and recorder)."""

    class Case:
        ticker, default_start_year, default_end_year = "1785", 2011, 2016

    class Recorder:
        def record(self, ticker, years, **_):
            return [{"status": "recorded", "conference_rows": 0, "meeting_dates_json": "[]", "expected_documents": 0,
                     "downloaded_documents": 0, "non_pdf_attachments": 0, "missing_documents": 0}]

    @staticmethod
    def result(listed, archived, *, review="needs_review", errors=(), listing=True, status="failed"):
        documents = [{"filename": name, **({"sha256": "a" * 64, "status": review} if name in archived else {"status": "failed"})}
                     for name in listed]
        return {"status": status, "listing_pages": [1] if listing else [], "documents": documents, "errors": list(errors),
                "expected_pdfs": len(listed), "downloaded_pdfs": len(archived)}

    def run_years(self, outcomes, years=(2018, 2019)):
        from scripts.recover_historical_conference_pdfs import PacedTransport, run_recovery

        calls = []
        transport = PacedTransport(ConferenceRecoveryRunnerTests.Inner([]), delay=0, max_consecutive_failures=3,
                                   sleep=lambda _: None)

        def pipeline(*, ticker, year, transport, **_):
            calls.append(year)
            outcome = outcomes[year]
            if callable(outcome):
                return outcome(transport)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        report, code = run_recovery(self.Case(), list(years), market="otc", output=Path("unused"), transport=transport,
                                    recorder=self.Recorder(), pipeline=pipeline)
        return report, code, calls

    def test_classify_separates_acquisition_from_review(self) -> None:
        from scripts.recover_historical_conference_pdfs import classify_year

        pair = ["a.pdf", "b.pdf"]
        self.assertEqual(classify_year(self.result(pair, pair)), ("complete", "visual_review_pending"))  # LLM/OCR off
        self.assertEqual(classify_year(self.result(pair, pair, review="complete", status="complete")), ("complete", "complete"))
        self.assertEqual(classify_year(self.result(pair, ["a.pdf"])), ("partial", "visual_review_pending"))
        self.assertEqual(classify_year(self.result(pair, [])), ("failed", "not_applicable"))
        self.assertEqual(classify_year(self.result([], [], listing=False, errors=["MOPS reports no data (查無資料)"])),
                         ("no_official_record", "not_applicable"))
        self.assertEqual(classify_year(self.result([], [], listing=False, errors=["MOPS request failed: URLError"])),
                         ("failed", "not_applicable"))
        self.assertEqual(classify_year(self.result([], [])), ("no_documents_listed", "not_applicable"))

    def test_complete_years_exit_zero_even_with_review_pending(self) -> None:
        pair = ["a.pdf", "b.pdf"]
        report, code, _ = self.run_years({2018: self.result(pair, pair), 2019: self.result([], [], listing=False,
                                                                                            errors=["查無資料"])})
        self.assertEqual(code, 0)
        self.assertEqual(report["years"][2018]["review_status"], "visual_review_pending")

    def test_failed_year_then_next_year_still_runs_and_exits_nonzero(self) -> None:
        pair = ["a.pdf", "b.pdf"]
        report, code, calls = self.run_years({2018: RuntimeError("disk full"), 2019: self.result(pair, pair)})
        self.assertEqual(calls, [2018, 2019])
        self.assertEqual((report["years"][2018]["acquisition_status"], report["years"][2019]["acquisition_status"]),
                         ("failed", "complete"))
        self.assertEqual(code, 1)
        report, code, _ = self.run_years({2018: self.result(pair, [], errors=["a.pdf: timeout", "b.pdf: timeout"]),
                                          2019: self.result(pair, pair)})
        self.assertEqual((report["years"][2018]["acquisition_status"], code), ("failed", 1))

    def test_partial_download_exits_nonzero(self) -> None:
        report, code, _ = self.run_years({2018: self.result(["a.pdf", "b.pdf"], ["a.pdf"]), 2019: self.result([], [])})
        self.assertEqual((report["years"][2018]["acquisition_status"], code), ("partial", 1))

    def test_stop_inside_the_pipeline_is_not_swallowed(self) -> None:
        from app.services.mops_conference_pdf_pipeline import AcquisitionError

        def blocked(transport):
            transport.inner = ConferenceRecoveryRunnerTests.Inner(
                [AcquisitionError("MOPS request failed: HTTPError: HTTP Error 403: Forbidden")])
            try:  # the real pipeline catches per-document exceptions like this
                transport.pdf(type("A", (), {"filename": "a.pdf"})(), "https://mopsov.twse.com.tw/")
            except Exception:
                pass
            return self.result(["a.pdf"], [])

        report, code, calls = self.run_years({2018: blocked, 2019: self.result(["c.pdf"], ["c.pdf"])})
        self.assertEqual(calls, [2018])  # no further year once stopped
        self.assertEqual(report["years"][2018]["acquisition_status"], "stopped")
        self.assertEqual(report["years"][2019]["acquisition_status"], "not_attempted")
        self.assertEqual(code, 2)
        self.assertIn("access restricted", report["stopped"])
