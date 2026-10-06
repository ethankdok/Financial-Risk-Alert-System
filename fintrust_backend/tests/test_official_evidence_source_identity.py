"""Frontend contract 1.2.0: source_identity on every evidence item and the
conference_summary_state that relates conference items to the MOPS digest."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord
from app.services.analysis_repository import SqliteAnalysisRepository
from app.services.conference_document_digest import ConferenceDocumentDigestService
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
from app.services.official_evidence_cards import (
    OfficialEvidenceCardBuilder,
    conference_summary_state,
    digest_source_identity,
    record_source_identity,
)
from tests.test_conference_document_digest import FIXTURE_ROOT, Q3_FILE, Q3_SHA

IR_SOURCE_URL = "https://www.mediatek.com/zh-tw/investor-relations"
IR_DOCUMENT_URL = "https://www.mediatek.com/hubfs/Quarterly%20Earnings%20Release-2026Q2/Transcript.pdf"
MOPS_LISTING_PREFIX = "https://mopsov.twse.com.tw/"


def conference(event_id: str, *, year: int | None, quarter: int | None, date: str,
               document_url: str | None = IR_DOCUMENT_URL) -> InvestorConferenceRecord:
    return InvestorConferenceRecord(
        event_id=event_id, ticker="2454", company_name="聯發科", subindustry="IC 設計", fiscal_year=year, quarter=quarter,
        conference_date=date, title=f"MediaTek {year} Q{quarter} Results - Investors Conference",
        source_name="company_official_ir", source_url=IR_SOURCE_URL, document_url=document_url, status="available",
        retrieved_at=datetime(2026, 9, 26, tzinfo=timezone.utc),
    )


def material_event(event_id: str) -> MaterialEventRecord:
    return MaterialEventRecord(
        event_id=event_id, ticker="2454", company_name="聯發科", subindustry="IC 設計", event_date="2026-09-01",
        title="公告本公司董事會決議資本支出案", source_name="twse_openapi",
        source_url="https://openapi.twse.com.tw/v1/opendata/t187ap04_L", status="available",
    )


class StubDigestService:
    """Returns fixed (digest, status) pairs; models archive outcomes without an archive."""

    def __init__(self, targeted: str, latest: str) -> None:
        self.targeted, self.latest = targeted, latest

    def digest_for(self, ticker, *, period=None, conference_date=None):
        return None, self.targeted if (period or conference_date) else self.latest


class CardIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        ConferenceDocumentDigestService.clear_cache()
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self) -> None:
        self.folder.cleanup()

    def card(self, conferences, events=(), service=None):
        repository = SqliteAnalysisRepository(str(self.root / "card.sqlite3"))
        repository.save_official_events(ticker="2454", investor_conferences=list(conferences), material_events=list(events),
                                        refreshed_at=datetime.now(timezone.utc))
        return OfficialEvidenceCardBuilder(repository=repository, digest_service=service).build("2454").model_dump(mode="json")

    def fixture_service(self) -> ConferenceDocumentDigestService:
        return ConferenceDocumentDigestService(FileConferencePdfArchiveRepository(FIXTURE_ROOT))

    def test_2454_company_ir_2026q2_and_standalone_mops_2025q3_stay_separate(self) -> None:
        card = self.card([conference("q2-2026", year=2026, quarter=2, date="2026-07-31")], service=self.fixture_service())
        self.assertEqual(card["schema_version"], "frontend-official-evidence-card-1.3.0")
        self.assertEqual(card["conference_summary_state"], "standalone_latest")
        item = card["investor_conferences"][0]["source_identity"]
        self.assertEqual((item["source_type"], item["source_name"], item["period"], item["period_basis"]),
                         ("company_ir", "company_official_ir", "2026Q2", "fiscal_year_quarter"))
        self.assertEqual((item["filename"], item["document_type"], item["event_date"], item["availability"]),
                         (None, None, "2026-07-31", "available"))
        self.assertEqual(item["provenance"], {"url": IR_DOCUMENT_URL, "sha256": None, "retrieved_at": "2026-09-26T00:00:00Z"})
        digest = card["conference_document_digest"]["source_identity"]
        self.assertEqual((digest["source_type"], digest["source_name"], digest["period"], digest["period_basis"]),
                         ("mops_conference_pdf", "MOPS", "2025Q3", "document_identity"))
        self.assertEqual((digest["filename"], digest["document_type"], digest["event_date"], digest["availability"]),
                         (Q3_FILE, "earnings_presentation", "2025-10-31", "available"))
        self.assertEqual(digest["provenance"]["sha256"], Q3_SHA)
        self.assertTrue(digest["provenance"]["url"].startswith(MOPS_LISTING_PREFIX))
        self.assert_no_cross_source(card)

    def test_matched_period_keeps_company_ir_item_and_mops_digest_identities_apart(self) -> None:
        card = self.card([conference("q3-2025", year=2025, quarter=3, date="2025-10-31")], service=self.fixture_service())
        self.assertEqual(card["conference_summary_state"], "attached")
        self.assertIsNone(card["conference_document_digest"])
        item = card["investor_conferences"][0]
        self.assertEqual((item["source_identity"]["source_type"], item["source_identity"]["period"]), ("company_ir", "2025Q3"))
        attached = item["document_digest"]["source_identity"]
        self.assertEqual((attached["source_type"], attached["period"], attached["filename"]),
                         ("mops_conference_pdf", "2025Q3", Q3_FILE))
        self.assertNotEqual(attached["provenance"]["url"], item["source_identity"]["provenance"]["url"])
        self.assert_no_cross_source(card)

    def test_no_matching_archive(self) -> None:
        empty_archive = ConferenceDocumentDigestService(FileConferencePdfArchiveRepository(self.root / "empty-archive"))
        card = self.card([conference("q2-2026", year=2026, quarter=2, date="2026-07-31")], service=empty_archive)
        self.assertEqual(card["conference_summary_state"], "no_matching_archive")
        self.assertEqual(card["investor_conferences"][0]["summary_status"], "no_matching_archive")
        self.assertIsNone(card["conference_document_digest"])

    def test_archive_unavailable(self) -> None:
        class Unreachable:
            def available_years(self, ticker):
                raise RuntimeError("gcs unavailable")

        card = self.card([conference("q2-2026", year=2026, quarter=2, date="2026-07-31")],
                         service=ConferenceDocumentDigestService(Unreachable()))
        self.assertEqual(card["conference_summary_state"], "archive_unavailable")

    def test_digest_failed_and_timeout_states(self) -> None:
        for status in ("digest_failed", "digest_timeout"):
            card = self.card([conference("q3-2025", year=2025, quarter=3, date="2025-10-31")],
                             service=StubDigestService(targeted=status, latest=status))
            self.assertEqual(card["conference_summary_state"], status)

    def test_digest_service_exception_is_digest_failed(self) -> None:
        class Exploding:
            def digest_for(self, *args, **kwargs):
                raise RuntimeError("boom")

        card = self.card([conference("q3-2025", year=2025, quarter=3, date="2025-10-31")], service=Exploding())
        self.assertEqual(card["conference_summary_state"], "digest_failed")

    def test_not_configured_without_digest_service(self) -> None:
        card = self.card([conference("q2-2026", year=2026, quarter=2, date="2026-07-31")], service=None)
        self.assertEqual(card["conference_summary_state"], "not_configured")
        item = card["investor_conferences"][0]
        self.assertEqual(item["source_identity"]["source_type"], "company_ir")
        for key in ("document_digest", "summary_status", "evidence_coverage", "archive_identity"):
            self.assertNotIn(key, item)

    def test_material_event_source_identity(self) -> None:
        card = self.card([], events=[material_event("capex-event")], service=None)
        identity = card["material_events"][0]["source_identity"]
        self.assertEqual((identity["source_type"], identity["period"], identity["period_basis"], identity["event_date"]),
                         ("twse_openapi", None, "none", "2026-09-01"))
        self.assertEqual((identity["filename"], identity["document_type"], identity["availability"]), (None, None, "available"))
        self.assertEqual(identity["provenance"]["url"], "https://openapi.twse.com.tw/v1/opendata/t187ap04_L")

    def test_existing_fields_are_unchanged(self) -> None:
        legacy_card_keys = {
            "ticker", "company_name", "subindustry", "generated_at", "evidence_readiness", "overall_severity", "headline",
            "summary", "financial_snapshot", "key_metrics", "rule_cards", "investor_conferences", "conference_document_digest",
            "material_events", "disclosure_claims", "text_evidence", "narrative_shift", "semantic_analysis",
            "llm_evidence_ids", "sources", "source_status", "limitations", "frontend_hints",
        }
        record = conference("q2-2026", year=2026, quarter=2, date="2026-07-31")
        card = self.card([record], events=[material_event("capex-event")], service=self.fixture_service())
        self.assertTrue(legacy_card_keys <= set(card))
        item = card["investor_conferences"][0]
        persisted = record.model_dump(mode="json")
        for key in ("event_id", "fiscal_year", "quarter", "conference_date", "title", "source_name", "source_url",
                    "document_url", "status", "summary_status"):
            if key in persisted:
                self.assertEqual(item[key], persisted[key], key)
        self.assertTrue(set(InvestorConferenceRecord.model_fields) <= set(item))
        self.assertTrue(set(MaterialEventRecord.model_fields) <= set(card["material_events"][0]))
        self.assertEqual(card["source_status"]["document_digest_status"]["card_level_digest_status"], "available")

    def assert_no_cross_source(self, card: dict) -> None:
        ir_urls = {IR_SOURCE_URL, IR_DOCUMENT_URL}
        digests = [card.get("conference_document_digest")] + [item.get("document_digest") for item in card["investor_conferences"]]
        for digest in filter(None, digests):
            identity = digest["source_identity"]
            self.assertNotIn(identity["provenance"]["url"], ir_urls)
            self.assertNotIn("mediatek.com", json.dumps(identity))
        for item in card["investor_conferences"]:
            identity = json.dumps(item["source_identity"])
            self.assertNotIn(Q3_FILE, identity)
            self.assertNotIn(Q3_SHA, identity)


class IdentityRuleTests(unittest.TestCase):
    def test_conference_period_comes_only_from_fiscal_year_and_quarter(self) -> None:
        identity = record_source_identity({"source_name": "twse_openapi", "conference_date": "2025-10-31", "status": "available",
                                           "source_url": "https://openapi.twse.com.tw/x"}, "investor_conference")
        self.assertEqual((identity["period"], identity["period_basis"], identity["source_type"]), (None, "none", "twse_openapi"))

    def test_source_type_mapping(self) -> None:
        cases = [
            ({"source_name": "mops", "conference_date": "2025-10-31", "status": "available"}, "mops_listing"),
            ({"source_name": "mops", "status": "metadata_only"}, "metadata_placeholder"),
            ({"source_name": "公開資訊觀測站 法說會", "conference_date": "2025-10-31", "status": "metadata_only"}, "mops_listing"),
            ({"source_name": "DEMO FIXTURE（合成資料，非官方即時財報）", "status": "available"}, "demo_fixture"),
            ({"source_name": "somewhere-else", "status": "available"}, "unknown"),
        ]
        for record, expected in cases:
            self.assertEqual(record_source_identity(record, "investor_conference")["source_type"], expected, record)

    def test_availability_mapping(self) -> None:
        expected = {"available": "available", "metadata_only": "metadata_only", "needs_manual_review": "needs_review",
                    "blocked_by_source": "blocked", "missing": "unavailable", "error": "unavailable", "weird": "unavailable"}
        for status, availability in expected.items():
            identity = record_source_identity({"source_name": "mops", "event_date": "2026-01-01", "status": status}, "material_event")
            self.assertEqual(identity["availability"], availability, status)

    def test_material_event_prefers_detail_url(self) -> None:
        identity = record_source_identity({"source_name": "mops", "event_date": "2026-01-01", "status": "available",
                                           "source_url": "https://mops.example/list", "detail_url": "https://mops.example/detail"},
                                          "material_event")
        self.assertEqual(identity["provenance"]["url"], "https://mops.example/detail")

    def test_digest_identity_uses_only_mops_source(self) -> None:
        identity = digest_source_identity({
            "period": "2025Q3", "document_type": "earnings_presentation", "conference_date": "2025-10-31",
            "source": {"filename": Q3_FILE, "sha256": Q3_SHA, "listing_url": "https://mopsov.twse.com.tw/listing"},
        })
        self.assertEqual(identity["provenance"], {"url": "https://mopsov.twse.com.tw/listing", "sha256": Q3_SHA, "retrieved_at": None})

    def test_summary_state_precedence(self) -> None:
        digest = {"period": "2025Q3"}
        cases = [
            (None, None, "not_configured"),
            ({"matched_conference_count": 1, "card_level_digest_status": "attached_to_conference",
              "conference_summary_statuses": ["available", "no_matching_archive"]}, None, "attached"),
            ({"matched_conference_count": 0, "card_level_digest_status": "available",
              "conference_summary_statuses": ["archive_unavailable"]}, digest, "standalone_latest"),
            ({"matched_conference_count": 0, "card_level_digest_status": "digest_timeout",
              "conference_summary_statuses": ["archive_unavailable", "digest_failed"]}, None, "archive_unavailable"),
            ({"matched_conference_count": 0, "card_level_digest_status": "digest_timeout",
              "conference_summary_statuses": ["digest_failed"]}, None, "digest_failed"),
            ({"matched_conference_count": 0, "card_level_digest_status": "digest_timeout",
              "conference_summary_statuses": ["no_matching_archive"]}, None, "digest_timeout"),
            ({"matched_conference_count": 0, "card_level_digest_status": "no_matching_archive",
              "conference_summary_statuses": ["no_conference_period"]}, None, "no_matching_archive"),
            ({"card_level_digest_status": "digest_failed"}, None, "digest_failed"),
        ]
        for status, card_digest, expected in cases:
            self.assertEqual(conference_summary_state(status, card_digest), expected, status)


if __name__ == "__main__":
    unittest.main()
