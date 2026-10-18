"""Hermetic Phase6 official-source retrieval and strict no-label case review tests."""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import phase6_official_evidence_recovery as r


class Phase6OfficialEvidenceRecoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.seed=r.ROOT_SEED
        self.cases=r.validate(json.loads(self.seed.read_text(encoding="utf-8")))
        self.case=next(c for c in self.cases if c["ticker"]=="3027")
        self.source=self.case["sources"][0]
        self.fake_count=0

    def mock_fetch(self,url):
        self.fake_count+=1
        case=next(c for c in self.cases if any(s["url"]==url for s in c["sources"]))
        name=case["company"]
        # Note: fixture data are NOT real court findings or actual labels.
        fixture=("<html><head><title>TEST FAKE SOURCE</title></head><body>"
                 f"<h1>{name}</h1><p>Official source fixture for offline testing.</p>"
                 +("For testing no positive outcome label can be admitted. "*16)
                 +"</body></html>").encode("utf-8")
        self.assertGreater(len(fixture),500)
        return fixture,url,"text/html; charset=utf-8"

    def test_offline_no_http_and_candidate_reviews_no_labels(self):
        def blocked(url):
            raise AssertionError("Network must not be invoked")
        result=r.run(self.seed,self.root/"offline",retrieve=False,fetcher=blocked)
        self.assertEqual(result["candidate_case_count"],3)
        self.assertEqual(result["case_year_review_rows"],7)
        self.assertEqual(result["official_source_bytes_archived"],0)
        self.assertEqual(result["case_year_positive_labels_approved"],0)
        self.assertEqual(result["eligible_supervised_training_rows"],0)
        self.assertTrue(result["holdout_1785_untouched"])

    def test_official_https_mock_creates_sha_evidence_but_no_labels(self):
        result=r.run(self.seed,self.root/"online",retrieve=True,
                     pace_seconds=0,fetcher=self.mock_fetch)
        self.assertEqual(result["official_source_bytes_archived"],4)
        self.assertEqual(result["source_collection_statuses"]
                         ["HTTPS_ARCHIVED_WITH_SHA_NEEDS_FACT_REVIEW"],4)
        self.assertEqual(result["source_collection_statuses"]["SECONDARY_EXCLUDED"],1)
        self.assertEqual(result["original_pre_restatement_filing_count_verified"],0)
        with (self.root/"online"/"taiwan_misstatement_review_queue.csv").open(
                encoding="utf-8",newline="") as f:
            items=list(csv.DictReader(f))
        self.assertEqual({x["outcome_label"] for x in items},{"UNKNOWN"})
        self.assertTrue(all(x["eligible_historical_asof_training"]=="false"
                            for x in items))
        self.assertNotIn("1785",{x["ticker"] for x in items})
        self.assertEqual({x["event_evidence_status"] for x in items},
                         {"OFFICIAL_DOCUMENTS_ARCHIVED_PENDING_PERIOD_AND_CASE_OUTCOME_REVIEW"})

    def test_idempotent_archive_reuses_byte_exact_cache(self):
        first=r.archive_official(self.case,self.source,self.root,fetcher=self.mock_fetch,
                                 retrieve=True)
        self.assertEqual(first["collection_status"],"HTTPS_ARCHIVED_WITH_SHA_NEEDS_FACT_REVIEW")
        second=r.archive_official(self.case,self.source,self.root,fetcher=self.mock_fetch,
                                  retrieve=True)
        self.assertEqual(second["collection_status"],"CACHED_BYTE_ARCHIVE_NEEDS_MANUAL_REVIEW")
        self.assertEqual(self.fake_count,1)
        self.assertEqual(first["raw_sha256"],second["raw_sha256"])

    def test_existing_archive_corruption_does_not_get_overwritten(self):
        first=r.archive_official(self.case,self.source,self.root,fetcher=self.mock_fetch,
                                 retrieve=True)
        file=Path(first["raw_file"])
        file.write_text("TAMPERED",encoding="utf-8")
        second=r.archive_official(self.case,self.source,self.root,
                                  fetcher=self.mock_fetch,retrieve=True)
        self.assertEqual(second["collection_status"],"ARCHIVE_TAMPER_OR_IDENTITY_CONFLICT")
        self.assertEqual(file.read_text(encoding="utf-8"),"TAMPERED")
        self.assertEqual(self.fake_count,1)

    def test_garbage_html_without_correct_company_never_archived(self):
        def missing(url):
            return b"<html>" + b"please enable javascript"*30 + b"</html>",url,"text/html"
        result=r.archive_official(self.case,self.source,self.root,
                                  fetcher=missing,retrieve=True)
        self.assertEqual(result["collection_status"],"DOCUMENT_IDENTITY_UNVERIFIED_NOT_SAVED")
        self.assertFalse(list(self.root.rglob("*.html")))

    def test_court_redirect_or_nonofficial_urls_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"non_official_source_url"):
            r.safe_url("https://example.com/phishing")
        with self.assertRaisesRegex(ValueError,"userinfo_or_port"):
            r.safe_url("https://judgment.judicial.gov.tw:8443/FJUD/")
        def redirect(url):
            return b"<html>"+self.case["company"].encode("utf-8")+b"x"*700+b"</html>", \
                   "https://example.com/login", "text/html"
        result=r.archive_official(self.case,self.source,self.root,
                                  fetcher=redirect,retrieve=True)
        self.assertEqual(result["collection_status"],"RETRIEVAL_FAILED_NO_LABEL")

    def test_secondary_news_is_not_official_ground_truth(self):
        item=next(c for c in self.cases if c["ticker"]=="8299")
        news=next(s for s in item["sources"] if "SECONDARY_NEWS" in s["kind"])
        result=r.archive_official(item,news,self.root,fetcher=self.mock_fetch,
                                  retrieve=True)
        self.assertEqual(result["collection_status"],"SECONDARY_EXCLUDED")
        self.assertEqual(self.fake_count,0)

    def test_original_filing_and_earliest_notice_not_inferred_from_court(self):
        report=r.run(self.seed,self.root/"offline",retrieve=True,
                     pace_seconds=0,fetcher=self.mock_fetch)
        self.assertEqual(report["earliest_public_revelation_times_verified"],0)
        with (self.root/"offline"/"taiwan_misstatement_review_queue.csv").open(
                encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertTrue(all(not row["original_filing_sha256"] for row in rows))
        self.assertTrue(all(not row["original_filing_publication_at"] for row in rows))
        self.assertTrue(all(not row["first_public_disclosure_verified_at"] for row in rows))

    def test_no_user_requested_network_runs_when_file_cached(self):
        r.run(self.seed,self.root/"archive",retrieve=True,
              pace_seconds=0,fetcher=self.mock_fetch)
        self.fake_count=0
        report=r.run(self.seed,self.root/"archive",retrieve=True,
                     pace_seconds=0,fetcher=self.mock_fetch)
        self.assertEqual(self.fake_count,0)
        self.assertEqual(report["official_source_bytes_archived"],4)
        self.assertEqual(report["case_year_positive_labels_approved"],0)

    def test_invalid_interval_is_refused(self):
        with self.assertRaisesRegex(ValueError,"invalid_official_fetch_interval"):
            r.run(self.seed,self.root/"out",pace_seconds=-1)


if __name__=="__main__":
    unittest.main()
