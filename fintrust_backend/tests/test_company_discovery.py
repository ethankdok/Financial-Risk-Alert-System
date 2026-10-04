"""Hardening round 1: /companies and company resolution share one source.

Every company the card endpoint resolves (reviewed seeds plus listed TWSE
semiconductor rows of the company master) is listed by /companies in a fresh
process, without depending on what that process resolved earlier.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.models import CompanyMasterRecord
from app.services import company_registry
from app.services.company_master_repository import SqliteCompanyMasterRepository

BACKEND = Path(__file__).resolve().parents[1]


def master(ticker: str, name: str, subindustry: str = "記憶體製造", **overrides) -> CompanyMasterRecord:
    payload = {"ticker": ticker, "name": name, "legal_name": f"{name}股份有限公司", "subindustry": subindustry,
               "source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L", "synced_at": datetime.now(timezone.utc)}
    payload.update(overrides)
    return CompanyMasterRecord(**payload)


MASTER_ROWS = [
    master("2408", "南亞科"),
    master("2330", "台積電(主檔)", "晶圓代工"),            # seed ticker: the reviewed seed profile wins
    master("9998", "已下市半導體", listing_status="delisted"),
    master("9997", "非半導體公司", industry="電子零組件業", industry_code="28"),
]


class _Repository:
    def __init__(self, rows=None, error: Exception | None = None) -> None:
        self.rows, self.error = rows or [], error

    def list_all(self):
        if self.error:
            raise self.error
        return list(self.rows)


class SupportedCompanyListTests(unittest.TestCase):
    def test_lists_seeds_plus_supported_master_rows_only(self) -> None:
        companies = company_registry.list_supported_companies(_Repository(MASTER_ROWS))
        tickers = [company.ticker for company in companies]
        self.assertEqual(tickers, ["2303", "2330", "2408", "2454", "3711"])
        self.assertEqual(next(c for c in companies if c.ticker == "2330").name, "台積電")
        self.assertEqual(next(c for c in companies if c.ticker == "2408").subindustry, "記憶體製造")

    def test_master_failure_still_serves_reviewed_seeds(self) -> None:
        companies = company_registry.list_supported_companies(_Repository(error=RuntimeError("firestore down")))
        self.assertEqual([company.ticker for company in companies], ["2303", "2330", "2454", "3711"])

    def test_supported_predicate_matches_mvp_scope(self) -> None:
        self.assertTrue(company_registry.is_supported_master_record(MASTER_ROWS[0]))
        self.assertFalse(company_registry.is_supported_master_record(MASTER_ROWS[2]))
        self.assertFalse(company_registry.is_supported_master_record(MASTER_ROWS[3]))

    def test_seed_listing_never_includes_runtime_cached_profiles(self) -> None:
        cached = company_registry.profile_from_master(MASTER_ROWS[0])
        company_registry.register_company_profile(cached)
        try:
            self.assertNotIn("2408", [company.ticker for company in company_registry.list_companies()])
        finally:
            company_registry.SEMICONDUCTOR_COMPANIES.pop("2408", None)


FRESH_PROCESS_SCRIPT = r"""
import json
from fastapi.testclient import TestClient
from app.services import company_registry
from app.main import app

report = {"cached_before": sorted(company_registry.SEMICONDUCTOR_COMPANIES)}
client = TestClient(app)
listing = client.get("/api/v1/financial/companies")
report["companies_status"] = listing.status_code
report["companies"] = [company["ticker"] for company in listing.json()["companies"]]
report["cached_after_listing"] = sorted(company_registry.SEMICONDUCTOR_COMPANIES)
for ticker in ("2408", "9998", "9997", "2317"):
    response = client.get(f"/api/v1/financial/companies/{ticker}/official-evidence-card?include_material_events=false")
    report[f"card_{ticker}"] = response.status_code
    if response.status_code == 200:
        report[f"card_{ticker}_company"] = response.json()["company_name"]
print(json.dumps(report, ensure_ascii=False))
"""


class FreshProcessCompanyDiscoveryTests(unittest.TestCase):
    """Runs the real FastAPI app in a new interpreter: no warm registry cache exists."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        database = root / "pipeline.sqlite3"
        SqliteCompanyMasterRepository(str(database)).upsert_many(MASTER_ROWS)
        (root / "archive").mkdir()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("CONFERENCE_", "FINANCIAL_", "DATASTORE_", "GEMINI", "JSD_"))}
        env.update(APP_ENV="development", DATASTORE_BACKEND="sqlite", FINANCIAL_DATABASE_PATH=str(database),
                   FINANCIAL_FACT_DATABASE_PATH=str(root / "facts.sqlite3"), CONFERENCE_PDF_ARCHIVE_BACKEND="file",
                   CONFERENCE_PDF_ARCHIVE_ROOT=str(root / "archive"), PYTHONIOENCODING="utf-8")
        completed = subprocess.run([sys.executable, "-c", FRESH_PROCESS_SCRIPT], cwd=BACKEND, env=env,
                                   capture_output=True, timeout=180)
        if completed.returncode != 0:
            raise AssertionError(completed.stderr.decode("utf-8", "replace")[-2000:])
        cls.report = json.loads(completed.stdout.decode("utf-8").strip().splitlines()[-1])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.folder.cleanup()

    def test_fresh_process_lists_2408_without_warmup(self) -> None:
        self.assertNotIn("2408", self.report["cached_before"])
        self.assertEqual(self.report["companies_status"], 200)
        self.assertEqual(self.report["companies"], ["2303", "2330", "2408", "2454", "3711"])
        # Listing does not depend on, or populate, the resolution cache.
        self.assertNotIn("2408", self.report["cached_after_listing"])

    def test_2408_card_resolves_without_prior_lookup(self) -> None:
        self.assertEqual(self.report["card_2408"], 200)
        self.assertEqual(self.report["card_2408_company"], "南亞科")

    def test_unsupported_tickers_stay_rejected(self) -> None:
        for ticker in ("9998", "9997", "2317"):
            self.assertEqual(self.report[f"card_{ticker}"], 400, ticker)
            self.assertNotIn(ticker, self.report["companies"])


if __name__ == "__main__":
    unittest.main()
