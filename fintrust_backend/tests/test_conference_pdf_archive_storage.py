from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from google.api_core import exceptions as gexc

from app.claim_verification_models import ClaimVerifyRequest
from app.services.claim_evidence_adapter import ClaimEvidenceAdapter
from app.services.claim_verification_service import ClaimVerificationService
from app.services.conference_pdf_archive_storage import (
    GcsConferencePdfArchiveRepository,
    _TtlCache,
    publish_after_ingestion,
    publish_archive,
    verify_archive,
)
from app.services.mops_conference_pdf_repository import (
    FileConferencePdfArchiveRepository,
    build_conference_pdf_archive_repository,
)
from tests.test_claim_verification import income_table

PDF = b"%PDF-1.7 fake conference deck"
FILENAME = "233020251016E001.pdf"


class FakeBlob:
    def __init__(self, bucket: "FakeBucket", name: str) -> None:
        self.bucket, self.name = bucket, name
        self.metadata = None

    @property
    def _stored(self):
        return self.bucket.objects.get(self.name)

    @property
    def size(self):
        return len(self._stored["data"]) if self._stored else None

    @property
    def generation(self):
        return self._stored["generation"] if self._stored else None

    def download_as_bytes(self, timeout=None):
        self.bucket.client.check()
        if self._stored is None:
            raise gexc.NotFound(self.name)
        self.bucket.client.downloads.append(self.name)
        return self._stored["data"]

    def upload_from_string(self, data, content_type=None, timeout=None, if_generation_match=None):
        self.bucket.client.check()
        current = self._stored
        if if_generation_match == 0 and current is not None:
            raise gexc.PreconditionFailed(self.name)
        if if_generation_match not in (None, 0) and (current is None or current["generation"] != if_generation_match):
            raise gexc.PreconditionFailed(self.name)
        self.bucket.objects[self.name] = {"data": bytes(data), "metadata": dict(self.metadata or {}),
                                          "generation": (current["generation"] + 1) if current else 1,
                                          "content_type": content_type}
        self.bucket.client.uploads.append(self.name)


class FakeBucket:
    def __init__(self, client: "FakeClient") -> None:
        self.client, self.objects = client, {}

    def blob(self, name):
        return FakeBlob(self, name)

    def get_blob(self, name, timeout=None):
        self.client.check()
        if name not in self.objects:
            return None
        blob = FakeBlob(self, name)
        blob.metadata = dict(self.objects[name]["metadata"])
        return blob


class FakeIterator(list):
    prefixes: set


class FakeClient:
    def __init__(self) -> None:
        self.buckets: dict[str, FakeBucket] = {}
        self.fail: Exception | None = None
        self.uploads: list[str] = []
        self.downloads: list[str] = []
        self.listings = 0

    def check(self):
        if self.fail is not None:
            raise self.fail

    def bucket(self, name):
        return self.buckets.setdefault(name, FakeBucket(self))

    def list_blobs(self, bucket, prefix="", delimiter=None, timeout=None):
        self.check()
        self.listings += 1
        names = [n for n in self.bucket(bucket).objects if n.startswith(prefix)]
        iterator = FakeIterator(n for n in names if "/" not in n[len(prefix):])
        iterator.prefixes = {prefix + n[len(prefix):].split("/", 1)[0] + "/" for n in names if "/" in n[len(prefix):]}
        return iterator


def make_archive(root: Path, *, records=None) -> Path:
    directory = root / "2330" / "2025"
    directory.mkdir(parents=True)
    stem = FILENAME.removesuffix(".pdf")
    (directory / FILENAME).write_bytes(PDF)
    (directory / f"{stem}.txt").write_text("[page 4]\nGross Margin 59.5%", encoding="utf-8")
    for suffix, payload in ((".pages.json", [{"page": 4, "text": "Gross Margin 59.5%"}]),
                            (".analysis.json", [{"kind": "numeric_text", "page": 4, "value_text": "59.5%"}]),
                            (".semantic.json", records if records is not None else [income_table()])):
        (directory / f"{stem}{suffix}").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (directory / "listing-page-1.html").write_text("<html>公司代號 法人說明會簡報內容</html>", encoding="utf-8")
    review = directory / f"{stem}-review"
    review.mkdir()
    (review / "page-004.png").write_bytes(b"\x89PNG review")
    local = str(directory).replace("/", "\\")
    manifest = {
        "ticker": "2330", "year": 2025, "listing_url": "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1?co_id=2330",
        "retrieved_at": "2026-09-25T00:00:00+00:00", "status": "failed", "expected_pdfs": 1, "downloaded_pdfs": 1,
        "errors": [],
        "documents": [{
            "filename": FILENAME, "language": "en", "conference_dates": ["114/10/16"],
            "sha256": hashlib.sha256(PDF).hexdigest(), "page_count": 11,
            **{key: f"{local}\\{stem}{suffix}" for key, suffix in (
                ("pdf_path", ".pdf"), ("text_path", ".txt"), ("pages_path", ".pages.json"),
                ("analysis_path", ".analysis.json"), ("semantic_path", ".semantic.json"))},
        }],
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return directory


class ArchiveStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "archive"
        self.directory = make_archive(self.root)
        self.client = FakeClient()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def publish(self, **kwargs):
        return publish_archive(client=self.client, bucket="evidence", prefix="conference-pdf-archive", ticker="2330",
                               year=2025, directory=self.directory, **{"execute": True, **kwargs})

    def gcs_repo(self) -> GcsConferencePdfArchiveRepository:
        return GcsConferencePdfArchiveRepository("evidence", "conference-pdf-archive", client=self.client,
                                                 cache=_TtlCache(0))

    # A / B / E
    def test_gcs_repository_matches_local_repository(self) -> None:
        self.assertEqual(self.publish()["status"], "ok")
        local, gcs = FileConferencePdfArchiveRepository(self.root), self.gcs_repo()
        self.assertEqual(gcs.available_years("2330"), [2025])
        self.assertEqual(gcs.available_years("9999"), [])
        local_manifest, gcs_manifest = local.latest_manifest("2330", 2025), gcs.latest_manifest("2330", 2025)
        for key in ("ticker", "year", "listing_url", "retrieved_at", "status"):
            self.assertEqual(gcs_manifest[key], local_manifest[key])
        self.assertEqual(gcs_manifest["documents"][0]["sha256"], local_manifest["documents"][0]["sha256"])
        self.assertEqual(gcs_manifest["documents"][0]["semantic_path"], "233020251016E001.semantic.json")
        self.assertTrue(gcs_manifest["storage_contract"]["is_durable"])
        for method in ("pages", "analysis", "semantic"):
            self.assertEqual(getattr(gcs, method)("2330", 2025, FILENAME), getattr(local, method)("2330", 2025, FILENAME))
        self.assertEqual(gcs.document("2330", 2025, FILENAME)["filename"], FILENAME)

    def test_reads_are_bounded(self) -> None:
        self.publish()
        repo = self.gcs_repo()
        for _ in range(3):
            repo.semantic("2330", 2025, FILENAME)
        self.assertEqual(self.client.downloads.count("conference-pdf-archive/2330/2025/manifest.json"), 1)
        self.assertEqual(self.client.listings, 0)

    # C / D
    def test_missing_and_failing_storage_degrade_safely(self) -> None:
        repo = self.gcs_repo()
        self.assertIsNone(repo.latest_manifest("2330", 2025))
        self.assertEqual(repo.semantic("2330", 2025, FILENAME), [])
        self.publish()
        for error in (gexc.Forbidden("denied"), gexc.ServiceUnavailable("down"), TimeoutError("slow")):
            with self.subTest(error=type(error).__name__):
                self.client.fail = error
                failing = self.gcs_repo()
                self.assertEqual(failing.available_years("2330"), [])
                self.assertIsNone(failing.latest_manifest("2330", 2025))
                self.assertEqual(failing.semantic("2330", 2025, FILENAME), [])
        self.client.fail = None
        with self.assertRaises(ValueError):
            GcsConferencePdfArchiveRepository("", client=self.client)
        with self.assertRaises(ValueError):
            self.gcs_repo().latest_manifest("../2330", 2025)

    # F / G
    def test_factory_selects_backend_from_configuration(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"CONFERENCE_PDF_ARCHIVE_ROOT": str(self.root)}, clear=False):
            os.environ.pop("CONFERENCE_PDF_ARCHIVE_BACKEND", None)
            self.assertIsInstance(build_conference_pdf_archive_repository(), FileConferencePdfArchiveRepository)
        with unittest.mock.patch.dict(os.environ, {"CONFERENCE_PDF_ARCHIVE_BACKEND": "gcs",
                                                   "CONFERENCE_PDF_ARCHIVE_GCS_BUCKET": "evidence"}):
            repo = build_conference_pdf_archive_repository()
            self.assertIsInstance(repo, GcsConferencePdfArchiveRepository)
            self.assertEqual((repo.bucket_name, repo.prefix), ("evidence", "conference-pdf-archive"))
        with unittest.mock.patch.dict(os.environ, {"CONFERENCE_PDF_ARCHIVE_BACKEND": "gcs",
                                                   "CONFERENCE_PDF_ARCHIVE_GCS_BUCKET": ""}):
            with self.assertRaises(ValueError):
                build_conference_pdf_archive_repository()

    # H / I / J
    def test_dry_run_writes_nothing(self) -> None:
        report = self.publish(execute=False)
        self.assertEqual((report["mode"], report["uploaded"], self.client.uploads), ("dry_run", 0, []))
        self.assertEqual(report["planned"], 7)  # manifest, listing, pdf, txt, pages, analysis, semantic
        self.assertFalse(any(entry["type"] == "review_image" for entry in report["objects"]))
        self.assertEqual(self.publish(execute=False, include_review_images=True)["planned"], 8)

    def test_rerun_skips_same_sha256_and_verifies(self) -> None:
        first = self.publish()
        second = self.publish()
        self.assertEqual((first["uploaded"], second["uploaded"], second["skipped_same_sha256"]), (7, 0, 7))
        verification = verify_archive(client=self.client, bucket="evidence", prefix="conference-pdf-archive",
                                      ticker="2330", year=2025, directory=self.directory)
        self.assertEqual((verification["status"], verification["verified"]), ("ok", 7))
        stored = self.client.bucket("evidence").objects["conference-pdf-archive/2330/2025/233020251016E001.pdf"]
        self.assertEqual(stored["metadata"]["sha256"], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(stored["metadata"]["artifact_type"], "pdf")
        manifest = self.client.bucket("evidence").objects["conference-pdf-archive/2330/2025/manifest.json"]["data"]
        self.assertNotIn("\\", manifest.decode("utf-8"))

    def test_different_destination_is_a_conflict_not_an_overwrite(self) -> None:
        self.publish()
        name = "conference-pdf-archive/2330/2025/233020251016E001.semantic.json"
        objects = self.client.bucket("evidence").objects
        objects[name] = {"data": b"[]", "metadata": {"sha256": hashlib.sha256(b"[]").hexdigest()}, "generation": 7}
        report = self.publish()
        self.assertEqual((report["status"], report["conflicts"], report["uploaded"]), ("failed", [name], 0))
        self.assertEqual(objects[name]["data"], b"[]")
        verification = verify_archive(client=self.client, bucket="evidence", prefix="conference-pdf-archive",
                                      ticker="2330", year=2025, directory=self.directory)
        self.assertEqual(verification["status"], "failed")
        self.assertEqual(verification["size_mismatch"] + verification["sha256_mismatch"], [name])
        forced = self.publish(overwrite=True)
        self.assertEqual((forced["status"], forced["overwritten"]), ("ok", [name]))

    def test_corrupted_local_pdf_is_never_published(self) -> None:
        (self.directory / FILENAME).write_bytes(b"%PDF-tampered")
        with self.assertRaises(ValueError):
            self.publish()
        self.assertEqual(self.client.uploads, [])

    def test_local_archive_is_unchanged_by_publishing(self) -> None:
        before = {p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}
        self.publish()
        self.assertEqual({p: p.read_bytes() for p in self.directory.rglob("*") if p.is_file()}, before)

    # write-through hook
    def test_publish_after_ingestion_is_opt_in_and_never_raises(self) -> None:
        result = {"ticker": "2330", "year": 2025, "expected_pdfs": 1, "downloaded_pdfs": 1, "errors": []}
        self.assertIsNone(publish_after_ingestion(result, self.directory, client=self.client, environ={}))
        env = {"CONFERENCE_PDF_ARCHIVE_PUBLISH": "true", "CONFERENCE_PDF_ARCHIVE_GCS_BUCKET": "evidence"}
        incomplete = dict(result, downloaded_pdfs=0)
        self.assertEqual(publish_after_ingestion(incomplete, self.directory, client=self.client, environ=env)["status"],
                         "skipped")
        self.assertEqual(publish_after_ingestion(result, self.directory, client=self.client, environ=env)["uploaded"], 7)
        self.client.fail = gexc.Forbidden("no write")
        failed = publish_after_ingestion(result, self.directory, client=self.client, environ=env)
        self.assertEqual(failed["status"], "failed")

    # Gate 10 + K: Claim Verification over the GCS repository
    def test_claim_verification_over_gcs_backed_evidence(self) -> None:
        self.publish()
        service = ClaimVerificationService(ClaimEvidenceAdapter(fact_repository=None,
                                                                conference_repository=self.gcs_repo()))
        verdicts = {}
        for claim in ("台積電 2025 年第三季毛利率為 59.5%", "台積電 2025 年第三季毛利率為 65%",
                      "台積電 2025 年第三季 AI 加速器營收占比 30%"):
            response = service.verify(ClaimVerifyRequest(company_code="2330", claim=claim))
            verdicts[claim] = response.verdict
            payload = json.dumps(response.model_dump(), ensure_ascii=False)
            self.assertNotIn("gs://", payload)
            self.assertNotIn("conference-pdf-archive/", payload)
            self.assertNotIn(str(self.root), payload)
            self.assertNotIn("\\\\", payload)
        self.assertEqual(list(verdicts.values()), ["supported", "conflicting", "insufficient_evidence"])
        supported = service.verify(ClaimVerifyRequest(company_code="2330", claim="台積電 2025 年第三季毛利率為 59.5%"))
        decisive = next(item for item in supported.evidence if item.decisive)
        self.assertEqual((decisive.document, decisive.page, decisive.document_sha256),
                         (FILENAME, 4, hashlib.sha256(PDF).hexdigest()))
        self.assertTrue(decisive.source_reference.startswith("https://mopsov.twse.com.tw/"))

    def test_claim_verification_survives_gcs_outage(self) -> None:
        self.publish()
        self.client.fail = gexc.ServiceUnavailable("down")
        service = ClaimVerificationService(ClaimEvidenceAdapter(fact_repository=None,
                                                                conference_repository=self.gcs_repo()))
        response = service.verify(ClaimVerifyRequest(company_code="2330", claim="台積電 2025 年第三季毛利率為 59.5%"))
        self.assertEqual((response.verdict, response.reason_code), ("insufficient_evidence", "no_official_evidence"))


if __name__ == "__main__":
    unittest.main()
