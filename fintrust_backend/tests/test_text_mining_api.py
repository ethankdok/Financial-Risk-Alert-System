from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord
from app.services.analysis_repository import SqliteAnalysisRepository
from app.services.official_evidence_cards import OfficialEvidenceCardBuilder


class TextMiningApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tempdir = tempfile.TemporaryDirectory()
        root = Path(cls.tempdir.name)
        os.environ["DATASTORE_BACKEND"] = "sqlite"
        os.environ["FINANCIAL_DATABASE_PATH"] = str(root / "pipeline.sqlite3")
        os.environ["FINANCIAL_FACT_DATABASE_PATH"] = str(root / "facts.sqlite3")
        os.environ["APP_ENV"] = "development"
        from app.dependencies import get_analysis_repository, get_fact_repository

        get_analysis_repository.cache_clear()
        get_fact_repository.cache_clear()
        from app.main import app

        cls.client = TestClient(app, raise_server_exceptions=False)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tempdir.cleanup()

    def test_text_mining_analyze_endpoint_is_read_only_and_structured(self) -> None:
        response = self.client.post(
            "/api/v1/financial/text-mining/analyze",
            json={
                "documents": [
                    {
                        "ticker": "2454",
                        "company_name": "聯發科",
                        "source_type": "synthetic_fixture",
                        "source_name": "unit_test",
                        "source_url": "https://example.test/source",
                        "period": "2026Q2",
                        "text": "客戶庫存逐步恢復正常，因此公司預期下半年營收成長。",
                    }
                ]
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["schema_version"], "text-intelligence-v2.0")
        self.assertEqual(payload["documents"][0]["ticker"], "2454")
        self.assertGreater(payload["documents"][0]["relevant_sentence_count"], 0)

    def test_narrative_shift_endpoint_reports_separate_metrics(self) -> None:
        response = self.client.post(
            "/api/v1/financial/text-mining/narrative-shift",
            json={
                "document_1": {
                    "ticker": "2330",
                    "company_name": "台積電",
                    "source_type": "synthetic_fixture",
                    "source_name": "unit_test",
                    "source_url": "https://example.test/1",
                    "period": "2026Q1",
                    "text": "公司說明先進封裝需求穩定，資本支出維持紀律。",
                },
                "document_2": {
                    "ticker": "2330",
                    "company_name": "台積電",
                    "source_type": "synthetic_fixture",
                    "source_name": "unit_test",
                    "source_url": "https://example.test/2",
                    "period": "2026Q2",
                    "text": "公司說明矽光子平台開始導入，CoWoS 產能與 AI 加速器需求提升。",
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        metrics = response.json()["metrics"]
        self.assertIn("raw_text_word_jsd", metrics)
        self.assertIn("relevant_text_word_jsd", metrics)
        self.assertIn("topic_distribution_jsd", metrics)

    def test_company_text_evidence_endpoint_reads_persisted_official_events(self) -> None:
        from app.dependencies import get_analysis_repository

        repository = get_analysis_repository()
        refreshed_at = datetime.now(timezone.utc)
        repository.save_official_events(
            ticker="2454",
            investor_conferences=[
                InvestorConferenceRecord(
                    event_id="api-conf",
                    ticker="2454",
                    company_name="聯發科",
                    subindustry="IC 設計",
                    conference_date="2026-07-31",
                    title="MediaTek investor conference",
                    source_name="company_official_ir",
                    source_url="https://example.test/ir",
                    document_text_preview="Management expects product momentum and revenue growth to improve.",
                    document_extract_status="text_extracted",
                )
            ],
            material_events=[],
            refreshed_at=refreshed_at,
        )

        response = self.client.get("/api/v1/financial/text-mining/companies/2454/text-evidence")

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(response.json()["documents"][0]["relevant_sentence_count"], 1)

    def test_official_evidence_card_adds_text_evidence_without_breaking_contract(self) -> None:
        repository = SqliteAnalysisRepository(str(Path(self.tempdir.name) / "card.sqlite3"))
        repository.save_official_events(
            ticker="2454",
            investor_conferences=[],
            material_events=[
                MaterialEventRecord(
                    event_id="card-event",
                    ticker="2454",
                    company_name="聯發科",
                    subindustry="IC 設計",
                    event_date="2026-09-01",
                    title="公告本公司董事會決議資本支出案",
                    source_name="twse_openapi",
                    source_url="https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
                    status="available",
                    raw_text="本公司董事會決議資本支出以支援產品需求成長。",
                )
            ],
            refreshed_at=datetime.now(timezone.utc),
        )

        card = OfficialEvidenceCardBuilder(repository=repository).build("2454")

        self.assertIsInstance(card.text_evidence, list)
        self.assertTrue(card.text_evidence)
        self.assertEqual(card.text_evidence[0]["ticker"], "2454")


if __name__ == "__main__":
    unittest.main()

