"""Bounded 360 official archive data-readiness; synthetic fixtures only."""
import asyncio
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from research.financial_ml import fy2013_2015_official_archive_reconcile as target
from research.financial_ml.fy2013_2015_stage1_freeze import FIELDS,YEARS
from research.financial_ml.round10_disclosure_event_label_gate import cohort
from research.financial_ml.annual_panel_readiness import METRICS
from app.services.historical_audit.archive import RawEvidenceArchive

class TestActualOfficialArchivalBatch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.csv=self.root/"fy_stage1.csv"
        self.out=self.root/"official"
        self.source=[]
        for i,ticker in enumerate(cohort()):
            for year in YEARS:
                row={x:"" for x in FIELDS}
                row.update(ticker=ticker,fiscal_year=str(year),
                           research_window="FY2013_FY2014_FY2015_ONLY",
                           approved_for_supervision="false",
                           numeric_source_tier="FINMIND_PROVISIONAL_NOT_ORIGINAL",
                           candidate_complete_12="false" if i%4 else "true")
                for j,metric in enumerate(METRICS):
                    row[metric]=str(1000+i+j) if i%4==0 else ""
                self.source.append(row)
        with self.csv.open("w",newline="",encoding="utf-8-sig") as f:
            wr=csv.DictWriter(f,fieldnames=FIELDS)
            wr.writeheader();wr.writerows(self.source)

    def test_360_three_year_batches_and_missing_prioritized(self):
        chunks=target.batches(self.csv)
        self.assertEqual(len(chunks),30)
        self.assertEqual(sum(len(x) for x in chunks),360)
        self.assertTrue(all(len(x)<=12 for x in chunks))
        self.assertNotIn("1785",{v["ticker"] for chunk in chunks for v in chunk})
        self.assertEqual({v["fiscal_year"] for chunk in chunks for v in chunk},
                         set(YEARS))
        self.assertEqual(chunks[0][0]["ticker"],cohort()[1])

    def test_offline_plan_generates_real_360x12_reconciliation_without_fake_originals(self):
        report=asyncio.run(target.run(self.csv,self.out,execute=False))
        self.assertEqual(report["target_company_years"],360)
        self.assertEqual(report["current_archive_validated_company_years"],0)
        self.assertEqual(report["approved_supervised_labels_0"],0)
        self.assertEqual(report["approved_supervised_labels_1"],0)
        self.assertTrue(report["financial_features_not_ready_for_original_training"])
        with (self.out/"fy1315_4320_metric_reconciliation.csv").open(
            encoding="utf-8-sig",newline="") as f:
            results=list(csv.DictReader(f))
        self.assertEqual(len(results),4320)
        self.assertEqual({int(x["fiscal_year"]) for x in results},set(YEARS))

    def test_archived_2026_retrieval_not_proven_2014_original(self):
        chunks=target.batches(self.csv)
        selected=chunks[0][0]
        ticker=selected["ticker"];year=selected["fiscal_year"]
        key=f"{ticker}:{year}"
        batchdir=self.out/"batch_001"
        archive=RawEvidenceArchive(batchdir/"raw")
        xml=b"<xbrl>This is a hermetic mock of a validated report</xbrl>"
        entry=archive.store(ticker=ticker,period=f"{year}FY",
                            content=xml,detected_format="xbrl_instance",
                            retrieval={"source_url":selected["source_url"]})
        result={"ticker":ticker,"fiscal_year":year,
                "status":"validated","statement_scope":"consolidated",
                "filing_version_type":"original",
                "source_url":selected["source_url"],
                "training_admitted":False,"normal_label_status":"UNREVIEWED",
                "content_hash":entry.content_hash,
                "archive_path":entry.relative_path,
                "facts":[{"metric_code":"revenue","value":"123.4","unit":"TWD"},
                         {"metric_code":"net_income","value":"45","unit":"TWD"}]}
        batchdir.mkdir(exist_ok=True,parents=True)
        (batchdir/"acquisition_results.json").write_text(
            json.dumps({"outcomes":{key:result}}),encoding="utf-8")
        index,comparison,status=target.summarize_archived_outcomes(self.csv,self.out)
        row=next(r for r in index if (r["ticker"],r["fiscal_year"])==(ticker,year))
        self.assertEqual(row["mops_12_metric_coverage"],2)
        self.assertEqual(row["current_archive_sha256"],entry.content_hash)
        self.assertEqual(row["current_archive_is_original_first_filing"],"false")
        self.assertEqual(row["source_eligible_for_0_1_training"],"false")
        record=next(r for r in comparison if r["ticker"]==ticker
                    and r["fiscal_year"]==year and r["metric"]=="revenue")
        self.assertEqual(record["result_status"],"CANDIDATE_MISSING_CURRENT_FOUND")

    def test_tampered_archived_bytes_are_rejected(self):
        chunks=target.batches(self.csv);item=chunks[0][0]
        ticker=item["ticker"];year=item["fiscal_year"]
        batchdir=self.out/"batch_001"
        archive=RawEvidenceArchive(batchdir/"raw")
        entry=archive.store(ticker=ticker,period=f"{year}FY",
                            content=b"<xml>ok</xml>",detected_format="xbrl_instance",
                            retrieval={})
        filename=batchdir/"raw"/entry.relative_path
        filename.write_bytes(b"bad tamper")
        batchdir.mkdir(exist_ok=True,parents=True)
        (batchdir/"acquisition_results.json").write_text(
            json.dumps({"outcomes":{f"{ticker}:{year}":{
                "ticker":ticker,"fiscal_year":year,"status":"validated",
                "source_url":item["source_url"],
                "training_admitted":False,"normal_label_status":"UNREVIEWED",
                "archive_path":entry.relative_path,
                "content_hash":entry.content_hash,"facts":[]}}}),encoding="utf-8")
        with self.assertRaisesRegex((ValueError,RuntimeError),"SHA-256|sha256|tamper"):
            target.summarize_archived_outcomes(self.csv,self.out)

    def test_reject_future_fiscal_year_2016_in_stage1(self):
        self.source[0]["fiscal_year"]="2016"
        with self.csv.open("w",newline="",encoding="utf-8-sig") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS);w.writeheader();w.writerows(self.source)
        with self.assertRaisesRegex(ValueError,"wrong_year|broken_three_year|duplicate"):
            target.batches(self.csv)

if __name__=="__main__":
    unittest.main()
