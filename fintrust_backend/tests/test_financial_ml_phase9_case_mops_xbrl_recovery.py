"""Phase9 official MOPS 13 issuer-year plan; 12 bounded XBRL source candidates."""
from __future__ import annotations

import asyncio
import csv
import json
import tempfile
import unittest
from pathlib import Path

from app.services.historical_audit.sources import FetchResult
from research.financial_ml import phase9_case_mops_xbrl_recovery as m
from research.financial_ml.phase6_official_evidence_recovery import ROOT_SEED
from research.financial_ml.phase1_case_registry import validate
from research.financial_ml.phase8_original_filing_intake import OUTPUT_COLUMNS,QUEUE_COLUMNS


class FakeFetcher:
    def __init__(self,*,success=False):
        self.calls=[]
        self.success=success

    async def fetch(self,url,*,expect):
        self.calls.append(url)
        if self.success:
            return FetchResult(
                status="ok",url=url,final_url=url,
                content=b"<?xml version='1.0' encoding='utf-8'?><xbrl></xbrl>",
                detected_format="xbrl_instance",
            )
        return FetchResult(status="filing_not_found",url=url,final_url=url,
                           content=None,detected_format=None)


def fake_parser(content,ticker,year):
    return {
        "status":"validated","statement_scope":"consolidated",
        "filing_version_type":"unknown_revision",
        "accounting_framework":"TIFRS","validation_status":"validated",
        "facts":[],"warnings":["TEST_FIXTURE_NOT_ORIGINAL_FILING"]
    }


class Phase9CaseMopsAcquisitionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.phase7=self.root/"phase7_official_case_asof_recovery"
        self.phase8=self.root/"phase8_case_original_filing_recovery"
        self.phase7.mkdir()
        self.phase8.mkdir()
        self.seed=validate(json.loads(ROOT_SEED.read_text(encoding="utf-8")))
        wants=set()
        demand=[]
        for case in self.seed:
            for target in case["affected_fiscal_years"]:
                for year in range(target-2,target+1):
                    wants.add((case["ticker"],year))
                    demand.append({
                        "ticker":case["ticker"],"case_id":case["case_id"],
                        "affected_fiscal_year":target,"historical_input_year":year,
                        "historical_role":"TARGET" if year==target else "PRIOR_YEAR",
                        "required_source":"ORIGINAL_MOPS_FILING_AS_FIRST_PUBLISHED",
                        "original_publication_time":"","original_filing_version_sha256":"",
                        "filing_status":"UNKNOWN_ORIGINAL_VERSION_NEEDS_RECOVERY",
                        "case_outcome_status":"POTENTIAL_CASE_PERIOD_REVIEW_PENDING",
                        "label_approved":"false","heldout_1785_excluded":"true",
                        "review_note":""
                    })
        with (self.phase7/"phase7_original_filing_asof_gap_queue.csv").open(
                "w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=QUEUE_COLUMNS)
            w.writeheader();w.writerows(demand)
        docs=[]
        for ticker,year in sorted(wants):
            docs.append({
                "ticker":ticker,"fiscal_year":year,"target_year_demands":"",
                "accounting_regime":"PRE_TIFRS_GAAP_NEEDS_HISTORICAL_MAPPING"
                    if year==2012 else "TIFRS_CANDIDATE_SCOPE_NEEDS_REVIEW",
                "local_original_candidate_status":"NO_USER_SUPPLIED_ORIGINAL_VERSION",
                "local_source_sha256":"","bytes_archived":0,
                "claimed_mops_original_publication_at":"","original_notice_sha256":"",
                "original_filing_document_id":"","archived_raw_report_path":"",
                "prior_official_archives":0,"official_archives_sha_verified":0,
                "publication_time_independently_verified":"false",
                "original_version_independently_verified":"false",
                "safe_for_historical_features":"false",
                "supervised_label":"UNKNOWN",
                "outcome_known_at_verified":"false",
                "training_admitted":"false",
                "reason":"NO_OFFICIAL_HISTORICAL_ARCHIVE"
            })
        with (self.phase8/"original_case_filing_source_intake.csv").open(
                "w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=OUTPUT_COLUMNS)
            w.writeheader();w.writerows(docs)

    def test_13_true_unique_needs_split_into_12_ifrs_and_one_legacy(self):
        planned,old=m.plan(self.phase7,self.phase8)
        self.assertEqual(len(planned),12)
        self.assertEqual(len(old),1)
        self.assertEqual((old[0]["ticker"],old[0]["fiscal_year"]),("8299",2012))
        self.assertTrue(all(int(x["fiscal_year"])>=2013 for x in planned))
        self.assertEqual(len({(r["ticker"],r["fiscal_year"]) for r in planned}),12)
        self.assertTrue(all(r["source_url"].startswith("https://mopsov.twse.com.tw/") for r in planned))
        self.assertTrue(all(r["training_admitted"] is False for r in planned))

    def test_no_network_dry_run_writes_honest_waiting_report(self):
        report=asyncio.run(m.run(self.root,execute=False))
        self.assertEqual(report["network_requests"],0)
        self.assertEqual(report["required_company_years"],13)
        self.assertEqual(report["xbrl_archived_with_sha_verified"],0)
        self.assertEqual(report["pre_restated_original_filing_versions_approved"],0)
        with (self.root/"phase9_case_mops_xbrl_candidates"/
              "phase9_case_mops_version_review.csv").open(
                encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual({r["financial_statement_misstatement_label"] for r in rows},{"UNKNOWN"})
        self.assertEqual({r["approved_for_historical_model_training"] for r in rows},{"false"})

    def test_empty_official_response_is_not_inferred_normal(self):
        fetcher=FakeFetcher()
        report=asyncio.run(m.run(self.root,execute=True,fetcher=fetcher,
                                 processor=fake_parser))
        self.assertEqual(len(fetcher.calls),12)
        self.assertEqual(report["xbrl_archived_with_sha_verified"],0)
        self.assertEqual(report["source_acquisition_counts"]["filing_not_found"],12)
        self.assertEqual(report["approved_supervised_model_rows"],0)

    def test_12_sha_archives_reused_when_identical_replay(self):
        fetcher=FakeFetcher(success=True)
        initial=asyncio.run(m.run(self.root,execute=True,fetcher=fetcher,
                                  processor=fake_parser))
        self.assertEqual(initial["xbrl_archived_with_sha_verified"],12)
        self.assertEqual(initial["xbrl_parsed_validated"],12)
        self.assertEqual(initial["pre_restated_original_filing_versions_approved"],0)
        self.assertEqual(initial["network_requests"],12)
        fetcher.calls.clear()
        later=asyncio.run(m.run(self.root,execute=True,fetcher=fetcher,
                                processor=fake_parser))
        self.assertEqual(len(fetcher.calls),0)
        self.assertEqual(later["network_requests"],0)
        self.assertEqual(later["xbrl_archived_with_sha_verified"],12)

    def test_archive_manifest_corruption_cannot_count_as_verified(self):
        fetcher=FakeFetcher(success=True)
        asyncio.run(m.run(self.root,execute=True,fetcher=fetcher,
                          processor=fake_parser))
        folder=self.root/"phase9_case_mops_xbrl_candidates"
        manifest=folder/"acquisition_results.json"
        j=json.loads(manifest.read_text(encoding="utf-8"))
        first=next(iter(j["outcomes"].values()))
        first["content_hash"]="0"*64
        manifest.write_text(json.dumps(j),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"sha256_mismatch"):
            m.validate_manifest(manifest,m.plan(self.phase7,self.phase8)[0])

    def test_holdout_year_forgery_is_rejected(self):
        path=self.phase7/"phase7_original_filing_asof_gap_queue.csv"
        with path.open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        rows[0]["ticker"]="1785"
        with path.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=QUEUE_COLUMNS)
            w.writeheader();w.writerows(rows)
        with self.assertRaisesRegex(ValueError,"heldout_or_unknown"):
            m.plan(self.phase7,self.phase8)

    def test_phase8_false_approved_original_is_rejected(self):
        path=self.phase8/"original_case_filing_source_intake.csv"
        with path.open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        rows[0]["original_version_independently_verified"]="true"
        with path.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=OUTPUT_COLUMNS)
            w.writeheader();w.writerows(rows)
        with self.assertRaisesRegex(ValueError,"admission_not_permitted"):
            m.plan(self.phase7,self.phase8)

    def test_phase8_missing_company_year_blocks_download(self):
        path=self.phase8/"original_case_filing_source_intake.csv"
        with path.open(encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        with path.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=OUTPUT_COLUMNS)
            w.writeheader();w.writerows(rows[1:])
        with self.assertRaisesRegex(ValueError,"coverage_mismatch"):
            m.plan(self.phase7,self.phase8)

    def test_official_sources_cannot_promote_unverified_labels_in_manifest(self):
        fetcher=FakeFetcher(success=True)
        asyncio.run(m.run(self.root,execute=True,fetcher=fetcher,processor=fake_parser))
        folder=self.root/"phase9_case_mops_xbrl_candidates"
        manifest=folder/"acquisition_results.json"
        j=json.loads(manifest.read_text(encoding="utf-8"))
        first=next(iter(j["outcomes"].values()))
        first["normal_label_status"]="reviewed_normal"
        manifest.write_text(json.dumps(j),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"false_training_or_normal"):
            m.validate_manifest(manifest,m.plan(self.phase7,self.phase8)[0])

    def test_2012_pre_tifrs_source_is_not_xbrl_silently(self):
        planned,old=m.plan(self.phase7,self.phase8)
        self.assertTrue(all(x["fiscal_year"]>=2013 for x in planned))
        self.assertIn("pre-TIFRS",old[0]["reason"])
        report=asyncio.run(m.run(self.root,execute=False))
        self.assertEqual(report["legacy_gaap_years_not_automatically_fetched"],1)
        self.assertFalse(report["approved_supervised_model_rows"])


if __name__=="__main__":
    unittest.main()
