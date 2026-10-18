"""Single-command Phase 1 evidence gate and Phase 2 financial data processing.

Research-only: candidate source amounts, NO approved features, labels or models.
One optional explicit network execution resumes bounded FinMind batches.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from .finmind_bulk_stage import DATASETS, URL
from .finmind_scaled_cohort import batch as fetch_batch
from .finmind_cross_industry_pilot import FIELDS, read_universe, audit as alias_audit
from .finmind_annual_candidate_stage import stage as annual_stage
from .annual_panel_readiness import prepare as panel_stage
from .phase1_case_registry import extract as phase1_extract
from .finmind_annual_crosscheck import compare as mops_compare

START, END = "2013-01-01", "2025-12-31"
RAW_COLS = ("ticker","industry_category","dataset","status","raw_rows",
            "amount_rows","percentage_rows","non_quarter_end_rows",
            "periods_observed","source_sha256","reason")


def save_csv(path, names, entries):
    with Path(path).open("w", encoding="utf-8", newline="") as file:
        w=csv.DictWriter(file, fieldnames=names)
        w.writeheader()
        w.writerows(entries)


def inspect_archive(path, ticker, dataset):
    """Fails closed on bad archive identities, dates, numeric types and clashes."""
    result=dict(status="archive_missing",raw_rows=0,amount_rows=0,
                percentage_rows=0,non_quarter_end_rows=0,periods_observed=0,
                source_sha256="",reason="")
    path=Path(path)
    if not path.exists():
        return result
    if not path.is_file() or path.stat().st_size > 45_000_000:
        return {**result,"status":"quarantined","reason":"bad_file_type_or_size"}
    raw=path.read_bytes()
    result["source_sha256"]=hashlib.sha256(raw).hexdigest()
    try:
        doc=json.loads(raw)
        if (not isinstance(doc,dict) or doc.get("source")!=URL
                or doc.get("ticker")!=ticker or doc.get("dataset")!=dataset
                or doc.get("period")!=[START,END]
                or not isinstance(doc.get("records"),list)):
            raise ValueError("archive_identity_or_period_invalid")
        if doc.get("original_filing_vintage") not in (None,"UNKNOWN"):
            raise ValueError("unproved_original_filing_vintage")
        if doc.get("period_semantics") not in (
                None,"QUARTERLY_UNVERIFIED_ANNUAL_AGGREGATION"):
            raise ValueError("unverified_provider_period_claim")
        seen=defaultdict(set)
        dates=set()
        monetary=percent=off_quarter=0
        for row in doc["records"]:
            if not isinstance(row,dict) or str(row.get("stock_id"))!=ticker:
                raise ValueError("wrong_issuer_row")
            typ=str(row.get("type") or "").strip()
            if not typ:
                raise ValueError("missing_financial_item_type")
            try:
                day=date.fromisoformat(str(row["date"]))
            except (KeyError,ValueError,TypeError):
                raise ValueError("invalid_financial_period") from None
            if not START<=day.isoformat()<=END:
                raise ValueError("out_of_range_financial_period")
            try:
                if row.get("value") is None or isinstance(row["value"],bool):
                    raise ValueError("bad_boolean_or_null")
                value=Decimal(str(row["value"]))
            except (KeyError,InvalidOperation,ValueError):
                raise ValueError("nonnumeric_financial_item") from None
            if not value.is_finite():
                raise ValueError("nonfinite_financial_item")
            if typ.endswith("_per"):
                percent+=1
                continue
            monetary+=1
            dates.add(day.isoformat())
            if (day.month,day.day) not in ((3,31),(6,30),(9,30),(12,31)):
                off_quarter+=1
            seen[(typ,day.isoformat())].add(value)
        if any(len(values)>1 for values in seen.values()):
            raise ValueError("conflicting_same_type_and_period")
        result.update(status=("nonempty_provisional_archive" if monetary else
                              "provider_empty_response" if not doc["records"] else
                              "no_monetary_rows"),
                      raw_rows=len(doc["records"]),amount_rows=monetary,
                      percentage_rows=percent,non_quarter_end_rows=off_quarter,
                      periods_observed=len(dates))
    except (ValueError,TypeError,KeyError,UnicodeDecodeError) as exc:
        result.update(status="quarantined",reason=str(exc)[:160])
    return result


def raw_audit(cohort_csv,raw_root,output):
    companies=read_universe(cohort_csv)
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    statuses=Counter();by_issuer=defaultdict(Counter);rows=[];quarantined=set()
    for c in companies:
        ticker=c["ticker"]
        if ticker=="1785":
            raise ValueError("reserved_holdout")
        for dataset in DATASETS:
            r=inspect_archive(Path(raw_root)/ticker/(dataset+".json"),ticker,dataset)
            rows.append(dict(ticker=ticker,industry_category=c["industry_category"],
                             dataset=dataset,**r))
            statuses[r["status"]]+=1
            by_issuer[ticker][r["status"]]+=1
            if r["status"]=="quarantined":
                quarantined.add(ticker)
    save_csv(output/"phase2_raw_audit.csv",RAW_COLS,rows)
    safe=[c for c in companies if c["ticker"] not in quarantined]
    save_csv(output/"phase2_safe_cohort.csv",FIELDS,safe)
    return {
        "cohort_companies":len(companies),"statement_jobs":len(companies)*len(DATASETS),
        "statuses":dict(sorted(statuses.items())),
        "missing_archives":statuses["archive_missing"],
        "provider_empty_responses":statuses["provider_empty_response"],
        "quarantined_issuers":sorted(quarantined),"safe_companies":len(safe),
        "fully_cached_issuers":sum(sum(by_issuer[t][kind] for kind in
             ("nonempty_provisional_archive","provider_empty_response","no_monetary_rows"))
             ==len(DATASETS) for t in by_issuer),
        "fully_nonempty_issuers":sum(v["nonempty_provisional_archive"]==len(DATASETS)
                                     for v in by_issuer.values()),
        "historical_company_membership_verified":False,
        "original_filing_publication_asof_verified":False,
        "finmind_accounting_policy_approved":False,
        "confirmed_normal_labels_created":0,
        "holdout_1785_excluded":True
    }


def official_reconciliation(data_root,raw,cohort_csv,output):
    source=Path(data_root)/"official_batch"/"acquisition_results.json"
    if not source.exists():
        return {"status":"SKIP_MOPS_OFFICIAL_ARCHIVE_NOT_PRESENT"}
    try:
        docs=json.loads(source.read_text(encoding="utf-8"))["outcomes"]
        allowed={c["ticker"] for c in read_universe(cohort_csv)}
        candidates=set()
        for item in docs.values():
            if (isinstance(item,dict) and str(item.get("ticker")) in allowed
                  and item.get("status")=="validated"
                  and item.get("statement_scope")=="consolidated"
                  and item.get("accounting_framework")=="TIFRS"
                  and 2013<=int(item.get("fiscal_year",0))<=2015):
                candidates.add(str(item["ticker"]))
        candidates.discard("1785")
        if not candidates:
            return {"status":"SKIP_NO_OVERLAPPING_OFFICIAL_FINANCIALS"}
        return {**mops_compare(raw,source,output,tickers=tuple(sorted(candidates)),
                               start_year=2013,end_year=2015),
                "overlapping_issuers":sorted(candidates)}
    except (KeyError,ValueError,TypeError,OSError) as exc:
        return {"status":"BLOCKED_MOPS_CROSSCHECK","error":str(exc)[:160]}


def run(data_root,output,*,execute_download=False,max_rounds=5,batch_size=12):
    if not 1<=max_rounds<=10 or not 1<=batch_size<=40:
        raise ValueError("unbounded_or_invalid_batch_arguments")
    data_root=Path(data_root);out=Path(output)
    out.mkdir(parents=True,exist_ok=True)
    cohort=data_root/"finmind_scaled_120"/"finmind_scaled_cohort.csv"
    raw=data_root/"finmind_cross_industry_raw"
    if not cohort.exists():
        raise FileNotFoundError("scaled_120_company_cohort_missing")
    read_universe(cohort)
    phase1=phase1_extract(Path(__file__).with_name("phase1_case_sources_seed.json"),
                          out/"phase1")
    attempts=[]
    if execute_download:
        old_missing=None
        for _ in range(max_rounds):
            before=raw_audit(cohort,raw,out/"before")
            if not before["missing_archives"]:
                break
            if before["quarantined_issuers"]:
                attempts.append({"status":"STOP_QUARANTINED_SOURCE_BEFORE_NETWORK"})
                break
            if old_missing is not None and before["missing_archives"]>=old_missing:
                attempts.append({"status":"STOP_NO_PROGRESS"})
                break
            old_missing=before["missing_archives"]
            result=fetch_batch(cohort,raw,out/"download_reports",
                               batch_size=batch_size,max_batches=3,execute=True)
            attempts.append({k:result.get(k) for k in (
                "network_requests","reused_cached","zero_record_responses",
                "stop_reason","remaining_chunks_after_run")})
            if result["stop_reason"]!="none":
                break
    phase2=raw_audit(cohort,raw,out/"phase2")
    if phase2["safe_companies"]:
        selected=out/"phase2"/"phase2_safe_cohort.csv"
        annual=annual_stage(selected,raw,out/"phase2"/"annual")
        panel=panel_stage(out/"phase2"/"annual"/"finmind_annual_candidate_lines.csv",
                          out/"phase2"/"sequence")
        schema=alias_audit(selected,raw,out/"phase2"/"schema")
        official=official_reconciliation(data_root,raw,selected,out/"phase2"/"official")
    else:
        annual=panel=schema={"status":"BLOCKED_ALL_ISSUERS_QUARANTINED"}
        official={"status":"BLOCKED"}
    result={
        "status":("PHASE1_EVIDENCE_REVIEW_OPEN_PHASE2_RAW_ACQUISITION_FINISHED_RESEARCH_APPROVAL_PENDING"
                  if phase2["missing_archives"]==0 and not phase2["quarantined_issuers"] else
                  "PHASE1_EVIDENCE_REVIEW_OPEN_PHASE2_RAW_ACQUISITION_PARTIAL"),
        "phase1_case_candidates":phase1["candidate_cases"],
        "phase1_candidate_company_years":phase1["candidate_company_years"],
        "phase1_approved_positive_labels":phase1["approved_positive_labels"],
        "phase1_approved_negative_labels":phase1["approved_negative_labels"],
        "phase1_evidence_complete":False,
        "phase1_evidence_refs":phase1["evidence_reference_count"],
        "phase1_remaining":["archive_primary_source_bytes","verify_first_public_revelation",
                            "review_exact_affected_filing_periods_and_legal_findings",
                            "method_owner_approval","review_negative_cohort"],
        "phase2_raw":phase2,
        "phase2_annual_candidate_rows":annual.get("rows",0),
        "phase2_annual_candidate_amounts":annual.get("counts",{}).get("candidate_annual_value",0),
        "phase2_panel":dict(company_years=panel.get("source_company_years",0),
                             complete_12=panel.get("complete_12_metric_company_years",0),
                             windows=panel.get("window_stats",{})),
        "phase2_schema_alias_statuses":schema.get("statuses",{}),
        "phase2_official_check":official,
        "phase2_all_requested_sources_present":phase2["missing_archives"]==0,
        "phase2_end_to_end_code_executed":bool(phase2["safe_companies"]),
        "phase2_original_filing_pit_verified":False,
        "phase2_vendor_mapping_certified":False,
        "phase2_complete_for_trusted_15_features":False,
        "download_opt_in":execute_download,
        "download_attempts":attempts,"training_labels_created":0,
        "models_trained":0,"production_db_writes":0,
        "reserved_1785_final_holdout":True,
        "warning":"Engineering pass does not certify case labels, original filing "
                  "vintage, TIFRS mapping or paper 15-feature readiness."
    }
    (out/"phase12_gate_report.json").write_text(
        json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description="One-run Phase1+Phase2 local research gate")
    p.add_argument("--data-root",required=True)
    p.add_argument("--output",required=True)
    p.add_argument("--execute-download",action="store_true")
    p.add_argument("--max-rounds",type=int,default=5)
    p.add_argument("--batch-size",type=int,default=12)
    o=p.parse_args(argv)
    print(json.dumps(run(o.data_root,o.output,execute_download=o.execute_download,
                         max_rounds=o.max_rounds,batch_size=o.batch_size),
                     ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
