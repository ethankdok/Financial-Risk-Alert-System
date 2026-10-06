"""Material-event data path and the card's explicit material_event_status contract.

No test reaches the network: the MOPS listing comes from a sanitized capture of the
public mopsov.twse.com.tw ajax_t05st01 page for 2454 (ROC 115) and the TWSE feed
from inline rows.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.official_event_models import OfficialEventSyncStatus
from app.services.analysis_repository import SqliteAnalysisRepository
from app.services.firestore_analysis_repository import FirestoreAnalysisRepository
from app.services.material_event_status import (
    material_event_status,
    read_material_event_sync,
    record_material_event_sync,
)
from app.services.official_event_batch_ingestion import OfficialEventBatchIngestionService
from app.services.official_event_ingestion import OfficialEventIngestionService
from app.services.official_event_sources import (
    MOPS_MATERIAL_LISTING_URL,
    check_recent_mops_material_events,
    current_day_material_event_check,
    is_mops_material_listing,
    material_event_identity,
    parse_material_event_list_html,
)
from app.services.official_evidence_cards import OfficialEvidenceCardBuilder

FIXTURE = Path(__file__).parent / "fixtures" / "mops_material_events" / "2454_115_listing.html"
LISTING_HTML = FIXTURE.read_text(encoding="utf-8")
TODAY = date(2026, 10, 6)
SECURITY_PAGE = "<html><body>因為安全性考量，您所執行的頁面無法呈現。 FOR SECURITY REASONS, THIS PAGE CAN NOT BE ACCESSED.</body></html>"
TWSE_ROW_2303 = {
    "出表日期": "1151005", "發言日期": "1151005", "發言時間": "173000", "公司代號": "2303",
    "公司名稱": "聯電", "主旨 ": "公告本公司取得機器設備之相關資料", "符合條款": "第20款",
    "事實發生日": "1151005", "說明": "取得機器設備之相關資料。",
}
# A feed for 2026-10-05 that carries no 2454 row.
TWSE_ROWS_WITHOUT_2454 = [TWSE_ROW_2303]


def listing_fetcher(html: str = LISTING_HTML, calls: list | None = None):
    def fetch(ticker: str, year: int) -> str:
        if calls is not None:
            calls.append((ticker, year))
        return html
    return fetch


class _Repository:
    """Temporary SQLite repository for one test."""

    def __enter__(self) -> SqliteAnalysisRepository:
        self._directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        return SqliteAnalysisRepository(str(Path(self._directory.name) / "pipeline.sqlite3"))

    def __exit__(self, *_exc) -> None:
        self._directory.cleanup()


def card_for(repository, ticker: str) -> dict:
    builder = OfficialEvidenceCardBuilder(repository=repository)
    return builder.build(ticker, include_conferences=False).model_dump(mode="json")


class MopsListingParserTests(unittest.TestCase):
    def test_2454_listing_keeps_titles_that_contain_the_company_name(self) -> None:
        records = parse_material_event_list_html("2454", LISTING_HTML, max_items=20)
        titles = [record.title for record in records]
        self.assertIn("聯發科技115年8月份自結合併營收淨額公告", titles)
        self.assertIn("聯發科技114年12月份自結合併營收淨額公告", titles)
        self.assertNotIn("聯發科 重大訊息", titles)

    def test_listing_is_newest_first_and_skips_the_banner_row(self) -> None:
        records = parse_material_event_list_html("2454", LISTING_HTML, max_items=20)
        self.assertEqual(len(records), 6)
        self.assertEqual([record.event_date for record in records[:2]], ["2026-09-11", "2026-09-10"])
        self.assertEqual(records[0].event_time, "18:04:11")
        self.assertTrue(all(record.event_date for record in records))
        # max_items keeps the newest rows, not the oldest.
        newest_two = parse_material_event_list_html("2454", LISTING_HTML, max_items=2)
        self.assertEqual([record.event_date for record in newest_two], ["2026-09-11", "2026-09-10"])

    def test_identity_is_stable_and_comes_from_the_listing_form_fields(self) -> None:
        first = parse_material_event_list_html("2454", LISTING_HTML, max_items=20)
        second = parse_material_event_list_html("2454", LISTING_HTML, max_items=20)
        self.assertEqual([item.event_id for item in first], [item.event_id for item in second])
        self.assertEqual(len({item.event_id for item in first}), len(first))
        self.assertTrue(all(item.event_id == material_event_identity(item) for item in first))

    def test_records_keep_official_provenance_without_inventing_a_detail_url(self) -> None:
        record = parse_material_event_list_html("2454", LISTING_HTML, max_items=1)[0]
        self.assertEqual(record.source_name, "mops")
        self.assertTrue(record.source_url.startswith(MOPS_MATERIAL_LISTING_URL + "?"))
        self.assertIn("co_id=2454", record.source_url)
        self.assertIsNone(record.detail_url)
        self.assertEqual(record.status, "available")
        self.assertIn("115/09/11", record.raw_text or "")
        self.assertIsNotNone(record.retrieved_at)
        self.assertTrue(any("表單送出" in limitation for limitation in record.limitations))

    def test_listing_recognition_never_accepts_shell_or_security_pages(self) -> None:
        self.assertTrue(is_mops_material_listing(LISTING_HTML))
        self.assertFalse(is_mops_material_listing(SECURITY_PAGE))
        self.assertFalse(is_mops_material_listing("<script>location.href = location.origin + '/mops';</script>"))
        self.assertTrue(is_mops_material_listing("<html><body>查無資料</body></html>"))


class SourceCheckTests(unittest.TestCase):
    def test_recent_window_finds_2454_records_with_one_bounded_request(self) -> None:
        calls: list = []
        records, status = check_recent_mops_material_events("2454", today=TODAY, fetch_html=listing_fetcher(calls=calls))
        self.assertEqual(calls, [("2454", 2026)])
        self.assertEqual(status.outcome, "records_found")
        self.assertEqual(status.coverage, "recent_window")
        self.assertEqual((status.window_start, status.window_end), ("2026-07-08", "2026-10-06"))
        self.assertEqual([record.event_date for record in records], ["2026-09-11", "2026-09-10", "2026-09-03", "2026-09-02"])

    def test_window_crossing_a_year_queries_at_most_two_years(self) -> None:
        calls: list = []
        check_recent_mops_material_events("2454", today=date(2027, 1, 15), fetch_html=listing_fetcher(calls=calls))
        self.assertEqual(calls, [("2454", 2027), ("2454", 2026)])

    def test_successful_listing_with_no_rows_in_window_is_no_records_in_window(self) -> None:
        records, status = check_recent_mops_material_events("2454", today=date(2026, 12, 31), fetch_html=listing_fetcher())
        self.assertEqual(records, [])
        self.assertEqual(status.outcome, "no_records_in_window")

    def test_failed_blocked_or_unrecognised_source_is_source_unavailable(self) -> None:
        def raises(_ticker: str, _year: int) -> str:
            raise TimeoutError("The read operation timed out")

        for fetch, expected_error in (
            (raises, "TimeoutError"),
            (listing_fetcher(SECURITY_PAGE), "blocked_by_source"),
            (listing_fetcher("<html><body><div>redesigned page</div></body></html>"), "unrecognized_listing"),
        ):
            with self.subTest(expected_error=expected_error):
                records, status = check_recent_mops_material_events("2454", today=TODAY, fetch_html=fetch)
                self.assertEqual(records, [])
                self.assertEqual(status.outcome, "source_unavailable")
                self.assertIn(expected_error, status.error or "")

    def test_current_day_feed_without_the_ticker_is_not_a_no_events_answer(self) -> None:
        records, status = current_day_material_event_check("2454", TWSE_ROWS_WITHOUT_2454)
        self.assertEqual(records, [])
        self.assertEqual(status.outcome, "no_current_day_records")
        self.assertEqual(status.coverage, "current_day")
        self.assertEqual((status.window_start, status.window_end), ("2026-10-05", "2026-10-05"))
        self.assertEqual(status.records_found, 0)


class MaterialEventStateTests(unittest.TestCase):
    def status(self, coverage: str, outcome: str, *, age: timedelta = timedelta(0), ticker: str = "2454") -> OfficialEventSyncStatus:
        return OfficialEventSyncStatus(
            ticker=ticker, coverage=coverage, source_name="mops", source_url=MOPS_MATERIAL_LISTING_URL,
            outcome=outcome, checked_at=datetime.now(timezone.utc) - age,
            window_start="2026-07-08", window_end="2026-10-06",
        )

    def test_records_available(self) -> None:
        records = parse_material_event_list_html("2454", LISTING_HTML, max_items=3)
        result = material_event_status(records, [self.status("recent_window", "records_found")])
        self.assertEqual(result.state, "available")
        self.assertEqual(result.message, "已取得 3 筆近期重大訊息")
        self.assertEqual(result.latest_event_date, "2026-09-11")

    def test_checked_window_without_records_is_no_recent_events(self) -> None:
        result = material_event_status([], [self.status("recent_window", "no_records_in_window")])
        self.assertEqual(result.state, "no_recent_events")
        self.assertEqual(result.message, "目前查詢期間內未發現重大訊息")
        self.assertEqual((result.window_start, result.window_end), ("2026-07-08", "2026-10-06"))

    def test_no_recorded_check_is_not_synced(self) -> None:
        result = material_event_status([], [])
        self.assertEqual(result.state, "not_synced")
        self.assertEqual(result.message, "重大訊息尚未完成同步")

    def test_unreadable_source_is_source_unavailable(self) -> None:
        result = material_event_status([], [self.status("recent_window", "source_unavailable")])
        self.assertEqual(result.state, "source_unavailable")
        self.assertEqual(result.message, "官方來源目前無法取得，請稍後再試")
        current_only = material_event_status([], [self.status("current_day", "source_unavailable")])
        self.assertEqual(current_only.state, "source_unavailable")

    def test_current_day_only_check_never_claims_no_events(self) -> None:
        result = material_event_status([], [self.status("current_day", "no_current_day_records")])
        self.assertEqual(result.state, "needs_refresh")
        self.assertNotIn("未發現", result.message)
        self.assertTrue(any("只列出當日公告" in item for item in result.limitations))

    def test_stale_no_events_answer_needs_refresh(self) -> None:
        result = material_event_status([], [self.status("recent_window", "no_records_in_window", age=timedelta(days=8))])
        self.assertEqual(result.state, "needs_refresh")


class CardContractTests(unittest.TestCase):
    def test_card_reports_persisted_2454_records_with_provenance(self) -> None:
        with _Repository() as repository:
            records, status = check_recent_mops_material_events("2454", today=TODAY, fetch_html=listing_fetcher())
            repository.save_official_events(ticker="2454", investor_conferences=[], material_events=records,
                                            refreshed_at=datetime.now(timezone.utc))
            record_material_event_sync(repository, [status])
            card = card_for(repository, "2454")

        self.assertEqual(card["schema_version"], "frontend-official-evidence-card-1.3.0")
        self.assertEqual(card["material_event_status"]["state"], "available")
        self.assertEqual(card["material_event_status"]["record_count"], 4)
        event = card["material_events"][0]
        self.assertEqual(event["ticker"], "2454")
        self.assertEqual((event["event_date"], event["event_time"]), ("2026-09-11", "18:04:11"))
        self.assertTrue(event["title"].startswith("代子公司MediaTek Singapore"))
        self.assertEqual(event["category"], "financing_or_debt")
        self.assertTrue(event["raw_text"])
        self.assertTrue(event["retrieved_at"])
        self.assertTrue(event["limitations"])
        identity = event["source_identity"]
        self.assertEqual(identity["source_type"], "mops_listing")
        self.assertEqual(identity["event_date"], "2026-09-11")
        self.assertTrue(identity["provenance"]["url"].startswith(MOPS_MATERIAL_LISTING_URL))

    def test_companies_are_isolated(self) -> None:
        with _Repository() as repository:
            records, status = check_recent_mops_material_events("2454", today=TODAY, fetch_html=listing_fetcher())
            repository.save_official_events(ticker="2454", investor_conferences=[], material_events=records,
                                            refreshed_at=datetime.now(timezone.utc))
            record_material_event_sync(repository, [status])
            twse_records, twse_status = current_day_material_event_check("2303", [TWSE_ROW_2303])
            repository.save_official_events(ticker="2303", investor_conferences=[], material_events=twse_records,
                                            refreshed_at=datetime.now(timezone.utc))
            record_material_event_sync(repository, [twse_status])
            card_2454 = card_for(repository, "2454")
            card_2303 = card_for(repository, "2303")
            card_2330 = card_for(repository, "2330")

        self.assertEqual({event["ticker"] for event in card_2454["material_events"]}, {"2454"})
        self.assertTrue(all(event["source_name"] == "mops" for event in card_2454["material_events"]))
        self.assertEqual({event["ticker"] for event in card_2303["material_events"]}, {"2303"})
        self.assertEqual(card_2303["material_event_status"]["record_count"], 1)
        self.assertTrue(all(source["source_name"] == "twse_openapi" for source in card_2303["material_event_status"]["checked_sources"]))
        self.assertEqual(card_2330["material_events"], [])
        self.assertEqual(card_2330["material_event_status"]["state"], "not_synced")

    def test_empty_list_without_any_check_is_not_reported_as_no_events(self) -> None:
        with _Repository() as repository:
            card = card_for(repository, "2454")
        self.assertEqual(card["material_events"], [])
        self.assertEqual(card["material_event_status"]["state"], "not_synced")
        self.assertNotIn("未發現", card["material_event_status"]["message"])

    def test_repository_without_sync_support_degrades_to_not_synced(self) -> None:
        class LegacyRepository:
            def get_latest_snapshot(self, _ticker):
                return None

            def list_investor_conferences(self, _ticker, limit=20):
                return []

            def list_material_events(self, _ticker, limit=50):
                return []

        record_material_event_sync(LegacyRepository(), [self.sample_status()])
        self.assertEqual(read_material_event_sync(LegacyRepository(), "2454"), [])
        card = card_for(LegacyRepository(), "2454")
        self.assertEqual(card["material_event_status"]["state"], "not_synced")
        self.assertEqual(card_for(None, "2454")["material_event_status"]["state"], "not_synced")

    def test_sqlite_keeps_the_latest_check_per_coverage(self) -> None:
        with _Repository() as repository:
            older = self.sample_status(outcome="no_records_in_window", checked_at=datetime(2026, 10, 1, tzinfo=timezone.utc))
            newer = self.sample_status(outcome="records_found", checked_at=datetime(2026, 10, 6, tzinfo=timezone.utc))
            current = self.sample_status(coverage="current_day", outcome="no_current_day_records")
            for status in (older, newer, current):
                repository.save_official_event_sync_status(status)
            stored = {item.coverage: item for item in repository.list_official_event_sync_status("2454")}
        self.assertEqual(set(stored), {"recent_window", "current_day"})
        self.assertEqual(stored["recent_window"].outcome, "records_found")

    @staticmethod
    def sample_status(*, coverage: str = "recent_window", outcome: str = "records_found",
                      checked_at: datetime | None = None) -> OfficialEventSyncStatus:
        return OfficialEventSyncStatus(
            ticker="2454", coverage=coverage, source_name="mops", source_url=MOPS_MATERIAL_LISTING_URL,
            outcome=outcome, checked_at=checked_at or datetime.now(timezone.utc),
        )


class _FirestoreDocument:
    def __init__(self, store: dict, key: str) -> None:
        self.store, self.key = store, key

    def set(self, payload) -> None:
        self.store[self.key] = payload

    def get(self):
        store, key = self.store, self.key

        class Snapshot:
            exists = key in store

            def to_dict(self):
                return store.get(key)

        return Snapshot()


class _FirestoreClient:
    def __init__(self) -> None:
        self.store: dict = {}

    def collection(self, name: str):
        client = self

        class Collection:
            def document(self, document_id: str):
                return _FirestoreDocument(client.store, f"{name}/{document_id}")

        return Collection()


class FirestoreSyncStatusTests(unittest.TestCase):
    def test_sync_status_round_trips_one_document_per_coverage(self) -> None:
        repository = FirestoreAnalysisRepository.__new__(FirestoreAnalysisRepository)
        repository.client = _FirestoreClient()
        status = CardContractTests.sample_status(outcome="no_records_in_window")
        repository.save_official_event_sync_status(status)
        self.assertIn("official_event_sync_status/material_event:2454:recent_window", repository.client.store)
        loaded = repository.list_official_event_sync_status("2454")
        self.assertEqual([item.outcome for item in loaded], ["no_records_in_window"])
        self.assertEqual(repository.list_official_event_sync_status("2408"), [])


class IngestionTests(unittest.TestCase):
    def test_company_refresh_falls_back_to_bounded_mops_history(self) -> None:
        with _Repository() as repository, \
                patch("app.services.official_event_ingestion.fetch_twse_material_event_rows", return_value=TWSE_ROWS_WITHOUT_2454), \
                patch("app.services.official_event_sources.fetch_material_event_listing_html", side_effect=listing_fetcher()), \
                patch("app.services.official_event_sources.taipei_today", return_value=TODAY):
            result = OfficialEventIngestionService(repository=repository).refresh_company("2454", include_conferences=False)
            stored = repository.list_material_events("2454")
            statuses = {item.coverage: item for item in repository.list_official_event_sync_status("2454")}
            card = card_for(repository, "2454")

        self.assertEqual(result.material_event_count, 4)
        self.assertEqual(result.live_source_outcome["material_event"], "PASS")
        self.assertEqual(len(stored), 4)
        self.assertEqual(statuses["current_day"].outcome, "no_current_day_records")
        self.assertEqual(statuses["recent_window"].outcome, "records_found")
        self.assertEqual(statuses["recent_window"].records_persisted, 4)
        self.assertEqual(card["material_event_status"]["state"], "available")

    def test_company_refresh_with_unreachable_mops_reports_source_unavailable(self) -> None:
        def raises(_ticker: str, _year: int) -> str:
            raise TimeoutError("The read operation timed out")

        with _Repository() as repository, \
                patch("app.services.official_event_ingestion.fetch_twse_material_event_rows", return_value=TWSE_ROWS_WITHOUT_2454), \
                patch("app.services.official_event_sources.fetch_material_event_listing_html", side_effect=raises):
            result = OfficialEventIngestionService(repository=repository).refresh_company("2454", include_conferences=False)
            card = card_for(repository, "2454")

        self.assertEqual(result.live_source_outcome["material_event"], "NETWORK_ERROR")
        self.assertEqual(card["material_event_status"]["state"], "source_unavailable")

    def test_openapi_only_batch_records_a_current_day_check(self) -> None:
        with _Repository() as repository:
            batch = OfficialEventBatchIngestionService(
                repository=repository, company_repository=object(), company_service=object(),
                material_rows_fetcher=lambda: TWSE_ROWS_WITHOUT_2454,
            )
            batch._material_from_shared_rows("2454", TWSE_ROWS_WITHOUT_2454, material_event_year=None)
            card = card_for(repository, "2454")

        self.assertEqual(card["material_event_status"]["state"], "needs_refresh")
        self.assertEqual(card["material_event_status"]["checked_sources"][0]["outcome"], "no_current_day_records")

    def test_openapi_only_batch_feed_failure_is_recorded_and_still_raised(self) -> None:
        class Companies:
            def get(self, _ticker):
                return None

        def failing_feed():
            raise RuntimeError("TWSE OpenAPI unavailable")

        with _Repository() as repository, patch.dict(os.environ, {"OFFICIAL_EVENT_BATCH_MAX_ATTEMPTS": "1"}):
            batch = OfficialEventBatchIngestionService(
                repository=repository, company_repository=Companies(), company_service=object(),
                material_rows_fetcher=failing_feed,
            )
            with self.assertRaises(RuntimeError):
                asyncio.run(batch.refresh_all(
                    include_conferences=False, include_material_events=True, material_openapi_only=True,
                    trigger="manual", batch_scope="explicit", tickers=["2454"],
                ))
            card = card_for(repository, "2454")

        self.assertEqual(card["material_event_status"]["state"], "source_unavailable")


if __name__ == "__main__":
    unittest.main()
