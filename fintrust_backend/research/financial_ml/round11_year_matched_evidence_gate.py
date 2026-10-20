"""Round11: fiscal-year-matched, original-as-of 24-month correction labels.

Keep three different targets separate:
  CORRECTION_24M: official FINANCIAL STATEMENT (not note-only) correction of
    the same original annual FY report, announced <24 calendar months from its
    verified first publication.
  RESTATEMENT_EVER: separate historic research, NOT used as 24m label.
  ADJUDICATED_FRAUD: separate independently adjudicated misstatement, NOT
    interchangeable with the mere fact a company corrected an annual report.

No lack-of-search-hit auto-0: negative outcome requires complete official
correction-announcement coverage, an archived evidence file and dual approval.
A company that restates 4 years later cannot become a 'clean' control.
"""
from __future__ import annotations
import argparse
import csv
import json
import re
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path
from .annual_panel_readiness import METRICS
from .round8_human_supervised_classifier import (
    verify_file,timestamp,feature_matrix,study
)
from .round10_disclosure_event_label_gate import cohort,evidence

SCHEMA="FINTRUST_ROUND11_ANNUAL_CORRECTION_WITHIN_24M_V1"
FIELDS=(
    "ticker","fiscal_year","year_type","target","label",
    "original_annual_filing_published_at",
    "original_pdf_relative_path","original_pdf_sha256",
    "original_first_publication_notice_path","original_first_publication_notice_sha256",
    "original_filing_statement_scope","original_filing_version",
    "outcome_notice_issued_at","outcome_document_relative_path","outcome_document_sha256",
    "outcome_report_type","outcome_affected_fiscal_year",
    "complete_official_screening_from","complete_official_screening_until",
    "official_search_coverage_manifest_path","official_search_coverage_manifest_sha256",
    "any_later_known_restatement_for_same_filing",
    "reviewer_a","reviewer_b","method_owner_approval",
    "original_12_features_double_reviewed",
    "outcome_and_period_double_reviewed",
    "company_eligible_to_be_separately_held_out",
    *METRICS,
)
TRACKER_FIELDS=("ticker","fiscal_year","review_focus",
                "published_filing_timestamp_known",
                "financial_statement_correction_lead",
                "note_only_or_interim_event",
                "approved_24m_positive","approved_24m_negative",
                "supervised_target_label",
                "source_evidence_url","review_next_step")
TARGET="ANNUAL_STATEMENT_CORE_AMOUNT_CORRECTION_WITHIN_24_CALENDAR_MONTHS"
EXCLUDE_CASE="1785"
MIN_SPLIT={"fit":(5,10),"validation":(2,2),"test":(2,2)}

def two_years_after(dt):
    try:return dt.replace(year=dt.year+2)
    except ValueError:return dt.replace(year=dt.year+2,day=28)

def year_band(year):
    return ("fit" if year<=2019 else
            "validation" if year<=2022 else "test")

def candidate_tracker(output,roster=None,lead_index=None):
    from .round10_disclosure_event_label_gate import ROSTER,LEADS
    ids=cohort(roster or ROSTER)
    events=evidence(lead_index or LEADS)
    per_year=defaultdict(list)
    for e in events:
        for y in e["candidate_fiscal_years"]:
            per_year[(e["ticker"],y)].append(e)
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("round11_tracker_output_immutable")
    rows=[]
    for t in ids:
        for y in range(2013,2026):
            leads=per_year[(t,y)]
            # Critically: prior Round10's year mapping is a lead, NOT
            # evidence of annual report core amount correction.
            potentially_core=[e for e in leads if e["event_class"] in (
                "MAIN_STATEMENT_CORRECTION","BALANCE_CASHFLOW_AND_NOTES_CORRECTION")]
            other=[e for e in leads if e not in potentially_core]
            rows.append({
                "ticker":t,"fiscal_year":y,
                "review_focus":"FY2022_MATCHED_PILOT" if y==2022 else
                     "FY2023_MATCHED_PILOT" if y==2023 else "OTHER_FY_BACKLOG",
                "published_filing_timestamp_known":"false",
                "financial_statement_correction_lead":";".join(
                    e["event_id"] for e in potentially_core),
                "note_only_or_interim_event":";".join(e["event_id"] for e in other),
                "approved_24m_positive":"false",
                "approved_24m_negative":"false",
                "supervised_target_label":"UNKNOWN",
                "source_evidence_url":";".join(e["document_url"] for e in leads),
                "review_next_step":"Retrieve original ANNUAL consolidated filing + publish-time "
                    "notice and full official issuer corrections within 24m; "
                    "double review before 0 or 1.",
            })
    output.mkdir(parents=True,exist_ok=True)
    with (output/"round11_same_fy_human_annotation_queue.csv").open(
            "w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=TRACKER_FIELDS);w.writeheader()
        w.writerows(rows)
    with (output/"round11_approved_year_matched_label_TEMPLATE.csv").open(
            "w",newline="",encoding="utf-8-sig") as f:
        csv.DictWriter(f,fieldnames=FIELDS).writeheader()
    summary={
        "status":"ROUND11_SAME_FY_PILOT_READY_LABEL_EVIDENCE_PENDING",
        "roster_company_count":len(ids),
        "year_rows":len(rows),"pilot_years":[2022,2023],
        "fy2022_candidate_company_count":120,
        "fy2023_candidate_company_count":120,
        "24m_positive_approved":0,"24m_negative_approved":0,
        "training_allowed":False,
        "target":TARGET,
        "target_not_equivalent_to_adjudicated_fraud":True,
        "unverified_quarterly_or_note_only_events_not_annual_labels":True,
    }
    (output/"round11_year_matched_prepare_report.json").write_text(
        json.dumps(summary,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return summary

def audited_rows(approved_panel,evidence_root,*,report_time=None):
    root=Path(evidence_root)
    now=report_time or datetime.now(timezone.utc)
    with Path(approved_panel).open("r",encoding="utf-8-sig",newline="") as f:
        rd=csv.DictReader(f)
        if not set(FIELDS).issubset(rd.fieldnames or []):
            raise ValueError("round11_approved_panel_schema_wrong")
        rows=list(rd)
    accepted=[]
    errors=Counter()
    seen=set()
    for r in rows:
        t=r["ticker"].strip()
        year=int(r["fiscal_year"])
        k=(t,year)
        if k in seen:raise ValueError("round11_duplicate_issuer_year")
        seen.add(k)
        if (t==EXCLUDE_CASE or t not in cohort()
            or year not in range(2013,2026)):
            raise ValueError("round11_outside_cohort_or_final_blind_case")
        if r["label"] not in ("0","1"):
            errors["DRAFT_UNKNOWN"]+=1;continue
        if (r["target"]!=TARGET
            or r["year_type"]!="ANNUAL"
            or r["original_filing_statement_scope"]!="consolidated"
            or r["original_filing_version"]!="ORIGINAL_FIRST_PUBLISHED"
            or r["original_12_features_double_reviewed"]!="true"
            or r["outcome_and_period_double_reviewed"]!="true"
            or r["method_owner_approval"]!="APPROVED"
            or r["reviewer_a"]==r["reviewer_b"]
            or not r["reviewer_a"] or not r["reviewer_b"]):
            errors["REVIEW_OR_SCOPE_INCOMPLETE"]+=1;continue
        original=verify_file(root,r["original_pdf_relative_path"],
                             r["original_pdf_sha256"])
        verify_file(root,r["original_first_publication_notice_path"],
                    r["original_first_publication_notice_sha256"])
        if original.suffix.lower() not in (".pdf",".xml",".xhtml",".html"):
            raise ValueError("round11_not_an_original_financial_statement")
        published=timestamp(r["original_annual_filing_published_at"])
        deadline=two_years_after(published)
        if (published<=datetime(year,12,31,tzinfo=timezone.utc)
            or published.year>year+2
            or published>now):
            raise ValueError("round11_original_annual_publication_time_wrong")
        # Year-matched controls must BOTH have had an equal-length window.
        # If an early correction event exists, its public date must be after
        # original published date; an early-public result cannot leak in.
        if r["label"]=="1":
            if (r["outcome_report_type"]!="CORE_AMOUNT_CORRECTION_ANNUAL"
                or r["outcome_affected_fiscal_year"]!=str(year)):
                raise ValueError("round11_not_same_year_annual_correction")
            announced=timestamp(r["outcome_notice_issued_at"])
            if not published<announced<=deadline or announced>now:
                raise ValueError("round11_correction_outside_equal_24_month_window")
            verify_file(root,r["outcome_document_relative_path"],
                        r["outcome_document_sha256"])
            if r["company_eligible_to_be_separately_held_out"]!="true":
                errors["HOLDOUT_RESTRICTION_MISSING"]+=1;continue
        else:
            if r["outcome_report_type"]!="NONE_FOUND_AFTER_EXHAUSTIVE_OFFICIAL_ARCHIVE_REVIEW":
                raise ValueError("round11_negative_is_unsupported_search_absence")
            if r["any_later_known_restatement_for_same_filing"]!="false":
                errors["POST_HORIZON_RESTATEMENT_CONTAMINATION"]+=1;continue
            if deadline>now:
                errors["NEGATIVE_OUTCOME_FOLLOWUP_NOT_YET_COMPLETE"]+=1;continue
            start=timestamp(r["complete_official_screening_from"])
            through=timestamp(r["complete_official_screening_until"])
            if start>published or through<deadline:
                errors["INCOMPLETE_FULL_OFFICIAL_24M_COVERAGE"]+=1;continue
            verify_file(root,r["official_search_coverage_manifest_path"],
                        r["official_search_coverage_manifest_sha256"])
        data=[]
        for f in METRICS:
            try: v=float(r[f])
            except (ValueError,TypeError):
                raise ValueError("round11_missing_original_financial_feature:"+f)
            if not __import__("math").isfinite(v) or abs(v)>1e16:
                raise ValueError("round11_bad_amount")
            data.append(v)
        accepted.append({
            "ticker":t,"fiscal_year":year,"label":int(r["label"]),
            "features":data,"original_sha256":r["original_pdf_sha256"],
            "target":TARGET,"first_published_utc":published.isoformat(),
            "deadline_utc":deadline.isoformat(),
            "source_tier":"FULL_OFFICIAL_ISSUER_ARCHIVE_DOUBLE_REVIEWED",
        })
    return accepted,dict(errors)

def same_year_gate(records):
    partitions=defaultdict(list)
    for r in records:
        partitions[year_band(r["fiscal_year"])].append(r)
    issues=[]
    eligible=True
    for partition,(pmin,nmin) in MIN_SPLIT.items():
        rows=partitions[partition]
        count=Counter(r["label"] for r in rows)
        if count[1]<pmin or count[0]<nmin:
            eligible=False;issues.append(f"{partition}:sample_counts_{count[1]}_positive_{count[0]}_negative")
        peryear=defaultdict(Counter)
        for x in rows:peryear[x["fiscal_year"]][x["label"]]+=1
        matched_years=sorted(y for y,c in peryear.items() if c[1]>0 and c[0]>0)
        if not matched_years:
            eligible=False;issues.append(f"{partition}:NO_SAME_FY_POSITIVE_NEGATIVE_MATCH")
        for fiscal_year,counts in peryear.items():
            if not counts[1] or not counts[0]:
                eligible=False
                issues.append(f"{partition}:UNMATCHED_FISCAL_YEAR:{fiscal_year}")
    assigned={}
    for name,samples in partitions.items():
        for r in samples:
            if r["ticker"] in assigned and assigned[r["ticker"]]!=name:
                eligible=False;issues.append("SAME_ISSUER_CROSSED_PARTITIONS")
            assigned[r["ticker"]]=name
    return eligible,issues

def evaluate(approved_panel,evidence_root,output):
    out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("round11_training_output_immutable")
    records,blocked=audited_rows(approved_panel,evidence_root)
    allow,issues=same_year_gate(records)
    if allow:
        result=study(records,out,persist=True)
    else:
        out.mkdir(parents=True,exist_ok=True)
        result={
            "status":"ROUND11_MISSING_EQUAL_FY_AUDITED_0_AND_1_DATA_NO_TRAIN",
            "target":TARGET,
            "approved_sample_count":len(records),
            "approved_positive_count":sum(r["label"]==1 for r in records),
            "approved_negative_count":sum(r["label"]==0 for r in records),
            "blocked_reviews":blocked,
            "year_match_rejections":issues,
            "real_f1":None,"real_precision":None,"real_recall":None,
            "fraud_accuracy_claim_allowed":False,
            "persisted_model_count":0,
        }
    (out/"round11_evidence_matched_training_report.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",
        encoding="utf-8")
    return result

def main(argv=None):
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="mode",required=True)
    a=sub.add_parser("prepare")
    a.add_argument("--out",required=True)
    b=sub.add_parser("train")
    b.add_argument("--approved-panel",required=True)
    b.add_argument("--evidence-root",required=True)
    b.add_argument("--out",required=True)
    x=p.parse_args(argv)
    print(json.dumps(
        candidate_tracker(x.out) if x.mode=="prepare"
        else evaluate(x.approved_panel,x.evidence_root,x.out),
        ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
