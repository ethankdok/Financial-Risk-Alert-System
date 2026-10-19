"""Phase11 hermetic regression: exact quarter allegations, no fake positive labels.

Tests use synthetic period and source fixtures, not real issuer evidence.
"""
from __future__ import annotations
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.historical_audit.sources import FetchResult
from research.financial_ml import phase11_case_quarterly_gap_analysis as m
from research.financial_ml.phase6_official_evidence_recovery import ROOT_SEED
from research.financial_ml.literature_dataset import FEATURES


class MockFetcher:
    def __init__(self,status="filing_not_found",content=None):
        self.calls=[]
        self.status=status
        self.content=content
    async def fetch(self,url,*,expect):
        self.calls.append((url,tuple(expect)))
        return FetchResult(status=self.status,url=url,final_url=url,
                           content=self.content,detected_format="xbrl_instance" if self.content else None)


class Phase11QuarterAndFeatureGapTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.phase10=self.root/"phase10_case_official_paper_audit"
        detail=self.phase10/"official_case_literature"
        detail.mkdir(parents=True)
        self.seed=json.loads(ROOT_SEED.read_text(encoding="utf-8"))
        # The values mirror the user-observed FY2013-20 current MOPS result.
        coverage=dict(zip(FEATURES,(11,11,11,11,11,11,5,4,1,11,11,8,10,10,7)))
        self.count=coverage
        self.report={
            "actual_paper_feature_years":11,
            "official_paper_variable_coverage":coverage,
            "missing_literature_feature_cells":62,
            "missing_official_years":[
                {"ticker":"6452","fiscal_year":2020,"status":"filing_not_found"},
                {"ticker":"8299","fiscal_year":2012,"status":"LEGACY_ORIGINAL_PDF_REQUIRES_SEPARATE_SOURCE"}],
            "final_holdout_1785_excluded":True,"verified_positive_labels":0,
            "historical_asof_training_rows_admitted":0
        }
        self.write_fixture()

    def write_fixture(self):
        (self.phase10/"phase10_integrated_report.json").write_text(
            json.dumps(self.report,ensure_ascii=False),encoding="utf-8")
        with (self.phase10/"official_case_literature"/
              "literature_missing_reasons.jsonl").open("w",encoding="utf-8") as f:
            for year in range(2013,2024):
                miss=[]
                for feat in FEATURES:
                    if year-2013 >= self.count[feat]:
                        miss.append({"variable":feat,"status":"not_computable",
                                     "reasons":[{"code":"missing_official_account_or_prior_year"}]})
                f.write(json.dumps({
                    "ticker":"TEST","fiscal_year":year,
                    "stage":"missing_components","details":miss
                },ensure_ascii=False)+"\n")

    def test_quarterly_2017q2_through_2020q1_precise_and_unknown(self):
        rows=m.case_reporting_periods(self.seed)
        kang=[x for x in rows if x["ticker"]=="6452"]
        self.assertEqual(len(rows),15)
        self.assertEqual(len(kang),12)
        self.assertEqual(kang[0]["reporting_period"],"2017Q2")
        self.assertEqual(kang[-1]["reporting_period"],"2020Q1")
        self.assertNotIn("2020FY",{r["reporting_period"] for r in kang})
        self.assertEqual({r["verified_misstatement_label"] for r in rows},{"UNKNOWN"})
        self.assertNotIn("1785",{r["ticker"] for r in rows})

    def test_requires_official_seed_2020q1_scope_evidence(self):
        clone=json.loads(json.dumps(self.seed))
        c=next(x for x in clone["candidates"] if x["ticker"]=="6452")
        c["affected_reporting_period_description"]="2017-2020 annual only"
        # Registry validator may reject its invalid claims before Phase11 checks.
        with self.assertRaises((ValueError,AssertionError,KeyError)):
            m.case_reporting_periods(clone)

    def test_archived_year_missing_reasons_exactly_32_not_62(self):
        gaps=m.yearly_missing_reasons(self.phase10)
        self.assertEqual(sum(r["case_years_missing"] for r in gaps),32)
        self.assertEqual(gaps[0]["feature"],"d_rsst_acc")
        self.assertEqual(gaps[0]["case_years_missing"],10)
        self.assertEqual(gaps[1]["case_years_missing"],7)
        self.assertEqual({r["missing_is_not_financial_zero"] for r in gaps},{"true"})
        self.assertEqual(gaps[0]["observed_missing_reason_instances"],10)

    def test_mismatch_between_report_and_source_detail_fails_closed(self):
        p=self.phase10/"official_case_literature"/"literature_missing_reasons.jsonl"
        lines=p.read_text(encoding="utf-8").splitlines()
        p.write_text("\n".join(lines[:-1])+"\n",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"not_reproducible"):
            m.yearly_missing_reasons(self.phase10)

    def test_one_official_quarter_request_is_only_6452_2020q1(self):
        f=MockFetcher()
        state=asyncio.run(m.acquire_6452_2020q1(
            self.root/"quarter",execute=True,fetcher=f))
        self.assertEqual(len(f.calls),1)
        self.assertIn("co_id=6452",f.calls[0][0])
        self.assertIn("year=2020",f.calls[0][0])
        self.assertIn("season=1",f.calls[0][0])
        self.assertEqual(state["acquisition_status"],"filing_not_found")
        self.assertEqual(state["misstatement_label"],"UNKNOWN")
        self.assertFalse(state["quarterly_data_used_as_fy2020_annual"])

    def test_quarter_raw_sha_cached_and_no_annual_recomputation(self):
        raw=b'<?xml version="1.0" encoding="utf-8"?><xbrl xmlns="http://www.xbrl.org/2003/instance"></xbrl>'
        f=MockFetcher(status="ok",content=raw)
        fake={
            "document_format":"xbrl_instance","reported_scope":"consolidated",
            "scope_evidence":"TEST_ONLY","quarter_end_contexts":1,
            "contexts_total":1,"numeric_facts_total":5,"source_schema_refs":1,
            "q1_2020_context_proven":True,"original_filing_vintage_verified":False,
            "historical_publication_time_verified":False,
            "annual_literature_score_calculated":False
        }
        with patch.object(m,"_parsed_quarter_metadata",return_value=fake):
            a=asyncio.run(m.acquire_6452_2020q1(self.root/"quarter",execute=True,fetcher=f))
        b=asyncio.run(m.acquire_6452_2020q1(self.root/"quarter",execute=True,fetcher=f))
        self.assertEqual(len(f.calls),1)
        self.assertEqual(a["raw_sha256"],b["raw_sha256"])
        self.assertTrue(b["cached_reused"])
        self.assertEqual(b["network_requests_this_run"],0)
        self.assertFalse(b["document_diagnostics"]["annual_literature_score_calculated"])

    def test_forged_quarterly_archive_checksum_rejected(self):
        raw=b'<?xml version="1.0" encoding="utf-8"?><xbrl xmlns="http://www.xbrl.org/2003/instance"></xbrl>'
        f=MockFetcher(status="ok",content=raw)
        with patch.object(m,"_parsed_quarter_metadata",return_value={
            "q1_2020_context_proven":False,"reported_scope":"unknown"}):
            a=asyncio.run(m.acquire_6452_2020q1(self.root/"quarter",execute=True,fetcher=f))
        archive=self.root/"quarter"/"raw"/a["raw_path"]
        archive.write_bytes(b"bad")
        with self.assertRaises((ValueError,RuntimeError)):
            asyncio.run(m.acquire_6452_2020q1(self.root/"quarter",execute=True,fetcher=f))

    def test_complete_offline_integrated_report_tells_62_32_30_gap_story(self):
        result=asyncio.run(m.run(self.root,execute=False))
        self.assertEqual(result["phase10_total_15_feature_cells_missing"],62)
        self.assertEqual(result["phase10_missing_from_11_parsed_xbrl_years"],32)
        self.assertEqual(result["phase10_missing_from_two_unavailable_annual_source_years"],30)
        self.assertEqual(result["6452_alleged_quarterly_periods"],12)
        self.assertTrue(result["6452_2020Q1_not_FY2020_annual"])
        self.assertEqual(result["network_requests"],0)
        self.assertEqual(result["confirmed_positive_labels"],0)
        self.assertEqual(result["audited_negative_labels"],0)
        self.assertTrue(result["holdout_1785_excluded"])


if __name__=="__main__":
    unittest.main()
