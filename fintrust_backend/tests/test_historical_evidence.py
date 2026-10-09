"""Phase 1B acceptance matrix EVID-01 … EVID-14 on SYNTHETIC evidence fixtures.

Fixture success proves parser / linkage / point-in-time behaviour. Real-source
results are covered separately by tests/test_historical_evidence_real.py.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.backfill import HistoricalBackfillService
from app.services.historical_audit.evidence_export import (
    COMPARISON_FIELDS,
    COVERAGE_FIELDS,
    INVENTORY_FIELDS,
    SUMMARY_FIELDS,
    TIMELINE_FIELDS,
    coverage_matrix,
    export_evidence_dataset,
    list_publication_timeline,
    list_restatement_comparisons,
    list_summary_observations,
    source_inventory,
)
from app.services.historical_audit.evidence_import import (
    EvidencePlanError,
    HistoricalEvidenceService,
    availability_instant,
    load_plan,
)
from app.services.historical_audit.evidence_parsers import parse_restatement_comparison
from app.services.historical_audit.export import EXPORT_FIELDS, build_export_records
from app.services.historical_audit.reader import list_historical_facts
from app.services.historical_audit.repository import HistoricalAuditRepository
from app.services.historical_audit.sources import OfficialSourceFetcher, SourceNotAllowedError
from tests.historical_audit_fixtures import synthetic_instance, write_manifest
from tests.historical_evidence_fixtures import (
    COMPARISON_EXPLANATION,
    EBOOK_URL,
    MOPS_DETAIL_URL,
    ebook_listing,
    ebook_step9_page,
    fake_open_workbook,
    fake_xls,
    mops_detail,
    mops_listing,
    synthetic_pdf,
    tpex_announcement,
)


async def _no_sleep(_: float) -> None:
    return None


TPEX_B = "https://www.tpex.org.tw/storage/eb_data/10511/10502013431.htm"
MOPS_LIST = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01?step=1&co_id=1785&year=105"
EBOOK_LIST_102 = "https://doc.twse.com.tw/server-java/t57sb01?step=1&co_id=1785&year=102&mtype=A"
EBOOK_LIST_103 = "https://doc.twse.com.tw/server-java/t57sb01?step=1&co_id=1785&year=103&mtype=A"
SUMMARY_2012 = "https://www.tpex.org.tw/storage/statistic/financial/O_2012Q4.xls"
SUMMARY_2013 = "https://www.tpex.org.tw/storage/statistic/financial/O_2013Q4.xls"
BOTH = ["consolidated", "individual"]


def detail_source(day, time, seq, event_type, periods, quote, *, comparison=False, affects=None):
    source = {
        "source_key": f"mops-material-detail-{day}-{time}-{seq}",
        "category": "official_restatement_comparison" if comparison else "official_publication_notice",
        "issuer": "MOPS (company disclosure)", "document_type": "detail", "parser": "mops_material_detail",
        "request": {"method": "POST", "url": MOPS_DETAIL_URL,
                    "data": {"co_id": "1785", "spoke_date": day, "spoke_time": time, "seq_no": seq, "step": "2"}},
        "events": [{"event_key": f"mops:{day}:{time}:{seq}", "event_type": event_type, "affected_periods": periods,
                    "affected_scopes": BOTH if not comparison else ["consolidated"], "quote": quote}],
    }
    if affects:
        source["events"][0]["affects_version_types"] = affects
    if comparison:
        source["comparison_scope"] = "consolidated"
    return source


def ebook_source(year, name):
    return {"source_key": f"twse-ebook-{name[:-4]}", "category": "official_filing_pdf", "issuer": "TWSE (e-document archive)",
            "document_type": "pdf", "parser": "twse_ebook_pdf", "listing_source_key": f"twse-ebook-listing-{year}",
            "request": {"method": "TWSE_EBOOK", "url": EBOOK_URL,
                        "data": {"step": "9", "kind": "A", "co_id": "1785", "filename": name}}}


PLAN = {
    "plan_version": 1, "ticker": "1785",
    "sources": [
        {"source_key": "tpex-announcement-10502013431", "category": "official_publication_notice", "issuer": "TPEx",
         "document_type": "notice", "parser": "tpex_announcement", "request": {"method": "GET", "url": TPEX_B},
         "events": [{"event_key": "restated_annual_reports_filed_20161114", "event_type": "restated_annual_reports_filed",
                     "event_date": "2016-11-14", "affected_periods": ["2013FY", "2014FY"], "affected_scopes": BOTH,
                     "affects_version_types": ["restated"], "quote": "業於105年11月14日公告並申報重編之年度財務報告"},
                    {"event_key": "missing_quote", "event_type": "regulatory_claim", "quote": "這段文字不存在於公告中"}]},
        {"source_key": "mops-material-listing-105", "category": "official_document_index", "issuer": "MOPS (company disclosure)",
         "document_type": "listing", "parser": "mops_material_listing", "request": {"method": "GET", "url": MOPS_LIST}},
        detail_source("20161113", "212622", "3", "restatement_disclosure", ["2013FY", "2014FY"],
                      "更正且重編之財務報告年季:100年至104年各期合併財報", comparison=True, affects=["restated"]),
        detail_source("20161205", "174316", "2", "financial_report_correction", ["2013FY", "2014FY"],
                      "予以更(補)正其內容", affects=["restated"]),
        {"source_key": "twse-ebook-listing-102", "category": "official_document_index", "issuer": "TWSE (e-document archive)",
         "document_type": "listing", "parser": "twse_ebook_listing", "request": {"method": "GET", "url": EBOOK_LIST_102}},
        {"source_key": "twse-ebook-listing-103", "category": "official_document_index", "issuer": "TWSE (e-document archive)",
         "document_type": "listing", "parser": "twse_ebook_listing", "request": {"method": "GET", "url": EBOOK_LIST_103}},
        ebook_source(102, "201304_1785_AI1.pdf"),
        ebook_source(102, "201304_1785_AI4.pdf"),
        ebook_source(103, "201404_1785_AI1.pdf"),
        {"source_key": "tpex-quarterly-summary-O_2012Q4", "category": "official_historical_summary", "issuer": "TPEx",
         "document_type": "summary", "parser": "tpex_quarterly_summary_xls", "request": {"method": "GET", "url": SUMMARY_2012}},
        {"source_key": "tpex-quarterly-summary-O_2013Q4", "category": "official_historical_summary", "issuer": "TPEx",
         "document_type": "summary", "parser": "tpex_quarterly_summary_xls", "request": {"method": "GET", "url": SUMMARY_2013}},
    ],
}

PDF_SIZES = {"201304_1785_AI1.pdf": 5000, "201304_1785_AI4.pdf": 6000, "201404_1785_AI1.pdf": 7000}
SUMMARY_ROW_2013 = ["1785", "光洋科", 1000000.0, 980000.0, 2.0, 190000.0, 150000.0, -5000.0, 3000.0, 40000.0, 35000.0, 14.0,
                    400000.0, 0.97, 0.9, 22.7, 0.47, 1.85]
SUMMARY_ROW_2012 = ["1785", "光洋科", 900000.0, 850000.0, 5.0, 150000.0, 140000.0, 3000.0, 2000.0, 35000.0, 30000.0, 16.0,
                    400000.0, 0.9, 0.8, 23.5, 0.46, 2.76]


class OfficialStub:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.served_pdf_sizes = dict(PDF_SIZES, **{"201404_1785_AI1.pdf": 6999})  # one size mismatch

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if request.method == "POST" and url == MOPS_DETAIL_URL:
            form = parse_qs(request.content.decode())
            day, time = form["spoke_date"][0], form["spoke_time"][0]
            if time == "212622":
                body = mops_detail(day, time, "3", "本公司重編100年至104年各期合併財務報告說明", COMPARISON_EXPLANATION)
            else:
                body = mops_detail(day, time, "2", "公告更正本公司各年度財報",
                                   "5.發生緣由:因財務報告內容有誤植之情事，予以更(補)正其內容。")
            return httpx.Response(200, content=body)
        if request.method == "POST" and url == EBOOK_URL:
            name = parse_qs(request.content.decode())["filename"][0]
            return httpx.Response(200, content=ebook_step9_page(f"/pdf/{name[:-4]}_tmp.pdf"))
        if url.startswith("https://doc.twse.com.tw/pdf/"):
            name = url.rsplit("/", 1)[1].replace("_tmp", "")
            return httpx.Response(200, content=synthetic_pdf(self.served_pdf_sizes[name]))
        pages = {
            TPEX_B: tpex_announcement("10502013431", "105年11月15日", "光洋科公司業於105年11月14日公告並申報重編之年度財務報告。"),
            MOPS_LIST: mops_listing([("20161113", "212622", "3", "本公司重編100年至104年各期合併財務報告說明"),
                                     ("20161205", "174316", "2", "公告更正本公司各年度財報")]),
            EBOOK_LIST_102: ebook_listing([
                {"year": "102 年 第四季", "detail": "IFRSs合併財報", "remark": "此檔案為重編前之財報", "filename": "201304_1785_AI1.pdf",
                 "size": 5000, "uploaded": "105/08/25 16:17:04", "correction": "無"},
                {"year": "102 年 第四季", "detail": "IFRSs合併財報(重編)", "remark": "此檔案為重編後之財報", "filename": "201304_1785_AI4.pdf",
                 "size": 6000, "uploaded": "105/11/14 16:47:57", "correction": ""}]),
            EBOOK_LIST_103: ebook_listing([
                {"year": "103 年 第四季", "detail": "IFRSs合併財報", "remark": "此檔案為重編前之財報", "filename": "201404_1785_AI1.pdf",
                 "size": 7000, "uploaded": "105/08/25 16:18:27", "correction": "無"}]),
            SUMMARY_2012: fake_xls(2012, [SUMMARY_ROW_2012]),
            SUMMARY_2013: fake_xls(2013, [SUMMARY_ROW_2013]),
        }
        if url in pages:
            return httpx.Response(200, content=pages[url], headers={"last-modified": "Mon, 25 Jul 2016 03:10:49 GMT"})
        return httpx.Response(404)


RESTATED_TEXT = "如重編後財務報表附註十二所述"


class EvidenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.repository = HistoricalAuditRepository(str(self.root / "evidence.sqlite3"))
        self.archive = RawEvidenceArchive(self.root / "raw")
        self.stub = OfficialStub()
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(PLAN, ensure_ascii=False), encoding="utf-8")
        self._xlrd = patch("xlrd.open_workbook", side_effect=fake_open_workbook)
        self._xlrd.start()
        self._ingest_restated_xbrl()

    def tearDown(self) -> None:
        self._xlrd.stop()
        self._tmp.cleanup()

    def _ingest_restated_xbrl(self) -> None:
        docs = self.root / "xbrl"
        docs.mkdir()
        (docs / "2013.xml").write_bytes(synthetic_instance(
            fiscal_year=2013, audit_date="2016-11-11", emphasis_text=RESTATED_TEXT,
            extra_facts='<tifrs-ar:EmphasizeCertainImportantItem contextRef="AsOf20161111">Y</tifrs-ar:EmphasizeCertainImportantItem>',
            overrides={"total_assets": 990_000_000, "equity": 550_000_000, "total_liabilities": 440_000_000,
                       "cost_of_goods_sold": 810_000_000, "gross_profit": 190_000_000, "net_income": 30_000_000}))
        manifest = write_manifest(docs, [{"period": "2013FY", "source_kind": "mops_xbrl_instance", "local_path": "2013.xml",
                                          "source_url": "https://mopsov.twse.com.tw/server-java/FileDownLoad?year=2013"}])
        service = HistoricalBackfillService(repository=self.repository, archive=self.archive)
        asyncio.run(service.run("1785", 2013, 2013, source_strategy="manifest", manifest_path=manifest))

    def service(self) -> HistoricalEvidenceService:
        fetcher = OfficialSourceFetcher(transport=httpx.MockTransport(self.stub), sleep=_no_sleep,
                                        min_interval_seconds=0, backoff_seconds=0)
        return HistoricalEvidenceService(repository=self.repository, archive=self.archive, fetcher=fetcher)

    def run_all(self):
        plan = load_plan("1785", self.plan_path)
        service = self.service()
        outcomes = asyncio.run(service.acquire(plan))
        return outcomes, service.import_evidence(plan)

    def table(self, name: str) -> list[dict]:
        with self.repository.connect() as connection:
            return [dict(row) for row in connection.execute(f"SELECT * FROM {name}").fetchall()]


class Evid01To02InventoryTests(EvidenceTestCase):
    def test_evid01_inventory_is_reproducible(self) -> None:
        outcomes, report = self.run_all()
        self.assertTrue(all(o.status == "acquired" for o in outcomes), outcomes)
        first = source_inventory(self.repository, "1785")
        HistoricalEvidenceService(repository=self.repository, archive=self.archive).import_evidence(load_plan("1785", self.plan_path))
        self.assertEqual(source_inventory(self.repository, "1785"), first)
        categories = {row["source_key"]: row["source_category"] for row in first}
        self.assertEqual(categories["twse-ebook-201304_1785_AI1"], "official_original_filing")
        self.assertEqual(categories["twse-ebook-201304_1785_AI4"], "official_restated_filing")
        self.assertEqual(categories["tpex-quarterly-summary-O_2013Q4"], "official_historical_summary")
        self.assertEqual(categories["mops-material-detail-20161113-212622-3"], "official_restatement_comparison")
        self.assertEqual(categories["mops-t164sb01-2013FY"], "official_restated_filing")
        row = next(r for r in first if r["source_key"] == "twse-ebook-201304_1785_AI1")
        self.assertTrue(row["contains_full_statements"])
        self.assertEqual(row["content_hash"], hashlib.sha256(synthetic_pdf(5000)).hexdigest())

    def test_evid02_quote_and_source_status_are_accurate(self) -> None:
        _, report = self.run_all()
        self.assertIn("tpex-announcement-10502013431: quote not found for missing_quote", report.errors)
        statuses = {e["event_key"]: e["verification_status"] for e in self.table("historical_publication_events")}
        self.assertEqual(statuses["missing_quote"], "quote_not_found")
        self.assertEqual(statuses["restated_annual_reports_filed_20161114"], "verified_official_quote")
        # A 404 official source is reported, not silently treated as "no filing".
        plan = load_plan("1785", self.plan_path)
        plan["sources"].append({"source_key": "missing", "category": "official_publication_notice", "issuer": "TPEx",
                                "document_type": "x", "parser": "tpex_announcement",
                                "request": {"method": "GET", "url": "https://www.tpex.org.tw/storage/eb_data/none.htm"}})
        outcomes = asyncio.run(self.service().acquire(plan, only={"missing"}))
        self.assertEqual(outcomes[0].status, "source_unavailable")


class Evid03To05EvidenceTypeTests(EvidenceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_all()

    def test_evid03_gaap_and_ifrs_remain_distinct(self) -> None:
        rows = list_summary_observations(self.repository, "1785")
        fy2012 = {(r["report_period"], r["accounting_framework"], r["value"]) for r in rows
                  if r["fiscal_year"] == 2012 and r["source_metric_code"] == "tpex_operating_revenue"}
        self.assertEqual(fy2012, {("2012FY", "TW_GAAP", "900000"), ("2013FY", "TIFRS", "980000")})
        frameworks = {(c["fiscal_year"], c["accounting_framework"]) for c in list_restatement_comparisons(self.repository, "1785")}
        self.assertEqual(frameworks, {(2013, "TIFRS"), (2014, "TIFRS")})

    def test_evid04_summaries_are_not_filings(self) -> None:
        versions = self.repository.list_filing_versions("1785")
        self.assertFalse([v for v in versions if "summary" in (v["source_url"] or "")])
        self.assertEqual({v["source_kind"] for v in versions}, {"mops_xbrl_instance", "official_pdf"})
        facts = list_historical_facts(self.repository, "1785", 2010, 2016)
        self.assertEqual({f["source_kind"] for f in facts}, {"mops_xbrl_instance"})
        summary = list_summary_observations(self.repository, "1785")
        self.assertTrue(all(r["evidence_type"] == "official_historical_summary" and r["completeness"] == "summary_values_only"
                            for r in summary))
        net_income = next(r for r in summary if r["source_metric_code"] == "tpex_net_income_after_tax")
        self.assertIsNone(net_income["canonical_metric"])
        self.assertEqual(net_income["mapping_status"], "requires_review")

    def test_evid05_comparisons_keep_before_after_provenance(self) -> None:
        rows = {(r["fiscal_year"], r["canonical_metric"]): r for r in list_restatement_comparisons(self.repository, "1785")}
        net_2014 = rows[(2014, "net_income")]
        self.assertEqual((net_2014["pre_restatement_value"], net_2014["post_restatement_value"], net_2014["difference"]),
                         ("45000", "-5000", "-50000"))
        cogs = rows[(2013, "cost_of_goods_sold")]
        self.assertEqual((cogs["pre_restatement_value"], cogs["sign_factor"]), ("-800000", -1))
        self.assertEqual(net_2014["disclosed_at"], "2016-11-13T13:26:22+00:00")  # = 21:26:22 Asia/Taipei
        self.assertTrue(net_2014["source_url"].startswith("https://mopsov.twse.com.tw/"))
        self.assertIn("as previously reported", net_2014["pre_value_semantics"])
        self.assertEqual(len(net_2014["content_hash"]), 64)


class Evid06To08PointInTimeTests(EvidenceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_all()

    def links(self) -> dict[tuple[str, str], str]:
        with self.repository.connect() as connection:
            return {(row["event_key"], row["source_kind"]): row["link_status"] for row in connection.execute(
                """SELECT e.event_key, v.source_kind, l.link_status FROM publication_evidence_links l
                JOIN historical_publication_events e USING (event_id)
                JOIN financial_filing_versions v ON v.filing_version_id = l.target_id""")}

    def test_evid06_publication_evidence_is_linked_conservatively(self) -> None:
        links = self.links()
        self.assertEqual(links[("restated_annual_reports_filed_20161114", "mops_xbrl_instance")], "period_level_only")
        self.assertEqual(links[("mops:20161205:174316:2", "mops_xbrl_instance")], "unverified_linkage")
        self.assertEqual(links[("ebook:201304_1785_AI1.pdf", "official_pdf")], "verified_linkage")
        self.assertEqual(links[("ebook:201304_1785_AI4.pdf", "official_pdf")], "period_level_only")
        versions = {json.loads(v["diagnostics_json"]).get("ebook_listing", {}).get("filename"): v
                    for v in self.repository.list_filing_versions("1785")}
        original = versions["201304_1785_AI1.pdf"]
        self.assertEqual((original["filing_version_type"], original["availability_status"], original["available_at"]),
                         ("original", "verified", "2016-08-25T08:17:04+00:00"))
        restated = versions["201304_1785_AI4.pdf"]
        self.assertEqual((restated["filing_version_type"], restated["availability_status"]), ("restated", "unverified"))
        mismatch = versions["201404_1785_AI1.pdf"]
        self.assertEqual(mismatch["availability_status"], "unverified")
        self.assertIn("MISMATCH", mismatch["verification_evidence_json"])
        xbrl = versions[None]
        self.assertIsNone(xbrl["available_at"])  # never set from a period-level announcement

    def test_evid06_conflicting_evidence(self) -> None:
        with self.repository.connect() as connection:
            connection.execute("UPDATE financial_filing_versions SET document_dated_at = '2016-12-01' WHERE source_kind = 'mops_xbrl_instance'")
            connection.execute("DELETE FROM publication_evidence_links")
        HistoricalEvidenceService(repository=self.repository, archive=self.archive).import_evidence(load_plan("1785", self.plan_path))
        self.assertEqual(self.links()[("restated_annual_reports_filed_20161114", "mops_xbrl_instance")], "conflicting_evidence")

    def test_evid07_unverified_dates_remain_ineligible(self) -> None:
        facts = {f["metric_code"]: f for f in list_historical_facts(self.repository, "1785", 2013, 2013)}
        self.assertTrue(facts["total_assets"]["point_in_time_eligible"])
        self.assertEqual(facts["total_assets"]["availability_scope"], "observation")
        self.assertFalse(facts["inventory"]["point_in_time_eligible"])  # not disclosed in any verified notice
        self.assertIsNone(facts["inventory"]["effective_available_at"])
        self.assertEqual(list_summary_observations(self.repository, "1785", as_of="2030-01-01")
                         and {r["source_metric_code"] for r in list_summary_observations(self.repository, "1785", as_of="2030-01-01")},
                         {"tpex_operating_revenue"})

    def test_evid08_strict_pit_prevents_restatement_leakage(self) -> None:
        before = list_historical_facts(self.repository, "1785", 2013, 2014, as_of="2016-11-13T21:26:21+08:00")
        self.assertEqual(before, [])
        self.assertEqual(list_restatement_comparisons(self.repository, "1785", as_of="2016-11-13T21:26:21+08:00"), [])
        at = list_historical_facts(self.repository, "1785", 2013, 2014, as_of="2016-11-13T21:26:22+08:00")
        self.assertEqual({f["metric_code"] for f in at},
                         {"total_assets", "equity", "revenue", "cost_of_goods_sold", "net_income"})
        self.assertEqual(len(list_restatement_comparisons(self.repository, "1785", as_of="2016-11-13T21:26:22+08:00")), 10)
        # Date-only TPEx announcement: public from the next Taipei day.
        self.assertEqual(availability_instant("2016-11-15", "date").isoformat(), "2016-11-16T00:00:00+08:00")
        timeline = {e["event_key"]: e for e in list_publication_timeline(self.repository, "1785")}
        self.assertEqual(timeline["restated_annual_reports_filed_20161114"]["available_from"], "2016-11-16T00:00:00+08:00")

    def test_parser_rejects_misaligned_rows(self) -> None:
        with self.assertRaises(ValueError):
            parse_restatement_comparison("重編前-合併資產負債簡表： 單位:仟元\n 102.12.31 103.12.31\n資產總計 1,000\n")


class Evid09To11IdempotencyAndExportTests(EvidenceTestCase):
    def test_evid09_reruns_are_idempotent_and_reuse_archive(self) -> None:
        self.run_all()
        counts = self.repository.table_counts()
        requests = len(self.stub.requests)
        outcomes, report = self.run_all()
        self.assertEqual(len(self.stub.requests), requests)  # archived copies reused; no new downloads
        self.assertTrue(all(o.reused for o in outcomes))
        self.assertEqual(self.repository.table_counts(), counts)
        self.assertEqual(sum(v for k, v in report.counts.items()), 0)

    def test_evid10_existing_versions_and_raw_evidence_unchanged(self) -> None:
        before_versions = self.repository.list_filing_versions("1785")
        before_facts = self.table("versioned_financial_facts")
        raw = {v["raw_storage_path"]: hashlib.sha256((self.archive.root / v["raw_storage_path"]).read_bytes()).hexdigest()
               for v in before_versions}
        self.run_all()
        after = {v["filing_version_id"]: v for v in self.repository.list_filing_versions("1785")}
        for version in before_versions:
            self.assertEqual(after[version["filing_version_id"]], version)
        self.assertEqual(self.table("versioned_financial_facts"), before_facts)
        for path, digest in raw.items():
            self.assertEqual(hashlib.sha256((self.archive.root / path).read_bytes()).hexdigest(), digest)

    def test_evid11_exports_support_new_evidence_types(self) -> None:
        self.run_all()
        for dataset, fields in (("summary_observations", SUMMARY_FIELDS), ("restatement_comparisons", COMPARISON_FIELDS),
                                ("publication_timeline", TIMELINE_FIELDS), ("source_inventory", INVENTORY_FIELDS),
                                ("coverage_matrix", COVERAGE_FIELDS)):
            path = self.root / f"{dataset}.csv"
            count = export_evidence_dataset(self.repository, "1785", dataset, output_path=path, start_year=2013, end_year=2014)
            header = next(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
            self.assertEqual(tuple(header), fields)
            self.assertGreater(count, 0, dataset)
            json_path = self.root / f"{dataset}.json"
            export_evidence_dataset(self.repository, "1785", dataset, output_path=json_path, output_format="json",
                                    start_year=2013, end_year=2014)
            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["record_count"], count)
        records = build_export_records(self.repository, "1785", 2013, 2014)
        self.assertEqual(tuple(records[0]), EXPORT_FIELDS)
        self.assertEqual(EXPORT_FIELDS[-5:], ("evidence_type", "accounting_framework", "completeness",
                                              "availability_scope", "effective_available_at"))
        self.assertEqual({r["accounting_framework"] for r in records}, {"TIFRS"})
        matrix = {row["fiscal_year"]: row for row in coverage_matrix(self.repository, "1785", 2013, 2014)}
        self.assertIn("pdf", matrix[2013]["original_evidence"])
        self.assertTrue(matrix[2013]["pit_ready"].startswith("partial: 5 filing facts"))
        with self.assertRaises(ValueError):
            export_evidence_dataset(self.repository, "1785", "publication_timeline", output_path=self.root / "x.csv", as_of="2016-12-31")


class Evid14SafetyTests(EvidenceTestCase):
    def test_evid14_no_production_writes_or_secret_leakage(self) -> None:
        secret = "sk-phase1b-SECRET-987654321"
        with patch.dict(os.environ, {"DATASTORE_BACKEND": "firestore", "GEMINI_API_KEY": secret, "ANTHROPIC_API_KEY": secret}), \
             patch("google.cloud.firestore.Client", side_effect=AssertionError("Firestore must not be used")):
            self.run_all()
            export_evidence_dataset(self.repository, "1785", "source_inventory", output_path=self.root / "inv.json", output_format="json")
        for request in self.stub.requests:
            self.assertFalse({"authorization", "cookie"} & {name.lower() for name in request.headers})
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes(), str(path))

    def test_plan_rejects_unofficial_sources(self) -> None:
        bad = dict(PLAN, sources=[dict(PLAN["sources"][0], request={"method": "GET", "url": "https://news.example.com/1785"})])
        path = self.root / "bad.json"
        path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(SourceNotAllowedError):
            load_plan("1785", path)
        duplicate = dict(PLAN, sources=[PLAN["sources"][0], PLAN["sources"][0]])
        path.write_text(json.dumps(duplicate, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(EvidencePlanError):
            load_plan("1785", path)


if __name__ == "__main__":
    unittest.main()
