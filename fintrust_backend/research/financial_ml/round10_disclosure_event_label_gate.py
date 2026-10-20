"""Round10 exact-cohort disclosure evidence integration (NOT supervised fraud labels).

Initial public-event leads from 2026-10-20 are candidate annotations only.
An entire fiscal year's official archives cannot be certified just because a
web search had no correction hits. Training must use Round8's separately
approved dual-reviewed original-vintage panel.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import defaultdict,Counter
from pathlib import Path
from .round3_research_models import ANNUAL_COLUMNS
from .round8_human_supervised_classifier import REVIEW_FIELDS

YEAR_COLS=("ticker","fiscal_year","available_annual_numeric_candidate",
           "event_lead_ids","event_classes","disclosure_urls",
           "event_screening_state","supervised_fraud_label",
           "original_first_filing_verified","reviewed_negative_control",
           "approved_supervised_training","note")
QTR_COLS=("ticker","period","fiscal_year","quarter",
          "event_lead_ids","event_classes",
          "supervised_fraud_label","original_quarterly_filing_verified",
          "review_completed","event_disclosure_urls")
CASE_TYPES={
    "MAIN_STATEMENT_CORRECTION","QUARTER_RESTATEMENT_AND_OTHERS_CORRECTION",
    "RELATED_PARTY_FILING_NOTE_CORRECTION",
    "INVESTMENT_DISCLOSURE_NOTE_CORRECTION",
    "BALANCE_CASHFLOW_AND_NOTES_CORRECTION",
    "PRIOR_PERIOD_NOTE_CORRECTION",
    "IXBRL_TAG_CORRECTION",
}
NON_CASE_TYPES={
    "MONTHLY_REVENUE_CORRECTION_NOT_FINANCIAL_STATEMENT",
    "REVENUE_ANNOUNCEMENT_NOT_NET_PROFIT_CORRECTION",
    "AFFILIATE_BUSINESS_REPORT_NON_TARGET",
    "BOARD_RESULTS_DISCLOSURE_NOT_RESTATEMENT",
    "BOARD_MEETING_DATE_NON_TARGET",
}
LEADS=Path(__file__).with_name("round10_user_cohort_20261020_disclosure_leads.json")
ROSTER=Path(__file__).with_name("round10_user_confirmed_120_tickers.txt")


def cohort(path=ROSTER):
    ids=[x.strip() for x in Path(path).read_text(encoding="utf-8-sig").splitlines()
         if x.strip()]
    if len(ids)!=120 or len(set(ids))!=120 or "1785" in ids or any(
        len(x)!=4 or not x.isascii() or not x.isdecimal() for x in ids):
        raise ValueError("round10_exact_120_roster_invalid")
    return sorted(ids)


def evidence(path=LEADS):
    x=json.loads(Path(path).read_text(encoding="utf-8"))
    if x.get("schema")!="FINTRUST_ROUND10_EVENT_SCREENING_V1":
        raise ValueError("round10_event_schema_invalid")
    seen=set();r=[]
    for e in x["events"]:
        if e["event_id"] in seen or e["event_class"] not in CASE_TYPES|NON_CASE_TYPES:
            raise ValueError("round10_duplicate_or_bad_event_class")
        seen.add(e["event_id"])
        if (e["approved_for_training"] is not False
            or e["fraud_label"]!="UNKNOWN"
            or e["first_original_filing_verified"] is not False
            or not e["document_url"].startswith("https://")):
            raise ValueError("round10_public_notice_fraud_approval_forged")
        if any(not 2013<=int(y)<=2025 for y in e["candidate_fiscal_years"]):
            raise ValueError("round10_event_year_outside_scope")
        for quarter in e["candidate_quarters"]:
            if not (len(quarter)==6 and quarter[:4].isdigit()
                    and quarter[4]=="Q" and quarter[5] in "1234"):
                raise ValueError("round10_event_quarter_invalid")
        r.append(e)
    return r


def index(annual_index,selected):
    with Path(annual_index).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not set(ANNUAL_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError("round10_source_annual_schema_invalid")
        content=list(reader)
    if len(content)!=1560:
        raise ValueError("round10_expected_1560_annual_rows")
    by={}
    for row in content:
        k=(row["ticker"],int(row["fiscal_year"]))
        if (k in by or row["label_status"]!="UNKNOWN"
            or row["training_admitted"].lower()!="false"):
            raise ValueError("round10_existing_training_or_duplicate_annual")
        by[k]=row
    if set(x[0] for x in by)!=set(selected) or any(
        (t,y) not in by for t in selected for y in range(2013,2026)):
        raise ValueError("round10_real_round1_cohort_disagrees_with_user_roster")
    return by


def materialize(annual_index,output,*,roster=ROSTER,lead_index=LEADS):
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("round10_no_overwrite_existing_manual_audit")
    ids=cohort(roster)
    events=evidence(lead_index)
    annual=index(annual_index,ids)
    group=defaultdict(list);qgroup=defaultdict(list)
    for e in events:
        if e["ticker"] not in ids:
            raise ValueError("round10_event_outside_user_cohort")
        for y in e["candidate_fiscal_years"]:
            group[(e["ticker"],int(y))].append(e)
        for q in e["candidate_quarters"]:
            qgroup[(e["ticker"],q)].append(e)
    yrows=[];qrows=[];manual_rows=[];counts=Counter()
    for t in ids:
        for y in range(2013,2026):
            src=annual[(t,y)]
            events_y=group[(t,y)]
            cases=[e for e in events_y if e["event_class"] in CASE_TYPES]
            state=("COMPANY_DISCLOSURE_CORRECTION_LEAD_REQUIRES_HUMAN_ADJUDICATION"
                   if cases else "NON_TARGET_DISCLOSURE_ONLY"
                   if events_y else "NOT_COMPLETED_HISTORICAL_OFFICIAL_SCREENING")
            yrows.append({
                "ticker":t,"fiscal_year":y,
                "available_annual_numeric_candidate":src["complete_candidate_vector"],
                "event_lead_ids":";".join(e["event_id"] for e in events_y),
                "event_classes":";".join(e["event_class"] for e in events_y),
                "disclosure_urls":";".join(e["document_url"] for e in events_y),
                "event_screening_state":state,
                "supervised_fraud_label":"UNKNOWN",
                "original_first_filing_verified":"false",
                "reviewed_negative_control":"false",
                "approved_supervised_training":"false",
                "note":"PUBLIC DISCLOSURE CANDIDATE NOT CONFIRMED FRAUD OR CLEAN FINANCIALS",
            })
            counts[state]+=1
            if events_y:
                manual_rows.append({
                    "sample_key":f"{t}:{y}FY","ticker":t,"fiscal_year":y,
                    "sample_grain":"issuer_fiscal_year",
                    "candidate_financial_source_tier":
                        "MOPS_ISSUER_DISCLOSURE_REPUBLICATION_NOT_ORIGINAL",
                    "proposed_outcome":"UNKNOWN","outcome_reason":
                        "Requires period-specific restatement/misstatement adjudication",
                    "positive_regulator_or_court_document":"",
                    "negative_followup_review_document":"",
                    "first_published_original_pdf_evidence":"",
                    "first_publication_notice_evidence":"",
                    "reviewer_a":"","reviewer_b":"","method_owner":"",
                    "review_status":"PENDING_SOURCE_AND_PERIOD_APPROVAL",
                    "comments":"; ".join(e["event_id"]+":"+e["document_url"]
                                         for e in events_y),
                })
            for q in range(1,5):
                qname=f"{y}Q{q}";listed=qgroup[(t,qname)]
                qrows.append({
                    "ticker":t,"period":qname,"fiscal_year":y,"quarter":q,
                    "event_lead_ids":";".join(e["event_id"] for e in listed),
                    "event_classes":";".join(e["event_class"] for e in listed),
                    "supervised_fraud_label":"UNKNOWN",
                    "original_quarterly_filing_verified":"false",
                    "review_completed":"false",
                    "event_disclosure_urls":";".join(e["document_url"] for e in listed),
                })
    if len(yrows)!=1560 or len(qrows)!=6240:
        raise ValueError("round10_incomplete_company_period_review")
    output.mkdir(parents=True,exist_ok=True)
    def write(name,cols,rs):
        with (output/name).open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=cols,extrasaction="raise")
            w.writeheader();w.writerows(rs)
    write("round10_1560_annual_manual_review.csv",YEAR_COLS,yrows)
    write("round10_6240_quarter_manual_review.csv",QTR_COLS,qrows)
    write("round10_official_event_candidate_human_review.csv",REVIEW_FIELDS,manual_rows)
    result={
        "status":"ROUND10_DISCLOSURE_LEAD_COHORT_READY_SUPERVISED_LABELS_NOT_APPROVED",
        "companies":120,"annual_periods":1560,"quarterly_periods":6240,
        "notice_leads":len(events),"unique_notice_companies":
            len(set(e["ticker"] for e in events)),
        "candidate_issuer_year_review_rows":len(manual_rows),
        "annual_screening_status_counts":dict(counts),
        "fraud_positive_labels_approved":0,"negative_controls_approved":0,
        "supervised_classifier_fit_allowed":False,
        "true_fraud_accuracy":None,"true_fraud_precision":None,
        "true_fraud_recall":None,"true_fraud_f1":None,
        "reporting_cutoff":"2026-10-20",
        "current_cohort_sha256":hashlib.sha256(Path(roster).read_bytes()).hexdigest(),
        "real_round1_annual_sha256":hashlib.sha256(
            Path(annual_index).read_bytes()).hexdigest(),
        "scope":"Event leads are verified announcement texts, not certified court fraud or absence of other filings.",
        "no_prod_writes":True,
    }
    (output/"round10_label_gate_report.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    return result


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--annual-index",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args(argv)
    print(json.dumps(materialize(a.annual_index,a.out),ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
