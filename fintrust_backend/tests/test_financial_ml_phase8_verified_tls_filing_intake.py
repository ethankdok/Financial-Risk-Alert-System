"""Phase8 hermetic tests: TLS identity must stay verified; 13 original MOPS years.

No external network and no case/issuer labeling even in synthetic fixtures.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from research.financial_ml import phase6_official_evidence_recovery as c
from research.financial_ml import phase8_original_filing_intake as m
from research.financial_ml import phase8_integrated_run as integrated


class Response:
    def __init__(self,url):
        self.url=url
        self.status=200
        self.headers={"Content-Type":"text/html; charset=utf-8"}
    def geturl(self):
        return self.url
    def read(self,maxbytes):
        return b"<html>" + (b"official-fixture-no-labels" * 35) + b"</html>"
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return False


class Phase8VerifiedTLSAndFilingTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root=Path(t.name)
        self.cases=m.validate(json.loads(m.ROOT_SEED.read_text(encoding="utf-8")))
        self.queue=self.root/"phase7_official_case_asof_recovery"
        self.queue.mkdir()
        self.data=self.root/"financial_ml"
        self.data.mkdir()
        self.write_queue()

    def write_queue(self):
        with (self.queue/"phase7_original_filing_asof_gap_queue.csv").open(
                "w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=m.QUEUE_COLUMNS)
            w.writeheader()
            for case in self.cases:
                for target_year in case["affected_fiscal_years"]:
                    for year in range(target_year-2,target_year+1):
                        w.writerow(dict(
                            ticker=case["ticker"],case_id=case["case_id"],
                            affected_fiscal_year=target_year,
                            historical_input_year=year,
                            historical_role="TARGET" if year==target_year else "PRIOR_YEAR",
                            required_source="ORIGINAL_MOPS_FILING_AS_FIRST_PUBLISHED",
                            original_publication_time="",
                            original_filing_version_sha256="",
                            filing_status="UNKNOWN_ORIGINAL_VERSION_NEEDS_RECOVERY",
                            case_outcome_status="POTENTIAL_CASE_PERIOD_REVIEW_PENDING",
                            label_approved="false",
                            heldout_1785_excluded="true",
                            review_note=""))

    def test_context_remains_ca_and_hostname_verified(self):
        ctx=c.judiciary_verified_context()
        self.assertEqual(ctx.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        compatible=c.judiciary_verified_context(compatibility=True)
        self.assertEqual(compatible.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(compatible.check_hostname)
        if hasattr(ssl,"VERIFY_X509_STRICT"):
            self.assertFalse(compatible.verify_flags & ssl.VERIFY_X509_STRICT)
            if ctx.verify_flags & ssl.VERIFY_X509_STRICT:
                self.assertTrue(ctx.verify_flags & ssl.VERIFY_X509_STRICT)

    def test_judiciary_missing_subject_retries_only_for_that_reason(self):
        url="https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=test"
        calls=[]
        def fake(req,timeout,*,compatibility=False):
            calls.append(compatibility)
            if not compatibility:
                raise URLError(ssl.SSLCertVerificationError("certificate verify failed: Missing Subject"))
            return Response(req.full_url)
        with patch.object(c,"_open_verified",side_effect=fake):
            raw,endpoint,mime,mode=c.http_get(url)
        self.assertEqual(calls,[False,True])
        self.assertEqual(endpoint,url)
        self.assertIn("STRICT_ONLY_RELAXED",mode)
        self.assertTrue(len(raw)>500)

    def test_other_certificate_errors_never_downgrade(self):
        url="https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=test"
        calls=[]
        def fake(req,timeout,*,compatibility=False):
            calls.append(compatibility)
            raise URLError(ssl.SSLCertVerificationError("certificate verify failed: hostname mismatch"))
        with patch.object(c,"_open_verified",side_effect=fake):
            with self.assertRaises(URLError):
                c.http_get(url)
        self.assertEqual(calls,[False])

    def test_other_official_host_missing_subject_never_downgrade(self):
        url="https://www.sfipc.org.tw/News_Content.aspx?n=7458"
        calls=[]
        def fake(req,timeout,*,compatibility=False):
            calls.append(compatibility)
            raise URLError(ssl.SSLCertVerificationError("certificate verify failed: Missing Subject"))
        with patch.object(c,"_open_verified",side_effect=fake):
            with self.assertRaises(URLError):
                c.http_get(url)
        self.assertEqual(calls,[False])

    def test_already_archived_case_13_deduplicated_company_years(self):
        n=m.case_needs(self.queue/"phase7_original_filing_asof_gap_queue.csv",
                       json.loads(m.ROOT_SEED.read_text(encoding="utf-8")))
        self.assertEqual(len(n),13)
        self.assertIn(("8299",2012),n)
        self.assertEqual(n[("3027",2015)],{2015,2016})
        self.assertNotIn(("1785",2015),n)
        report=m.intake_report(self.data,self.queue,self.root/"results")
        self.assertEqual(report["unique_source_year_requirements"],13)
        self.assertEqual(report["phase7_year_window_slots"],21)
        self.assertEqual(report["independently_verified_original_versions"],0)
        self.assertEqual(report["supervised_positive_labels_approved"],0)
        with (self.root/"results"/"original_case_filing_source_intake.csv").open(
                encoding="utf-8",newline="") as f:
            rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),13)
        self.assertEqual({r["supervised_label"] for r in rows},{"UNKNOWN"})
        self.assertTrue(all(r["training_admitted"]=="false" for r in rows))
        sample=next(r for r in rows if r["ticker"]=="8299" and r["fiscal_year"]=="2012")
        self.assertEqual(sample["accounting_regime"],"PRE_TIFRS_GAAP_NEEDS_HISTORICAL_MAPPING")

    def test_alleged_original_report_and_notice_stay_unapproved(self):
        pdf=self.root/"report.pdf"
        pdf.write_bytes(b"%PDF-1.4\n" + b"Case research fixture"*100)
        notice=self.root/"announcement.html"
        notice.write_bytes(b"<html>" + b"official first publication NOT VERIFIED"*40 + b"</html>")
        manifest=self.root/"import.csv"
        with manifest.open("w",encoding="utf-8",newline="") as f:
            w=csv.DictWriter(f,fieldnames=m.INTAKE_COLUMNS)
            w.writeheader()
            w.writerow(dict(ticker="3027",fiscal_year=2015,
                local_report_file=str(pdf),mops_original_notice_file=str(notice),
                claimed_mops_original_publication_at="2016-03-31T17:00:00+08:00",
                original_filing_document_id="unverified-2015FY",
                review_notes="fixture"))
        report=m.intake_report(self.data,self.queue,self.root/"results",
                               import_manifest=manifest)
        self.assertEqual(report["user_submitted_original_candidate_years"],1)
        self.assertEqual(report["independently_verified_original_versions"],0)
        self.assertEqual(report["verified_historical_publication_times"],0)
        with (self.root/"results"/"original_case_filing_source_intake.csv").open(
                encoding="utf-8",newline="") as f:
            row=next(r for r in csv.DictReader(f)
                     if r["ticker"]=="3027" and r["fiscal_year"]=="2015")
        self.assertEqual(row["training_admitted"],"false")
        self.assertEqual(row["safe_for_historical_features"],"false")
        self.assertEqual(row["local_source_sha256"],hashlib.sha256(pdf.read_bytes()).hexdigest())

    def test_import_does_not_overwrite_existing_source_even_tamper(self):
        file=self.root/"file.pdf";file.write_bytes(b"%PDF"+"A".encode()*400)
        notice=self.root/"notice.html";notice.write_bytes(b"<html>"+b"B"*400)
        folder=self.root/"archive"
        hashes,files,_=m.archive_local(folder,"3027",2015,file,notice)
        self.assertEqual(m.archive_local(folder,"3027",2015,file,notice)[0],hashes)
        Path(files[0]).write_bytes(b"tampered original evidence")
        with self.assertRaisesRegex(ValueError,"tampered"):
            m.archive_local(folder,"3027",2015,file,notice)

    def test_import_timestamp_requires_timezone_and_case_in_queue(self):
        with self.assertRaisesRegex(ValueError,"explicit_timezone"):
            m._aware_time("2016-04-01T12:00:00")
        self.assertEqual(m._aware_time("2016-04-01T12:00:00+08:00"),
                         "2016-04-01T12:00:00+08:00")
        p=self.queue/"phase7_original_filing_asof_gap_queue.csv"
        rows=m.read_table(p,m.QUEUE_COLUMNS)
        rows[0]["ticker"]="1785"
        m.table(p,m.QUEUE_COLUMNS,rows)
        with self.assertRaisesRegex(ValueError,"heldout_or_unknown"):
            m.intake_report(self.data,self.queue,self.root/"out")

    def test_historical_manifest_invalid_identity_is_not_claimed_original(self):
        batch=self.data/"official_batch"
        batch.mkdir()
        (batch/"acquisition_results.json").write_text(json.dumps({
            "outcomes":{"3027:2015":{
                "status":"validated","ticker":"8299","fiscal_year":2014,
                "archive_path":"8299/2014FY/anything.xml","content_hash":"a"*64
            }}
        }),encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"archive_identity"):
            m.verified_archive_references(self.data,"3027",2015)


if __name__=="__main__":
    unittest.main()
