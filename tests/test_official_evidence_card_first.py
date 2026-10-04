"""P2: Flask uses the official evidence card as its canonical source.

A fake FastAPI backend records every request path, so the tests can tell the
canonical one-call path from the legacy multi-call fallback.
"""
from __future__ import annotations

import copy
import importlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse

from flask import Blueprint, Flask

from financial_routes import create_financial_blueprint
from fintrust_client import FinTrustClient
from tests.test_claim_verification_proxy import FakeHttpResponse

BASE = "https://api.example.test"
CARD_PATH = "/api/v1/financial/companies/2454/official-evidence-card"
IR_URL = "https://www.mediatek.com/zh-tw/investor-relations"
IR_DOCUMENT_URL = "https://www.mediatek.com/hubfs/Quarterly%20Earnings%20Release-2026Q2/Transcript.pdf"
MOPS_LISTING = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1?step=1&co_id=2454"
MOPS_FILE = "245420251031M001.pdf"
MOPS_SHA = "23bb35fa060a626dc89b51892a49f250a73806b36aa018f23ae6ce73505258b6"

SNAPSHOT = {"ticker": "2454", "company_name": "聯發科", "subindustry": "IC 設計", "overall_severity": "attention",
            "summary": "persisted snapshot", "key_metrics": [{"code": "revenue"}], "rule_cards": [], "ai_analysis": None}


def ir_identity(period: str, date: str) -> dict:
    return {"source_type": "company_ir", "source_name": "company_official_ir", "period": period,
            "period_basis": "fiscal_year_quarter", "document_type": None, "filename": None, "event_date": date,
            "availability": "available", "provenance": {"url": IR_DOCUMENT_URL, "sha256": None, "retrieved_at": "2026-09-26T00:00:00Z"}}


def mops_digest() -> dict:
    return {
        "digest_version": "conference-document-digest-v1", "summary_mode": "deterministic", "ticker": "2454",
        "document_title": "聯發科技 2025年第三季法人說明會", "period": "2025Q3", "document_type": "earnings_presentation",
        "language": "zh-Hant", "conference_date": "2025-10-31",
        "overview": [{"text": "聯發科（2454）於公開資訊觀測站（MOPS）揭露之2025Q3 法說會簡報，日期 2025-10-31，共 20 頁。", "evidence_refs": []}],
        "sections": [{"section_type": "financial_performance", "title_zh": "財務表現", "title_en": "Financial Performance",
                      "bullets": [{"id": "financial_performance-1", "text": "營業收入：2025年 第三季 142,097"}]}],
        "key_quantitative_disclosures": [{"label": "營業收入", "value_text": "142,097"}],
        "document_notices": [],
        "coverage": {"coverage_status": "partial", "coverage_ratio": 0.933, "content_page_count": 15,
                     "covered_content_pages": [3, 4], "uncovered_content_pages": [5], "coverage_warnings": ["第 5 頁…"]},
        "limitations": ["摘要僅重組官方文件既有 evidence"],
        "source": {"provider": "MOPS", "filename": MOPS_FILE, "sha256": MOPS_SHA, "listing_url": MOPS_LISTING,
                   "download_form": {"method": "POST", "fields": {"fileName": MOPS_FILE}},
                   "identity": {"identity_version": "conference-identity-v6", "recomputed_from_archive": True}},
        "source_identity": {"source_type": "mops_conference_pdf", "source_name": "MOPS", "period": "2025Q3",
                            "period_basis": "document_identity", "document_type": "earnings_presentation",
                            "filename": MOPS_FILE, "event_date": "2025-10-31", "availability": "available",
                            "provenance": {"url": MOPS_LISTING, "sha256": MOPS_SHA, "retrieved_at": None}},
    }


def conference(year: int, quarter: int, date: str, **extra) -> dict:
    return {"event_id": f"ir-{year}q{quarter}", "ticker": "2454", "company_name": "聯發科", "fiscal_year": year,
            "quarter": quarter, "conference_date": date, "title": f"MediaTek {year} Q{quarter} Results - Investors Conference",
            "source_name": "company_official_ir", "source_url": IR_URL, "document_url": IR_DOCUMENT_URL,
            "status": "available", "retrieved_at": "2026-09-26T00:00:00Z", "extracted_topics": ["營收"],
            "related_metrics": ["revenue"], **extra}


MATERIAL_EVENT = {"event_id": "capex", "ticker": "2454", "company_name": "聯發科", "event_date": "2026-09-01",
                  "title": "公告本公司董事會決議資本支出案", "category": "capacity_or_capex", "source_name": "twse_openapi",
                  "source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L", "status": "available",
                  "retrieved_at": "2026-09-15T00:00:00Z",
                  "source_identity": {"source_type": "twse_openapi", "source_name": "twse_openapi", "period": None,
                                      "period_basis": "none", "document_type": None, "filename": None,
                                      "event_date": "2026-09-01", "availability": "available",
                                      "provenance": {"url": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
                                                     "sha256": None, "retrieved_at": "2026-09-15T00:00:00Z"}}}


def standalone_card() -> dict:
    """2454 as in production: a 2026Q2 company-IR item and a standalone 2025Q3 MOPS digest."""
    return {
        "schema_version": "frontend-official-evidence-card-1.2.0", "ticker": "2454", "company_name": "聯發科",
        "subindustry": "IC 設計", "evidence_readiness": "ready_for_frontend_integration", "headline": "h", "summary": "s",
        "financial_snapshot": copy.deepcopy(SNAPSHOT),
        "investor_conferences": [conference(2026, 2, "2026-07-31", summary_status="no_matching_archive",
                                            source_identity=ir_identity("2026Q2", "2026-07-31"))],
        "conference_document_digest": mops_digest(), "conference_summary_state": "standalone_latest",
        "material_events": [copy.deepcopy(MATERIAL_EVENT)],
        "narrative_shift": {"baseline_period": "2026Q1", "current_period": "2026Q2"},
        "source_status": {"document_digest_status": {"card_level_digest_status": "available"}},
        "sources": [], "limitations": [],
    }


def matched_card() -> dict:
    card = standalone_card()
    card["investor_conferences"] = [conference(2025, 3, "2025-10-31", summary_status="available",
                                              source_identity=ir_identity("2025Q3", "2025-10-31"),
                                              document_digest=mops_digest())]
    card["conference_document_digest"] = None
    card["conference_summary_state"] = "attached"
    return card


def legacy_card_v110() -> dict:
    """Schema 1.1.0: no source_identity and no conference_summary_state anywhere."""
    card = standalone_card()
    card["schema_version"] = "frontend-official-evidence-card-1.1.0"
    card.pop("conference_summary_state")
    card["conference_document_digest"].pop("source_identity")
    for item in [*card["investor_conferences"], *card["material_events"]]:
        item.pop("source_identity")
    return card


class FakeBackend:
    """Opener for FinTrustClient: routes by path, records every call, can fail paths."""

    def __init__(self, card: dict | None, *, fail: set[str] | None = None) -> None:
        self.card = card
        self.fail = fail or set()
        self.paths: list[str] = []
        self.routes = {
            CARD_PATH: lambda: self.card,
            "/api/v1/financial/companies/2454/analysis/latest": lambda: SNAPSHOT,
            "/api/v1/financial/companies/2454/official-evidence": lambda: {"readiness": "financial_plus_event_metadata",
                                                                           "evidence_layers": ["financial_snapshot"],
                                                                           "sources": [], "limitations": []},
            "/api/v1/financial/companies/2454/conferences": lambda: [conference(2026, 2, "2026-07-31")],
            "/api/v1/financial/companies/2454/material-events": lambda: [{k: v for k, v in MATERIAL_EVENT.items() if k != "source_identity"}],
            "/api/v1/financial/companies": lambda: {"companies": [{"ticker": "2454", "name": "聯發科", "subindustry": "IC 設計"}]},
            "/api/v1/financial/text-mining/companies/2454/latest-run": lambda: {"run_id": "run-1", "text_evidence": []},
        }

    def __call__(self, request, timeout):
        path = urlparse(request.full_url).path
        self.paths.append(path)
        if path in self.fail or path not in self.routes:
            raise HTTPError(request.full_url, 503, "unavailable", hdrs=None, fp=io.BytesIO(b'{"detail": "unavailable"}'))
        return FakeHttpResponse(self.routes[path]())


class CardFirstProxyTests(unittest.TestCase):
    def call(self, backend: FakeBackend):
        app = Flask(__name__)
        app.register_blueprint(create_financial_blueprint(client=FinTrustClient(base_url=BASE, opener=backend)))
        return app.test_client().get("/api/financial/companies/2454/card")

    def test_successful_card_is_the_only_backend_call(self) -> None:
        backend = FakeBackend(standalone_card())
        response = self.call(backend)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(backend.paths, [CARD_PATH])
        data = response.get_json()["data"]
        self.assertTrue(response.get_json()["success"])
        self.assertEqual(data["errors"], [])
        self.assertEqual(data["raw"]["mode"], "card_first")
        self.assertEqual(data["conference_summary_state"], "standalone_latest")

    def test_raw_is_rebuilt_only_from_equivalent_card_data(self) -> None:
        card = standalone_card()
        data = self.call(FakeBackend(card)).get_json()["data"]
        raw = data["raw"]
        self.assertEqual(raw["snapshot"], card["financial_snapshot"])
        self.assertEqual(raw["conferences"], card["investor_conferences"])
        self.assertEqual(raw["material_events"], card["material_events"])
        # Not faithfully derivable from the card: explicitly omitted, never invented.
        self.assertIsNone(raw["official_evidence"])
        self.assertEqual(raw["conference_documents"], [])
        self.assertIsNone(raw["official_evidence_card"])
        self.assertEqual(set(raw["omitted"]), {"official_evidence", "conference_documents", "official_evidence_card"})
        # Top-level card fields are passed through unchanged.
        for key, value in card.items():
            self.assertEqual(data[key], value, key)

    def test_card_failure_falls_back_to_legacy_calls_without_retrying_the_card(self) -> None:
        backend = FakeBackend(standalone_card(), fail={CARD_PATH})
        response = self.call(backend)
        self.assertEqual(response.status_code, 207)
        self.assertEqual(backend.paths.count(CARD_PATH), 1)
        self.assertEqual(backend.paths[0], CARD_PATH)
        self.assertEqual(set(backend.paths[1:]), {
            "/api/v1/financial/companies/2454/analysis/latest",
            "/api/v1/financial/companies/2454/official-evidence",
            "/api/v1/financial/companies/2454/conferences",
            "/api/v1/financial/companies/2454/material-events",
        })
        data = response.get_json()["data"]
        self.assertEqual(data["errors"][0]["layer"], "official_evidence_card")
        self.assertEqual(data["raw"]["mode"], "legacy_fallback")
        self.assertEqual(data["raw"]["snapshot"], SNAPSHOT)
        self.assertEqual(len(data["raw"]["conferences"]), 1)
        self.assertEqual(data["evidence_readiness"], "financial_plus_event_metadata")

    def test_partial_failure_in_fallback_stays_safe(self) -> None:
        backend = FakeBackend(standalone_card(), fail={CARD_PATH, "/api/v1/financial/companies/2454/material-events",
                                                       "/api/v1/financial/companies/2454/analysis/latest"})
        response = self.call(backend)
        self.assertEqual(response.status_code, 207)
        data = response.get_json()["data"]
        self.assertEqual({error["layer"] for error in data["errors"]}, {"official_evidence_card", "material_events", "snapshot"})
        self.assertEqual(data["raw"]["material_events"], [])
        self.assertEqual(len(data["raw"]["conferences"]), 1)

    def test_schema_110_card_without_new_fields_still_works(self) -> None:
        card = legacy_card_v110()
        backend = FakeBackend(card)
        response = self.call(backend)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(backend.paths, [CARD_PATH])
        data = response.get_json()["data"]
        self.assertNotIn("conference_summary_state", data)
        self.assertEqual(data["raw"]["conferences"], card["investor_conferences"])


class OfficialEvidenceBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.old_env = {key: os.environ.get(key) for key in ("ALLOW_DEMO_SEED_DATA", "FLASK_DATABASE_PATH", "APP_ENV", "SECRET_KEY")}
        os.environ["ALLOW_DEMO_SEED_DATA"] = "false"
        os.environ["FLASK_DATABASE_PATH"] = str(Path(cls.temp_dir.name) / "browser.db")
        os.environ["APP_ENV"] = "development"
        os.environ.pop("SECRET_KEY", None)
        fake_data_shift = types.ModuleType("data_shift")
        fake_data_shift.data_shift_bp = Blueprint("data_shift_card_first_test", __name__)
        cls.old_data_shift = sys.modules.get("data_shift")
        sys.modules["data_shift"] = fake_data_shift
        sys.modules.pop("app", None)
        cls.app_module = importlib.import_module("app")
        cls.app_module.app.config["TESTING"] = True
        cls.original_client = cls.app_module.FinTrustClient

    @classmethod
    def tearDownClass(cls) -> None:
        cls.app_module.FinTrustClient = cls.original_client
        sys.modules.pop("app", None)
        if cls.old_data_shift is None:
            sys.modules.pop("data_shift", None)
        else:
            sys.modules["data_shift"] = cls.old_data_shift
        for key, value in cls.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        cls.temp_dir.cleanup()

    def browse(self, backend: FakeBackend, query: str = "ticker=2454"):
        self.app_module.FinTrustClient = lambda: FinTrustClient(base_url=BASE, opener=backend)
        return self.app_module.app.test_client().get(f"/api/official-evidence/browser?{query}")

    def conference_record(self, data: dict) -> dict:
        return next(record for record in data["records"] if record["type"] == "investor_conference")

    def test_card_is_the_record_source_without_redundant_list_calls(self) -> None:
        backend = FakeBackend(standalone_card())
        response = self.browse(backend)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(backend.paths, [CARD_PATH, "/api/v1/financial/text-mining/companies/2454/latest-run"])
        data = response.get_json()
        self.assertEqual(data["evidence_source"], "official_evidence_card")
        self.assertEqual(data["conference_summary_state"], "standalone_latest")
        self.assertEqual(data["conference_document_digest"], standalone_card()["conference_document_digest"])
        self.assertEqual(data["source_status"], standalone_card()["source_status"])
        self.assertEqual(data["summary"]["company_name"], "聯發科")
        self.assertEqual(data["summary"]["subindustry"], "IC 設計")
        self.assertEqual(data["summary"]["investor_conference_count"], 1)
        self.assertEqual(data["summary"]["material_event_count"], 1)
        event = next(record for record in data["records"] if record["type"] == "material_event")
        self.assertEqual(event["source_identity"]["source_type"], "twse_openapi")
        self.assertNotIn("document_digest", event)

    def test_2454_company_ir_record_and_standalone_mops_digest_stay_separate(self) -> None:
        data = self.browse(FakeBackend(standalone_card())).get_json()
        record = self.conference_record(data)
        self.assertEqual(record["source_identity"]["source_type"], "company_ir")
        self.assertEqual(record["source_identity"]["period"], "2026Q2")
        self.assertEqual(record["summary_status"], "no_matching_archive")
        self.assertIsNone(record["document_digest"])
        record_json = json.dumps(record, ensure_ascii=False)
        self.assertNotIn(MOPS_FILE, record_json)
        self.assertNotIn(MOPS_SHA, record_json)
        digest = data["conference_document_digest"]
        self.assertEqual(digest["source_identity"]["source_type"], "mops_conference_pdf")
        self.assertEqual(digest["source_identity"]["period"], "2025Q3")
        self.assertNotIn("mediatek.com", json.dumps(digest["source_identity"]))

    def test_matched_period_keeps_ir_record_and_mops_digest_as_separate_sources(self) -> None:
        data = self.browse(FakeBackend(matched_card())).get_json()
        record = self.conference_record(data)
        self.assertEqual(data["conference_summary_state"], "attached")
        self.assertIsNone(data["conference_document_digest"])
        self.assertEqual(record["source_identity"]["source_type"], "company_ir")
        self.assertEqual(record["source_identity"]["provenance"]["url"], IR_DOCUMENT_URL)
        compact = record["document_digest"]
        self.assertEqual(compact["source_identity"]["source_type"], "mops_conference_pdf")
        self.assertEqual(compact["source_identity"]["provenance"]["url"], MOPS_LISTING)
        self.assertEqual((compact["period"], compact["filename"], compact["provenance"]["sha256"]), ("2025Q3", MOPS_FILE, MOPS_SHA))
        self.assertEqual(compact["sections"], [{"section_type": "financial_performance", "title_zh": "財務表現",
                                                "title_en": "Financial Performance", "bullet_count": 1}])
        self.assertEqual(compact["coverage"]["coverage_status"], "partial")
        self.assertEqual(compact["key_quantitative_count"], 1)
        self.assertNotIn("bullets", json.dumps(compact))
        self.assertNotIn("download_form", json.dumps(compact))
        self.assertIsNone(record["source_identity"]["filename"])

    def test_card_failure_falls_back_to_legacy_lists(self) -> None:
        backend = FakeBackend(standalone_card(), fail={CARD_PATH})
        response = self.browse(backend)
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["evidence_source"], "legacy_lists")
        self.assertIsNotNone(data["official_card_error"])
        self.assertEqual(set(backend.paths), {CARD_PATH, "/api/v1/financial/companies", "/api/v1/financial/companies/2454/conferences",
                                              "/api/v1/financial/companies/2454/material-events",
                                              "/api/v1/financial/text-mining/companies/2454/latest-run"})
        self.assertEqual(len(data["records"]), 2)
        self.assertIsNone(data["conference_summary_state"])
        self.assertIsNone(data["conference_document_digest"])
        self.assertIsNone(self.conference_record(data)["source_identity"])

    def test_schema_110_card_without_new_fields_does_not_crash(self) -> None:
        data = self.browse(FakeBackend(legacy_card_v110())).get_json()
        self.assertEqual(data["evidence_source"], "official_evidence_card")
        self.assertIsNone(data["conference_summary_state"])
        self.assertIsNone(self.conference_record(data)["source_identity"])
        self.assertIsNone(data["conference_document_digest"].get("source_identity"))

    def test_unusual_identity_values_pass_through(self) -> None:
        card = standalone_card()
        card["investor_conferences"][0]["source_identity"].update(source_type="unknown", availability="needs_review")
        card["material_events"][0]["source_identity"]["source_type"] = "demo_fixture"
        data = self.browse(FakeBackend(card)).get_json()
        self.assertEqual(self.conference_record(data)["source_identity"]["source_type"], "unknown")
        self.assertEqual(self.conference_record(data)["source_identity"]["availability"], "needs_review")
        event = next(record for record in data["records"] if record["type"] == "material_event")
        self.assertEqual(event["source_identity"]["source_type"], "demo_fixture")

    def test_card_without_company_details_uses_company_list_only_then(self) -> None:
        card = standalone_card()
        card.pop("subindustry")
        backend = FakeBackend(card)
        data = self.browse(backend).get_json()
        self.assertIn("/api/v1/financial/companies", backend.paths)
        self.assertNotIn("/api/v1/financial/companies/2454/conferences", backend.paths)
        self.assertEqual(data["summary"]["subindustry"], "IC 設計")


if __name__ == "__main__":
    unittest.main()
