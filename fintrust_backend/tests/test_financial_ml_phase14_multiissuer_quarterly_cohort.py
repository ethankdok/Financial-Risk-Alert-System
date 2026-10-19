"""Phase14: hermetic multi-issuer Taiwan quarter source acquisition safety tests.

Uses synthetic issuer and financial source XML solely as isolated test data,
never used as real labels, financial research data or heldout 1785 evidence.
"""
from __future__ import annotations

import asyncio
import csv
import json
import re
import tempfile
import unittest
from pathlib import Path

from app.services.historical_audit.sources import FetchResult
from research.financial_ml import phase14_multiissuer_quarterly_cohort as m
from research.financial_ml.finmind_cross_industry_pilot import FIELDS


def quarter_xml(ticker,period,*,wrong_ticker=False, conflicting=False):
    yy=int(period[:4]);q=int(period[-1])
    quarter_ends=(31,30,30,31)
    end=f"{yy}-{q*3:02d}-{quarter_ends[q-1]:02d}"
    start=f"{yy}-{(q-1)*3+1:02d}-01"
    issuer="9999" if wrong_ticker else ticker
    extra=('<ifrs:Assets contextRef="i" unitRef="twd" decimals="0">999</ifrs:Assets>'
           if conflicting else "")
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
 xmlns:link="http://www.xbrl.org/2003/linkbase"
 xmlns:xlink="http://www.w3.org/1999/xlink"
 xmlns:ifrs="http://example.com/ifrs-full">
<link:schemaRef xlink:type="simple"
 xlink:href="https://mopsov.twse.com.tw/tifrs-ci-cr-2019-03-31.xsd"/>
<xbrli:context id="i"><xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">{issuer}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>{end}</xbrli:instant></xbrli:period></xbrli:context>
<xbrli:context id="d"><xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">{issuer}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="y"><xbrli:entity><xbrli:identifier scheme="http://www.twse.com.tw">{issuer}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>{yy}-01-01</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:unit id="twd"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
<ifrs:Assets contextRef="i" unitRef="twd" decimals="0">100</ifrs:Assets>
{extra}
<ifrs:Revenue contextRef="d" unitRef="twd" decimals="0">40</ifrs:Revenue>
<ifrs:Revenue contextRef="y" unitRef="twd" decimals="0">{q*40}</ifrs:Revenue>
</xbrli:xbrl>'''.encode("utf-8")


class FakeFetcher:
    def __init__(self,*,unavailable=frozenset(),wrong_entity=frozenset(),
                 conflicts=frozenset()):
        self.calls=[]
        self.unavailable=unavailable
        self.wrong_entity=wrong_entity
        self.conflicts=conflicts
    async def fetch(self,url,*,expect):
        ticker=re.search(r"co_id=(\d{4})",url).group(1)
        year=re.search(r"year=(\d{4})",url).group(1)
        q=re.search(r"season=([1-4])",url).group(1)
        p=f"{year}Q{q}"
        self.calls.append((ticker,p))
        if (ticker,p) in self.unavailable:
            return FetchResult(status="filing_not_found",url=url,final_url=url,
                               content=None,detected_format=None)
        xml=quarter_xml(ticker,p,wrong_ticker=(ticker,p) in self.wrong_entity,
                        conflicting=(ticker,p) in self.conflicts)
        return FetchResult(status="ok",url=url,final_url=url,
                           content=xml,detected_format="xbrl_instance")


class Phase14MultiCompanyQuarterTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data=Path(temp.name)
        self.cohort=self.data/"finmind_scaled_cohort.csv"
        self.out=self.data/"phase14"
        self.make_cohort()

    def make_cohort(self):
        rows=[]
        for i in range(120):
            ticker=str(3000+i)
            industry=("半導體業" if i<30 else f"非半導體產業{(i-30)%15:02d}")
            fields={x:"" for x in FIELDS}
            fields.update(
                ticker=ticker,
                market="twse" if i%2 else "tpex",
                industry_category=industry,
                normal_label_status="UNREVIEWED",
                historical_eligibility="UNVERIFIED",
            )
            rows.append(fields)
        with self.cohort.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=FIELDS)
            w.writeheader();w.writerows(rows)

    def test_reproducible_12_issuers_10_industries_no_known_cases(self):
        selected=m.selection(self.cohort)
        self.assertEqual(len(selected),12)
        self.assertEqual(len({x["ticker"] for x in selected}),12)
        self.assertEqual(sum(x["industry_category"]=="半導體業" for x in selected),3)
        self.assertEqual(len({x["industry_category"] for x in selected}),10)
        self.assertTrue({x["ticker"] for x in selected}.isdisjoint(m.CASE_OR_HOLDOUT))
        self.assertEqual(selected,m.selection(self.cohort))

    def test_tsmc_method_anchor_preserved_when_in_frozen_cohort(self):
        with self.cohort.open(encoding="utf-8",newline="") as file:
            rows=list(csv.DictReader(file))
        rows[0]["ticker"]="2330"
        with self.cohort.open("w",encoding="utf-8",newline="") as file:
            w=csv.DictWriter(file,fieldnames=FIELDS)
            w.writeheader();w.writerows(rows)
        selected=m.selection(self.cohort)
        self.assertIn("2330",{row["ticker"] for row in selected})
        self.assertEqual(sum(row["industry_category"]=="半導體業"
                             for row in selected),3)
        self.assertEqual(len(selected),12)

    def test_public_source_allowlist_and_time_range_contract(self):
        for ticker in ("2330","1558"):
            for p in m.FROZEN_PERIODS:
                uri=m.url_for(ticker,p)
                self.assertIn(f"co_id={ticker}",uri)
                self.assertIn(f"season={p[-1]}",uri)
        with self.assertRaisesRegex(ValueError,"issuer_not_allowed"):
            m.url_for("1785","2017Q2")
        with self.assertRaisesRegex(ValueError,"issuer_not_allowed"):
            m.url_for("6452","2019Q2")
        with self.assertRaisesRegex(ValueError,"period_outside_fixed_window"):
            m.url_for("2330","2016Q1")

    def test_no_network_preview_and_all_144_unknown_source_outcomes(self):
        f=FakeFetcher()
        r=asyncio.run(m.run(self.cohort,self.out,fetcher=f,execute=False))
        self.assertEqual(f.calls,[])
        self.assertEqual(r["official_quarter_jobs"],144)
        self.assertEqual(r["selected_issuers"],12)
        self.assertEqual(r["source_status_counts"],{"NOT_REQUESTED":144})
        self.assertEqual(r["supervised_ml_rows_admitted"],0)
        self.assertEqual(r["verified_true_negative_company_quarters"],0)
        self.assertTrue(r["final_holdout_1785_excluded"])
        with (self.out/"multiissuer_official_quarter_sources.csv").open(
                encoding="utf-8",newline="") as file:
            rows=list(csv.DictReader(file))
        self.assertEqual(len(rows),144)
        self.assertEqual({r["outcome_label"] for r in rows},{"UNKNOWN"})

    def test_mock_all_144_source_files_make_company_isolated_signals(self):
        f=FakeFetcher()
        one=asyncio.run(m.run(self.cohort,self.out,fetcher=f,execute=True))
        self.assertEqual(len(f.calls),144)
        self.assertEqual(one["official_quarters_context_and_primary_TWD_validated"],144)
        self.assertEqual(one["fully_sourced_12_quarter_comparison_issuers"],12)
        self.assertGreater(one["unreviewed_same_grain_changes"],0)
        self.assertEqual(one["supervised_ml_rows_admitted"],0)
        self.assertEqual(one["verified_true_negative_company_quarters"],0)
        self.assertEqual(one["verified_false_filing_positive_company_quarters"],0)
        with (self.out/"multiissuer_quarter_same_grain_changes.csv").open(
                encoding="utf-8",newline="") as src:
            rows=list(csv.DictReader(src))
        self.assertEqual(len({x["ticker"] for x in rows}),12)
        self.assertEqual({x["model_training_admitted"] for x in rows},{"false"})
        self.assertTrue(all(x["current_source_sha256"] and x["prior_source_sha256"]
                            for x in rows))
        self.assertTrue(all(x["period_grain"] in ("instant","quarter_duration","ytd_duration")
                            for x in rows))
        f.calls.clear()
        second=asyncio.run(m.run(self.cohort,self.out,fetcher=f,execute=True))
        self.assertEqual(f.calls,[])
        self.assertEqual(second["previous_SHA_archives_reused"],144)
        self.assertEqual(second["new_network_requests_this_run"],0)

    def test_missing_old_quarters_are_not_financial_zero_or_normal(self):
        selected=m.selection(self.cohort)
        missing={(selected[0]["ticker"],"2017Q2"),(selected[1]["ticker"],"2018Q1")}
        f=FakeFetcher(unavailable=missing)
        r=asyncio.run(m.run(self.cohort,self.out,fetcher=f,execute=True))
        self.assertEqual(r["source_status_counts"]["filing_not_found"],2)
        self.assertEqual(r["fully_sourced_12_quarter_comparison_issuers"],10)
        self.assertEqual(r["verified_true_negative_company_quarters"],0)
        self.assertEqual(r["official_quarters_context_and_primary_TWD_validated"],142)
        with (self.out/"multiissuer_official_quarter_sources.csv").open(
                encoding="utf-8",newline="") as file:
            source=list(csv.DictReader(file))
        self.assertTrue(all(x["outcome_label"]=="UNKNOWN" for x in source))
        self.assertTrue(all(x["normal_label_approved"]=="false" for x in source))
        self.assertEqual({x["accepted_concept_grain_observations"]
                          for x in source if x["source_status"]=="filing_not_found"},{"0"})

    def test_wrong_entity_is_preserved_quarantined_and_not_retried(self):
        selected=m.selection(self.cohort)
        key=(selected[0]["ticker"],"2017Q2")
        f=FakeFetcher(wrong_entity={key})
        report=asyncio.run(m.run(self.cohort,self.out,fetcher=f,execute=True))
        self.assertEqual(report["source_status_counts"]["QUARTER_PARSE_OR_IDENTITY_REJECTED"],1)
        self.assertEqual(report["official_quarters_context_and_primary_TWD_validated"],143)
        f.calls.clear()
        later=asyncio.run(m.run(self.cohort,self.out,fetcher=f,execute=True))
        self.assertEqual(f.calls,[])
        self.assertEqual(later["previous_SHA_archives_reused"],144)
        self.assertEqual(later["source_status_counts"]["QUARTER_PARSE_OR_IDENTITY_REJECTED"],1)

    def test_changed_cohort_after_freeze_fails_without_rewriting_manifest(self):
        m.plan(self.cohort,self.out)
        prev=(self.out/"frozen_phase14_plan.json").read_bytes()
        with self.cohort.open(encoding="utf-8",newline="") as file:
            rows=list(csv.DictReader(file))
        rows[0]["market"]="twse" if rows[0]["market"]=="tpex" else "tpex"
        with self.cohort.open("w",encoding="utf-8",newline="") as file:
            w=csv.DictWriter(file,fieldnames=FIELDS)
            w.writeheader();w.writerows(rows)
        with self.assertRaisesRegex(ValueError,"frozen_quarter_source_plan_changed"):
            m.plan(self.cohort,self.out)
        self.assertEqual(prev,(self.out/"frozen_phase14_plan.json").read_bytes())

    def test_forged_normal_label_rejected_before_new_web_request(self):
        f=FakeFetcher()
        asyncio.run(m.run(self.cohort,self.out,fetcher=f,execute=True))
        path=self.out/"quarterly_acquisition_results.json"
        j=json.loads(path.read_text(encoding="utf-8"))
        first=next(iter(j["outcomes"].values()))
        first["normal_label_approved"]=True
        path.write_text(json.dumps(j),encoding="utf-8")
        another=FakeFetcher()
        with self.assertRaisesRegex(ValueError,"forged_identity_or_labels"):
            asyncio.run(m.run(self.cohort,self.out,fetcher=another,execute=True))
        self.assertEqual(another.calls,[])


if __name__=="__main__":
    unittest.main()
