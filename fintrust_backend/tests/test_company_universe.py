from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx

from app.services.company_master_repository import SqliteCompanyMasterRepository
from app.services.twse_company_universe import TwseCompanyUniverseService


class CompanyUniverseTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_filters_semiconductor_rows_and_is_idempotent(self) -> None:
        rows = [
            {
                "出表日期": "1150919",
                "公司代號": "2330",
                "公司名稱": "台灣積體電路製造股份有限公司",
                "公司簡稱": "台積電",
                "英文簡稱": "TSMC",
                "產業別": "24",
                "上市日期": "19940905",
            },
            {
                "出表日期": "1150919",
                "公司代號": "9999",
                "公司名稱": "測試股份有限公司",
                "公司簡稱": "測試半導體",
                "英文簡稱": "TEST",
                "產業別": "24",
                "上市日期": "20240102",
            },
            {
                "出表日期": "1150919",
                "公司代號": "1101",
                "公司名稱": "臺灣水泥股份有限公司",
                "公司簡稱": "台泥",
                "產業別": "01",
                "上市日期": "19620209",
            },
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=rows)

        with tempfile.TemporaryDirectory() as directory:
            repository = SqliteCompanyMasterRepository(str(Path(directory) / "pipeline.sqlite3"))
            service = TwseCompanyUniverseService(
                repository=repository,
                transport=httpx.MockTransport(handler),
            )
            first = await service.sync()
            second = await service.sync()

            self.assertEqual(first.fetched_rows, 3)
            self.assertEqual(first.semiconductor_rows, 2)
            self.assertEqual(second.persisted_rows, 2)
            self.assertEqual(len(repository.list_all()), 2)

            tsmc = repository.get("2330")
            self.assertIsNotNone(tsmc)
            assert tsmc is not None
            self.assertEqual(tsmc.subindustry, "晶圓代工")
            self.assertEqual(tsmc.subindustry_confidence, "reviewed")
            self.assertEqual(tsmc.source_report_date.isoformat(), "2026-09-19")
            self.assertIn("TSMC", tsmc.aliases)

            unknown = repository.get("9999")
            self.assertIsNotNone(unknown)
            assert unknown is not None
            self.assertEqual(unknown.subindustry, "待分類")
            self.assertEqual(unknown.subindustry_confidence, "unclassified")


if __name__ == "__main__":
    unittest.main()
