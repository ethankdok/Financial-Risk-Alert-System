"""Synthetic-only 1785 PDF review/SQLite gates. Never use synthetic values as real results."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pymupdf as fitz
from research.financial_ml import round7_original_pdf_review as study


def fake_pdf(year):
    pdf=fitz.open()
    for p in range(14):
        page=pdf.new_page()
        page.insert_text((50,50),f"TEST ORIGINAL {year} PAGE {p+1}")
    data=pdf.tobytes();pdf.close()
    return data


def archive(path,pdfs):
    root="fintrust_historical_research_dataset/"
    rows=[]
    with zipfile.ZipFile(path,"w") as z:
        for year,raw in pdfs.items():
            sha=hashlib.sha256(raw).hexdigest()
            relative=f"raw_evidence/financial_filings/{sha}.pdf"
            z.writestr(root+relative,raw)
            rows.append({"ticker":"1785","fiscal_year":year,
                "statement_scope":"consolidated",
                "filing_version_type":"original",
                "package_raw_path":relative,"content_hash":sha,
                "filing_version_id":f"fake_{year}",
                "source_url":"https://doc.twse.com.tw"})
        csv_bytes=io.StringIO()
        writer=csv.DictWriter(csv_bytes,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
        z.writestr(root+"data/filing_versions.csv",csv_bytes.getvalue())
    return {year:hashlib.sha256(raw).hexdigest() for year,raw in pdfs.items()}


def fill(path, reviewer, manifest, *, changed=None, empty=()):
    rows=[]
    with path.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    for r in rows:
        k=(int(r["fiscal_year"]),r["metric"])
        if k in empty:continue
        r["reviewer_id"]=reviewer
        r["pdf_page_1based"]="6"
        r["value_thousand_twd"]=str(changed if (changed is not None and k==(2014,"revenue"))
                                    else 1000+int(r["fiscal_year"])-2013)
    with path.open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=study.REVIEW_FIELDS)
        w.writeheader();w.writerows(rows)


class OriginalPdfTests(unittest.TestCase):
    def setUp(self):
        size_gate=patch.object(study,"MIN_ORIGINAL_PDF_BYTES",100)
        size_gate.start()
        self.addCleanup(size_gate.stop)
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.zip=self.base/"fake_original.zip"
        pdfs={year:fake_pdf(year) for year in (2013,2014,2015)}
        self.hashes=archive(self.zip,pdfs)
        self.review=self.base/"source_review"
        self.review.mkdir()
        self.pin={year:(f"{year}04_1785_AI1.pdf",sha[:16])
                  for year,sha in self.hashes.items()}
        self.expected=study.digest(self.zip)

    def fake_originals(self):
        return (
            patch.object(study,"FULL_SHA",self.expected),
            patch.object(study,"PINNED",self.pin),
            patch.object(study,"verify_package",return_value={
                "status":"verified","mode":"retrospective"}),
        )

    def prepare(self):
        a,b,c=self.fake_originals()
        with a,b,c:
            return study.render_originals(self.zip,self.review,render=False)

    def test_only_exact_three_original_pdf_hashes(self):
        a,b,c=self.fake_originals()
        with a,b,c:
            status,src=study.originals_from_full_zip(self.zip)
        self.assertEqual(len(src),3)
        self.assertEqual({int(y) for y in src},set(self.hashes))
        self.assertTrue(all(v["data"].startswith(b"%PDF") for v in src.values()))

    def test_original_zip_content_hash_must_match(self):
        with self.assertRaisesRegex(ValueError,"full_archive_sha_disagrees"):
            study.originals_from_full_zip(self.zip)

    def test_prepare_make_36_reviewable_fields_per_reviewer(self):
        info=self.prepare()
        self.assertEqual(info["page_inventory_count"],39)
        self.assertTrue(info["human_review_required"])
        for label in ("A","B"):
            with (self.review/f"original_review_{label}.csv").open(
                    encoding="utf-8-sig") as f:
                rows=list(csv.DictReader(f))
            self.assertEqual(len(rows),36)
            self.assertTrue(all(not x["value_thousand_twd"] for x in rows))

    def test_no_fabricated_values_from_scanned_pdf(self):
        self.prepare()
        with patch.object(study,"official_pre_pairs",return_value=({}, {}, {})):
            out=study.finalize(self.review,self.zip,self.base/"db1")
        self.assertEqual(out["double_reviewed_cells"],0)
        self.assertEqual(out["review_status_counts"],{"PENDING_DOUBLE_TRANSCRIPTION":36})

    def test_two_independent_reviewers_accept_original_not_notice_amount(self):
        manifest=self.prepare()
        fill(self.review/"original_review_A.csv","auditor_one",manifest)
        fill(self.review/"original_review_B.csv","auditor_two",manifest)
        official={(2014,"revenue"):(Decimal("60000000"),Decimal("80000000"))}
        with patch.object(study,"official_pre_pairs",return_value=(official,{},{})):
            out=study.finalize(self.review,self.zip,self.base/"db2")
        self.assertEqual(out["double_reviewed_cells"],36)
        self.assertEqual(out["original_and_2016_notice_amount_disagreements"],1)
        db=sqlite3.connect(self.base/"db2"/"original_1785_research.sqlite3")
        try:
            n=db.execute("SELECT COUNT(*) FROM original_1785_financial_facts").fetchone()[0]
            one=db.execute("SELECT value_twd,model_training_admitted FROM original_1785_financial_facts WHERE fiscal_year=2014 AND metric='revenue'").fetchone()
        finally:db.close()
        self.assertEqual(n,36)
        self.assertEqual(one,("1001000",0))
        self.assertTrue(out["1785_reserved_final_case_not_used_for_classifier_fit"])

    def test_one_disagreement_blocks_only_that_field(self):
        manifest=self.prepare()
        fill(self.review/"original_review_A.csv","auditor_one",manifest)
        fill(self.review/"original_review_B.csv","auditor_two",manifest,
             changed=999)
        with patch.object(study,"official_pre_pairs",return_value=({}, {}, {})):
            out=study.finalize(self.review,self.zip,self.base/"db3")
        self.assertEqual(out["double_reviewed_cells"],35)
        self.assertEqual(out["review_status_counts"]["REJECT_REVIEWER_DISAGREEMENT"],1)

    def test_same_amount_different_page_is_not_silently_imported(self):
        manifest=self.prepare()
        fill(self.review/"original_review_A.csv","auditor_one",manifest)
        fill(self.review/"original_review_B.csv","auditor_two",manifest)
        second=self.review/"original_review_B.csv"
        with second.open("r",encoding="utf-8-sig",newline="") as f:
            records=list(csv.DictReader(f))
        target=next(r for r in records
                    if r["fiscal_year"]=="2014" and r["metric"]=="revenue")
        target["pdf_page_1based"]="7"
        with second.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=study.REVIEW_FIELDS)
            w.writeheader()
            w.writerows(records)
        with patch.object(study,"official_pre_pairs",return_value=({}, {}, {})):
            out=study.finalize(self.review,self.zip,self.base/"db_pages")
        self.assertEqual(out["double_reviewed_cells"],35)
        self.assertEqual(
            out["review_status_counts"]["REJECT_PDF_PAGE_DISAGREEMENT"],1)

    def test_self_review_not_certified(self):
        manifest=self.prepare()
        fill(self.review/"original_review_A.csv","same_user",manifest)
        fill(self.review/"original_review_B.csv","same_user",manifest)
        with patch.object(study,"official_pre_pairs",return_value=({}, {}, {})):
            out=study.finalize(self.review,self.zip,self.base/"db4")
        self.assertEqual(out["double_reviewed_cells"],0)
        self.assertEqual(out["review_status_counts"]["REJECT_REVIEWER_NOT_INDEPENDENT"],36)

    def test_source_document_sha_cannot_be_forged(self):
        manifest=self.prepare()
        fill(self.review/"original_review_A.csv","A",manifest)
        fill(self.review/"original_review_B.csv","B",manifest)
        f=self.review/"original_review_A.csv"
        s=f.read_text(encoding="utf-8-sig").replace(
            self.hashes[2013],"0"*64)
        f.write_text(s,encoding="utf-8-sig")
        with self.assertRaisesRegex(ValueError,"review_pdf_hash_mismatch"):
            study.finalize(self.review,self.zip,self.base/"db5")


if __name__=="__main__":
    unittest.main()
