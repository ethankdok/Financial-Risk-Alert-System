"""B1 hotfix: a degraded MOPS refresh must not replace the last good latest snapshot.

MOPS answers throttling with HTTP 200 and a non-iXBRL body. Only its exact
"file does not exist" page is a legitimate no-filing; every other non-iXBRL body
fails closed as source_invalid_content.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.historical_analysis_models import HistoricalPeriodRecord
from app.services.analysis_repository import SqliteAnalysisRepository
from app.services.demo_fixture_sources import DemoMopsInlineXbrlClient, DemoTwseOpenApiClient
from app.services.financial_analysis_service import FinancialAnalysisService
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService
from app.services.ingestion_pipeline import FinancialIngestionPipeline, snapshot_usable_years
from app.services.ingestion_run_repository import SqliteIngestionRunRepository
from app.services.mops_inline_xbrl import (
    FILING_NOT_FOUND,
    SOURCE_INVALID_CONTENT,
    SOURCE_UNAVAILABLE,
    ClassifyingMOPSXBRLClient,
    XBRLParserError,
    classify_mops_non_ixbrl_body,
)
from app.services.robust_mops_inline_xbrl import RobustMopsInlineXbrlClient

# Byte-for-byte the page MOPS FileDownLoad served (HTTP 200, Big5) for 3135 FY2024.
MOPS_NOT_FOUND_BODY = (
    "<html>\r\n<body>\r\n<center>\r\n<br><h4 align='center'><font color='red'>下載檔名或路徑不正確，請檢查!!</font></h4>\r\n"
    "<form action='/server-java/FileDownLoad'>\r\n<center><input type='button' value=' 回上頁 ' "
    "onClick={window.history.back()}></center>\r\n</form>\r\n</center>\r\n</body>\r\n</html>\r\n"
).encode("cp950")
THROTTLE_BODY = "<html><body><h3>查詢過於頻繁，請稍後再試</h3></body></html>".encode("cp950")
IXBRL_BODY = b'<html><body><ix:nonFraction name="x">1</ix:nonFraction></body></html>'


class FailingParser:
    def parse(self, *args: object) -> object:
        raise XBRLParserError("unparseable filing")


class PatchedMops:
    """Robust MOPS client over the real vendored download code; MOPS answers every request with `body`."""

    def __init__(self, body: bytes = b"", status: int = 200, parser: object | None = None) -> None:
        self.requests: list[str] = []
        self.body, self.status = body, status
        self.client = RobustMopsInlineXbrlClient(
            xbrl_client=ClassifyingMOPSXBRLClient(max_retries=1),
            parser=parser or FailingParser(),
            require_arelle=False,
            cache_enabled=False,
        )

    def _async_client(self, *args: object, **kwargs: object) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url))
            return httpx.Response(self.status, content=self.body)

        kwargs["transport"] = httpx.MockTransport(handler)
        return REAL_ASYNC_CLIENT(*args, **kwargs)

    async def fetch_history(self, profile, *, years=5, end_roc_year=None):  # type: ignore[no-untyped-def]
        with patch("twmops.clients.xbrl_client.httpx.AsyncClient", side_effect=self._async_client):
            return await self.client.fetch_history(profile, years=years, end_roc_year=end_roc_year)


REAL_ASYNC_CLIENT = httpx.AsyncClient


class NoAI:
    def supports(self, subindustry: str) -> bool:
        return False


class NoCompanyMaster:
    backend_name = "fake"

    def get(self, ticker: str) -> None:
        return None


class ClassificationTests(unittest.TestCase):
    def test_exact_mops_not_found_page_is_filing_not_found(self) -> None:
        self.assertEqual(classify_mops_non_ixbrl_body(MOPS_NOT_FOUND_BODY), FILING_NOT_FOUND)

    def test_whitespace_and_encoding_normalization_only(self) -> None:
        compact = MOPS_NOT_FOUND_BODY.decode("cp950").replace("\r\n", "")
        self.assertEqual(classify_mops_non_ixbrl_body(compact.encode("cp950")), FILING_NOT_FOUND)
        self.assertEqual(classify_mops_non_ixbrl_body(compact.encode("utf-8")), FILING_NOT_FOUND)

    def test_every_other_non_ixbrl_body_fails_closed(self) -> None:
        text = MOPS_NOT_FOUND_BODY.decode("cp950")
        for body in (
            THROTTLE_BODY,
            b"",
            b"<html></html>",
            (text + "<p>系統忙碌</p>").encode("cp950"),
            text.replace("下載檔名或路徑不正確", "下載檔名或路徑不存在").encode("cp950"),
            "下載檔名或路徑不正確，請檢查!!".encode("cp950"),
            b"\xff\xfe\x00garbage",
        ):
            with self.subTest(body=body[:40]):
                self.assertEqual(classify_mops_non_ixbrl_body(body), SOURCE_INVALID_CONTENT)

    def test_ixbrl_and_zip_bodies_still_pass_through(self) -> None:
        client = ClassifyingMOPSXBRLClient()
        self.assertTrue(client.is_ixbrl(IXBRL_BODY))
        self.assertFalse(client.is_ixbrl(b"PK\x03\x04zip"))


class VendoredDownloadPathTests(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, mops: PatchedMops) -> list[HistoricalPeriodRecord]:
        from app.services.company_registry import get_company

        return await mops.fetch_history(get_company("2454"), years=5, end_roc_year=114)

    async def test_throttle_body_is_source_invalid_content_with_one_request_per_year(self) -> None:
        mops = PatchedMops(THROTTLE_BODY)
        periods = await self.fetch(mops)
        self.assertEqual({period.status for period in periods}, {"error"})
        self.assertEqual({period.source_diagnostic for period in periods}, {SOURCE_INVALID_CONTENT})
        self.assertEqual(len(mops.requests), len(periods))  # the fetched body is reused, never refetched

    async def test_not_found_page_is_filing_not_found(self) -> None:
        mops = PatchedMops(MOPS_NOT_FOUND_BODY)
        periods = await self.fetch(mops)
        self.assertEqual({period.source_diagnostic for period in periods}, {FILING_NOT_FOUND})
        self.assertEqual(len(mops.requests), len(periods))

    async def test_http_error_is_source_unavailable(self) -> None:
        periods = await self.fetch(PatchedMops(b"busy", status=503))
        self.assertEqual({period.source_diagnostic for period in periods}, {SOURCE_UNAVAILABLE})

    async def test_parser_failure_is_not_a_source_signal(self) -> None:
        periods = await self.fetch(PatchedMops(IXBRL_BODY))
        self.assertEqual({period.status for period in periods}, {"error"})
        self.assertEqual({period.source_diagnostic for period in periods}, {None})


class PreserveLastGoodSnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self.tempdir.name)
        self.db_path = root / "pipeline.sqlite3"
        self.repository = SqliteAnalysisRepository(str(self.db_path))
        self.runs = SqliteIngestionRunRepository(str(root / "runs.sqlite3"))
        self.pipeline = FinancialIngestionPipeline(
            repository=self.repository,
            latest_service=FinancialAnalysisService(twse_client=DemoTwseOpenApiClient()),
            historical_service=self.history(DemoMopsInlineXbrlClient()),
            ai_service=NoAI(),
            ingestion_run_repository=self.runs,
            company_repository=NoCompanyMaster(),
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    @staticmethod
    def history(mops: object) -> HistoricalFinancialAnalysisService:
        return HistoricalFinancialAnalysisService(mops_client=mops)

    async def refresh(self, ticker: str, mops: object):  # type: ignore[no-untyped-def]
        self.pipeline.historical_service = self.history(mops)
        return await self.pipeline.refresh_company(ticker, years=5, end_year=2025, trigger="scheduler")

    async def good(self, ticker: str = "2454"):  # type: ignore[no-untyped-def]
        result = await self.refresh(ticker, DemoMopsInlineXbrlClient())
        self.assertIsNone(result.error)
        self.assertEqual(snapshot_usable_years(self.repository.get_latest_snapshot(ticker)), 5)
        return result

    def latest_run_id(self, ticker: str) -> str | None:
        snapshot = self.repository.get_latest_snapshot(ticker)
        return snapshot.analysis_run_id if snapshot else None

    def query(self, sql: str, *args: object) -> list[sqlite3.Row]:
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(sql, args).fetchall()

    async def test_a_degraded_refresh_keeps_previous_good_snapshot_and_records_the_attempt(self) -> None:
        good = await self.good()
        filings_before = {row["period"]: row["status"] for row in self.query("SELECT period, status FROM financial_filings WHERE ticker = '2454'")}

        degraded = await self.refresh("2454", PatchedMops(THROTTLE_BODY))

        self.assertEqual(self.latest_run_id("2454"), good.run_id)
        self.assertEqual(snapshot_usable_years(self.repository.get_latest_snapshot("2454")), 5)
        self.assertEqual(degraded.status, "partial")
        self.assertEqual(degraded.history_available_years, 0)
        self.assertTrue(degraded.error.startswith("source_degraded:"))
        self.assertIn(good.run_id, degraded.error)
        run_row = self.query("SELECT status, error_message FROM analysis_runs WHERE run_id = ?", degraded.run_id)[0]
        self.assertEqual(run_row["status"], "partial")
        self.assertTrue(run_row["error_message"].startswith("source_degraded:"))
        self.assertEqual(len(self.query("SELECT run_id FROM analysis_snapshots WHERE run_id = ?", degraded.run_id)), 1)
        ingestion = self.runs.get(degraded.run_id)
        self.assertEqual(ingestion.status, "partial")
        self.assertTrue(ingestion.error_message.startswith("source_degraded:"))
        filings_after = {row["period"]: row["status"] for row in self.query("SELECT period, status FROM financial_filings WHERE ticker = '2454'")}
        self.assertEqual(filings_after, filings_before)  # prior good filing evidence is not rewritten

    async def test_b_valid_refresh_still_advances_latest(self) -> None:
        await self.good()
        second = await self.good()
        self.assertEqual(self.latest_run_id("2454"), second.run_id)

    async def test_c_first_ever_genuine_no_filing_keeps_existing_no_data_behavior(self) -> None:
        result = await self.refresh("2454", PatchedMops(MOPS_NOT_FOUND_BODY))
        snapshot = self.repository.get_latest_snapshot("2454")
        self.assertEqual(snapshot.analysis_run_id, result.run_id)
        self.assertEqual(snapshot_usable_years(snapshot), 0)
        self.assertIsNone(result.error)
        self.assertEqual(self.query("SELECT status FROM analysis_runs WHERE run_id = ?", result.run_id)[0]["status"], "completed")

    async def test_c_first_ever_degraded_source_is_saved_as_observable_degraded_state(self) -> None:
        result = await self.refresh("2454", PatchedMops(THROTTLE_BODY))
        snapshot = self.repository.get_latest_snapshot("2454")
        self.assertEqual(snapshot.analysis_run_id, result.run_id)  # nothing fabricated or borrowed
        self.assertEqual(snapshot.ticker, "2454")
        self.assertEqual(snapshot_usable_years(snapshot), 0)
        self.assertIn("尚無先前有效 snapshot", result.error)
        self.assertEqual(self.query("SELECT status FROM analysis_runs WHERE run_id = ?", result.run_id)[0]["status"], "partial")

    async def test_d_zero_years_without_source_error_is_not_treated_as_throttling(self) -> None:
        for mops in (PatchedMops(MOPS_NOT_FOUND_BODY), PatchedMops(IXBRL_BODY)):  # not-found page; parser failure
            with self.subTest(body=mops.body[:20]):
                await self.good()
                result = await self.refresh("2454", mops)
                self.assertIsNone(result.error)
                self.assertEqual(self.latest_run_id("2454"), result.run_id)
                self.assertEqual(snapshot_usable_years(self.repository.get_latest_snapshot("2454")), 0)

    async def test_e_repeated_failed_retries_keep_previous_good_latest(self) -> None:
        good = await self.good()
        degraded_ids = []
        for body, status in ((THROTTLE_BODY, 200), (b"busy", 503), (THROTTLE_BODY, 200)):
            result = await self.refresh("2454", PatchedMops(body, status=status))
            self.assertEqual(result.status, "partial")
            degraded_ids.append(result.run_id)
            self.assertEqual(self.latest_run_id("2454"), good.run_id)
        recorded = {row["run_id"] for row in self.query("SELECT run_id FROM analysis_runs WHERE ticker = '2454'")}
        self.assertTrue(set(degraded_ids) | {good.run_id} <= recorded)

    async def test_f_failure_for_one_company_cannot_affect_another(self) -> None:
        good = {ticker: (await self.good(ticker)).run_id for ticker in ("2454", "2303", "2330")}
        await self.refresh("2454", PatchedMops(THROTTLE_BODY))
        for ticker, run_id in good.items():
            self.assertEqual(self.latest_run_id(ticker), run_id)
            self.assertEqual(self.repository.get_latest_snapshot(ticker).ticker, ticker)

    async def test_g_api_contract_is_unchanged(self) -> None:
        good = await self.good()
        await self.refresh("2454", PatchedMops(THROTTLE_BODY))
        period = HistoricalPeriodRecord(
            ticker="2454", company_name="聯發科", subindustry="IC 設計", fiscal_year=2024, roc_year=113,
            period="2024FY", source_url="https://mopsov.twse.com.tw/", status="error",
            source_diagnostic=SOURCE_INVALID_CONTENT,
        )
        self.assertNotIn("source_diagnostic", period.model_dump())
        self.assertNotIn("source_diagnostic", period.model_dump_json())

        from fastapi.testclient import TestClient

        from app.dependencies import get_analysis_repository
        from app.main import app

        app.dependency_overrides[get_analysis_repository] = lambda: self.repository
        try:
            with TestClient(app) as client:
                latest = client.get("/api/v1/financial/companies/2454/analysis/latest")
                runs = client.get("/api/v1/financial/companies/2454/analysis-runs?limit=5")
        finally:
            app.dependency_overrides.pop(get_analysis_repository, None)
        self.assertEqual(latest.status_code, 200)
        body = latest.json()
        self.assertEqual(body["analysis_run_id"], good.run_id)
        self.assertEqual(body["schema_version"], "frontend-financial-snapshot-1.1.0")
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(set(runs.json()[0]), {
            "analysis_type", "completed_at", "error_message", "overall_severity", "rule_version",
            "run_id", "started_at", "status", "summary", "ticker", "trigger",
        })
        self.assertEqual({run["status"] for run in runs.json()}, {"completed", "partial"})


if __name__ == "__main__":
    unittest.main()
