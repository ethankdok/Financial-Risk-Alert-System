"""Hardening round 2: an unreadable archive backend is archive_unavailable, not
no_matching_archive, while a single unreadable object stays a per-document issue.

All GCS behaviour runs against an in-memory fake client; nothing touches a real bucket.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from google.api_core import exceptions as gexc

from app.official_event_models import InvestorConferenceRecord
from app.services.analysis_repository import SqliteAnalysisRepository
from app.services.conference_document_digest import ConferenceDocumentDigestService
from app.services.conference_jsd_corpus_adapter import build_records
from app.services.conference_pdf_archive_storage import GcsConferencePdfArchiveRepository, _TtlCache
from app.services.mops_conference_pdf_repository import (
    ConferenceArchiveUnavailableError,
    FileConferencePdfArchiveRepository,
)
from app.services.official_evidence_cards import OfficialEvidenceCardBuilder
from tests.test_conference_document_digest import FIXTURE_DIR, Q2_FILE, Q3_FILE
from tests.test_conference_pdf_archive_storage import FakeClient

BUCKET = "test-archive-bucket"
PREFIX = "conference-pdf-archive"


class SelectiveFailClient(FakeClient):
    """Fails downloads of chosen object names; everything else behaves normally."""

    def __init__(self, failing: dict[str, Exception] | None = None) -> None:
        super().__init__()
        self.failing = failing or {}
        client = self

        original_bucket = FakeClient.bucket

        def bucket(name):
            store = original_bucket(client, name)
            original_blob = store.blob

            def blob(object_name):
                handle = original_blob(object_name)
                if object_name in client.failing:
                    def fail(timeout=None, _error=client.failing[object_name]):
                        raise _error
                    handle.download_as_bytes = fail
                return handle
            store.blob = blob
            return store
        self.bucket = bucket


def load_fixture(client: FakeClient) -> None:
    store = FakeClient.bucket(client, BUCKET)
    for path in FIXTURE_DIR.iterdir():
        store.objects[f"{PREFIX}/2454/2025/{path.name}"] = {"data": path.read_bytes(), "metadata": {}, "generation": 1}


def gcs_repo(client: FakeClient) -> GcsConferencePdfArchiveRepository:
    return GcsConferencePdfArchiveRepository(BUCKET, PREFIX, client=client, cache=_TtlCache(300))


class ListingFailureTests(unittest.TestCase):
    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()

    def digest(self, repo, **target):
        return ConferenceDocumentDigestService(repo).digest_for("2454", **target)

    def test_readable_empty_local_archive_is_no_matching_archive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.digest(FileConferencePdfArchiveRepository(folder)), (None, "no_matching_archive"))

    def test_readable_empty_gcs_prefix_is_no_matching_archive(self) -> None:
        repo = gcs_repo(FakeClient())
        self.assertEqual(repo.list_available_years("2454"), [])
        self.assertEqual(self.digest(repo), (None, "no_matching_archive"))
        self.assertEqual(self.digest(repo, period="2025Q3"), (None, "no_matching_archive"))

    def test_listing_failures_are_archive_unavailable(self) -> None:
        for error in (gexc.NotFound("bucket missing"), gexc.Forbidden("permission denied"),
                      gexc.PermissionDenied("permission denied"), gexc.ServiceUnavailable("backend down"),
                      ConnectionError("transport"), TimeoutError("timed out")):
            client = FakeClient()
            load_fixture(client)
            client.fail = error
            repo = gcs_repo(client)
            with self.subTest(error=type(error).__name__):
                with self.assertRaises(ConferenceArchiveUnavailableError) as raised:
                    repo.list_available_years("2454")
                self.assertEqual(raised.exception.error_type, type(error).__name__)
                with self.assertLogs("app.services.conference_document_digest", level="WARNING") as logs:
                    self.assertEqual(self.digest(repo), (None, "archive_unavailable"))
                self.assertIn(type(error).__name__, "\n".join(logs.output))
                self.assertEqual(self.digest(repo, period="2025Q3"), (None, "archive_unavailable"))

    def test_lenient_listing_is_unchanged_for_jsd_and_claim_callers(self) -> None:
        client = FakeClient()
        client.fail = gexc.Forbidden("permission denied")
        repo = gcs_repo(client)
        with self.assertLogs("app.services.conference_pdf_archive_storage", level="WARNING"):
            self.assertEqual(repo.available_years("2454"), [])
        self.assertEqual(build_records(repo, "2454"), [])

    def test_valid_archive_behaviour_is_unchanged(self) -> None:
        digest, status = self.digest(gcs_repo(self._loaded()))
        self.assertEqual(status, "available")
        self.assertEqual((digest["source"]["filename"], digest["period"], digest["language"]), (Q3_FILE, "2025Q3", "zh-Hant"))
        self.assertEqual(digest["coverage"]["coverage_status"], "partial")

    def _loaded(self, failing: dict[str, Exception] | None = None) -> FakeClient:
        client = SelectiveFailClient(failing)
        load_fixture(client)
        return client


class PartialObjectResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()

    def test_one_unreadable_candidate_does_not_block_the_valid_one(self) -> None:
        q2_pages = f"{PREFIX}/2454/2025/{Q2_FILE[:-4]}.pages.json"
        client = SelectiveFailClient({q2_pages: gexc.Forbidden("object acl")})
        load_fixture(client)
        digest, status = ConferenceDocumentDigestService(gcs_repo(client)).digest_for("2454")
        self.assertEqual(status, "available")
        self.assertEqual(digest["source"]["filename"], Q3_FILE)

    def test_one_unreadable_manifest_year_does_not_block_other_years(self) -> None:
        client = SelectiveFailClient({f"{PREFIX}/2454/2026/manifest.json": gexc.ServiceUnavailable("flaky")})
        load_fixture(client)
        store = FakeClient.bucket(client, BUCKET)
        store.objects[f"{PREFIX}/2454/2026/manifest.json"] = {"data": b"{}", "metadata": {}, "generation": 1}
        repo = gcs_repo(client)
        self.assertEqual(repo.list_available_years("2454"), [2026, 2025])
        digest, status = ConferenceDocumentDigestService(repo).digest_for("2454")
        self.assertEqual(status, "available")
        self.assertEqual(digest["source"]["filename"], Q3_FILE)


class CardPropagationTests(unittest.TestCase):
    """The existing archive_unavailable contract state reaches the card and the API without a 500."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        cls.repository = SqliteAnalysisRepository(str(Path(cls.folder.name) / "card.sqlite3"))
        cls.repository.save_official_events(ticker="2454", investor_conferences=[InvestorConferenceRecord(
            event_id="ir-2026q2", ticker="2454", company_name="聯發科", subindustry="IC 設計", fiscal_year=2026, quarter=2,
            conference_date="2026-07-31", title="MediaTek 2026 Q2 Results - Investors Conference",
            source_name="company_official_ir", source_url="https://www.mediatek.com/zh-tw/investor-relations",
            status="available")], material_events=[], refreshed_at=datetime.now(timezone.utc))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()

    def failing_service(self) -> ConferenceDocumentDigestService:
        client = FakeClient()
        client.fail = gexc.Forbidden("permission denied")
        return ConferenceDocumentDigestService(gcs_repo(client))

    def test_card_reports_archive_unavailable(self) -> None:
        card = OfficialEvidenceCardBuilder(repository=self.repository, digest_service=self.failing_service()).build("2454")
        payload = card.model_dump(mode="json")
        self.assertEqual(payload["conference_summary_state"], "archive_unavailable")
        self.assertEqual(payload["investor_conferences"][0]["summary_status"], "archive_unavailable")
        self.assertIsNone(payload["conference_document_digest"])
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(BUCKET, text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn("permission denied", text)

    def test_api_returns_200_with_archive_unavailable(self) -> None:
        from app.dependencies import get_analysis_repository
        from app.main import app
        from app.routers.financial import get_conference_digest_service

        app.dependency_overrides[get_analysis_repository] = lambda: self.repository
        app.dependency_overrides[get_conference_digest_service] = self.failing_service
        try:
            response = TestClient(app).get("/api/v1/financial/companies/2454/official-evidence-card?include_material_events=false")
        finally:
            app.dependency_overrides.clear()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["conference_summary_state"], "archive_unavailable")


if __name__ == "__main__":
    unittest.main()
