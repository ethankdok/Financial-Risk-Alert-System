"""Acceptance matrix CASE-01 … CASE-14 for Phase 1 historical audit-case ingestion.

All documents here are SYNTHETIC fixtures (tests/historical_audit_fixtures.py);
they prove pipeline behaviour, not the existence of real 1785 filings.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import httpx

from app.models import CompanyMasterRecord, FinancialFact
from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.backfill import HistoricalBackfillService, validate_year_range
from app.services.historical_audit.case_registry import get_case, load_cases
from app.services.historical_audit.export import (
    CONTRACT_VERSION,
    EXPORT_FIELDS,
    build_export_records,
    export_historical_facts,
)
from app.services.historical_audit.models import as_of_cutoff, filing_version_id
from app.services.historical_audit.quality import quality_report
from app.services.historical_audit.reader import list_historical_facts
from app.services.historical_audit.repository import (
    HistoricalAuditRepository,
    ProductionDatabaseRefusedError,
)
from app.services.historical_audit.sources import (
    OfficialSourceFetcher,
    SourceNotAllowedError,
    ensure_official_url,
    load_manifest,
)
from tests.historical_audit_fixtures import (
    MOPS_NOT_FOUND_PAGE,
    synthetic_inline,
    synthetic_instance,
    write_manifest,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = BACKEND_ROOT / "app" / "services" / "historical_audit"
RESTATED_TEXT = "如重編後財務報表附註十二所述"


async def _no_sleep(_: float) -> None:
    return None


def run(coro):
    return asyncio.run(coro)


class MopsStub:
    """httpx.MockTransport handler serving fixture bytes per fiscal year."""

    def __init__(self, responses: dict[int, object]) -> None:
        self.responses = responses
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        year = int(request.url.params["year"])
        response = self.responses.get(year, MOPS_NOT_FOUND_PAGE)
        if callable(response):
            response = response()
        if isinstance(response, httpx.Response):
            return response
        if isinstance(response, Exception):
            raise response
        return httpx.Response(200, content=response, headers={"content-type": "application/octet-stream"})

    @property
    def requested_years(self) -> list[int]:
        return [int(request.url.params["year"]) for request in self.requests]


class HistoricalAuditTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.db_path = str(self.root / "historical.sqlite3")
        self.archive = RawEvidenceArchive(self.root / "raw")
        self.repository = HistoricalAuditRepository(self.db_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def service(self, stub: MopsStub | None = None) -> HistoricalBackfillService:
        fetcher = None
        if stub is not None:
            fetcher = OfficialSourceFetcher(
                transport=httpx.MockTransport(stub), sleep=_no_sleep,
                min_interval_seconds=0, backoff_seconds=0,
            )
        return HistoricalBackfillService(repository=self.repository, archive=self.archive, fetcher=fetcher)

    def versioned_manifest(self) -> Path:
        """2014FY original (A) and restated (B) with verified, distinct availability (synthetic)."""
        docs = self.root / "docs"
        docs.mkdir(exist_ok=True)
        (docs / "a.xml").write_bytes(synthetic_instance(fiscal_year=2014, audit_date="2015-03-20"))
        (docs / "b.xml").write_bytes(synthetic_instance(
            fiscal_year=2014, audit_date="2016-11-11", emphasis_text=RESTATED_TEXT,
            overrides={"inventory": 250_000_000, "current_assets": 650_000_000, "total_assets": 1_950_000_000,
                       "equity": 750_000_000},
        ))
        (docs / "c.xml").write_bytes(synthetic_instance(fiscal_year=2015, audit_date="2016-03-25"))
        return write_manifest(docs, [
            {"period": "2014FY", "source_kind": "test_fixture", "local_path": "a.xml",
             "source_url": "fixture://1785/2014FY/A", "statement_scope": "consolidated",
             "filing_version_type": "original",
             "source_published_at": "2015-03-31T10:00:00+08:00", "available_at": "2015-03-31T10:00:00+08:00",
             "availability_basis": "synthetic fixture timeline", "verification_evidence": ["synthetic test evidence A"]},
            {"period": "2014FY", "source_kind": "test_fixture", "local_path": "b.xml",
             "source_url": "fixture://1785/2014FY/B", "statement_scope": "consolidated",
             "source_published_at": "2016-11-15T09:00:00+08:00", "available_at": "2016-11-15T09:00:00+08:00",
             "availability_basis": "synthetic fixture timeline", "verification_evidence": ["synthetic test evidence B"]},
            {"period": "2015FY", "source_kind": "test_fixture", "local_path": "c.xml",
             "source_url": "fixture://1785/2015FY/C", "statement_scope": "consolidated",
             "available_at": "2016-03-31T15:00:00+08:00",
             "availability_basis": "synthetic fixture timeline", "verification_evidence": ["synthetic test evidence C"]},
        ])

    def counts(self) -> dict[str, int]:
        return self.repository.table_counts()


class Case01RegistrationIsolationTests(HistoricalAuditTestCase):
    def test_1785_is_a_tpex_historical_case_outside_the_production_universe(self) -> None:
        from app.services import company_registry
        from app.services.ingestion_pipeline import ALLOWED_BATCH_REFRESH_TICKERS, validate_refresh_tickers
        from app.services.semiconductor_coverage import production_eligible_tickers
        from app.services.semiconductor_subindustries import classified_tickers

        case = get_case("1785")
        self.assertEqual((case.ticker, case.market, case.company_name), ("1785", "TPEX", "光洋科"))
        before = dict(company_registry.SEMICONDUCTOR_COMPANIES)
        run(self.service().run("1785", 2014, 2015, source_strategy="manifest", manifest_path=self.versioned_manifest()))
        self.assertEqual(company_registry.SEMICONDUCTOR_COMPANIES, before)
        self.assertNotIn("1785", company_registry.SEED_COMPANIES)
        self.assertNotIn("1785", classified_tickers())
        self.assertNotIn("1785", ALLOWED_BATCH_REFRESH_TICKERS)
        self.assertNotIn("1785", production_eligible_tickers())
        with self.assertRaises(ValueError):
            validate_refresh_tickers(["1785"])
        self.assertEqual(company_registry.get_company("2330").name, "台積電")
        self.assertEqual(company_registry.get_company("2454").name, "聯發科")
        # Company Master stays TWSE-only; the case did not widen it.
        with self.assertRaises(Exception):
            CompanyMasterRecord(ticker="1785", name="光洋科", legal_name="x", market="TPEX",
                                source_url="https://example.invalid", synced_at=datetime.now(timezone.utc))
        self.assertEqual(self.repository.get_case("1785").market, "TPEX")

    def test_get_company_does_not_resolve_1785(self) -> None:
        from app.services import company_registry

        with patch.dict(os.environ, {"DATASTORE_BACKEND": "sqlite",
                                     "FINANCIAL_DATABASE_PATH": str(self.root / "master.sqlite3")}):
            self.assertIsNone(company_registry.get_company("1785"))

    def test_refresh_all_rejects_1785(self) -> None:
        from app.services.ingestion_pipeline import FinancialIngestionPipeline

        pipeline = FinancialIngestionPipeline.__new__(FinancialIngestionPipeline)
        with self.assertRaises(ValueError):
            run(pipeline.refresh_all(tickers=["1785"]))

    def test_unregistered_ticker_is_refused(self) -> None:
        with self.assertRaises(LookupError):
            run(self.service().run("9999", 2014, 2014, dry_run=True))


class Case02ExactRangeTests(HistoricalAuditTestCase):
    def test_exact_2011_to_2016_years_without_substitution(self) -> None:
        stub = MopsStub({year: synthetic_instance(fiscal_year=year) for year in range(2013, 2017)})
        result = run(self.service(stub).run("1785", 2011, 2016))
        self.assertEqual(sorted(stub.requested_years), [2011, 2012, 2013, 2014, 2015, 2016])
        self.assertEqual([year.fiscal_year for year in result.years], list(range(2011, 2017)))
        statuses = {year.fiscal_year: year.status for year in result.years}
        self.assertEqual(statuses[2011], "filing_not_found")
        self.assertEqual(statuses[2012], "filing_not_found")
        self.assertTrue(all(statuses[year] == "available" for year in range(2013, 2017)))
        self.assertEqual(result.status, "partial")
        facts = list_historical_facts(self.repository, "1785", 2000, 2030)
        self.assertEqual({fact["period"] for fact in facts}, {"2013FY", "2014FY", "2015FY", "2016FY"})
        for request in stub.requests:
            self.assertEqual(request.url.params["season"], "4")
            self.assertEqual(request.url.params["report_id"], "C")

    def test_arbitrary_bounded_ranges(self) -> None:
        self.assertEqual(validate_year_range(2017, 2025), list(range(2017, 2026)))
        with self.assertRaises(ValueError):
            validate_year_range(2016, 2011)
        with self.assertRaises(ValueError):
            validate_year_range(1990, 2025)

    def test_dry_run_writes_nothing(self) -> None:
        planning_db = self.root / "never-created.sqlite3"
        service = HistoricalBackfillService(
            repository=HistoricalAuditRepository.for_planning(str(planning_db)), archive=RawEvidenceArchive(self.root / "dry"))
        result = run(service.run("1785", 2011, 2016, dry_run=True))
        self.assertEqual(result.status, "dry_run")
        self.assertEqual([item["fiscal_year"] for item in result.plan], list(range(2011, 2017)))
        self.assertIn("year=2011", result.plan[0]["source_url"])
        self.assertFalse(planning_db.exists())
        self.assertFalse((self.root / "dry").exists())


class Case03To05VersioningTests(HistoricalAuditTestCase):
    def test_case03_original_and_restated_versions_coexist(self) -> None:
        run(self.service().run("1785", 2014, 2015, source_strategy="manifest", manifest_path=self.versioned_manifest()))
        versions = [v for v in self.repository.list_filing_versions("1785") if v["period"] == "2014FY"]
        self.assertEqual(len(versions), 2)
        self.assertEqual(sorted(v["filing_version_type"] for v in versions), ["original", "restated"])
        inventory = list_historical_facts(self.repository, "1785", 2014, 2014, metrics=["inventory"])
        self.assertEqual(sorted(row["value"] for row in inventory), [250_000_000.0, 300_000_000.0])
        self.assertEqual(len({row["filing_version_id"] for row in inventory}), 2)

    def test_case04_rerun_creates_no_duplicates(self) -> None:
        manifest = self.versioned_manifest()
        first = run(self.service().run("1785", 2014, 2015, source_strategy="manifest", manifest_path=manifest))
        after_first = self.counts()
        second = run(self.service().run("1785", 2014, 2015, source_strategy="manifest", manifest_path=manifest))
        after_second = self.counts()
        for table in ("financial_filing_versions", "versioned_financial_facts", "filing_version_annotations"):
            self.assertEqual(after_first[table], after_second[table], table)
        self.assertTrue(all(year.new_version for year in first.years))
        self.assertFalse(any(year.new_version for year in second.years))
        self.assertEqual(sum(year.facts_inserted for year in second.years), 0)
        self.assertEqual([y.filing_version_id for y in first.years], [y.filing_version_id for y in second.years])
        self.assertEqual(after_second["historical_acquisition_attempts"], 2 * after_first["historical_acquisition_attempts"])

    def test_case05_changed_content_creates_distinct_unknown_revision(self) -> None:
        stub = MopsStub({2014: synthetic_instance(fiscal_year=2014)})
        first = run(self.service(stub).run("1785", 2014, 2014))
        stub.responses[2014] = synthetic_instance(fiscal_year=2014, overrides={"revenue": 1_100_000_000, "gross_profit": 300_000_000})
        second = run(self.service(stub).run("1785", 2014, 2014))
        self.assertNotEqual(first.years[0].filing_version_id, second.years[0].filing_version_id)
        self.assertTrue(second.years[0].new_version)
        versions = self.repository.list_filing_versions("1785", 2014, 2014)
        self.assertEqual(len(versions), 2)
        # A hash difference alone is never labelled an official restatement.
        self.assertEqual({v["filing_version_type"] for v in versions}, {"unknown_revision"})
        revenue = sorted(row["value"] for row in list_historical_facts(self.repository, "1785", 2014, 2014, metrics=["revenue"]))
        self.assertEqual(revenue, [1_000_000_000.0, 1_100_000_000.0])

    def test_scope_and_unit_are_part_of_identity(self) -> None:
        content_hash = "a" * 64
        self.assertNotEqual(filing_version_id("1785", "2014FY", "consolidated", content_hash),
                            filing_version_id("1785", "2014FY", "individual", content_hash))
        self.assertEqual(filing_version_id("1785", "2014FY", "consolidated", content_hash),
                         filing_version_id("1785", "2014FY", "consolidated", content_hash))

    def test_restatement_wording_variants_used_by_auditors(self) -> None:
        from app.services.historical_audit.backfill import classify_version
        from app.services.historical_audit.xbrl_document import parse_xbrl_document

        for text, expected in (
            ("如重編後財務報表附註十二、10所述", "restated"),
            ("上開重編後合併財務報告之編製係管理階層之責任", "restated"),
            ("公司及其子公司重編後民國104年及103年12月31日之合併資產負債表", "restated"),
            ("如合併財務報告附註十二.11及12所述", "unknown_revision"),
            ("民國一○三年度之比較數字業已重新分類", "unknown_revision"),
        ):
            document = parse_xbrl_document(synthetic_instance(fiscal_year=2015, audit_date="2016-11-11", emphasis_text=text))
            self.assertEqual(classify_version(document, 2015)[0], expected, text)

    def test_restatement_markers_inside_normal_filing_window_stay_unknown(self) -> None:
        stub = MopsStub({2014: synthetic_instance(fiscal_year=2014, audit_date="2015-03-20", emphasis_text=RESTATED_TEXT)})
        result = run(self.service(stub).run("1785", 2014, 2014))
        self.assertEqual(result.years[0].filing_version_type, "unknown_revision")
        self.assertTrue(any("left unknown" in warning for warning in result.years[0].warnings))

    def test_manifest_original_conflicting_with_document_restatement_is_quarantined(self) -> None:
        docs = self.root / "conflict"
        docs.mkdir()
        (docs / "b.xml").write_bytes(synthetic_instance(fiscal_year=2014, audit_date="2016-11-11", emphasis_text=RESTATED_TEXT))
        manifest = write_manifest(docs, [{
            "period": "2014FY", "source_kind": "test_fixture", "local_path": "b.xml",
            "filing_version_type": "original", "verification_evidence": ["mislabelled"]}])
        result = run(self.service().run("1785", 2014, 2014, source_strategy="manifest", manifest_path=manifest))
        self.assertEqual(result.years[0].status, "quarantined")
        self.assertTrue(result.years[0].quarantine_reason.startswith("version_type_conflict"))
        self.assertEqual(self.counts()["versioned_financial_facts"], 0)


class Case06ProvenanceTests(HistoricalAuditTestCase):
    def test_every_fact_links_to_version_hash_and_raw_bytes(self) -> None:
        run(self.service().run("1785", 2014, 2015, source_strategy="manifest", manifest_path=self.versioned_manifest()))
        with self.repository.connect() as connection:
            rows = connection.execute(
                """SELECT f.fact_id, v.content_hash, v.raw_storage_path, v.retrieved_at, v.parser_version, f.source_url
                FROM versioned_financial_facts f LEFT JOIN financial_filing_versions v USING (filing_version_id)"""
            ).fetchall()
        self.assertGreater(len(rows), 0)
        for row in rows:
            self.assertIsNotNone(row["content_hash"])
            raw = (self.archive.root / row["raw_storage_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row["content_hash"])
            self.assertTrue(row["retrieved_at"] and row["parser_version"] and row["source_url"])
        report = quality_report(self.repository, self.archive, "1785", 2014, 2015)
        self.assertTrue(report["integrity_passed"], report["checks"])

    def test_tampered_archive_is_detected(self) -> None:
        run(self.service().run("1785", 2014, 2015, source_strategy="manifest", manifest_path=self.versioned_manifest()))
        version = self.repository.list_filing_versions("1785", 2014, 2014)[0]
        (self.archive.root / version["raw_storage_path"]).write_bytes(b"tampered")
        report = quality_report(self.repository, self.archive, "1785", 2014, 2015)
        self.assertFalse(report["integrity_passed"])
        self.assertEqual(len(report["checks"]["archive_hash_failures"]), 1)


class Case07PointInTimeTests(HistoricalAuditTestCase):
    def setUp(self) -> None:
        super().setUp()
        run(self.service().run("1785", 2014, 2015, source_strategy="manifest", manifest_path=self.versioned_manifest()))

    def inventory(self, **kwargs) -> list[dict]:
        return list_historical_facts(self.repository, "1785", 2014, 2015, metrics=["inventory"], **kwargs)

    def test_fiscal_year_end_is_not_publication_time(self) -> None:
        self.assertEqual(self.inventory(as_of="2014-12-31"), [])
        self.assertEqual([r["period"] for r in self.inventory(as_of="2015-12-31")], ["2014FY"])
        # 2015FY (published 2016-03-31) is invisible at 2015-12-31 and before its availability time.
        self.assertNotIn("2015FY", {r["period"] for r in self.inventory(as_of="2016-03-30")})
        self.assertIn("2015FY", {r["period"] for r in self.inventory(as_of="2016-03-31")})

    def test_restatement_is_not_visible_before_its_availability(self) -> None:
        before = self.inventory(as_of="2016-06-30", version_policy="latest_available", periods=["2014FY"])
        self.assertEqual([(r["filing_version_type"], r["value"]) for r in before], [("original", 300_000_000.0)])
        after = self.inventory(as_of="2016-12-31", version_policy="latest_available", periods=["2014FY"])
        self.assertEqual([(r["filing_version_type"], r["value"]) for r in after], [("restated", 250_000_000.0)])
        self.assertEqual(len(self.inventory(as_of="2016-12-31", periods=["2014FY"])), 2)
        originals = self.inventory(as_of="2016-12-31", version_policy="original_only", periods=["2014FY"])
        self.assertEqual([r["value"] for r in originals], [300_000_000.0])
        earliest = self.inventory(version_policy="earliest_available", periods=["2014FY"])
        self.assertEqual([r["filing_version_type"] for r in earliest], ["original"])

    def test_timestamp_boundaries_are_exact(self) -> None:
        self.assertEqual(self.inventory(as_of="2016-11-15T00:59:59+00:00", periods=["2014FY"], version_policy="latest_available")[0]["filing_version_type"], "original")
        self.assertEqual(self.inventory(as_of="2016-11-15T01:00:00+00:00", periods=["2014FY"], version_policy="latest_available")[0]["filing_version_type"], "restated")
        with self.assertRaises(ValueError):
            as_of_cutoff(datetime(2016, 1, 1))

    def test_unverified_availability_is_excluded_from_point_in_time_views(self) -> None:
        stub = MopsStub({2016: synthetic_instance(fiscal_year=2016)})
        run(self.service(stub).run("1785", 2016, 2016))
        unrestricted = list_historical_facts(self.repository, "1785", 2016, 2016)
        self.assertTrue(unrestricted)
        self.assertFalse(any(row["point_in_time_eligible"] for row in unrestricted))
        self.assertEqual(list_historical_facts(self.repository, "1785", 2016, 2016, as_of="2030-01-01"), [])
        version = self.repository.list_filing_versions("1785", 2016, 2016)[0]
        self.assertIsNone(version["available_at"])
        self.assertIsNone(version["source_published_at"])
        self.assertEqual(version["document_dated_at"], "2017-03-20")


class Case08ErrorIsolationTests(HistoricalAuditTestCase):
    def test_failed_years_do_not_block_other_years(self) -> None:
        stub = MopsStub({
            2011: httpx.Response(503),
            2012: b"<html><body>Too many requests, please retry</body></html>",
            2013: b"<?xml version=\"1.0\"?><xbrli:xbrl xmlns:xbrli=\"http://www.xbrl.org/2003/instance\"><broken>",
            2014: synthetic_instance(fiscal_year=2014),
            2015: httpx.ConnectError("boom"),
            2016: synthetic_instance(fiscal_year=2016),
        })
        result = run(self.service(stub).run("1785", 2011, 2016))
        statuses = {year.fiscal_year: year.status for year in result.years}
        self.assertEqual(statuses, {
            2011: "source_unavailable", 2012: "source_invalid_content", 2013: "parse_failed",
            2014: "available", 2015: "source_unavailable", 2016: "available",
        })
        self.assertEqual(result.status, "partial")
        self.assertEqual(stub.requested_years.count(2011), 3)  # bounded retries
        invalid = next(year for year in result.years if year.fiscal_year == 2012)
        self.assertTrue((self.archive.root / invalid.raw_storage_path).exists())
        self.assertEqual(len(self.repository.list_attempts(result.run_id)), 6)
        self.assertEqual({fact["period"] for fact in list_historical_facts(self.repository, "1785", 2011, 2016)},
                         {"2014FY", "2016FY"})

    def test_quarantine_rules(self) -> None:
        stub = MopsStub({
            2014: synthetic_instance(fiscal_year=2014, entity="2330"),
            2015: synthetic_instance(fiscal_year=2016),  # document for another fiscal year
            2016: synthetic_instance(fiscal_year=2016, omit=("revenue", "net_income", "total_assets", "total_liabilities",
                                                              "equity", "inventory", "current_assets", "current_liabilities",
                                                              "accounts_receivable", "cost_of_goods_sold", "gross_profit",
                                                              "operating_income", "operating_cash_flow", "investing_cash_flow",
                                                              "capital_expenditure", "cash_and_cash_equivalents")),
        })
        result = run(self.service(stub).run("1785", 2014, 2016))
        reasons = {year.fiscal_year: year.quarantine_reason for year in result.years}
        self.assertEqual(reasons[2014], "entity_identifier_mismatch")
        self.assertTrue(reasons[2015].startswith("document_period_mismatch"))
        self.assertEqual(reasons[2016], "insufficient_core_fields")
        self.assertEqual(self.counts()["versioned_financial_facts"], 0)
        self.assertEqual(self.counts()["financial_filing_versions"], 3)


class NormalizationQualityTests(HistoricalAuditTestCase):
    def test_contexts_units_missing_values_and_identities(self) -> None:
        stub = MopsStub({2014: synthetic_instance(fiscal_year=2014, omit=("accounts_receivable",),
                                                  overrides={"total_liabilities": 1_100_000_000})})
        result = run(self.service(stub).run("1785", 2014, 2014))
        year = result.years[0]
        self.assertIn("accounts_receivable", year.core_fields_missing)
        self.assertEqual(year.validation_status, "validated_with_warnings")
        self.assertTrue(any(w.startswith("identity_check") for w in year.warnings))
        facts = {row["metric_code"]: row for row in list_historical_facts(self.repository, "1785", 2014, 2014)}
        self.assertNotIn("accounts_receivable", facts)  # missing is never zero-filled
        self.assertEqual(facts["inventory"]["value"], 300_000_000.0)  # not the prior-year comparative
        self.assertEqual(facts["equity"]["value"], 800_000_000.0)  # not the dimensional member
        self.assertEqual(facts["revenue"]["taxonomy_concept"], "tifrs-bsci-ci:OperatingRevenue")
        self.assertEqual(facts["eps"]["unit"], "TWD/share")
        self.assertEqual(facts["eps"]["value_text"], "0.50")
        self.assertEqual(facts["revenue"]["statement_scope"], "consolidated")
        version = self.repository.list_filing_versions("1785", 2014, 2014)[0]
        diagnostics = json.loads(version["diagnostics_json"])
        self.assertIn("unmapped_current_period_concepts", diagnostics)
        self.assertNotIn("tifrs-notes:OperatingRevenue", [m["concept"] for m in diagnostics["mapping"].values()])

    def test_unknown_scope_is_not_assumed(self) -> None:
        stub = MopsStub({2014: synthetic_instance(fiscal_year=2014, entry_point="custom-entry.xsd")})
        run(self.service(stub).run("1785", 2014, 2014))
        self.assertEqual({row["statement_scope"] for row in list_historical_facts(self.repository, "1785", 2014, 2014)}, {"unknown"})

    def test_conflicting_duplicate_facts_are_not_selected(self) -> None:
        extra = '<ifrs:Inventories contextRef="AsOf20141231" decimals="-3" unitRef="TWD">123000</ifrs:Inventories>'
        stub = MopsStub({2014: synthetic_instance(fiscal_year=2014, extra_facts=extra)})
        result = run(self.service(stub).run("1785", 2014, 2014))
        self.assertIn("inventory", result.years[0].core_fields_missing)
        self.assertTrue(any("conflicting duplicate" in w for w in result.years[0].warnings))

    def test_inline_xbrl_scale_and_sign(self) -> None:
        stub = MopsStub({2019: synthetic_inline(fiscal_year=2019)})
        run(self.service(stub).run("1785", 2019, 2019))
        facts = {row["metric_code"]: row["value"] for row in list_historical_facts(self.repository, "1785", 2019, 2019)}
        self.assertEqual(facts["inventory"], 1_234_000.0)
        self.assertEqual(facts["net_income"], -250_000.0)
        self.assertEqual(facts["revenue"], 10_000_000.0)

    def test_pdf_is_archived_with_extraction_pending(self) -> None:
        docs = self.root / "pdf"
        docs.mkdir()
        (docs / "ar.pdf").write_bytes(b"%PDF-1.4\n% synthetic\n")
        manifest = write_manifest(docs, [{"period": "2012FY", "source_kind": "official_pdf", "local_path": "ar.pdf",
                                          "source_url": "https://doc.twse.com.tw/server-java/t57sb01"}])
        result = run(self.service().run("1785", 2012, 2012, source_strategy="manifest", manifest_path=manifest))
        self.assertEqual(result.years[0].status, "pending_verification")
        self.assertEqual(result.years[0].validation_status, "extraction_pending")
        self.assertEqual(self.counts()["versioned_financial_facts"], 0)


class Case10SnapshotIsolationTests(HistoricalAuditTestCase):
    PRODUCTION_TABLES = ("financial_filings", "normalized_financial_facts", "latest_analysis_snapshots",
                         "analysis_snapshots", "analysis_runs", "calculated_metrics", "rule_results")

    def dump(self, path: str) -> dict[str, list]:
        connection = sqlite3.connect(path)
        try:
            return {table: connection.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                    for table in self.PRODUCTION_TABLES}
        finally:
            connection.close()

    def test_backfill_never_touches_snapshots_pipeline_or_ai(self) -> None:
        from app.services.analysis_repository import SqliteAnalysisRepository

        shared = str(self.root / "shared.sqlite3")
        SqliteAnalysisRepository(shared)
        connection = sqlite3.connect(shared)
        connection.execute("INSERT INTO latest_analysis_snapshots VALUES ('2330', 'run-x', '{\"ticker\":\"2330\"}', '2026-10-01T00:00:00+00:00')")
        connection.execute("INSERT INTO financial_filings VALUES ('2330','2024FY','台積電','晶圓代工',2024,4,'MOPS','https://x','available','{}','[]','2026-10-01')")
        connection.commit()
        connection.close()
        before = self.dump(shared)

        repository = HistoricalAuditRepository(shared, allow_shared_database=True)
        service = HistoricalBackfillService(repository=repository, archive=self.archive)
        guard = AssertionError("production path invoked")
        with patch("app.services.ingestion_pipeline.FinancialIngestionPipeline.refresh_company", side_effect=guard), \
             patch("app.services.analysis_repository.SqliteAnalysisRepository.save_pipeline_result", side_effect=guard), \
             patch("app.services.ai_financial_analysis_service.AIFinancialAnalysisService.analyze_report", side_effect=guard):
            result = run(service.run("1785", 2014, 2015, source_strategy="manifest", manifest_path=self.versioned_manifest()))
        self.assertTrue(all(year.status == "available" for year in result.years))
        self.assertEqual(self.dump(shared), before)

    def test_package_has_no_production_writer_imports(self) -> None:
        # Production writers/LLM/scheduler are forbidden everywhere (including lazy, indented imports).
        production = re.compile(
            r"ingestion_pipeline|analysis_repository|fact_repository|gemini|anthropic|llm|frontend_presenter|"
            r"ai_financial_analysis|refresh_company|save_pipeline_result|scheduler"
        )
        # Phase 1C: Google Cloud clients only in the isolated, opt-in cloud adapter modules (+ CLI wiring).
        cloud_modules = {"cloud_config.py", "cloud_sync.py", "firestore_repository.py", "object_storage.py",
                         "research_access.py", "historical_audit_case.py"}
        cloud = re.compile(r"firestore|google\.cloud|cloud_sync|cloud_config|object_storage|research_access")
        for path in [*PACKAGE_DIR.glob("*.py"), BACKEND_ROOT / "scripts" / "historical_audit_case.py"]:
            imports = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                       if line.strip().startswith(("import ", "from "))]
            for line in imports:
                self.assertIsNone(production.search(line), f"{path.name}: {line}")
                if path.name not in cloud_modules:
                    # The local ingestion / research / packaging path never touches cloud code.
                    self.assertIsNone(cloud.search(line), f"{path.name}: {line}")


class Case11ApiCompatibilityTests(unittest.TestCase):
    def test_existing_fact_endpoints_unchanged_and_no_historical_route(self) -> None:
        from fastapi.testclient import TestClient

        from app.dependencies import get_analysis_repository, get_company_master_repository, get_fact_repository, get_ingestion_run_repository
        from app.services.analysis_repository import SqliteAnalysisRepository

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            pipeline = str(Path(directory) / "pipeline.sqlite3")
            env = {"DATASTORE_BACKEND": "sqlite", "FINANCIAL_DATABASE_PATH": pipeline,
                   "FINANCIAL_FACT_DATABASE_PATH": str(Path(directory) / "facts.sqlite3"), "APP_ENV": "development"}
            with patch.dict(os.environ, env):
                for dependency in (get_analysis_repository, get_fact_repository, get_company_master_repository, get_ingestion_run_repository):
                    dependency.cache_clear()
                SqliteAnalysisRepository(pipeline).ingest_facts([FinancialFact(
                    ticker="2330", company_name="台積電", semiconductor_subindustry="晶圓代工", metric="revenue",
                    period="2024FY", value=1.0, unit="新台幣元", statement_type="income_statement",
                    source_kind="mops_xbrl", source_url="https://mopsov.twse.com.tw/x", statement_scope="consolidated")])
                from app.main import app

                client = TestClient(app, raise_server_exceptions=False)
                try:
                    def snapshot() -> tuple:
                        facts = client.get("/api/v1/financial/companies/2330/facts").json()
                        for fact in facts["facts"]:
                            fact.pop("retrieved_at", None)
                        return (facts, client.get("/api/v1/financial/companies").json())

                    before = snapshot()
                    # Apply the historical schema to the very same database (worst case).
                    HistoricalAuditRepository(pipeline, allow_shared_database=True)
                    after = snapshot()
                    self.assertEqual(before, after)
                    self.assertEqual(after[0]["count"], 1)
                    self.assertEqual(sorted(after[0]["facts"][0]), sorted(before[0]["facts"][0]))
                    self.assertNotIn("1785", [c["ticker"] for c in after[1]["companies"]])
                    self.assertEqual(client.get("/api/v1/financial/companies/1785/facts").json()["count"], 0)
                    paths = list(client.get("/openapi.json").json()["paths"])
                    self.assertFalse([p for p in paths if "historical-audit" in p or "historical_audit" in p])
                finally:
                    client.close()
                for dependency in (get_analysis_repository, get_fact_repository, get_company_master_repository, get_ingestion_run_repository):
                    dependency.cache_clear()


class Case12ExportContractTests(HistoricalAuditTestCase):
    def setUp(self) -> None:
        super().setUp()
        run(self.service().run("1785", 2014, 2015, source_strategy="manifest", manifest_path=self.versioned_manifest()))

    def test_csv_and_json_match_documented_schema_and_are_deterministic(self) -> None:
        fixed = datetime(2026, 10, 9, tzinfo=timezone.utc)
        csv_a, csv_b, json_path = self.root / "a.csv", self.root / "b.csv", self.root / "facts.json"
        count = export_historical_facts(self.repository, "1785", 2014, 2015, output_path=csv_a, include_test_fixtures=True)
        export_historical_facts(self.repository, "1785", 2014, 2015, output_path=csv_b, include_test_fixtures=True)
        self.assertEqual(csv_a.read_bytes(), csv_b.read_bytes())
        rows = list(csv.DictReader(io.StringIO(csv_a.read_text(encoding="utf-8"))))
        self.assertEqual(tuple(rows[0].keys()), EXPORT_FIELDS)
        self.assertEqual(len(rows), count)
        order = [(int(r["fiscal_year"]), r["period"], r["metric_code"]) for r in rows]
        self.assertEqual(order, sorted(order))
        self.assertTrue({"original", "restated"} <= {r["filing_version_type"] for r in rows})
        self.assertEqual({r["market"] for r in rows}, {"TPEX"})

        export_historical_facts(self.repository, "1785", 2014, 2015, output_path=json_path, output_format="json",
                                include_test_fixtures=True, generated_at=fixed)
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["contract"], "fintrust.historical_financial_facts")
        self.assertEqual(payload["contract_version"], CONTRACT_VERSION)
        self.assertEqual(tuple(payload["fields"]), EXPORT_FIELDS)
        self.assertTrue(all(tuple(record) == EXPORT_FIELDS for record in payload["records"]))
        self.assertEqual(payload["record_count"], count)
        self.assertTrue(all("core_fields_missing" in item for item in payload["coverage"]))

    def test_strict_as_of_and_fixture_exclusion(self) -> None:
        self.assertEqual(build_export_records(self.repository, "1785", 2014, 2015), [])  # fixtures excluded by default
        records = build_export_records(self.repository, "1785", 2014, 2015, as_of="2015-12-31",
                                       version_policy="latest_available", include_test_fixtures=True)
        self.assertEqual({r["period"] for r in records}, {"2014FY"})
        self.assertTrue(all(r["point_in_time_eligible"] for r in records))
        self.assertEqual({r["filing_version_type"] for r in records}, {"original"})


class Case13MigrationTests(unittest.TestCase):
    def test_migration_is_repeatable_and_legacy_safe(self) -> None:
        from app.services.analysis_repository import SqliteAnalysisRepository
        from app.services.fact_repository import SqliteFinancialFactRepository

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            legacy = str(Path(directory) / "legacy.sqlite3")
            analysis = SqliteAnalysisRepository(legacy)
            SqliteFinancialFactRepository(legacy)
            fact = FinancialFact(ticker="2454", company_name="聯發科", semiconductor_subindustry="IC 設計",
                                 metric="revenue", period="2024FY", value=2.0, unit="新台幣元",
                                 statement_type="income_statement", source_kind="mops_xbrl",
                                 source_url="https://mopsov.twse.com.tw/y", statement_scope="consolidated")
            analysis.ingest_facts([fact])

            def legacy_state() -> tuple:
                connection = sqlite3.connect(legacy)
                try:
                    from app.services.historical_audit.evidence_store import EVIDENCE_TABLES

                    added = ("financial_filing_versions", "versioned_financial_facts",
                             "filing_version_annotations", "sqlite_sequence", *EVIDENCE_TABLES)
                    schema = connection.execute(
                        "SELECT name, sql FROM sqlite_master WHERE tbl_name NOT LIKE 'historical_%' "
                        f"AND tbl_name NOT IN ({','.join('?' * len(added))}) ORDER BY name", added
                    ).fetchall()
                    rows = connection.execute("SELECT * FROM normalized_financial_facts").fetchall()
                    return schema, rows
                finally:
                    connection.close()

            before = legacy_state()
            for _ in range(3):
                repository = HistoricalAuditRepository(legacy, allow_shared_database=True)
            self.assertEqual(repository.schema_version(), "1")
            self.assertEqual(legacy_state(), before)
            self.assertEqual(analysis.get_fact("2454", "revenue", "2024FY").value, 2.0)
            self.assertEqual(len(analysis.list_facts("2454")), 1)

    def test_production_database_paths_are_refused(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            production = str(Path(directory) / "pipeline.sqlite3")
            with patch.dict(os.environ, {"FINANCIAL_DATABASE_PATH": production}):
                with self.assertRaises(ProductionDatabaseRefusedError):
                    HistoricalAuditRepository(production)
                with self.assertRaises(ProductionDatabaseRefusedError):
                    HistoricalAuditRepository.for_planning(production)
            self.assertFalse(Path(production).exists())


class Case14ProductionSafetyTests(HistoricalAuditTestCase):
    def test_no_firestore_client_and_no_secret_leakage(self) -> None:
        secret = "sk-historical-audit-SECRET-0123456789"
        env = {"DATASTORE_BACKEND": "firestore", "GOOGLE_CLOUD_PROJECT": "prod-project",
               "GEMINI_API_KEY": secret, "ANTHROPIC_API_KEY": secret, "FINANCIAL_INGESTION_TOKEN": secret}
        stub = MopsStub({2014: synthetic_instance(fiscal_year=2014)})
        with patch.dict(os.environ, env), \
             patch("google.cloud.firestore.Client", side_effect=AssertionError("Firestore must not be used")):
            run(self.service(stub).run("1785", 2014, 2014))
            export_historical_facts(self.repository, "1785", 2014, 2014, output_path=self.root / "out.json", output_format="json")
        for request in stub.requests:
            self.assertNotIn("authorization", {name.lower() for name in request.headers})
            self.assertNotIn("cookie", {name.lower() for name in request.headers})
            self.assertNotIn(secret, str(request.url))
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes(), str(path))

    def test_only_allowlisted_official_https_sources(self) -> None:
        ensure_official_url("https://mopsov.twse.com.tw/server-java/FileDownLoad?x=1")
        for url in ("http://mopsov.twse.com.tw/x", "https://example.com/x", "https://mopsov.twse.com.tw.evil.io/x"):
            with self.assertRaises(SourceNotAllowedError):
                ensure_official_url(url)

        def redirect(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://evil.example.com/file.xml"})

        fetcher = OfficialSourceFetcher(transport=httpx.MockTransport(redirect), sleep=_no_sleep, min_interval_seconds=0)
        with self.assertRaises(SourceNotAllowedError):
            run(fetcher.fetch("https://mopsov.twse.com.tw/server-java/FileDownLoad?year=2014", expect=("xbrl_instance",)))

    def test_manifest_cannot_fabricate_verification(self) -> None:
        docs = self.root / "m"
        docs.mkdir()
        for document in (
            {"period": "2014FY", "source_kind": "mops_xbrl_instance", "source_url": "https://example.com/a.xml"},
            {"period": "2014FY", "source_kind": "test_fixture", "local_path": "a.xml", "filing_version_type": "original"},
            {"period": "2014FY", "source_kind": "test_fixture", "local_path": "a.xml", "available_at": "2015-03-31T00:00:00+08:00"},
        ):
            with self.assertRaises(ValueError):
                load_manifest(write_manifest(docs, [document]))


if __name__ == "__main__":
    unittest.main()
