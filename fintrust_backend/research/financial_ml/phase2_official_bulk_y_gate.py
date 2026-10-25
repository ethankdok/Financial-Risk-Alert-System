"""Large-scale official Y1 company-FY adjudication, evidence-first.

Inputs are PRIVATE licensed or official MOPS archival manifests. Codes do not
fetch official archives and do not validate URL contents: labels that pass are
REVIEWER_ATTESTED, NOT independently audited gold.

No "unseen" negative is ever inferred. For Y1=0 demand complete 24-month
dated *official* amendment coverage, all suspected events resolved, and source
SHA256. For Y1=1 demand original first publication and official event evidence
with original/revised distinct SHA256, affected consolidated annual FY.

CSV schemas:
annual: ticker,fiscal_year,first_public_at,original_filing_url,
        original_sha256,statement_scope,original_verified,first_public_verified
coverage: ticker,fiscal_year,coverage_start,coverage_end,complete,
        all_candidates_resolved,source_evidence_url,source_sha256,reviewer_verified
event: ticker,fiscal_year,event_date,event_kind,event_url,
       original_sha256,revised_sha256,scope,core_delta_verified,
       reviewer_verified
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from research.financial_ml.round2_finlab_review_gate import _shift_months
from research.financial_ml.phase2_pit_x_y_bridge import immutable,csv_bytes,csv_load

ANNUAL={"ticker","fiscal_year","first_public_at","original_filing_url",
        "original_sha256","statement_scope","original_verified","first_public_verified"}
COVERAGE={"ticker","fiscal_year","coverage_start","coverage_end","complete",
          "all_candidates_resolved","source_evidence_url","source_sha256",
          "reviewer_verified"}
EVENT={"ticker","fiscal_year","event_date","event_kind","event_url",
       "original_sha256","revised_sha256","scope","core_delta_verified","reviewer_verified"}
FIELDS=("ticker","fiscal_year","y_official_annual_24m","label_status",
        "grade","first_public_at","window_end","event_date",
        "official_original_filing_url","official_event_url",
        "official_coverage_evidence_url","provenance_input_hash","blocker")

def issha(s):return bool(re.fullmatch(r"[a-fA-F0-9]{64}",str(s or "")))
def ismops(s):
    p=urlparse(str(s or ""))
    return p.scheme=="https" and p.hostname=="mops.twse.com.tw" and bool(p.path)
def yes(s):return str(s).strip().lower() in ("true","yes")
def chrono(s):
    try:return date.fromisoformat(s[:10])
    except (ValueError,TypeError):return None

def build(annual_file, coverage_file, event_file, out, cutoff="2026-10-25"):
    cutoff_day=date.fromisoformat(cutoff)
    ann,ah=csv_load(annual_file,ANNUAL)
    coverage,ch=csv_load(coverage_file,COVERAGE)
    events,eh=csv_load(event_file,EVENT)
    bycov={};byevent=defaultdict(list)
    for c in coverage:
        key=(c["ticker"],c["fiscal_year"])
        if key in bycov:raise ValueError("duplicate_coverage_key")
        bycov[key]=c
    for e in events:
        key=(e["ticker"],e["fiscal_year"])
        byevent[key].append(e)
    seen=set();out_rows=[];counts=Counter()
    provenance=hashlib.sha256((ah+ch+eh).encode()).hexdigest()
    for a in ann:
        key=(a["ticker"],a["fiscal_year"])
        if key in seen:raise ValueError("duplicate_annual_filing")
        seen.add(key)
        if a["ticker"]=="1785":continue # independent external holdout, no train labels.
        first=chrono(a["first_public_at"])
        deadline=_shift_months(first,24) if first else None
        row=dict(ticker=a["ticker"],fiscal_year=a["fiscal_year"],
            y_official_annual_24m="",label_status="UNKNOWN",grade="NOT_APPROVED",
            first_public_at=a["first_public_at"],window_end=deadline.isoformat() if deadline else "",
            event_date="",official_original_filing_url=a["original_filing_url"],
            official_event_url="",official_coverage_evidence_url="",
            provenance_input_hash=provenance,blocker="")
        if (not re.fullmatch(r"\d{4}",a["ticker"]) or
                int(a["fiscal_year"]) not in range(2013,2024) or not first or
                first.year<int(a["fiscal_year"]) or first>cutoff_day or
                a["statement_scope"]!="consolidated" or
                not yes(a["original_verified"]) or
                not yes(a["first_public_verified"]) or
                not ismops(a["original_filing_url"]) or not issha(a["original_sha256"])):
            row["blocker"]="ORIGINAL_ANNUAL_FILING_AND_PUBLICATION_NOT_VERIFIED"
        else:
            matched=[];unresolved=False
            for e in byevent[key]:
                d=chrono(e["event_date"])
                if not d:
                    unresolved=True;continue
                if d<first or d>deadline:
                    continue
                if (not yes(e["reviewer_verified"]) or
                    e["scope"]!="consolidated" or not ismops(e["event_url"]) or
                    not issha(e["original_sha256"]) or
                    not issha(e["revised_sha256"]) or
                    e["original_sha256"]==e["revised_sha256"] or
                    e["original_sha256"]!=a["original_sha256"] or
                    e["event_kind"] not in ("RESTATEMENT","CORE_AMOUNT_CORRECTION") or
                    (e["event_kind"]=="CORE_AMOUNT_CORRECTION" and
                     not yes(e["core_delta_verified"]))):
                    unresolved=True;continue
                matched.append((d,e))
            if matched:
                d,e=sorted(matched,key=lambda x:x[0])[0]
                row.update(y_official_annual_24m="1",label_status="APPROVED_REVIEWER_ATTESTED",
                    grade="REVIEWER_ATTESTED_SOURCE_NOT_INDEPENDENTLY_VERIFIED",
                    event_date=d.isoformat(),official_event_url=e["event_url"])
            elif unresolved:
                row["blocker"]="UNRESOLVED_OFFICIAL_EVENT_CANDIDATE"
            else:
                c=bycov.get(key)
                if not c:
                    row["blocker"]="MISSING_OFFICIAL_24M_COVERAGE"
                else:
                    start=chrono(c["coverage_start"]);end=chrono(c["coverage_end"])
                    if (not deadline or deadline>cutoff_day or
                        not yes(c["complete"]) or
                        not yes(c["all_candidates_resolved"]) or
                        not yes(c["reviewer_verified"]) or
                        not start or not end or start>first or end<deadline or
                        not issha(c["source_sha256"]) or
                        not ismops(c["source_evidence_url"])):
                        row["blocker"]="OFFICIAL_FULL_WINDOW_COVERAGE_UNVERIFIED"
                    else:
                        row.update(y_official_annual_24m="0",
                            label_status="APPROVED_REVIEWER_ATTESTED",
                            grade="REVIEWER_ATTESTED_SOURCE_NOT_INDEPENDENTLY_VERIFIED",
                            official_coverage_evidence_url=c["source_evidence_url"])
        if row["y_official_annual_24m"]=="" and not row["blocker"]:
            row["blocker"]="UNKNOWN_UNRESOLVED"
        counts[row["y_official_annual_24m"] or "UNKNOWN"]+=1
        counts["blocker:"+row["blocker"]]+=int(row["y_official_annual_24m"]=="")
        out_rows.append(row)
    report={
        "schema":"fintrust_phase2_official_bulk_y_reviewer_attested_v1",
        "annual_records_input":len(ann),"output_records":len(out_rows),
        "reviewer_attested_positive":counts["1"],
        "reviewer_attested_negative":counts["0"],
        "unknown":counts["UNKNOWN"],
        "independently_verified_gold_positive":0,
        "independently_verified_gold_negative":0,
        "blocker_counts":{k.split(":",1)[1]:v for k,v in sorted(counts.items()) if k.startswith("blocker:") and v},
        "source_inputs_sha256":{"annual":ah,"coverage":ch,"events":eh},
        "warning":"Reviewer attestation and plausible HTTPS URL are not independent verification of MOPS content. Never promote as GOLD without document inspection. FinLab/TEJ silence is not Y1=0.",
        "scope":"Consolidated annual company FY, first official publication plus 24 months",
    }
    out_rows.sort(key=lambda x:(x["ticker"],int(x["fiscal_year"])))
    target=Path(out);b=csv_bytes(out_rows,FIELDS)
    report["output_sha256"]=hashlib.sha256(b).hexdigest()
    immutable(target/"official_y1_adjudication_private.csv",b)
    immutable(target/"official_y1_bulk_coverage_report.json",
              (json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8"))
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--annual",required=True)
    p.add_argument("--coverage",required=True)
    p.add_argument("--events",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    print(json.dumps(build(a.annual,a.coverage,a.events,a.out),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
