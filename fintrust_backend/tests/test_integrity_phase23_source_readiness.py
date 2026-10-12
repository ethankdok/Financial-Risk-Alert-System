"""Synthetic source-readiness API coverage, without protected or cloud datasets."""
from __future__ import annotations

import sys
from pathlib import Path
import unittest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from flask import Flask
from b2b_routes import create_b2b_blueprint
from app.main import app
from app.routers.integrity import get_integrity_workbench
from app.services.integrity.source_readiness import summarize_source_readiness
from tests.test_integrity_phase23_nfm_bridge import financial_index, nonfinancial


class StubFacts:
    def __init__(self, rows):
        self.rows = rows

    def collect(self, _ticker):
        return self.rows


class StubLiterature:
    def frozen_observation_count(self, _ticker):
        return (None, "no_frozen_store")


class StubWorkbench:
    def __init__(self, rows):
        self.facts = StubFacts(rows)
        self.literature = StubLiterature()
        self.nfm_records = []

    def resolve(self, ticker):
        if ticker != "2454":
            from app.services.integrity.service import UnsupportedTicker
            raise UnsupportedTicker(ticker)
        return object()


class FakeFlaskClient:
    def b2b_source_readiness(self, ticker):
        return {"ticker": ticker, "f4_data_ready": False}


class SourceReadinessTests(unittest.TestCase):
    def setUp(self):
        self.rows = {"index": financial_index(), "quality": [], "excluded": []}

    def test_financial_url_only_is_not_complete_evidence(self):
        index = financial_index()
        index[("revenue", 2024)].pop("source_sha256")
        index[("revenue", 2024)]["source_document_verified"] = False
        result = summarize_source_readiness(
            {"index": index, "quality": [], "excluded": []}, ticker="2454", nfm_records=[],
        )
        self.assertFalse(result["f4_data_ready"])
        self.assertIn("source_artifact_sha256_missing", result["blockers"])
        self.assertIn("original_document_bytes_not_verified", result["blockers"])

    def test_two_years_of_nfm_are_not_enough_if_units_conflict(self):
        data = nonfinancial()
        data[1]["unit"] = "FTE"
        result = summarize_source_readiness(self.rows, ticker="2454", nfm_records=data)
        self.assertFalse(result["f4_data_ready"])
        self.assertEqual(result["f4_verification_status"], "not_comparable")

    def test_valid_synthetic_four_row_dataset_is_consistent(self):
        result = summarize_source_readiness(self.rows, ticker="2454", nfm_records=nonfinancial())
        self.assertTrue(result["f4_data_ready"])
        self.assertEqual(result["blockers"], [])
        self.assertEqual(result["f4_verification_status"], "descriptive_gap")

    def test_missing_latest_facts_show_explicit_blocker(self):
        result = summarize_source_readiness({"index": {}, "quality": [], "excluded": []}, ticker="2454")
        self.assertFalse(result["f4_data_ready"])
        self.assertEqual(result["latest_fiscal_year"], None)
        self.assertIn("no_annual_financial_evidence", result["blockers"])


class ReadinessApiTests(unittest.TestCase):
    def setUp(self):
        app.dependency_overrides[get_integrity_workbench] = lambda: StubWorkbench(
            {"index": financial_index(), "quality": [], "excluded": []}
        )
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()

    def test_source_readiness_separate_from_phase1_api(self):
        response = self.client.get("/api/v1/b2b/companies/2454/source-readiness")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["ticker"], "2454")
        self.assertFalse(response.json()["f4_data_ready"])
        self.assertEqual(response.json()["frozen_literature_store_reason"], "no_frozen_store")

    def test_unknown_and_malformed_ticker(self):
        self.assertEqual(self.client.get("/api/v1/b2b/companies/9999/source-readiness").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/b2b/companies/24O4/source-readiness").status_code, 422)

    def test_flask_proxies_only_fixed_ticker(self):
        flask = Flask(__name__)
        flask.register_blueprint(create_b2b_blueprint(FakeFlaskClient()))
        with flask.test_client() as client:
            response = client.get("/api/b2b/companies/2454/source-readiness")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["data"]["ticker"], "2454")
            self.assertEqual(client.get("/api/b2b/companies/24O4/source-readiness").status_code, 400)


if __name__ == "__main__":
    unittest.main()
