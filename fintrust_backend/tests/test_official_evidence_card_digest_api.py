from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.official_event_models import InvestorConferenceRecord, OfficialEvidenceCardResponse
from app.services.analysis_repository import SqliteAnalysisRepository
from app.services.conference_document_digest import ConferenceDocumentDigestService
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
from tests.test_conference_document_digest import FIXTURE_ROOT, Q3_FILE, Q3_SHA


class OfficialEvidenceCardDigestApiTests(unittest.TestCase):
    LEGACY_CARD_KEYS = {
        "schema_version", "ticker", "company_name", "subindustry", "generated_at", "evidence_readiness", "overall_severity",
        "headline", "summary", "financial_snapshot", "key_metrics", "rule_cards", "investor_conferences", "material_events",
        "disclosure_claims", "text_evidence", "narrative_shift", "semantic_analysis", "llm_evidence_ids", "sources",
        "source_status", "limitations", "frontend_hints",
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        root = Path(cls.tempdir.name)
        os.environ.setdefault("DATASTORE_BACKEND", "sqlite")
        os.environ.setdefault("FINANCIAL_DATABASE_PATH", str(root / "pipeline.sqlite3"))
        os.environ.setdefault("FINANCIAL_FACT_DATABASE_PATH", str(root / "facts.sqlite3"))
        os.environ.setdefault("APP_ENV", "development")
        from app.dependencies import get_analysis_repository
        from app.main import app
        from app.routers.financial import get_conference_digest_service

        cls.app = app
        # Kept in a dict: functions stored as class attributes would bind as methods
        # and no longer match the dependency_overrides keys.
        cls.dependencies = {"repository": get_analysis_repository, "digest": get_conference_digest_service}
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.app.dependency_overrides.clear()
        cls.tempdir.cleanup()

    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()

    def tearDown(self) -> None:
        self.app.dependency_overrides.clear()

    def repository(self, name: str, conferences: list[InvestorConferenceRecord]) -> SqliteAnalysisRepository:
        repository = SqliteAnalysisRepository(str(Path(self.tempdir.name) / f"{name}.sqlite3"))
        repository.save_official_events(ticker="2454", investor_conferences=conferences, material_events=[],
                                        refreshed_at=datetime.now(timezone.utc))
        return repository

    @staticmethod
    def conference(event_id: str, *, year: int | None, quarter: int | None, date: str, title: str) -> InvestorConferenceRecord:
        return InvestorConferenceRecord(
            event_id=event_id, ticker="2454", company_name="聯發科", subindustry="IC 設計", fiscal_year=year, quarter=quarter,
            conference_date=date, title=title, source_name="company_official_ir",
            source_url="https://www.mediatek.com/zh-tw/investor-relations", status="available",
            extracted_topics=["營收"], related_metrics=["revenue"],
        )

    def get_card(self, repository, service) -> dict:
        self.app.dependency_overrides[self.dependencies["repository"]] = lambda: repository
        self.app.dependency_overrides[self.dependencies["digest"]] = lambda: service
        response = self.client.get("/api/v1/financial/companies/2454/official-evidence-card?include_material_events=false")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_matching_period_attaches_digest_to_the_conference_item(self) -> None:
        repository = self.repository("match", [self.conference("q3", year=2025, quarter=3, date="2025-10-31", title="2025Q3 法說會")])
        card = self.get_card(repository, ConferenceDocumentDigestService(FileConferencePdfArchiveRepository(FIXTURE_ROOT)))
        self.assertEqual(card["schema_version"], "frontend-official-evidence-card-1.3.0")
        self.assertTrue(self.LEGACY_CARD_KEYS <= set(card))
        item = card["investor_conferences"][0]
        self.assertTrue(set(InvestorConferenceRecord.model_fields) <= set(item))
        self.assertEqual(item["summary_status"], "available")
        self.assertEqual(item["document_digest"]["source"]["filename"], Q3_FILE)
        self.assertEqual(item["archive_identity"]["sha256"], Q3_SHA)
        self.assertEqual(item["evidence_coverage"], item["document_digest"]["coverage"])
        self.assertIsNone(card["conference_document_digest"])

    def test_unmatched_company_ir_period_never_borrows_another_document(self) -> None:
        repository = self.repository("nomatch", [self.conference("q2-2026", year=2026, quarter=2, date="2026-07-30", title="2026Q2 法說會 company IR")])
        card = self.get_card(repository, ConferenceDocumentDigestService(FileConferencePdfArchiveRepository(FIXTURE_ROOT)))
        item = card["investor_conferences"][0]
        self.assertEqual(item["summary_status"], "no_matching_archive")
        self.assertNotIn("document_digest", item)
        standalone = card["conference_document_digest"]
        self.assertEqual(standalone["period"], "2025Q3")
        self.assertEqual(standalone["source"]["filename"], Q3_FILE)
        self.assertNotIn("2026", json.dumps(standalone, ensure_ascii=False))
        self.assertNotIn("company IR", json.dumps(standalone, ensure_ascii=False))

    def test_without_digest_service_payload_is_unchanged(self) -> None:
        repository = self.repository("none", [self.conference("q3b", year=2025, quarter=3, date="2025-10-31", title="2025Q3 法說會")])
        card = self.get_card(repository, None)
        item = card["investor_conferences"][0]
        for key in ("document_digest", "summary_status", "evidence_coverage", "archive_identity"):
            self.assertNotIn(key, item)
        self.assertIsNone(card["conference_document_digest"])
        self.assertTrue(set(InvestorConferenceRecord.model_fields) <= set(item))

    def test_archive_errors_do_not_break_the_card(self) -> None:
        class Unreachable:
            def available_years(self, ticker):
                raise RuntimeError("gcs unavailable")

        repository = self.repository("broken", [self.conference("q3c", year=2025, quarter=3, date="2025-10-31", title="2025Q3 法說會")])
        card = self.get_card(repository, ConferenceDocumentDigestService(Unreachable()))
        self.assertEqual(card["investor_conferences"][0]["summary_status"], "archive_unavailable")
        self.assertIsNone(card["conference_document_digest"])
        self.assertIn("financial_snapshot", card)

    def test_response_model_keeps_item_level_digest_fields(self) -> None:
        response = OfficialEvidenceCardResponse(
            ticker="2454", company_name="聯發科", subindustry="IC 設計", generated_at=datetime.now(timezone.utc),
            evidence_readiness="partial", headline="h", summary="s",
            investor_conferences=[{"title": "t", "document_digest": {"period": "2025Q3"}, "summary_status": "available"}],
        )
        dumped = response.model_dump(mode="json")
        self.assertEqual(dumped["investor_conferences"][0]["document_digest"], {"period": "2025Q3"})
        self.assertEqual(dumped["investor_conferences"][0]["summary_status"], "available")


if __name__ == "__main__":
    unittest.main()
