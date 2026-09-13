from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient


class ApiContractTests(unittest.TestCase):
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

    def test_empty_persisted_endpoints_do_not_500(self) -> None:
        metrics = self.client.get("/api/v1/financial/companies/2330/metrics?limit=10")
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json()["metrics"], [])

        runs = self.client.get("/api/v1/financial/companies/2330/analysis-runs?limit=5")
        self.assertEqual(runs.status_code, 200)
        self.assertEqual(runs.json(), [])

    def test_claim_extract_contract(self) -> None:
        response = self.client.post(
            "/api/v1/financial/claims/extract",
            json={"text": "台積電 2025 年營收成長 10%", "ticker": "2330", "period": "2025FY"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["claim"]["ticker"], "2330")
        self.assertIn("verdict", payload)

    def test_claim_verify_returns_structured_insufficient_evidence(self) -> None:
        response = self.client.post(
            "/api/v1/financial/claims/verify",
            json={"text": "台積電 2025 年營收成長 10%", "ticker": "2330", "period": "2025FY"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["verdict"], "insufficient_evidence")


if __name__ == "__main__":
    unittest.main()
