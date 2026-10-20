"""FinTrust FY2013-2015 Stage 1 — reuse immutable annual candidate panel.

120 exact issuer IDs x FY2013/2014/2015 = 360 REVIEW TARGETS, not 360
verified original filings. Candidate numeric data stays explicitly provisional.
No other FY in any feature row, model label or training output.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from .annual_panel_readiness import METRICS
from .round3_research_models import ANNUAL_COLUMNS
from .round10_disclosure_event_label_gate import cohort

YEARS=(2013,2014,2015)
FIELDS=(
    "ticker","fiscal_year","research_window",
    "candidate_complete_12","numeric_source_tier",
    "original_annual_filing_found","original_as_first_filed_verified",
    "original_as_first_filed_sha256","first_publication_at",
    "consolidated_TIFRS_verified","financial_field_review_status",
    "source_audit_status","material_restatement_5y_label",
    "adjudicated_misstatement_label","approved_for_supervision",
    "official_MOPS_correction_search","official_MOPS_historical_notice",
    *METRICS,
)
MOPS_CORRECTION="https://mops.twse.com.tw/mops/web/t120sb02_q10"
MOPS_NOTICE="https://mops.twse.com.tw/mops/web/t05st01"


def locked_2013_15_candidate_panel(source,output,roster=None):
    from .round10_disclosure_event_label_gate import ROSTER
    output=Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError("fy1315_stage1_do_not_overwrite")
    ids=cohort(roster or ROSTER)
    with Path(source).open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not set(ANNUAL_COLUMNS).issubset(reader.fieldnames or []):
            raise ValueError("fy1315_existing_round1_schema_not_found")
        data=list(reader)
    selected={}
    seen=set()
    for r in data:
        ticker=r["ticker"].strip()
        year=int(r["fiscal_year"])
        if ticker not in ids or year not in range(2013,2026):
            raise ValueError("fy1315_unexpected_issuer_or_year_in_source")
        k=(ticker,year)
        if k in seen:
            raise ValueError("fy1315_duplicate_same_fiscal_year")
        seen.add(k)
        if year in YEARS:
            selected[k]=r
        if r["label_status"]!="UNKNOWN" or r["training_admitted"].lower()!="false":
            raise ValueError("fy1315_original_source_contains_unapproved_labels")
    if len(seen)!=1560 or len(selected)!=360:
        raise ValueError("fy1315_round1_not_exactly_120x13_and_120x3")
    rows=[]
    counts=Counter()
    for ticker in ids:
        for year in YEARS:
            r=selected[(ticker,year)]
            complete=r["complete_candidate_vector"].lower()=="true"
            row={
                "ticker":ticker,"fiscal_year":year,
                "research_window":"FY2013_FY2014_FY2015_ONLY",
                "candidate_complete_12":str(complete).lower(),
                "numeric_source_tier":"FINMIND_PROVISIONAL_NOT_ORIGINAL",
                "original_annual_filing_found":"false",
                "original_as_first_filed_verified":"false",
                "original_as_first_filed_sha256":"",
                "first_publication_at":"",
                "consolidated_TIFRS_verified":"false",
                "financial_field_review_status":"NOT_REVIEWED",
                "source_audit_status":"UNREVIEWED_ORIGINAL_VERSION_AND_FILING_DUTY",
                "material_restatement_5y_label":"UNKNOWN",
                "adjudicated_misstatement_label":"UNKNOWN",
                "approved_for_supervision":"false",
                "official_MOPS_correction_search":MOPS_CORRECTION,
                "official_MOPS_historical_notice":MOPS_NOTICE,
            }
            for field in METRICS:
                # Feature COPY is for diagnostic data-readiness only. It is
                # unapproved & MUST NOT be mixed with a verified training row.
                row[field]=r.get(field,"")
            rows.append(row)
            counts["complete_candidate_12" if complete else "incomplete_candidate_12"]+=1
    output.mkdir(parents=True,exist_ok=True)
    with (output/"fy2013_2015_exact_360_financial_source_audit.csv").open(
            "w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)
    m={
        "status":"FY2013_2015_ONLY_SOURCE_AUDIT_CREATED",
        "years":list(YEARS),"companies":120,"issuer_year_rows":360,
        "annual_full_input_source_count":len(data),
        "original_candidate_12_complete":counts["complete_candidate_12"],
        "original_candidate_12_incomplete":counts["incomplete_candidate_12"],
        "verified_first_filing_rows":0,
        "approved_positive_labels":0,"approved_negative_labels":0,
        "fraud_training_permitted":False,
        "all_numeric_tier":"FINMIND_PROVISIONAL",
        "source_panel_sha256":hashlib.sha256(Path(source).read_bytes()).hexdigest(),
        "original_2013_15_features_only":True,
        "later_announcements_for_labels_not_features":True,
        "unlisted_historical_company_may_not_have_public_report":True,
        "no_inferred_normal_labels":True,
    }
    (output/"fy2013_2015_stage1_audit_report.json").write_text(
        json.dumps(m,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return m


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--round1-annual-index",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args(argv)
    print(json.dumps(locked_2013_15_candidate_panel(
        a.round1_annual_index,a.out),ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
