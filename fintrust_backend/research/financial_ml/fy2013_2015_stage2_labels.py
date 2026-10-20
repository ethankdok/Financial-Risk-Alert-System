"""FY2013-2015 Stage 2 — evidence-backed dual-review outcome labels.

Two parallel definitions MUST NOT be mixed:
(a) material restatement of a specified FY2013/14/15 original annual
    consolidated report, discovered within 5 years after first publication;
(b) separately court/regulator-confirmed financial misstatement.
The 5-year event horizon is ONLY for label evidence; model features are
the same FY2013-15 original first-filed figures.

A CSV of merely typed zeros/ones is NEVER a validated label set. Official
archive documents must be provided as immutable SHA-matched local files.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
from .annual_panel_readiness import METRICS
from .fy2013_2015_stage1_freeze import YEARS,FIELDS as SOURCE_FIELDS
from .round8_human_supervised_classifier import timestamp
from .round10_disclosure_event_label_gate import cohort

TARGET="MATERIAL_ANNUAL_RESTATEMENT_WITHIN_5_YEARS_OF_FIRST_REPORT"
OUTCOME_TYPES=("OFFICIAL_SAME_YEAR_CONSOLIDATED_CORE_AMOUNT_RESTATEMENT",
               "COMPLETE_OFFICIAL_FILING_AND_CORRECTION_SEARCH_NONE_FOUND")
LABEL_FIELDS=(
    "ticker","fiscal_year","label_target","human_label",
    "original_first_filing_relative_path","original_sha256",
    "original_published_at","original_is_consolidated_TIFRS_first_version",
    "original_12_amounts_verified_and_double_reviewed",
    "event_status","event_official_notice_relative_path",
    "event_official_notice_sha256","event_issued_at",
    "event_affected_fiscal_year",
    "official_correction_search_archive_relative_path",
    "official_correction_search_archive_sha256",
    "full_five_year_search_verified","no_known_later_restatement",
    "reviewer_A","reviewer_B","method_owner_approved",
    "audit_notes",*METRICS,
)
ACCEPTED_FIELDS=("ticker","fiscal_year","label","label_target",
                 "original_sha256","original_published_at",
                 "outcome_archive_sha256","reviewer_A","reviewer_B",
                 "review_window_end",*METRICS)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save_csv(path,fields,rows):
    with Path(path).open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction="raise")
        w.writeheader();w.writerows(rows)

def make_queue(stage1_csv,output):
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("fy1315_stage2_immutable_label_queue")
    with Path(stage1_csv).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not set(SOURCE_FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("fy1315_stage2_wrong_fy2013_15_input")
        panel=list(reader)
    if len(panel)!=360 or len({(r["ticker"],r["fiscal_year"]) for r in panel})!=360:
        raise ValueError("fy1315_stage2_not_exactly_360_issuer_years")
    rows=[]
    for p in panel:
        y=int(p["fiscal_year"])
        if y not in YEARS or p["approved_for_supervision"]!="false":
            raise ValueError("fy1315_stage2_out_of_window_or_labels_already_set")
        r={col:"" for col in LABEL_FIELDS}
        r.update(
            ticker=p["ticker"],fiscal_year=y,
            label_target=TARGET,human_label="UNKNOWN",
            original_is_consolidated_TIFRS_first_version="false",
            original_12_amounts_verified_and_double_reviewed="false",
            event_status="NOT_YET_REVIEWED",
            event_affected_fiscal_year="",
            full_five_year_search_verified="false",
            no_known_later_restatement="UNKNOWN",
            method_owner_approved="false",
            audit_notes="Complete MOPS original-vintage PDF and historical correction/filing archive; "
                        "do not call search silence proof of normal.",
        )
        # Deliberately leave financial amounts empty. They must be copied
        # from original first-filed document, not the FinMind provisional tier.
        rows.append(r)
    output.mkdir(parents=True,exist_ok=True)
    save_csv(output/"fy2013_15_360_manual_0_1_review_QUEUE.csv",LABEL_FIELDS,rows)
    save_csv(output/"fy2013_15_verified_0_1_training_template.csv",ACCEPTED_FIELDS,[])
    result={
        "status":"FY1315_360_HUMAN_EVIDENCE_QUEUE_NOT_APPROVED_YET",
        "years":list(YEARS),"issuer_years":360,
        "human_positive_reviewed":0,"human_negative_reviewed":0,
        "target":TARGET,
        "source_panel_sha256":sha(stage1_csv),
        "outside_years_never_admitted":True,
        "reserved_1785_never_admitted":True,
        "first_filing_features_not_backfilled_from_later_version":True,
    }
    (output/"fy2013_15_stage2_review_manifest.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result

def safe_document(root,rel,expected_sha):
    p=Path(rel)
    if not rel or p.is_absolute() or ".." in p.parts or "\\" in rel:
        raise ValueError("fy1315_unsafe_or_missing_evidence_reference")
    fp=(root/p).resolve()
    if not fp.is_relative_to(root.resolve()) or fp.is_symlink() or not fp.is_file():
        raise ValueError("fy1315_missing_or_unsafe_official_document")
    if not re.fullmatch("[0-9a-f]{64}",expected_sha) or sha(fp)!=expected_sha:
        raise ValueError("fy1315_official_document_sha_mismatch")
    if fp.stat().st_size<16:
        raise ValueError("fy1315_empty_official_document")
    return fp

def add_five_years(dt):
    try:return dt.replace(year=dt.year+5)
    except ValueError:return dt.replace(year=dt.year+5,day=28)

def original_is_public_by_fixed_asof(fiscal_year,first_published):
    """We evaluate all firms at March 31 of the year AFTER the target FY."""
    if fiscal_year not in YEARS:
        return False
    taiwan_tz=timezone(timedelta(hours=8))
    asof_deadline=datetime(fiscal_year+1,3,31,23,59,59,tzinfo=taiwan_tz)
    return (datetime(fiscal_year,12,31,tzinfo=timezone.utc)
            <first_published<=asof_deadline)

def approve(review_csv,document_root,output,*,now=None):
    root=Path(document_root)
    out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("fy1315_do_not_replace_previously_approved_labels")
    with Path(review_csv).open("r",encoding="utf-8-sig",newline="") as f:
        d=csv.DictReader(f)
        if not set(LABEL_FIELDS).issubset(d.fieldnames or []):
            raise ValueError("fy1315_incompatible_human_review_schema")
        rows=list(d)
    if len(rows)!=360:
        raise ValueError("fy1315_review_queue_must_cover_all_360_company_years")
    seen=set();accepted=[];states=Counter()
    allowed=set(cohort())
    today=now or datetime.now(timezone.utc)
    for r in rows:
        year=int(r["fiscal_year"])
        ticker=r["ticker"]
        key=(ticker,year)
        if (key in seen or year not in YEARS or ticker=="1785"
            or ticker not in allowed or not ticker.isdecimal() or len(ticker)!=4):
            raise ValueError("fy1315_duplicate_or_unauthorized_sample")
        seen.add(key)
        if r["human_label"] not in ("0","1"):
            states["UNKNOWN"]+=1;continue
        if (r["label_target"]!=TARGET
            or r["reviewer_A"]==r["reviewer_B"]
            or not r["reviewer_A"].strip() or not r["reviewer_B"].strip()
            or r["method_owner_approved"]!="true"
            or r["original_is_consolidated_TIFRS_first_version"]!="true"
            or r["original_12_amounts_verified_and_double_reviewed"]!="true"):
            states["REJECTED_INCOMPLETE_DOUBLE_REVIEW"]+=1;continue
        original_document=safe_document(
            root,r["original_first_filing_relative_path"],r["original_sha256"])
        if original_document.suffix.lower() not in (".pdf",".xml",".xhtml",".html"):
            raise ValueError("fy1315_original_evidence_not_filing_format")
        if (original_document.suffix.lower()==".pdf"
            and not original_document.read_bytes().startswith(b"%PDF-")):
            raise ValueError("fy1315_not_real_pdf_bytes")
        first=timestamp(r["original_published_at"])
        horizon=add_five_years(first)
        # The FY+1 3/31 source cutoff is essential for historical replay.
        # Later IPO comparison figures cannot become FY2015 inputs.
        if not (original_is_public_by_fixed_asof(year,first)
                and horizon<=today):
            states["REJECTED_NOT_PUBLIC_BY_FY_PLUS_ONE_MARCH31_OR_UNMATURED"]+=1
            continue
        screening=safe_document(root,
            r["official_correction_search_archive_relative_path"],
            r["official_correction_search_archive_sha256"])
        if r["full_five_year_search_verified"]!="true":
            states["REJECTED_INCOMPLETE_OFFICIAL_CORRECTION_COVERAGE"]+=1;continue
        if r["human_label"]=="1":
            if (r["event_status"]!=OUTCOME_TYPES[0]
                or r["event_affected_fiscal_year"]!=str(year)):
                states["REJECTED_WRONG_EVENT_PERIOD_OR_KIND"]+=1;continue
            safe_document(root,r["event_official_notice_relative_path"],
                          r["event_official_notice_sha256"])
            announced=timestamp(r["event_issued_at"])
            if not first<announced<=horizon or announced>today:
                states["REJECTED_EVENT_OUTSIDE_FIVE_YEAR_HORIZON"]+=1;continue
            event_hash=r["event_official_notice_sha256"]
        else:
            if (r["event_status"]!=OUTCOME_TYPES[1]
                or r["no_known_later_restatement"]!="true"):
                states["REJECTED_UNKNOWN_OR_LATER_PROBLEM_NOT_NORMAL"]+=1;continue
            event_hash=r["official_correction_search_archive_sha256"]
        vals={}
        for field in METRICS:
            try:v=float(r[field])
            except (ValueError,TypeError):
                states["REJECTED_MISSING_ORIGINAL_12_VALUES"]+=1
                vals=None
                break
            if not __import__("math").isfinite(v) or abs(v)>1e16:
                states["REJECTED_BAD_ORIGINAL_FINANCIAL_VALUE"]+=1
                vals=None;break
            vals[field]=v
        if vals is None:continue
        accepted.append({
            "ticker":ticker,"fiscal_year":year,
            "label":r["human_label"],"label_target":TARGET,
            "original_sha256":r["original_sha256"],
            "original_published_at":r["original_published_at"],
            "outcome_archive_sha256":event_hash,
            "reviewer_A":r["reviewer_A"],"reviewer_B":r["reviewer_B"],
            "review_window_end":horizon.isoformat(),**vals,
        })
        states["APPROVED_1" if r["human_label"]=="1" else "APPROVED_0"]+=1
    if seen!={(ticker,year) for ticker in allowed for year in YEARS}:
        raise ValueError("fy1315_review_queue_missing_or_unlisted_issuer_year")
    out.mkdir(parents=True,exist_ok=True)
    accepted_path=out/"fy2013_15_approved_original_0_1.csv"
    save_csv(accepted_path,ACCEPTED_FIELDS,accepted)
    report={
        "status":"FY1315_HUMAN_REVIEW_GATE_COMPLETE",
        "reviewed_issuer_years":len(rows),
        "approved_issuer_years":len(accepted),
        "approved_positives":states["APPROVED_1"],
        "approved_negatives":states["APPROVED_0"],
        "review_states":dict(states),
        "label_definition":TARGET,
        "real_supervised_training_permitted":
            states["APPROVED_1"]>0 and states["APPROVED_0"]>0,
        "review_panel_sha256":sha(review_csv),
        "approved_panel_sha256":sha(accepted_path),
        "source_evidence_root":str(root),
        "no_later_fy_financial_features":True,
    }
    (out/"fy2013_15_stage2_label_gate.json").write_text(
        json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report

def main(argv=None):
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="mode",required=True)
    a=sub.add_parser("prepare")
    a.add_argument("--stage1-csv",required=True)
    a.add_argument("--out",required=True)
    b=sub.add_parser("approve")
    b.add_argument("--review-queue",required=True)
    b.add_argument("--official-evidence-root",required=True)
    b.add_argument("--out",required=True)
    x=p.parse_args(argv)
    result=(make_queue(x.stage1_csv,x.out) if x.mode=="prepare"
            else approve(x.review_queue,x.official_evidence_root,x.out))
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
