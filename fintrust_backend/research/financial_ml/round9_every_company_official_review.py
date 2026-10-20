"""Round9: inventory EVERY issuer from the exact local 120-company study source.

A source lead is not an approved 0/1 label. This file deliberately never
constructs a 0 label because a web search returned no adverse record.

Output firm AND issuer-fiscal-year audit matrices to support genuine manual
per-company official source searches, *without* changing Round8 approvals.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .round3_research_models import ANNUAL_COLUMNS

COMPANY_FIELDS=(
    "ticker","years_in_round1","year_rows","full_12_years",
    "all_years_label_state","candidate_case_source_status",
    "source_research_completed","primary_case_evidence_url",
    "source_type","source_review_notes",
    "original_filing_verified","negative_followup_verified",
    "reviewer_a","reviewer_b","method_owner",
    "company_review_status",
)
YEAR_FIELDS=(
    "ticker","fiscal_year","complete_12_financial_amounts",
    "reviewed_source_case_lead","source_year_specificity",
    "proposed_label","approved_training_label","source_evidence_url",
    "source_document_issued_on","original_first_filing_verified",
    "same_year_outcome_document_verified",
    "normal_two_year_followup_reviewed","human_reviewer_a",
    "human_reviewer_b","method_owner_approval",
    "company_year_review_status",
)


def read_index(path):
    path=Path(path)
    with path.open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not set(ANNUAL_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError("round9_not_existing_round1_annual_index")
        data=list(reader)
    firms=defaultdict(dict)
    for r in data:
        t=r["ticker"].strip()
        y=int(r["fiscal_year"])
        if not re.fullmatch(r"[1-9][0-9]{3}",t) or t=="1785" or not 2013<=y<=2025:
            raise ValueError("round9_bad_cohort_or_reserved_1785")
        if y in firms[t]:
            raise ValueError("round9_duplicate_issuer_year")
        if r["label_status"]!="UNKNOWN" or r["training_admitted"].lower()!="false":
            raise ValueError("round9_existing_source_already_claims_approved_label")
        firms[t][y]=r
    if len(firms)!=120:
        raise ValueError("round9_expected_exact_120_issuers_received:"+str(len(firms)))
    if len(data)!=120*13:
        raise ValueError("round9_expected_13_years_per_issuer")
    if any(set(years)!=set(range(2013,2026)) for years in firms.values()):
        raise ValueError("round9_missing_issuer_fiscal_year_range")
    return firms,hashlib.sha256(path.read_bytes()).hexdigest()


def official_case_leads(path):
    raw=json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version")!="fintrust_manual_outcome_source_leads_v1":
        raise ValueError("round9_official_leads_schema_changed")
    res={}
    for c in raw["cases"]:
        t=c["ticker"]
        if t in res or not re.fullmatch(r"[1-9][0-9]{3}",t):
            raise ValueError("round9_bad_duplicate_lead_company")
        if c.get("approved_supervised_training") is not False:
            raise ValueError("round9_unauthorized_source_lead_training_approval")
        if not str(c["primary_url"]).startswith("https://"):
            raise ValueError("round9_non_https_primary_document")
        res[t]=c
    if "1785" not in res:
        raise ValueError("round9_final_case_lead_missing")
    return res


def make_audit(annual_index,leads_path,output):
    out=Path(output)
    if out.exists() and any(out.iterdir()):
        raise FileExistsError("round9_company_research_output_immutable")
    firms,digest=read_index(annual_index)
    leads=official_case_leads(leads_path)
    all_rows=[];years=[];case_lead_count=0
    for ticker,data in sorted(firms.items()):
        candidate=leads.get(ticker)
        if candidate:case_lead_count+=1
        included_years=sorted(data)
        year_candidate_source_status=(
            "OFFICIAL_SOURCE_LEAD_FOUND_REQUIRES_PERIOD_APPROVAL"
            if candidate else "NO_VERIFIED_CASE_RESEARCH_IN_THIS_PACKET")
        all_rows.append({
            "ticker":ticker,"years_in_round1":"2013-2025",
            "year_rows":13,
            "full_12_years":sum(str(x["complete_candidate_vector"]).lower()=="true"
                                for x in data.values()),
            "all_years_label_state":"UNKNOWN",
            "candidate_case_source_status":year_candidate_source_status,
            "source_research_completed":"false",
            "primary_case_evidence_url":candidate["primary_url"] if candidate else "",
            "source_type":candidate["source_category"] if candidate else "",
            "source_review_notes":candidate["reviewed_issue"] if candidate else "",
            "original_filing_verified":"false",
            "negative_followup_verified":"false",
            "reviewer_a":"","reviewer_b":"","method_owner":"",
            "company_review_status":"OFFICIAL_CASE_YEAR_REVIEW_PENDING"
                 if candidate else "PENDING_INDIVIDUAL_COMPANY_SOURCE_RESEARCH",
        })
        for year in included_years:
            key=year in candidate["affected_fiscal_years"] if candidate else False
            source_url=candidate["primary_url"] if key else ""
            years.append({
                "ticker":ticker,"fiscal_year":year,
                "complete_12_financial_amounts":
                    str(data[year]["complete_candidate_vector"]).lower(),
                "reviewed_source_case_lead":str(key).lower(),
                "source_year_specificity":("PRIMARY_LEAD_YEAR_NEEDS_FILING_PROOF"
                    if key else "NO_APPROVED_YEAR_OUTCOME"),
                "proposed_label":"CANDIDATE_1" if key else "UNKNOWN",
                "approved_training_label":"UNKNOWN",
                "source_evidence_url":source_url,
                "source_document_issued_on":"",
                "original_first_filing_verified":"false",
                "same_year_outcome_document_verified":"false",
                "normal_two_year_followup_reviewed":"false",
                "human_reviewer_a":"","human_reviewer_b":"",
                "method_owner_approval":"PENDING",
                "company_year_review_status":(
                    "POTENTIAL_EVENT_YEAR_MANUAL_CONFIRMATION_REQUIRED" if key
                    else "REQUIRES_OFFICIAL_NEGATIVE_AND_POSITIVE_CASE_SEARCH"),
            })
    out.mkdir(parents=True,exist_ok=True)
    def write(path,headers,entries):
        with path.open("w",encoding="utf-8-sig",newline="") as f:
            w=csv.DictWriter(f,fieldnames=headers,extrasaction="raise")
            w.writeheader();w.writerows(entries)
    write(out/"round9_each_company_research_queue.csv",COMPANY_FIELDS,all_rows)
    write(out/"round9_each_issuer_year_research_queue.csv",YEAR_FIELDS,years)
    review={
        "status":"ROUND9_ALL_120_COMPANY_AUDIT_QUEUE_GENERATED_NOT_ALL_REVIEWED",
        "frozen_annual_index_sha256":digest,
        "full_company_count":len(all_rows),
        "full_company_year_count":len(years),
        "official_source_lead_companies_in_cohort":case_lead_count,
        "official_source_lead_tickers":[x["ticker"] for x in all_rows
                                      if x["primary_case_evidence_url"]],
        "source_researched_and_approved_company_count":0,
        "approved_positive_years":0,"approved_negative_years":0,
        "UNKNOWN_training_labels":len(years),
        "1785_reserved_final_case_excluded":True,
        "labels_are_not_assigned_zero_on_no_search_results":True,
        "files":["round9_each_company_research_queue.csv",
                 "round9_each_issuer_year_research_queue.csv"],
    }
    (out/"round9_company_audit_report.json").write_text(
        json.dumps(review,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return review


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--annual-index",required=True)
    p.add_argument("--official-leads",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args(argv)
    print(json.dumps(make_audit(a.annual_index,a.official_leads,a.out),
                     ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
