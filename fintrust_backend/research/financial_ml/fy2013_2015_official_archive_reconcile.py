"""FY2013–2015 official MOPS archival-data acquisition for the frozen 120 issuers.

Reuses the already-tested official_batch XBRL parser and immutable SHA archive.
This fixes an actual source bottleneck: 246/360 company-years do not even have
12 complete provisional FinMind amounts.

IMPORTANT: current archived MOPS XBRL != proven original first-filed version.
The output is for reconciliation/review, NOT automatic 0/1 supervision.
"""
from __future__ import annotations
import argparse
import asyncio
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .fy2013_2015_stage1_freeze import FIELDS, YEARS
from .annual_panel_readiness import METRICS
from .official_batch import MAX_REQUESTS, acquire, atomic_json
from app.services.historical_audit.sources import mops_annual_url
from app.services.historical_audit.archive import RawEvidenceArchive

MAX_SOURCE_ROWS=360
PREP_COLS=("ticker","fiscal_year","candidate_complete_12","current_mops_source_url",
           "retrieval_state","mops_parsed_financial_fields","mops_12_metric_coverage",
           "current_archive_sha256","raw_archive_relative_path",
           "filing_scope","filing_version_type","current_archive_is_original_first_filing",
           "official_first_publication_verified","source_eligible_for_0_1_training")
COMPARE_COLS=("ticker","fiscal_year","metric","finmind_candidate_twd",
              "mops_current_archival_twd","absolute_difference_twd","relative_difference",
              "source_archive_sha256","version_identity","result_status")


def fixed_panel(stage1_csv):
    with Path(stage1_csv).open(encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        if not set(FIELDS).issubset(reader.fieldnames or []):
            raise ValueError("fy1315_expected_verified_stage1_input_schema")
        rows=list(reader)
    if len(rows)!=MAX_SOURCE_ROWS:
        raise ValueError("fy1315_expected_exact_360_research_company_years")
    keys=set()
    for row in rows:
        k=(row["ticker"],int(row["fiscal_year"]))
        if (k in keys or k[1] not in YEARS or k[0]=="1785"
            or row["research_window"]!="FY2013_FY2014_FY2015_ONLY"
            or row["approved_for_supervision"]!="false"
            or row["numeric_source_tier"]!="FINMIND_PROVISIONAL_NOT_ORIGINAL"):
            raise ValueError("fy1315_source_row_duplicate_wrong_year_or_false_training")
        keys.add(k)
    if len({t for t,y in keys})!=120 or {y for t,y in keys}!=set(YEARS):
        raise ValueError("fy1315_broken_three_year_120_issuer_cohort")
    # Fetch missing candidates first to maximize actual new information.
    return sorted(rows,key=lambda x:(
        x["candidate_complete_12"]=="true",x["ticker"],int(x["fiscal_year"])))


def batches(stage1_csv, batch_size=MAX_REQUESTS):
    if not 1<=batch_size<=MAX_REQUESTS:
        raise ValueError("fy1315_invalid_safe_official_batch_size")
    rows=fixed_panel(stage1_csv)
    jobs=[]
    for r in rows:
        ticker=r["ticker"];year=int(r["fiscal_year"])
        jobs.append({
            "ticker":ticker,"fiscal_year":year,
            "source_url":mops_annual_url(ticker,year),
            "historical_listing_status":"UNVERIFIED",
            "historical_industry_status":"UNVERIFIED",
            "normal_label_status":"UNREVIEWED","training_admitted":False,
        })
    return [jobs[n:n+batch_size] for n in range(0,len(jobs),batch_size)]


def _num(raw):
    from decimal import Decimal,InvalidOperation
    if raw is None or str(raw).strip()=="":
        return None
    try:
        return Decimal(str(raw).strip())
    except InvalidOperation:
        return None


def _twd_amount(value,unit):
    from decimal import Decimal
    n=_num(value)
    if n is None:
        return None
    unit=str(unit).strip()
    if unit in ("TWD","iso4217:TWD","NTD"):
        return n
    if unit=="TWD_thousand":
        return n*Decimal(1000)
    return None


def summarize_archived_outcomes(stage1_csv,download_root):
    root=Path(download_root)
    rows=fixed_panel(stage1_csv)
    by={(r["ticker"],int(r["fiscal_year"])):r for r in rows}
    stages=batches(stage1_csv)
    result={};source_cmp=[];statuses=Counter()
    for batch_no,plan in enumerate(stages,1):
        batchdir=root/f"batch_{batch_no:03}"
        manifest=batchdir/"acquisition_results.json"
        snapshot={}
        if manifest.exists():
            obj=json.loads(manifest.read_text(encoding="utf-8"))
            snapshot=obj.get("outcomes",{})
            if not isinstance(snapshot,dict):
                raise ValueError("fy1315_invalid_official_archive_manifest")
        archive=RawEvidenceArchive(batchdir/"raw")
        for request in plan:
            key=(request["ticker"],int(request["fiscal_year"]))
            name=f"{key[0]}:{key[1]}"
            d=snapshot.get(name,{})
            state=d.get("status","NOT_DOWNLOADED")
            digest=d.get("content_hash","")
            sha=""
            if d.get("archive_path"):
                raw=archive.read(d["archive_path"])
                sha=hashlib.sha256(raw).hexdigest()
                if sha!=digest:
                    raise ValueError("fy1315_archived_source_sha256_mismatch:"+name)
            elif digest:
                raise ValueError("fy1315_unpaired_source_hash")
            if d and (d.get("ticker")!=key[0] or int(d.get("fiscal_year",-1))!=key[1]
                or d.get("source_url")!=request["source_url"] or
                d.get("training_admitted") is not False or
                d.get("normal_label_status")!="UNREVIEWED"):
                raise ValueError("fy1315_download_manifest_identity_mismatch")
            facts=d.get("facts") if state=="validated" else []
            if facts is None: facts=[]
            if not isinstance(facts,list):
                raise ValueError("fy1315_unexpected_official_facts_shape")
            amounts={};invalid=0
            for fact in facts:
                metric=fact.get("metric_code")
                if metric not in METRICS:
                    continue
                val=_twd_amount(fact.get("value"),fact.get("unit"))
                if val is None:
                    invalid+=1;continue
                if metric in amounts and amounts[metric]!=val:
                    # A duplicate same metric with different accounting
                    # grain is an ambiguity, NEVER silently select one.
                    raise ValueError("fy1315_ambiguous_same_metric_current_archive:"+name+":"+metric)
                amounts[metric]=val
            base=by[key]
            for metric in METRICS:
                old=_num(base[metric])
                current=amounts.get(metric)
                diff=abs(current-old) if old is not None and current is not None else None
                ratio=diff/max(abs(old),abs(current)) if diff is not None and max(abs(old),abs(current))!=0 else None
                source_cmp.append({
                    "ticker":key[0],"fiscal_year":key[1],"metric":metric,
                    "finmind_candidate_twd":str(old) if old is not None else "",
                    "mops_current_archival_twd":str(current) if current is not None else "",
                    "absolute_difference_twd":str(diff) if diff is not None else "",
                    "relative_difference":str(ratio) if ratio is not None else "",
                    "source_archive_sha256":sha,
                    "version_identity":"MOPS_CURRENT_ARCHIVE_NOT_PROVEN_FIRST_FILING",
                    "result_status":("BOTH_ABSENT" if old is None and current is None else
                        "CANDIDATE_MISSING_CURRENT_FOUND" if old is None else
                        "CURRENT_NOT_AVAILABLE" if current is None else
                        "CURRENT_EQUALS_CANDIDATE" if diff==0 else
                        "AMOUNTS_DIFFER_NEED_VERSION_GRAIN_REVIEW"),
                })
            r={
                "ticker":key[0],"fiscal_year":key[1],
                "candidate_complete_12":base["candidate_complete_12"],
                "current_mops_source_url":request["source_url"],
                "retrieval_state":state,"mops_parsed_financial_fields":len(facts),
                "mops_12_metric_coverage":len(amounts),
                "current_archive_sha256":sha,
                "raw_archive_relative_path":(
                    f"batch_{batch_no:03}/"+d["archive_path"] if d.get("archive_path") else ""),
                "filing_scope":d.get("statement_scope",""),
                "filing_version_type":d.get("filing_version_type",""),
                "current_archive_is_original_first_filing":"false",
                "official_first_publication_verified":"false",
                "source_eligible_for_0_1_training":"false",
            }
            statuses[state]+=1
            result[key]=r
    if len(result)!=360 or len(source_cmp)!=360*len(METRICS):
        raise ValueError("fy1315_archival_reconciliation_wrong_row_count")
    return [result[k] for k in sorted(result)],source_cmp,dict(statuses)


def write_csv(path,headers,rows):
    with Path(path).open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=headers,extrasaction="raise")
        w.writeheader();w.writerows(rows)


async def run(stage1_csv,output,*,execute=False,max_batches=None):
    path=Path(output)
    path.mkdir(parents=True,exist_ok=True)
    jobs=batches(stage1_csv)
    atomic_json(path/"fy1315_official_archive_request_plan.json",{
        "periods":list(YEARS),"company_years":360,"number_of_batches":len(jobs),
        "each_batch_max":MAX_REQUESTS,"execute":bool(execute),
        "warning":"MOPS 2026-retrieved historical XBRL is NOT proven the first original filing.",
        "staged_requests":[{"batch":i,"requests":[
            {"ticker":r["ticker"],"fy":r["fiscal_year"],
             "url":r["source_url"]} for r in plan]}
             for i,plan in enumerate(jobs,1)],
    })
    completed=0
    if execute:
        for n,plan in enumerate(jobs,1):
            if max_batches is not None and completed>=max_batches:
                break
            folder=path/f"batch_{n:03}"
            await acquire(plan,folder,execute=True)
            completed+=1
    index,comparison,stats=summarize_archived_outcomes(stage1_csv,path)
    write_csv(path/"fy1315_360_official_archive_status.csv",PREP_COLS,index)
    write_csv(path/"fy1315_4320_metric_reconciliation.csv",COMPARE_COLS,comparison)
    newly=Counter(r["result_status"] for r in comparison)
    outcome={
        "status":"MOPS_ARCHIVE_RETRIEVAL_INCOMPLETE_OR_FY2013_15_RECONCILED",
        "input_years":list(YEARS),"target_company_years":360,
        "current_archive_validated_company_years":stats.get("validated",0),
        "current_archived_amounts_not_original":True,
        "finmind_missing_amounts_now_found_in_mops":newly["CANDIDATE_MISSING_CURRENT_FOUND"],
        "candidate_current_archive_amount_disagreements":newly["AMOUNTS_DIFFER_NEED_VERSION_GRAIN_REVIEW"],
        "download_status_counts":stats,"request_batches_executed_this_run":completed,
        "approved_supervised_labels_0":0,"approved_supervised_labels_1":0,
        "input_sha256":hashlib.sha256(Path(stage1_csv).read_bytes()).hexdigest(),
        "financial_features_not_ready_for_original_training":True,
        "production_database_writes":0,
        "output_files":[
            "fy1315_360_official_archive_status.csv",
            "fy1315_4320_metric_reconciliation.csv"],
    }
    atomic_json(path/"fy1315_official_archival_reconciliation_report.json",outcome)
    return outcome

def main(argv=None):
    p=argparse.ArgumentParser(description="Incremental bounded MOPS FY2013-15 archival evidence")
    p.add_argument("--stage1-csv",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--execute",action="store_true")
    p.add_argument("--max-batches",type=int)
    a=p.parse_args(argv)
    if a.max_batches is not None and not 1<=a.max_batches<=30:
        p.error("max-batches 1..30")
    print(json.dumps(asyncio.run(run(a.stage1_csv,a.out,
        execute=a.execute,max_batches=a.max_batches)),ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
