"""Round11 synthetic evidence-contract tests; zero fabricated real company labels."""
from __future__ import annotations
import csv
import json
import tempfile
import unittest
from datetime import datetime,timezone
from pathlib import Path
from research.financial_ml import round11_year_matched_evidence_gate as mod

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/"audit_files";self.source.mkdir()

    def file(self,name):
        p=self.source/name
        p.write_text("TEST FIXTURE NOT REAL OFFICIAL AUDIT EVIDENCE: "+name*2,encoding="utf-8")
        from research.financial_ml.round8_human_supervised_classifier import sha
        return name,sha(p)

    def item(self,ticker,year,label,publication,notice,*,later="false"):
        source,osh=self.file(f"{ticker}_{year}_original.pdf")
        first,fsh=self.file(f"{ticker}_{year}_filing_time.txt")
        event,esh=self.file(f"{ticker}_{year}_outcome.txt")
        cover,csh=self.file(f"{ticker}_{year}_coverage.txt")
        out={
            "ticker":ticker,"fiscal_year":str(year),"year_type":"ANNUAL",
            "target":mod.TARGET,"label":str(label),
            "original_annual_filing_published_at":publication,
            "original_pdf_relative_path":source,"original_pdf_sha256":osh,
            "original_first_publication_notice_path":first,
            "original_first_publication_notice_sha256":fsh,
            "original_filing_statement_scope":"consolidated",
            "original_filing_version":"ORIGINAL_FIRST_PUBLISHED",
            "outcome_notice_issued_at":notice,
            "outcome_document_relative_path":event,
            "outcome_document_sha256":esh,
            "outcome_report_type":("CORE_AMOUNT_CORRECTION_ANNUAL" if label
                 else "NONE_FOUND_AFTER_EXHAUSTIVE_OFFICIAL_ARCHIVE_REVIEW"),
            "outcome_affected_fiscal_year":str(year),
            "complete_official_screening_from":publication,
            "complete_official_screening_until":"2026-01-01T00:00:00+08:00",
            "official_search_coverage_manifest_path":cover,
            "official_search_coverage_manifest_sha256":csh,
            "any_later_known_restatement_for_same_filing":later,
            "reviewer_a":"reviewer_1","reviewer_b":"reviewer_2",
            "method_owner_approval":"APPROVED",
            "original_12_features_double_reviewed":"true",
            "outcome_and_period_double_reviewed":"true",
            "company_eligible_to_be_separately_held_out":"true",
        }
        for i,key in enumerate(mod.METRICS):
            out[key]=str(100000+i*130)
        return out

    def panel(self,rows):
        path=self.root/"panel.csv"
        with path.open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=mod.FIELDS)
            writer.writeheader();writer.writerows(rows)
        return path

    def test_twenty_four_calendar_months_are_bounded(self):
        now=datetime(2022,2,28,tzinfo=timezone.utc)
        self.assertEqual(mod.two_years_after(now).isoformat(),
                         "2024-02-28T00:00:00+00:00")
        leap=datetime(2024,2,29,tzinfo=timezone.utc)
        self.assertEqual(mod.two_years_after(leap).day,28)

    def test_real_company_cohort_120_and_year2022_year2023_focus(self):
        x=mod.candidate_tracker(self.root/"queue")
        self.assertEqual(x["year_rows"],1560)
        self.assertFalse(x["training_allowed"])
        with (self.root/"queue"/"round11_same_fy_human_annotation_queue.csv").open(
            encoding="utf-8-sig",newline="") as f:
            r=list(csv.DictReader(f))
        self.assertEqual(sum(x["review_focus"]=="FY2022_MATCHED_PILOT" for x in r),120)
        self.assertEqual(sum(x["review_focus"]=="FY2023_MATCHED_PILOT" for x in r),120)
        self.assertTrue(all(x["supervised_target_label"]=="UNKNOWN" for x in r))
        y=next(v for v in r if v["ticker"]=="8487" and v["fiscal_year"]=="2022")
        self.assertIn("S02",y["note_only_or_interim_event"])
        self.assertEqual(y["financial_statement_correction_lead"],"")

    def test_positive_fy2023_official_correction_in_24months_passes_review(self):
        y=self.item("6485",2023,1,"2024-03-29T12:00:00+08:00",
                    "2025-05-27T14:01:01+08:00")
        labels,blocked=mod.audited_rows(
            self.panel([y]),self.source,report_time=datetime(2026,10,20,tzinfo=timezone.utc))
        self.assertEqual(len(labels),1)
        self.assertEqual(labels[0]["label"],1)
        self.assertEqual(blocked,{})

    def test_fy2018_restated_in_2023_not_fake_24m_positive(self):
        y=self.item("8487",2018,1,"2019-03-25T12:00:00+08:00",
                    "2023-04-27T18:58:26+08:00")
        with self.assertRaisesRegex(ValueError,"outside_equal_24_month_window"):
            mod.audited_rows(self.panel([y]),self.source)

    def test_two_year_official_negative_with_full_evidence_can_be_zero(self):
        y=self.item("2330",2022,0,"2023-03-31T12:00:00+08:00","")
        labels,blocked=mod.audited_rows(self.panel([y]),self.source,
                                      report_time=datetime(2026,10,20,tzinfo=timezone.utc))
        self.assertEqual([r["label"] for r in labels],[0])
        self.assertEqual(blocked,{})

    def test_recent_fy2025_negative_cannot_be_assumed_mature(self):
        y=self.item("2330",2025,0,"2026-03-31T12:00:00+08:00","")
        labels,blocked=mod.audited_rows(self.panel([y]),self.source,
                                      report_time=datetime(2026,10,20,tzinfo=timezone.utc))
        self.assertEqual(labels,[])
        self.assertIn("NEGATIVE_OUTCOME_FOLLOWUP_NOT_YET_COMPLETE",blocked)

    def test_clean_label_denied_when_future_late_restatement_known(self):
        y=self.item("8487",2018,0,"2019-03-25T12:00:00+08:00",
                    "",later="true")
        labels,blocked=mod.audited_rows(self.panel([y]),self.source)
        self.assertEqual(labels,[])
        self.assertIn("POST_HORIZON_RESTATEMENT_CONTAMINATION",blocked)

    def test_positive_and_negative_from_different_years_not_enough(self):
        r=[
            {"ticker":"6485","fiscal_year":2023,"label":1,"features":[1.]*12},
            {"ticker":"2330","fiscal_year":2022,"label":0,"features":[1.]*12}
        ]
        ok,fail=mod.same_year_gate(r)
        self.assertFalse(ok)
        self.assertTrue(any("NO_SAME_FY_POSITIVE_NEGATIVE_MATCH" in x for x in fail))

    def test_yearly_matched_pairs_still_require_multiple_independent_issuers(self):
        r=[]
        for y in (2018,2021,2023):
            r.extend([
                {"ticker":str(3000+y),"fiscal_year":y,"label":1,"features":[1.]*12},
                {"ticker":str(5000+y),"fiscal_year":y,"label":0,"features":[1.]*12},
            ])
        ok,fail=mod.same_year_gate(r)
        self.assertFalse(ok)
        self.assertTrue(any("sample_counts" in x for x in fail))

    def test_real_fraud_f1_not_computed_on_no_approved_0_1(self):
        from unittest.mock import patch
        blank=self.panel([])
        m=mod.evaluate(blank,self.source,self.root/"evaluation")
        self.assertIsNone(m["real_f1"])
        self.assertEqual(m["persisted_model_count"],0)
        self.assertFalse(m["fraud_accuracy_claim_allowed"])
        with self.assertRaisesRegex(FileExistsError,"training_output_immutable"):
            mod.evaluate(blank,self.source,self.root/"evaluation")

if __name__=="__main__":
    unittest.main()
