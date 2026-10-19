"""Phase12 hermetic official Taiwanese 6452 quarterly source-panel tests."""
from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.sources import FetchResult
from research.financial_ml import phase12_kangyou_quarterly_panel as m


def fake_xbrl(period, *, wrong_period=False):
    year, quarter, start, end=m.quarter_parts(period)
    if wrong_period:
        end=m.quarter_parts("2020Q1")[3]
        start=m.quarter_parts("2020Q1")[2]
    jan=f"{end.year}-01-01"
    prior=f"{end.year-1}-06-30"
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink"
 xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
 xmlns:ifrs="http://example.com/ifrs">
 <link:schemaRef xlink:type="simple"
   xlink:href="https://mopsov.twse.com.tw/tifrs-ci-cr-2019-03-31.xsd"/>
 <xbrli:context id="currentI"><xbrli:entity><xbrli:identifier
 scheme="http://www.twse.com.tw">6452</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:instant>{end.isoformat()}</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:context id="currentQ"><xbrli:entity><xbrli:identifier
 scheme="http://www.twse.com.tw">6452</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>{start.isoformat()}</xbrli:startDate>
 <xbrli:endDate>{end.isoformat()}</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="currentY"><xbrli:entity><xbrli:identifier
 scheme="http://www.twse.com.tw">6452</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:startDate>{jan}</xbrli:startDate>
 <xbrli:endDate>{end.isoformat()}</xbrli:endDate></xbrli:period></xbrli:context>
 <xbrli:context id="previous"><xbrli:entity><xbrli:identifier
 scheme="http://www.twse.com.tw">6452</xbrli:identifier></xbrli:entity>
 <xbrli:period><xbrli:instant>{prior}</xbrli:instant></xbrli:period></xbrli:context>
 <xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
 <ifrs:Assets contextRef="currentI" unitRef="TWD" decimals="0">1000</ifrs:Assets>
 <ifrs:Revenue contextRef="currentQ" unitRef="TWD" decimals="0">40</ifrs:Revenue>
 <ifrs:Revenue contextRef="currentY" unitRef="TWD" decimals="0">50</ifrs:Revenue>
 <ifrs:Assets contextRef="previous" unitRef="TWD" decimals="0">10</ifrs:Assets>
 </xbrli:xbrl>'''.encode("utf-8")


class FakeFetcher:
    def __init__(self, *, missing=frozenset(), wrong=frozenset()):
        self.calls=[]
        self.missing=missing
        self.wrong=wrong
    async def fetch(self,url,*,expect):
        year=re.search(r"year=(\d{4})",url).group(1)
        quarter=re.search(r"season=([1-4])",url).group(1)
        period=f"{year}Q{quarter}"
        self.calls.append(period)
        if period in self.missing:
            return FetchResult(status="filing_not_found",url=url,final_url=url)
        return FetchResult(
            status="ok",url=url,final_url=url,
            content=fake_xbrl(period,wrong_period=period in self.wrong),
            detected_format="xbrl_instance",
        )


class Phase12QuarterlySourcePanelTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data=Path(temp.name)
        self.old=self.data/"phase11_case_quarterly_and_paper_gaps"
        folder=self.old/"official_quarterly_source"
        folder.mkdir(parents=True)
        archive=RawEvidenceArchive(folder/"raw")
        raw=fake_xbrl("2020Q1")
        stored=archive.store(
            ticker="6452",period="2020Q1",content=raw,
            detected_format="xbrl_instance",retrieval={"source_url":m.source_url("2020Q1")})
        self.prior={
            "ticker":"6452","reporting_period":"2020Q1",
            "source_url":m.source_url("2020Q1"),
            "acquisition_status":"QUARTERLY_XBRL_CONTEXT_FOUND_VINTAGE_UNKNOWN",
            "raw_path":stored.relative_path,
            "raw_sha256":stored.content_hash,
            "verified_historical_original":False,
            "misstatement_label":"UNKNOWN",
        }
        (self.old/"phase11_integrated_report.json").write_text(json.dumps({
            "holdout_1785_excluded":True,
            "confirmed_positive_labels":0,"supervised_early_warning_samples":0,
            "quarterly_source_status":self.prior,
        }),encoding="utf-8")
        self.out=self.data/"phase12_kangyou_quarterly_panel"

    def run_stage(self,*,execute=True,fetcher=None):
        return asyncio.run(m.acquire(
            self.data,self.out,execute=execute,fetcher=fetcher))

    def test_frozen_12_quarters_bounded_11_new_queries(self):
        seed=json.loads(m.ROOT_SEED.read_text(encoding="utf-8"))
        planned,new=m.freeze_plan(seed)
        self.assertEqual(len(planned),12)
        self.assertEqual(len(new),11)
        self.assertEqual(planned[0]["period"],"2017Q2")
        self.assertEqual(planned[-1]["period"],"2020Q1")
        self.assertEqual({x["ticker"] for x in planned},{"6452"})
        self.assertTrue(all(x["source_url"].startswith("https://mopsov.twse.com.tw")
                            for x in planned))
        self.assertTrue(all("1785" not in x["source_url"] for x in planned))

    def test_three_numeric_period_grains_cannot_be_merged(self):
        meta=m.analyze_document(fake_xbrl("2017Q2"),"2017Q2")
        self.assertEqual(meta["statement_scope"],"consolidated")
        self.assertEqual(meta["numeric_current_period_facts"],3)
        self.assertEqual(meta["numeric_instant_facts"],1)
        self.assertEqual(meta["numeric_quarter_duration_facts"],1)
        self.assertEqual(meta["numeric_ytd_duration_facts"],1)
        self.assertFalse(meta["annual_beneish_dechow_computed"])

    def test_twelve_periods_officially_acquired_with_phase11_cache(self):
        fetcher=FakeFetcher()
        res=self.run_stage(fetcher=fetcher)
        self.assertEqual(res["new_network_requests"],11)
        self.assertEqual(len(fetcher.calls),11)
        self.assertNotIn("2020Q1",fetcher.calls)
        self.assertEqual(res["official_quarters_context_scope_validated"],12)
        self.assertEqual(res["unavailable_or_quarantined_quarters"],[])
        self.assertTrue(res["reused_verified_2020Q1_from_phase11"])
        self.assertEqual(res["historical_original_filing_vintages_verified"],0)
        self.assertEqual(res["confirmed_period_outcome_labels"],0)
        self.assertEqual(res["financial_misstatement_supervised_training_rows"],0)
        self.assertTrue(res["final_holdout_1785_excluded"])
        with (self.out/"quarterly_case_official_source_index.csv").open(
                encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),12)
        self.assertEqual({r["independently_verified_fraud_outcome"] for r in rows},{"UNKNOWN"})
        self.assertEqual({r["admitted_for_model_training"] for r in rows},{"false"})
        self.assertEqual({r["annual_beneish_dechow_computed"] for r in rows},{"false"})

    def test_replay_sha_cache_never_refetches_success(self):
        fetcher=FakeFetcher()
        a=self.run_stage(fetcher=fetcher)
        self.assertEqual(a["new_network_requests"],11)
        fetcher.calls.clear()
        b=self.run_stage(fetcher=fetcher)
        self.assertEqual(b["new_network_requests"],0)
        self.assertEqual(len(fetcher.calls),0)
        self.assertEqual(b["cached_reused_prior_phase12"],11)
        self.assertEqual(b["official_quarters_context_scope_validated"],12)

    def test_not_found_remains_unknown_and_no_zero(self):
        f=FakeFetcher(missing={"2017Q2","2019Q3"})
        r=self.run_stage(fetcher=f)
        self.assertEqual(r["official_quarters_context_scope_validated"],10)
        self.assertEqual(len(r["unavailable_or_quarantined_quarters"]),2)
        self.assertEqual(r["source_status_counts"]["filing_not_found"],2)
        self.assertEqual(r["confirmed_period_outcome_labels"],0)
        with (self.out/"quarterly_case_official_source_index.csv").open(
                encoding="utf-8",newline="") as file:
            rows=list(csv.DictReader(file))
        self.assertEqual({x["independently_verified_fraud_outcome"] for x in rows},{"UNKNOWN"})
        self.assertEqual({x["historical_first_publication_verified"] for x in rows},{"false"})

    def test_wrong_period_xbrl_is_quarantined_even_on_official_host(self):
        f=FakeFetcher(wrong={"2017Q2"})
        r=self.run_stage(fetcher=f)
        self.assertEqual(r["official_quarters_context_scope_validated"],11)
        self.assertIn({"period":"2017Q2","status":"QUARTER_CONTEXT_OR_SCOPE_QUARANTINED"},
                      r["unavailable_or_quarantined_quarters"])

    def test_tampered_phase11_source_fails_before_network(self):
        raw=self.old/"official_quarterly_source"/"raw"/self.prior["raw_path"]
        raw.write_bytes(b"tampered")
        fetcher=FakeFetcher()
        with self.assertRaises((ValueError,RuntimeError)):
            self.run_stage(fetcher=fetcher)
        self.assertEqual(len(fetcher.calls),0)

    def test_tampered_phase12_cache_fails_without_overwrite(self):
        self.run_stage(fetcher=FakeFetcher())
        manifest=json.loads((self.out/"quarterly_acquisition_results.json").read_text(encoding="utf-8"))
        old=manifest["outcomes"]["2018Q1"]
        file=self.out/"raw"/old["raw_path"]
        file.write_bytes(b"fake-mops-safety-attack")
        f=FakeFetcher()
        with self.assertRaises((ValueError,RuntimeError)):
            self.run_stage(fetcher=f)
        self.assertEqual(len(f.calls),0)
        self.assertEqual(file.read_bytes(),b"fake-mops-safety-attack")

    def test_forged_approved_fraud_label_blocks_replay(self):
        self.run_stage(fetcher=FakeFetcher())
        p=self.out/"quarterly_acquisition_results.json"
        obj=json.loads(p.read_text(encoding="utf-8"))
        obj["outcomes"]["2017Q2"]["outcome_label"]="1"
        p.write_text(json.dumps(obj),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"identity_or_label_conflict"):
            self.run_stage(fetcher=FakeFetcher())

    def test_prior_phase11_claiming_fraud_label_blocks_recovery(self):
        r=json.loads((self.old/"phase11_integrated_report.json").read_text(encoding="utf-8"))
        r["confirmed_positive_labels"]=12
        (self.old/"phase11_integrated_report.json").write_text(json.dumps(r),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"prior_fraud_label_or_holdout_gate"):
            self.run_stage(fetcher=FakeFetcher())

    def test_dry_run_reuses_existing_q1_without_new_download(self):
        f=FakeFetcher()
        out=self.run_stage(execute=False,fetcher=f)
        self.assertEqual(out["new_network_requests"],0)
        self.assertEqual(out["official_quarters_context_scope_validated"],1)
        self.assertEqual(len(out["unavailable_or_quarantined_quarters"]),11)
        self.assertEqual(len(f.calls),0)


if __name__=="__main__":
    unittest.main()
