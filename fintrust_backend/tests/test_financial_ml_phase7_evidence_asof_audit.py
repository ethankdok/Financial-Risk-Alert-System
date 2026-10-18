"""Hermetic Phase7 source recovery, alias/charset, docket and PIT guard tests."""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml import phase7_evidence_asof_audit as a
from research.financial_ml import phase6_official_evidence_recovery as p6


class Phase7OfficialAsOfTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.seed=json.loads(p6.ROOT_SEED.read_text(encoding="utf-8"))
        self.cases=p6.validate(self.seed)
        self.url_case={}
        for case in self.cases:
            for src in case["sources"]:
                self.url_case[src["url"]]=(case,src)
        self.counter=0

    def fixture(self,case,source):
        marker=a.CASE_DOCUMENT_MARKERS[source["source_id"]]
        prefix=("臺灣高等法院民事判決" if source["kind"]=="JUDICIAL_JUDGMENT"
                else "投保中心公告")
        label={"3027":"盛達公司","8299":"群聯公司","6452":"康友公司"}[case["ticker"]]
        body="<html><head><meta charset='UTF-8'></head><body>"
        body+=f"<h1>{prefix}</h1><p>{marker}</p><p>{label}</p>"
        body+="此為安全來源封存之單元測試資料；不代表任何官方原文內容或財報不實認定。"*32
        body+="</body></html>"
        return body.encode("utf-8")

    def fetcher(self,url):
        self.counter+=1
        case,source=self.url_case[url]
        return self.fixture(case,source),url,"text/html; charset=utf-8"

    def test_company_alias_rescues_6452_from_false_rejection(self):
        case=next(c for c in self.cases if c["ticker"]=="6452")
        source=case["sources"][0]
        raw=self.fixture(case,source)
        self.assertTrue(p6.company_mentioned(p6.visible_document(raw),case))
        self.assertTrue(a.judge_identity(case,source,raw)["identity_supported_by_document"])

    def test_legacy_big5_judgment_decoding_and_docket_check(self):
        case=next(c for c in self.cases if c["ticker"]=="3027")
        source=case["sources"][0]
        raw=self.fixture(case,source).decode("utf-8").replace("UTF-8","big5").encode("cp950")
        self.assertIn("113年度金訴字第29號",p6.visible_document(raw))
        self.assertTrue(a.judge_identity(case,source,raw)["identity_supported_by_document"])

    def test_court_company_only_not_enough_to_approve_identity(self):
        case=next(c for c in self.cases if c["ticker"]=="8299")
        source=case["sources"][0]
        doc=self.fixture(case,source).replace(
            a.CASE_DOCUMENT_MARKERS[source["source_id"]].encode("utf-8"), b"UNRELATED CASE")
        result=a.judge_identity(case,source,doc)
        self.assertTrue(result["company_mentioned"])
        self.assertFalse(result["expected_marker_mentioned"])
        self.assertFalse(result["identity_supported_by_document"])

    def test_offline_recovery_creates_pre_event_missing_pit_queue(self):
        result=a.audit(self.root,self.root/"evidence",retrieve=False)
        self.assertEqual(result["case_count"],3)
        self.assertEqual(result["affected_company_year_candidates"],7)
        self.assertEqual(result["original_filing_requirements"],21)
        self.assertEqual(result["approved_taiwan_misstatement_labels"],0)
        self.assertEqual(result["archived_primary_sources_with_docket_and_company"],0)
        self.assertTrue(result["holdout_1785_untouched"])
        with (self.root/"evidence"/"phase7_original_filing_asof_gap_queue.csv").open(
                encoding="utf-8",newline="") as f:
            lines=list(csv.DictReader(f))
        self.assertEqual(len(lines),21)
        self.assertNotIn("1785",{row["ticker"] for row in lines})
        self.assertTrue(all(row["label_approved"]=="false" for row in lines))
        self.assertTrue(all(not row["original_filing_publication_time"]
                            for row in lines) if "original_filing_publication_time" in lines[0] else True)

    def test_mock_http_collects_all_4_docket_verified_but_zero_labels(self):
        result=a.audit(self.root,self.root/"evidence",retrieve=True,fetcher=self.fetcher)
        self.assertEqual(result["archived_primary_sources_with_docket_and_company"],4)
        self.assertEqual(result["supervised_ex_ante_ml_admitted_rows"],0)
        self.assertEqual(result["verified_original_financial_reports"],0)
        self.assertEqual(result["approved_negative_controls"],0)
        self.assertEqual(self.counter,4)
        self.assertTrue(all(x["status"]=="NO_ARCHIVED_OFFICIAL_BYTES" for x in
           result["source_failures"]) if result["source_failures"] else True)

    def test_browser_saved_html_requires_explicit_and_docket_validated_manifest(self):
        case=next(c for c in self.cases if c["ticker"]=="6452")
        source=case["sources"][0]
        body=self.fixture(case,source)
        local=self.root/"download.html"
        local.write_bytes(body)
        manifest=self.root/"imports.csv"
        with manifest.open("w",encoding="utf-8",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=("source_id","local_file"))
            writer.writeheader()
            writer.writerow({"source_id":source["source_id"],"local_file":str(local)})
        result=a.audit(self.root,self.root/"evidence",imports=manifest,retrieve=False)
        self.assertEqual(len(result["manual_import_results"]),1)
        self.assertEqual(result["archived_primary_sources_with_docket_and_company"],1)
        saved=(self.root/"evidence"/"official_case_bytes"/case["case_id"]/
               (source["source_id"]+".json"))
        receipt=json.loads(saved.read_text(encoding="utf-8"))
        self.assertEqual(receipt["method"],"MANUAL_IMPORTED_BROWSER_SAVE_ORIGIN_UNVERIFIED")
        self.assertIsNone(receipt["first_case_disclosure_at"])
        self.assertFalse(receipt["period_specific_label_approved"])
        self.assertEqual(result["supervised_ex_ante_ml_admitted_rows"],0)

    def test_mismatched_docket_cannot_be_imported_as_same_official_document(self):
        case=next(c for c in self.cases if c["ticker"]=="3027")
        source=case["sources"][0]
        local=self.root/"download.html"
        local.write_bytes(self.fixture(case,source).replace(
            a.CASE_DOCUMENT_MARKERS[source["source_id"]].encode("utf-8"),b"FAKE DOC"))
        manifest=self.root/"imports.csv"
        manifest.write_text("source_id,local_file\n"+
            source["source_id"]+","+str(local)+"\n",encoding="utf-8")
        result=a.audit(self.root,self.root/"evidence",imports=manifest,retrieve=False)
        self.assertEqual(result["manual_import_results"][0]["status"],
                         "LOCAL_DOCUMENT_IDENTITY_NOT_CONFIRMED")
        self.assertEqual(result["archived_primary_sources_with_docket_and_company"],0)

    def test_second_run_respects_immutable_cached_source(self):
        first=a.audit(self.root,self.root/"evidence",retrieve=True,fetcher=self.fetcher)
        self.assertEqual(self.counter,4)
        second=a.audit(self.root,self.root/"evidence",retrieve=True,fetcher=self.fetcher)
        self.assertEqual(self.counter,4)
        self.assertEqual(first["archived_primary_sources_with_docket_and_company"],
                         second["archived_primary_sources_with_docket_and_company"])

    def test_tampered_cached_source_fails_closed_no_label(self):
        a.audit(self.root,self.root/"evidence",retrieve=True,fetcher=self.fetcher)
        case=next(c for c in self.cases if c["ticker"]=="3027")
        target=self.root/"evidence"/"official_case_bytes"/case["case_id"]/"judicial_3027_trial_2025.html"
        target.write_text("BAD DATA",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"digest_or_url_conflict"):
            a.audit(self.root,self.root/"evidence",retrieve=True,fetcher=self.fetcher)

    def test_secondary_source_never_becomes_ground_truth(self):
        result=a.audit(self.root,self.root/"evidence",retrieve=True,fetcher=self.fetcher)
        self.assertEqual(result["primary_source_count"],4)
        self.assertEqual(result["approved_taiwan_misstatement_labels"],0)
        self.assertNotIn("public_8299_2016_press",
           [item["source_id"] for item in result["source_failures"]])


if __name__=="__main__":
    unittest.main()
