"""Round7 — convert the three archived 1785 ORIGINAL AI1 scanned reports into
reviewable evidence and (only after independent double transcription) a
separate research SQLite table. No OCR hallucination, label or production write.

Prepare: validate source ZIP + SHA, render statement pages for HUMAN review,
make independent A/B transcriptions. Finalize: require two independent
reviewers for the SAME original PDF field+page, compare against 2016 notice
PRE side, record discrepancies instead of silently replacing originals.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from datetime import datetime, timezone

from app.services.historical_audit.package_verify import verify_package
from .annual_panel_readiness import METRICS
from .final_1785_case_replay import STRICT_SHA, digest
from .round5_1785_pre_restatement_replay import official_pre_pairs

FULL_SHA="693e867155de00ebded16ffece99f6b32179d306e369028eee4045f6dfbaa826"
PINNED={
    2013:("201304_1785_AI1.pdf","44c777c18128a59d"),
    2014:("201404_1785_AI1.pdf","320b3dc81a7671c8"),
    2015:("201504_1785_AI1.pdf","0ca2d7e5636c0f6e"),
}
REVIEW_FIELDS=("ticker","fiscal_year","metric","value_thousand_twd",
               "source_pdf_sha256","pdf_page_1based","reviewer_id",
               "transcription_basis","review_notes")
FINAL_FIELDS=("ticker","fiscal_year","metric","value_twd","unit",
              "source_pdf_sha256","source_pdf_file","pdf_page_1based",
              "statement_scope","accounting_framework","filing_version_type",
              "reviewers","review_status","original_first_publication_verified",
              "model_training_admitted","notice_pre_twd","notice_delta_twd",
              "original_vs_notice_status")
SECTIONS=range(3,14)
MIN_ORIGINAL_PDF_BYTES=100_000


def checksum(data):
    return hashlib.sha256(data).hexdigest()


def _csv_bytes(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


def originals_from_full_zip(archive):
    archive=Path(archive)
    if digest(archive)!=FULL_SHA:
        raise ValueError("original_1785_full_archive_sha_disagrees")
    verdict=verify_package(archive)
    if verdict.get("status")!="verified" or verdict.get("mode")!="retrospective":
        raise ValueError("original_1785_full_archive_semantics_not_verified")
    sources={}
    with zipfile.ZipFile(archive) as z:
        root="fintrust_historical_research_dataset/"
        filing_records=_csv_bytes(z.read(root+"data/filing_versions.csv"))
        for year,(filename,prefix) in PINNED.items():
            rows=[r for r in filing_records
                  if str(r["ticker"])=="1785"
                  and int(r["fiscal_year"])==year
                  and r["statement_scope"]=="consolidated"
                  and r["filing_version_type"]=="original"]
            if len(rows)!=1:raise ValueError(f"original_1785_original_filing_identity:{year}")
            r=rows[0]
            raw_path=r.get("package_raw_path","")
            if not raw_path:
                raise ValueError(f"original_1785_raw_pdf_not_bundled:{year}")
            if not raw_path.startswith("raw_evidence/") or ".." in raw_path or "\\" in raw_path:
                raise ValueError("original_1785_unsafe_package_member")
            raw=z.read(root+raw_path)
            source_hash=checksum(raw)
            if not raw.startswith(b"%PDF") or len(raw)<MIN_ORIGINAL_PDF_BYTES:
                raise ValueError(f"original_1785_invalid_pdf_bytes:{year}")
            if not source_hash.startswith(prefix) or source_hash!=r["content_hash"]:
                raise ValueError(f"original_1785_pdf_content_hash_changed:{year}")
            sources[year]={"filename":filename,"sha256":source_hash,"data":raw,
                           "filing_version_id":r["filing_version_id"],
                           "source_url":r.get("source_url",""),
                           "filing_version_type":"original"}
    return verdict,sources


def render_originals(full_zip,output,*,max_pages=13,render=True):
    """Scanned Chinese statement tables require human transcription;
    rendering is *not* a model-derived numeric observation."""
    import pymupdf as fitz
    out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("original_1785_review_directory_must_be_new")
    verify,sources=originals_from_full_zip(full_zip)
    reports=[]
    out.mkdir(parents=True,exist_ok=True)
    for year,r in sources.items():
        pdf=fitz.open(stream=r["data"],filetype="pdf")
        pages=min(pdf.page_count,max_pages)
        if pages<9: raise ValueError("original_1785_unexpected_short_scanned_report")
        rendered=[]
        for p in range(pages):
            page=pdf.load_page(p)
            found=(page.get_text("text") or "").strip()
            # Render first 13 pages, including balance/income/cash-flow
            # candidates; reviewer must cite exact actual PDF page.
            if render:
                target=out/"pages"/str(year)/f"page_{p+1:03d}.png"
                target.parent.mkdir(parents=True,exist_ok=True)
                page.get_pixmap(matrix=fitz.Matrix(1.8,1.8),
                                alpha=False).save(str(target))
                rendered.append(str(target.relative_to(out)))
            reports.append({"ticker":"1785","fiscal_year":year,
                            "pdf_page_1based":p+1,
                            "extractable_text_characters":len(found),
                            "page_render_path":rendered[-1] if render else "",
                            "source_pdf_sha256":r["sha256"]})
        pdf.close()
    with (out/"original_pdf_page_inventory.csv").open(
            "w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(reports[0]))
        w.writeheader();w.writerows(reports)
    for reviewer in ("A","B"):
        target=out/f"original_review_{reviewer}.csv"
        with target.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=REVIEW_FIELDS);w.writeheader()
            w.writerows({
                "ticker":"1785","fiscal_year":year,"metric":metric,
                "value_thousand_twd":"","source_pdf_sha256":sources[year]["sha256"],
                "pdf_page_1based":"","reviewer_id":"","transcription_basis":"VISUAL_ORIGINAL_PDF",
                "review_notes":""}
                for year in PINNED for metric in METRICS)
    manifest={
        "status":"ORIGINAL_AI1_PDF_REVIEW_PREPARED",
        "original_source_full_zip_sha256":digest(full_zip),
        "source_verification":verify,
        "source_mode":"original_pdf_original_filing",
        "pdfs":{str(k):{x:v for x,v in r.items() if x!="data"}
                for k,r in sources.items()},
        "page_inventory_count":len(reports),
        "human_review_required":True,
        "no_ocr_inferred_financial_numbers":True,
        "original_first_publication_time_verified":False,
        "originals_never_enter_1785_model_training":True,
    }
    (out/"original_pdf_ingestion_manifest.json").write_text(
        json.dumps(manifest,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return manifest


def read_reviews(path,manifest):
    with Path(path).open(encoding="utf-8-sig",newline="") as f:
        src=csv.DictReader(f)
        if not set(REVIEW_FIELDS).issubset(src.fieldnames or []):
            raise ValueError("original_1785_review_schema_changed")
        rows=list(src)
    expected={(y,m) for y in PINNED for m in METRICS}
    if {(int(r["fiscal_year"]),r["metric"]) for r in rows}!=expected or len(rows)!=len(expected):
        raise ValueError("original_1785_review_rows_not_exactly_36")
    for row in rows:
        if row["ticker"]!="1785" or row["transcription_basis"]!="VISUAL_ORIGINAL_PDF":
            raise ValueError("original_1785_review_wrong_source_or_basis")
        year=int(row["fiscal_year"])
        if row["source_pdf_sha256"]!=manifest["pdfs"][str(year)]["sha256"]:
            raise ValueError("original_1785_review_pdf_hash_mismatch")
    return {(int(r["fiscal_year"]),r["metric"]):r for r in rows}


def money(raw):
    s=str(raw).strip().replace(",","")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?",s):
        raise ValueError("original_1785_invalid_manual_money")
    x=Decimal(s)
    if not x.is_finite() or abs(x)>Decimal("1e16"):
        raise ValueError("original_1785_extreme_manual_money")
    return x*Decimal(1000)


def finalize(review_dir,strict_zip,output):
    src=Path(review_dir)
    out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("original_1785_verified_database_output_immutable")
    manifest=json.loads((src/"original_pdf_ingestion_manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("status")!="ORIGINAL_AI1_PDF_REVIEW_PREPARED"
        or manifest.get("originals_never_enter_1785_model_training") is not True):
        raise ValueError("original_1785_review_manifest_rejected")
    a=read_reviews(src/"original_review_A.csv",manifest)
    b=read_reviews(src/"original_review_B.csv",manifest)
    official,sources,meta=official_pre_pairs(strict_zip)
    accepted=[];audit=[];statuses=Counter()
    for year in PINNED:
        for metric in METRICS:
            k=(year,metric);r1=a[k];r2=b[k]
            v1=r1["value_thousand_twd"].strip();v2=r2["value_thousand_twd"].strip()
            reviewers=(r1["reviewer_id"].strip(),r2["reviewer_id"].strip())
            pages=(r1["pdf_page_1based"].strip(),r2["pdf_page_1based"].strip())
            status="PENDING_DOUBLE_TRANSCRIPTION"
            value=None
            if v1 and v2:
                if not reviewers[0] or not reviewers[1] or reviewers[0]==reviewers[1]:
                    status="REJECT_REVIEWER_NOT_INDEPENDENT"
                elif not all(x.isdecimal() and int(x)>0 for x in pages):
                    status="REJECT_PAGE_EVIDENCE_MISSING"
                elif int(pages[0])>13 or int(pages[1])>13:
                    status="REJECT_PAGE_BEYOND_REVIEWED_INVENTORY"
                elif pages[0]!=pages[1]:
                    # Two equal amounts from different page references are not
                    # an independently verified observation of one statement.
                    # Prevent blank pdf_page / downstream SQLite conversion.
                    status="REJECT_PDF_PAGE_DISAGREEMENT"
                elif money(v1)!=money(v2):
                    status="REJECT_REVIEWER_DISAGREEMENT"
                else:
                    value=money(v1)
                    status="DOUBLE_REVIEWED_ORIGINAL_PDF"
            notice=official.get(k)
            notice_pre=notice[0] if notice else None
            diff=(value-notice_pre if value is not None and notice_pre is not None else None)
            comparison=("MATCHES_2016_NOTICE_PRE" if diff==0 else
                        "DIFFERS_FROM_2016_NOTICE_PRE" if diff is not None else
                        "NO_SAME_GRAIN_COMPARISON")
            data={"ticker":"1785","fiscal_year":year,"metric":metric,
                  "value_twd":format(value,"f") if value is not None else "",
                  "unit":"TWD","source_pdf_sha256":manifest["pdfs"][str(year)]["sha256"],
                  "source_pdf_file":manifest["pdfs"][str(year)]["filename"],
                  "pdf_page_1based":pages[0] if pages[0]==pages[1] else "",
                  "statement_scope":"consolidated","accounting_framework":"TIFRS",
                  "filing_version_type":"original",
                  "reviewers":"|".join(reviewers),
                  "review_status":status,
                  "original_first_publication_verified":"false",
                  "model_training_admitted":"false",
                  "notice_pre_twd":format(notice_pre,"f") if notice_pre is not None else "",
                  "notice_delta_twd":format(diff,"f") if diff is not None else "",
                  "original_vs_notice_status":comparison}
            audit.append(data)
            statuses[status]+=1
            if value is not None:
                accepted.append(data)
    out.mkdir(parents=True,exist_ok=True)
    with (out/"original_pdf_financial_fact_audit.csv").open(
            "w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FINAL_FIELDS)
        w.writeheader();w.writerows(audit)
    db=sqlite3.connect(out/"original_1785_research.sqlite3")
    try:
        db.execute("""CREATE TABLE original_1785_financial_facts (
            ticker TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
            metric TEXT NOT NULL, value_twd TEXT NOT NULL,
            unit TEXT NOT NULL, filing_version_type TEXT NOT NULL,
            source_pdf_sha256 TEXT NOT NULL, pdf_page INTEGER NOT NULL,
            statement_scope TEXT NOT NULL, accounting_framework TEXT NOT NULL,
            review_status TEXT NOT NULL, original_first_publication_verified INTEGER NOT NULL CHECK(original_first_publication_verified=0),
            model_training_admitted INTEGER NOT NULL CHECK(model_training_admitted=0),
            PRIMARY KEY(ticker,fiscal_year,metric)
        )""")
        for r in accepted:
            # Store only true double reviewed original PDF rows, NOT the
            # candidate notice amount (comparison sidecar only).
            db.execute("""INSERT INTO original_1785_financial_facts VALUES(
                ?,?,?,?,?,?,?,?,?,?,?,0,0)""",(
                "1785",r["fiscal_year"],r["metric"],r["value_twd"],"TWD",
                "original",r["source_pdf_sha256"],int(r["pdf_page_1based"]),
                "consolidated","TIFRS",r["review_status"]))
        db.commit()
    finally:db.close()
    summary={
        "status":"ORIGINAL_1785_REVIEW_IMPORTED_RESEARCH_ONLY",
        "expected_original_fact_cells":36,"double_reviewed_cells":len(accepted),
        "review_status_counts":dict(statuses),
        "original_and_2016_notice_amount_disagreements":sum(
            x["original_vs_notice_status"]=="DIFFERS_FROM_2016_NOTICE_PRE"
            for x in accepted),
        "source_pdf_sha256":{y:m["sha256"] for y,m in manifest["pdfs"].items()},
        "original_first_publication_verified":False,
        "1785_reserved_final_case_not_used_for_classifier_fit":True,
        "database":"original_1785_research.sqlite3",
        "official_notice_comparison_only":"2016-11-13",
        "never_auto_promote_to_main_financial_database":True,
    }
    (out/"original_1785_ingestion_report.json").write_text(
        json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return summary


def main(argv=None):
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="mode",required=True)
    a=sub.add_parser("prepare")
    a.add_argument("--full-zip",required=True)
    a.add_argument("--out",required=True)
    a.add_argument("--no-render",action="store_true")
    b=sub.add_parser("finalize")
    b.add_argument("--review-dir",required=True)
    b.add_argument("--strict-zip",required=True)
    b.add_argument("--out",required=True)
    v=p.parse_args(argv)
    result=(render_originals(v.full_zip,v.out,render=not v.no_render)
            if v.mode=="prepare" else
            finalize(v.review_dir,v.strict_zip,v.out))
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
