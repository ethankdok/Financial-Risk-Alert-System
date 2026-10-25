"""Phase2 canonical original XBRL facts (nine metrics) from EXISTING official archive.

Reuses financial_ml.literature_dataset.checked_manifest/archive_bytes,
app.services.financial_research.literature_extraction.extract_xbrl,
and literature_inputs.FilingLines. No FinMind substitution or HTTP requests.
Absence or disagreement remains NULL, never zero.

Run from fintrust_backend:
python -m research.financial_ml.phase2_mops_canonical_export \
 --acquisition-manifest data/financial_ml/official_batch/acquisition_results.json \
 --out data/financial_ml/phase2_mops_facts

This extractor stages *source-verified accounting lines* but DOES NOT claim the
actual FIRST public filing date or original version, which must be verified
separately by the Phase2 point-in-time bridge.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from pathlib import Path
from app.services.financial_research.literature_extraction import extract_xbrl
from app.services.financial_research.literature_inputs import FilingLines
from research.financial_ml.literature_dataset import checked_manifest,archive_bytes
from research.financial_ml.phase2_pit_x_y_bridge import immutable,csv_bytes

# Annual consolidated canonical candidates from specific TIFRS XBRL concepts.
# No "OtherReceivables" or quarterly/financial group proxy substitutions.
ALIAS={
    "net_income":("ProfitLoss",),  # after-tax consolidated profit/loss
    "total_assets":("Assets",),
    "current_assets":("CurrentAssets",),
    "current_liabilities":("CurrentLiabilities",),
    "total_liabilities":("Liabilities",),
    "operating_cash_flow":("CashFlowsFromUsedInOperatingActivities",
                            "NetCashFlowsFromUsedInOperatingActivities"),
    "accounts_receivable":("AccountsReceivableNet",),
    "inventory":("Inventories",),
    "revenue":("OperatingRevenue","Revenue"),
}
BALANCE={"total_assets","current_assets","current_liabilities",
         "total_liabilities","accounts_receivable","inventory"}
EXPORT_FIELDS=("ticker","fiscal_year","metric_code","value","unit",
               "filing_version_id","raw_sha256")
DETAIL_FIELDS=("ticker","fiscal_year","metric_code","status","line_key",
               "source_observation_hash","original_filing_type",
               "first_publication_verified","source_sha256")

def metric_observation(lines,fy,name):
    period=(f"I:{fy}-12-31" if name in BALANCE else
            f"D:{fy}-01-01/{fy}-12-31")
    values=[]
    problems=[]
    for alias in ALIAS[name]:
        obs,issue=lines.get(alias,period)
        if issue:problems.append(issue);continue
        if obs:
            reason=lines.gate(obs)
            if reason:
                problems.append(str(reason))
            elif obs.get("value") not in (None,""):
                values.append((str(obs["value"]),obs))
    if problems:
        return "AMBIGUOUS_OR_SOURCE_IDENTITY",None,None
    if not values:
        return "MISSING_STATEMENT_CONCEPT",None,None
    # Two aliases expressing the same metric must match, not first-in-list wins.
    try:
        from decimal import Decimal
        nums={Decimal(s) for s,_ in values}
    except ArithmeticError:
        return "NON_NUMERIC",None,None
    if len(nums)!=1:return "CONFLICTING_ACCOUNT_ALIASES",None,None
    text,obs=values[0]
    return "OBSERVED_OFFICIAL_XBRL_LINE",text,obs

def build(acquisition_manifest,out):
    records,excluded=checked_manifest(acquisition_manifest)
    folder=Path(acquisition_manifest).parent
    if not records:raise ValueError("no_validated_official_acquisition_records")
    rows=[];details=[];counts=Counter()
    ids=set()
    for item in records:
        ticker=str(item["ticker"]);fy=int(item["fiscal_year"])
        if ticker=="1785":continue
        key=(ticker,fy)
        if key in ids:raise ValueError("duplicate_acquisition_company_fy")
        ids.add(key)
        filing={
            "ticker":ticker,"fiscal_year":fy,
            "filing_version_id":item["filing_version_id"],
            "filing_version_type":item["filing_version_type"],
            "statement_scope":"consolidated","source_kind":item["source_kind"],
            "content_hash":item["content_hash"],"accounting_framework":"TIFRS",
            "available_at":None,"availability_status":"unverified",
            "source_url":item.get("source_url"),
        }
        try:
            raw=archive_bytes(folder,item)
            obs=extract_xbrl(raw,filing)
            lines=FilingLines(obs)
        except (ValueError,OSError,RuntimeError,KeyError) as error:
            counts["EXTRACTION_FAILED"]+=1
            continue
        for name in ALIAS:
            status,value,observation=metric_observation(lines,fy,name)
            counts[status]+=1
            rows.append({
                "ticker":ticker,"fiscal_year":fy,"metric_code":name,
                "value":value or "","unit":"TWD",
                "filing_version_id":item["filing_version_id"],
                "raw_sha256":item["content_hash"],
            })
            details.append({
                "ticker":ticker,"fiscal_year":fy,"metric_code":name,
                "status":status,
                "line_key":observation.get("line_key","") if observation else "",
                "source_observation_hash":observation.get("raw_sha256","") if observation else "",
                "original_filing_type":str(item.get("filing_version_type") or ""),
                "first_publication_verified":str(bool(item.get("first_publication_verified",False))).lower(),
                "source_sha256":item["content_hash"],
            })
    rows.sort(key=lambda r:(r["ticker"],int(r["fiscal_year"]),r["metric_code"]))
    details.sort(key=lambda r:(r["ticker"],int(r["fiscal_year"]),r["metric_code"]))
    report={
        "schema":"fintrust_phase2_mops_9canonical_features_v1",
        "validated_issuer_fy":len(ids),
        "official_annual_metric_rows":len(rows),
        "observed_official_amounts":counts["OBSERVED_OFFICIAL_XBRL_LINE"],
        "counts":dict(sorted(counts.items())),
        "excluded":dict(sorted(excluded.items())),
        "original_first_publication_verified_for_training":False,
        "warning":"This exports accounting facts, not training approval. Strict PIT Y2 bridge separately tests original filing and official first-public timestamp.",
        "mapping_caveat":"Receivables = AccountsReceivableNet only (not Beneish aggregate); missing concepts are null, not zero.",
        "raw_financial_rows_only_local":True,
    }
    target=Path(out)
    rbytes=csv_bytes(rows,EXPORT_FIELDS)
    dbytes=csv_bytes(details,DETAIL_FIELDS)
    report["sha256"]={"annual_facts":hashlib.sha256(rbytes).hexdigest(),
                      "detail":hashlib.sha256(dbytes).hexdigest()}
    immutable(target/"phase2_mops_annual_facts_private.csv",rbytes)
    immutable(target/"phase2_mops_line_quality_private.csv",dbytes)
    immutable(target/"phase2_mops_extract_report.json",
              (json.dumps(report,ensure_ascii=False,indent=2,sort_keys=True)+"\n").encode("utf-8"))
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--acquisition-manifest",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    print(json.dumps(build(a.acquisition_manifest,a.out),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
