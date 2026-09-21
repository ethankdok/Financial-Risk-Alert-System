from __future__ import annotations

import unittest
import unittest.mock
from datetime import datetime, timezone

from app.official_event_models import OfficialEventsRefreshResult
from app.services.company_registry import get_company
from app.services.official_event_batch_ingestion import OfficialEventBatchIngestionService


class _Master:
    def __init__(self, ticker: str, name: str, subindustry: str) -> None:
        self.ticker = ticker
        self.name = name
        self.subindustry = subindustry
        self.aliases = [ticker, name]


class _CompanyRepository:
    def __init__(self, rows: dict[str, _Master]) -> None:
        self.rows = rows

    def get(self, ticker: str):
        return self.rows.get(ticker)


class _AnalysisRepository:
    def __init__(self) -> None:
        self.saved: list[tuple[str, int, int]] = []

    def save_official_events(
        self,
        *,
        ticker,
        investor_conferences,
        material_events,
        refreshed_at,
    ):
        self.saved.append((ticker, len(investor_conferences), len(material_events)))
        return {
            "investor_conferences": len(investor_conferences),
            "material_events": len(material_events),
        }


class _FakeRefreshService:
    def __init__(self, outcomes: dict[str, dict[str, str]]) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def refresh_company(self, ticker: str, **_kwargs) -> OfficialEventsRefreshResult:
        self.calls.append(ticker)
        source_outcome = self.outcomes.get(ticker, {})
        if source_outcome.get("raise"):
            raise RuntimeError(source_outcome["raise"])
        return OfficialEventsRefreshResult(
            ticker=ticker,
            company_name=ticker,
            subindustry="IC 設計",
            refreshed_at=datetime.now(timezone.utc),
            investor_conference_count=1 if "investor_conference" in source_outcome else 0,
            material_event_count=1 if "material_event" in source_outcome else 0,
            persisted={},
            live_source_outcome=source_outcome,
            source_health=[],
            investor_conferences=[],
            material_events=[],
            limitations=[],
        )


class OfficialEventBatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_batch_isolates_company_failures(self) -> None:
        companies = {
            "2330": _Master("2330", "台積電", "晶圓代工"),
            "2454": _Master("2454", "聯發科", "IC 設計"),
        }
        service = _FakeRefreshService(
            {
                "2330": {"investor_conference": "PASS"},
                "2454": {"raise": "temporary test failure"},
            }
        )
        batch = OfficialEventBatchIngestionService(
            repository=_AnalysisRepository(),
            company_repository=_CompanyRepository(companies),
            company_service=service,
        )

        result = await batch.refresh_all(
            include_conferences=True,
            include_material_events=False,
            trigger="manual",
            batch_scope="explicit",
            tickers=["2330", "2454"],
        )

        self.assertEqual(result.requested_companies, 2)
        self.assertEqual(result.completed_companies, 1)
        self.assertEqual(result.failed_companies, 1)
        self.assertEqual(result.status, "partial")
        self.assertEqual([item.ticker for item in result.results], ["2330", "2454"])

    async def test_no_data_is_a_successful_poll_but_blocked_source_is_partial(self) -> None:
        companies = {
            "2330": _Master("2330", "台積電", "晶圓代工"),
            "2454": _Master("2454", "聯發科", "IC 設計"),
        }
        service = _FakeRefreshService(
            {
                "2330": {"investor_conference": "NO_DATA"},
                "2454": {"investor_conference": "BLOCKED_BY_SOURCE"},
            }
        )
        batch = OfficialEventBatchIngestionService(
            repository=_AnalysisRepository(),
            company_repository=_CompanyRepository(companies),
            company_service=service,
        )

        result = await batch.refresh_all(
            include_conferences=True,
            include_material_events=False,
            trigger="manual",
            batch_scope="explicit",
            tickers=["2330", "2454"],
        )

        by_ticker = {item.ticker: item for item in result.results}
        self.assertEqual(by_ticker["2330"].status, "completed")
        self.assertEqual(by_ticker["2454"].status, "partial")
        self.assertEqual(result.partial_companies, 1)
        self.assertEqual(result.failed_companies, 0)

    async def test_material_openapi_only_fetches_feed_once_and_fans_out(self) -> None:
        rows = [
            {
                "出表日期": "1150901",
                "發言日期": "1150831",
                "發言時間": "150001",
                "公司代號": "2454",
                "公司名稱": "聯發科",
                "主旨 ": "公告本公司營運展望",
                "符合條款": "第12款",
                "事實發生日": "1150901",
                "說明": "說明營收與需求展望。",
            }
        ]
        calls = 0

        def fetch_rows():
            nonlocal calls
            calls += 1
            return rows

        repository = _AnalysisRepository()
        companies = {
            "2330": _Master("2330", "台積電", "晶圓代工"),
            "2454": _Master("2454", "聯發科", "IC 設計"),
        }
        batch = OfficialEventBatchIngestionService(
            repository=repository,
            company_repository=_CompanyRepository(companies),
            company_service=_FakeRefreshService({}),
            material_rows_fetcher=fetch_rows,
        )

        result = await batch.refresh_all(
            include_conferences=False,
            include_material_events=True,
            material_openapi_only=True,
            trigger="manual",
            batch_scope="explicit",
            tickers=["2330", "2454"],
        )

        self.assertEqual(calls, 1)
        self.assertEqual(result.failed_companies, 0)
        self.assertEqual(result.completed_companies, 2)
        self.assertEqual(len(repository.saved), 2)
        by_ticker = {item.ticker: item for item in result.results}
        self.assertEqual(by_ticker["2330"].material_event_count, 0)
        self.assertEqual(by_ticker["2454"].material_event_count, 1)

    async def test_material_openapi_only_rejects_mixed_source_batch(self) -> None:
        batch = OfficialEventBatchIngestionService(
            repository=_AnalysisRepository(),
            company_repository=_CompanyRepository({}),
            company_service=_FakeRefreshService({}),
        )
        with self.assertRaises(ValueError):
            await batch.refresh_all(
                include_conferences=True,
                include_material_events=True,
                material_openapi_only=True,
            )

    def test_get_company_falls_back_to_persisted_master_and_caches_profile(self) -> None:
        master = _Master("9998", "測試公司", "IC 設計")
        repository = _CompanyRepository({"9998": master})
        with unittest.mock.patch(
            "app.services.company_master_repository.build_company_master_repository",
            return_value=repository,
        ):
            company = get_company("9998")

        self.assertIsNotNone(company)
        self.assertEqual(company.ticker, "9998")
        self.assertEqual(get_company("9998").name, "測試公司")


if __name__ == "__main__":
    unittest.main()
