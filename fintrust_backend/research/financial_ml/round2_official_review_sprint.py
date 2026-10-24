"""Round2 Y1 official evidence sprint generator: no binary labels assigned.

Uses PRIVATE TEJ calendar-year evidence and PRIVATE FinLab-TEJ reviewed
candidate ledger. Selects cross-source priority positives (review leads)
and 20 deterministic *unlabeled* matched controls per FY2016-2020.
TEJ zero is never evidence of official no-restatement; control candidate
status remains UNKNOWN until complete, dated official MOPS 24m coverage.

python -m research.financial_ml.round2_official_review_sprint \
 --finlab-tej-cases data/financial_ml/round2_tej_transparency/finlab_tej_join_review_private.csv \
 --tej-year-csv data/financial_ml/round2_tej_transparency/tej_calendar_year_evidence_private.csv \
 --out data/financial_ml/round2_official_sprint_20261025
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from research.financial_ml.round2_label_cohorts import _immutable

FIELDS = (
    "case_id","ticker","issuer_name","fiscal_year","candidate_type",
    "rank","tej_notice_calendar_year_nonzero_cue","evidence_confidence",
    "latest_candidate_notice","notice_count","notice_title",
    "original_mops_filing_publication_date","original_filing_evidence_url",
    "official_restated_filing_url","mops_amendment_notice_url",
    "correction_date","affected_consolidated_annual_fy_confirmed",
    "corrected_core_values_confirmed","within_24m_confirmed",
    "reviewer","review_status","y_official_annual_24m",
    "mops_search_entry","notes",
)
MONTHS=";".join(f"{x:02d}" for x in range(1,13))


def read_csv(path, required):
    raw=Path(path).read_bytes()
    txt=None
    for enc in ("utf-8-sig","cp950"):
        try:
            txt=raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if txt is None:
        raise ValueError("review_csv_unreadable")
    reader=csv.DictReader(io.StringIO(txt))
    if not reader.fieldnames or not set(required).issubset(reader.fieldnames):
        raise ValueError("review_required_columns_missing")
    return list(reader),hashlib.sha256(raw).hexdigest()


def _one(ticker,name,fy,typ,rank,tej,confidence,**extra):
    return dict(
        case_id=f"{ticker}-FY{fy}",ticker=ticker,issuer_name=name,
        fiscal_year=fy,candidate_type=typ,rank=rank,
        tej_notice_calendar_year_nonzero_cue=str(tej).lower(),
        evidence_confidence=confidence,
        latest_candidate_notice=extra.get("latest_candidate_notice",""),
        notice_count=extra.get("notice_count",""),
        notice_title=extra.get("notice_title",""),
        original_mops_filing_publication_date="",
        original_filing_evidence_url="",
        official_restated_filing_url="",
        mops_amendment_notice_url="",correction_date="",
        affected_consolidated_annual_fy_confirmed="",
        corrected_core_values_confirmed="",within_24m_confirmed="",
        reviewer="",review_status=(
            "PENDING_OFFICIAL_DOCUMENTS" if typ=="POSITIVE_EVENT_REVIEW" else
            "PENDING_FULL_24M_MOPS_COVERAGE"),
        y_official_annual_24m="",
        mops_search_entry="https://mops.twse.com.tw/mops/web/index",
        notes=("Verify official original first PUBLIC filing date, affected annual CONSOLIDATED FY, "
               "core changes, event date and <=24 months. TEJ/FinLab cue is not approved.")
              if typ=="POSITIVE_EVENT_REVIEW" else
              ("No FinLab lead and 3 later TEJ calendar-year counts=0. "
               "DO NOT LABEL 0 until full MOPS correction/restatement window "
               "and financial report source versions are reviewed."))


def build(finlab_tej_cases,tej_year_csv,out,controls_per_fy=20):
    cases,finlab_sha=read_csv(finlab_tej_cases,{"case_id","ticker","fiscal_year","rank",
          "first_notice_date","tej_notice_year_max_count","holdout","training_y"})
    yearly,tej_sha=read_csv(tej_year_csv,{"ticker","calendar_year","observed_month_count",
          "observed_months","max_reported_restatement_count","issuer_name"})
    index={}
    for r in yearly:
        k=(r["ticker"],int(r["calendar_year"]))
        if k in index:
            raise ValueError("duplicate_tej_year")
        index[k]=r
    finlab_pairs=set()
    positives=[]
    for c in cases:
        ticker=c["ticker"]
        fy=int(c["fiscal_year"])
        pair=(ticker,fy)
        if pair in finlab_pairs:
            raise ValueError("duplicate_finlab_case")
        finlab_pairs.add(pair)
        if c["training_y"].strip():
            raise ValueError("refuse_mixed_training_y")
        if c["rank"] not in ("P0","P1"):
            continue
        tej=int(float(c.get("tej_notice_year_max_count") or 0))>0
        positives.append(_one(ticker,c.get("issuer_name",""),fy,
            "POSITIVE_EVENT_REVIEW",c["rank"],tej,
            "CROSS_SOURCE_CUE_UNVERIFIED" if tej else "FINLAB_NOTICE_CUE_ONLY",
            latest_candidate_notice=c.get("last_notice_date",""),
            notice_count=c.get("notice_count",""),
            notice_title=c.get("representative_title","")))
    positives.sort(key=lambda r:(r["rank"],r["tej_notice_calendar_year_nonzero_cue"]!="true",
                                 r["fiscal_year"],r["ticker"]))
    if len({r["case_id"] for r in positives})!=len(positives):
        raise ValueError("positive_case_duplicate")
    sampled=[]
    rng=random.Random(20261025)
    for fy in range(2016,2021):
        pool=[]
        for (ticker,year),base in index.items():
            if year!=fy or (ticker,fy) in finlab_pairs or ticker=="1785":
                continue
            if not re.fullmatch(r"\d{4}",ticker):
                continue
            later=[index.get((ticker,fy+n)) for n in (1,2,3)]
            if any(v is None for v in later):
                continue
            if any(v["observed_months"]!=MONTHS or
                   v["observed_month_count"]!="12" or
                   float(v["max_reported_restatement_count"])!=0 for v in later):
                continue
            pool.append((ticker,base["issuer_name"]))
        if len(pool)<controls_per_fy:
            raise ValueError("not_enough_candidate_controls")
        for ticker,name in sorted(rng.sample(sorted(pool),controls_per_fy)):
            sampled.append(_one(ticker,name,fy,"UNLABELED_CONTROL_REVIEW",
                 "NEGATIVE_CONTROL_CHECK",False,
                 "THREE_TEJ_ZERO_YEARS_NO_FINLAB_CASE_NOT_OFFICIAL_NEGATIVE"))
    rows=positives+sampled
    f=io.StringIO(newline="")
    w=csv.DictWriter(f,fieldnames=FIELDS,lineterminator="\n")
    w.writeheader();w.writerows(rows)
    blob=f.getvalue().encode("utf-8-sig")
    summary={
        "schema":"fintrust_official_label_sprint_selection_v1",
        "finlab_source_sha256":finlab_sha,"tej_year_source_sha256":tej_sha,
        "positive_notice_candidates":len(positives),
        "cross_source_positive_cue":sum(x["tej_notice_calendar_year_nonzero_cue"]=="true" for x in positives),
        "control_candidates":len(sampled),
        "sample_seed":20261025,"negative_controls_per_fy":controls_per_fy,
        "official_y_1_assigned":0,"official_y_0_assigned":0,
        "label_status":"ALL_UNKNOWN_PENDING_OFFICIAL_MOPS",
        "output_sha256":hashlib.sha256(blob).hexdigest(),
    }
    dst=Path(out)
    _immutable(dst/"official_y1_evidence_review_sprint_private.csv",blob)
    _immutable(dst/"official_sprint_summary.json",
       (json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode("utf-8"))
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--finlab-tej-cases",required=True)
    p.add_argument("--tej-year-csv",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--controls-per-fy",type=int,default=20)
    a=p.parse_args()
    print(json.dumps(build(a.finlab_tej_cases,a.tej_year_csv,a.out,a.controls_per_fy),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
