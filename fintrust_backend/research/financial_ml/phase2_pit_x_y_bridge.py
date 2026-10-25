"""Phase 2: point-in-time MOPS-XBRL literature features + TEJ proxy label join.

NO NETWORK. Source-aware gates: only original version, dated and verified MOPS
publication, consolidated TIFRS, hashes and matching family/version are allowed.
8 Beneish variables reuse existing literature_dataset.py (NOT reimplemented).
7 extra ratios derived from canonical original MOPS facts. Missing != 0.

Run from fintrust_backend:
python -m research.financial_ml.phase2_pit_x_y_bridge \
  --proxy-labels data/financial_ml/round2_label_cohorts_20261025/tej_calendar_proxy_cohort_private.csv \
  --out data/financial_ml/phase2_pit_stage1

To evaluate actual X, add all THREE sources:
  --acquisition-manifest data/financial_ml/official_batch/acquisition_results.json
  --literature data/financial_ml/literature_phase5a/literature_15_features.csv
  --annual-facts <PRIVATE_CANONICAL_MOPS_FACTS.csv>

ANNUAL FACTS: ticker,fiscal_year,metric_code,value,unit,filing_version_id,
raw_sha256, with canonical metrics
net_income,total_assets,current_assets,current_liabilities,total_liabilities,
operating_cash_flow,accounts_receivable,inventory,revenue.
Existing MOPS XBRL pipeline must populate these, not FinMind annual candidates.
The acquisition manifest outcome for each FY must also specify:
  original_first_public_at, original_publication_evidence_url,
  original_version_verified=true, first_publication_verified=true,
  point_in_time_eligible=true and validated, original consolidated TIFRS.
An original filing without these independent time/version proofs is excluded.

Y2 target year CY=t: as-of 31-Dec t-1; current feature FY=t-2,
prior comparable FY=t-3. No revised FY2013 financial numbers are admissible.
Official Y1 remains NULL, and no actual models are trained here.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

BENEISH=("b_DSRI","b_GMI","b_AQI","b_SGI","b_DEPI","b_SGAI","b_LVGI","b_TATA")
EXTRAS=("roa","current_ratio","debt_assets","cfo_assets",
        "receivables_yoy","inventory_yoy","operating_cash_conversion")
FEATURES=BENEISH+EXTRAS
FACTS=("net_income","total_assets","current_assets","current_liabilities",
       "total_liabilities","operating_cash_flow","accounts_receivable","inventory","revenue")
SOURCE_KINDS={"mops_xbrl_instance","mops_inline_xbrl","mops_xbrl_zip"}
OUT_COLS=("ticker","target_calendar_year","case_key","split",
          "y_tej_calendar_proxy","y_official_annual_24m",
          "asof_date","feature_fy","prior_feature_fy","x_gate",
          "feature_count","missing_feature_names","source_current_sha256",
          "source_prior_sha256","x_original_version_and_asof_verified",
          "training_ready",*FEATURES)
REQUIRED_PROXY={"ticker","calendar_year","case_key","split",
                "y_tej_calendar_proxy","y_official_annual_24m",
                "feature_asof_date","max_safe_annual_financial_fy"}
LITERATURE_REQUIRED={"ticker","fiscal_year","filing_version_id",
          "filing_version_type","accounting_framework","statement_scope",
          "raw_sha256","analysis_mode",*BENEISH}
FACTS_REQUIRED={"ticker","fiscal_year","metric_code","value","unit",
                "filing_version_id","raw_sha256"}

def sha(raw):return hashlib.sha256(raw).hexdigest()

def csv_load(path, required):
    raw=Path(path).read_bytes()
    val=None
    for enc in ("utf-8-sig","cp950"):
        try:val=raw.decode(enc);break
        except UnicodeDecodeError:pass
    if val is None:raise ValueError("unreadable_csv_encoding")
    rd=csv.DictReader(io.StringIO(val))
    if not set(required).issubset(rd.fieldnames or []):
        raise ValueError("required_columns_missing:"+str(set(required)-set(rd.fieldnames or [])))
    return list(rd),sha(raw)

def csv_bytes(rows, cols):
    out=io.StringIO(newline="")
    wr=csv.DictWriter(out,fieldnames=cols,lineterminator="\n")
    wr.writeheader();wr.writerows(rows)
    return out.getvalue().encode("utf-8-sig")

def immutable(path,content):
    path=Path(path)
    if path.exists() and path.read_bytes()!=content:
        raise FileExistsError("immutable_phase2_output:"+str(path))
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():path.write_bytes(content)

def number(x):
    if str(x).strip()=="":
        return None
    v=float(str(x).strip())
    if not math.isfinite(v):raise ValueError("nonfinite_financial_value")
    return v

def ratio(top,bottom,positive=False):
    if top is None or bottom is None or bottom==0 or (positive and bottom<0):
        return None
    val=top/bottom
    return val if math.isfinite(val) else None

def formatnum(v):
    return "" if v is None else format(v,".12g")

def published(info,cutoff):
    """Require independent official provenance, not a synthetic date guess."""
    if not isinstance(info,dict):
        return "NO_ARCHIVED_OFFICIAL_FY"
    expected={
        "status":"validated","statement_scope":"consolidated",
        "accounting_framework":"TIFRS","filing_version_type":"original"
    }
    for k,v in expected.items():
        if info.get(k)!=v:return "MANIFEST_NOT_ORIGINAL_VALIDATED_CONSOLIDATED"
    if info.get("source_kind") not in SOURCE_KINDS:
        return "UNSUPPORTED_OFFICIAL_SOURCE_KIND"
    if not all(info.get(k) is True for k in (
        "point_in_time_eligible","original_version_verified",
        "first_publication_verified")):
        return "ORIGINAL_VERSION_OR_DATE_NOT_VERIFIED"
    link=str(info.get("original_publication_evidence_url") or "")
    u=urlparse(link)
    if u.scheme!="https" or u.hostname!="mops.twse.com.tw":
        return "NO_OFFICIAL_MOPS_PUBLICATION_EVIDENCE_URL"
    for name in ("content_hash","filing_version_id"):
        if not str(info.get(name) or ""):return "SOURCE_VERSION_HASH_MISSING"
    if not re.fullmatch(r"[a-fA-F0-9]{64}",str(info["content_hash"])):
        return "INVALID_SOURCE_HASH"
    value=str(info.get("original_first_public_at") or "")
    try:
        dt=date.fromisoformat(value[:10])
        if len(value)<10 or not re.fullmatch(r"\d{4}-\d\d-\d\d",value[:10]):
            raise ValueError()
    except ValueError:
        return "FIRST_PUBLICATION_DATE_INVALID_OR_MISSING"
    if dt>cutoff:return "PUBLICATION_AFTER_PREDICTION_CUTOFF"
    return ""

def enrich_facts(rows,manifest):
    by_key={}
    seen=set()
    for r in rows:
        tick=r["ticker"];yr=int(r["fiscal_year"]);metric=r["metric_code"]
        if metric not in FACTS:continue
        k=(tick,yr,metric)
        if k in seen:raise ValueError("duplicate_metric_line:"+str(k))
        seen.add(k)
        info=manifest.get(f"{tick}:{yr}")
        if not info:continue
        if r["raw_sha256"]!=str(info.get("content_hash")) or r["filing_version_id"]!=str(info.get("filing_version_id")):
            raise ValueError("annual_fact_version_or_hash_mismatch:"+str(k))
        if r["unit"]!="TWD":
            raise ValueError("annual_fact_unit_mismatch:"+str(k))
        by_key[k]=number(r["value"])
    return by_key

def extra_metrics(tick,fy,facts):
    def get(n,y=fy):return facts.get((tick,y,n))
    cur_a=get("total_assets");net=get("net_income")
    ca=get("current_assets");cl=get("current_liabilities")
    debt=get("total_liabilities");cfo=get("operating_cash_flow")
    ar=get("accounts_receivable");ar_prev=get("accounts_receivable",fy-1)
    inv=get("inventory");inv_prev=get("inventory",fy-1)
    return {
        "roa":ratio(net,cur_a,True),
        "current_ratio":ratio(ca,cl,True),
        "debt_assets":ratio(debt,cur_a,True),
        "cfo_assets":ratio(cfo,cur_a,True),
        "receivables_yoy":ratio(ar-ar_prev,abs(ar_prev),True)
            if ar is not None and ar_prev is not None else None,
        "inventory_yoy":ratio(inv-inv_prev,abs(inv_prev),True)
            if inv is not None and inv_prev is not None else None,
        "operating_cash_conversion":ratio(cfo,net),  # signed net income may be negative.
    }

def build(proxy_labels,out,acquisition_manifest=None,literature=None,annual_facts=None):
    has_any=any(x is not None for x in (acquisition_manifest,literature,annual_facts))
    has_all=all(x is not None for x in (acquisition_manifest,literature,annual_facts))
    if has_any and not has_all:
        raise ValueError("all_three_x_sources_required")
    labels,lab_sha=csv_load(proxy_labels,REQUIRED_PROXY)
    manifest={};lit={};facts={};source_sha={}
    if has_all:
        manifest_raw=Path(acquisition_manifest).read_bytes()
        manifest=json.loads(manifest_raw).get("outcomes")
        if not isinstance(manifest,dict):raise ValueError("acquisition_outcomes_missing")
        source_sha["manifest"]=sha(manifest_raw)
        literature_rows,source_sha["literature"]=csv_load(literature,LITERATURE_REQUIRED)
        fact_rows,source_sha["annual_facts"]=csv_load(annual_facts,FACTS_REQUIRED)
        facts=enrich_facts(fact_rows,manifest)
        for v in literature_rows:
            k=(v["ticker"],int(v["fiscal_year"]))
            if k in lit:raise ValueError("duplicate_literature_issuer_fy")
            lit[k]=v
    rows=[];stats=Counter();miss=Counter();year_counts=defaultdict(Counter)
    seen=set()
    for l in labels:
        tick=l["ticker"];cy=int(l["calendar_year"]);fy=cy-2
        key=(tick,cy)
        if key in seen:raise ValueError("duplicate_proxy_company_year")
        seen.add(key)
        if tick=="1785":raise ValueError("heldout_in_proxy_label_cohort")
        if l["y_official_annual_24m"].strip():raise ValueError("official_Y1_must_remain_unassigned")
        if l["y_tej_calendar_proxy"] not in ("0","1"):raise ValueError("invalid_proxy_label")
        expected=date(cy-1,12,31)
        if l["feature_asof_date"]!=expected.isoformat() or int(l["max_safe_annual_financial_fy"])!=fy:
            raise ValueError("proxy_feature_asof_policy_mismatch")
        name="";missing=list(FEATURES);computed={}
        curr=manifest.get(f"{tick}:{fy}")
        prior=manifest.get(f"{tick}:{fy-1}")
        if not has_all:
            reason="MOPS_X_SOURCE_NOT_PROVIDED"
        else:
            err1=published(curr,expected)
            err0=published(prior,expected)
            if err1:reason="CURRENT_"+err1
            elif err0:reason="PRIOR_"+err0
            else:
                p=lit.get((tick,fy))
                if not p:
                    reason="NO_MATCHING_BENEISH_FY"
                elif not (p["filing_version_type"]=="original" and
                    p["statement_scope"]=="consolidated" and
                    p["accounting_framework"]=="TIFRS" and
                    p["filing_version_id"]==curr["filing_version_id"] and
                    p["raw_sha256"]==curr["content_hash"]):
                    reason="LITERATURE_CURRENT_SOURCE_NOT_IDENTICAL"
                else:
                    for field in BENEISH:
                        computed[field]=number(p[field])
                    computed.update(extra_metrics(tick,fy,facts))
                    missing=[k for k,v in computed.items() if v is None]
                    reason="MATCHED_PIT_ORIGINAL_FEATURES" if not missing else "PIT_SOURCE_PARTIAL_FEATURES"
        output={
            "ticker":tick,"target_calendar_year":cy,"case_key":l["case_key"],
            "split":l["split"],"y_tej_calendar_proxy":l["y_tej_calendar_proxy"],
            "y_official_annual_24m":"","asof_date":expected.isoformat(),
            "feature_fy":fy,"prior_feature_fy":fy-1,"x_gate":reason,
            "feature_count":len(FEATURES)-len(missing),
            "missing_feature_names":";".join(missing),
            "source_current_sha256":curr.get("content_hash","") if isinstance(curr,dict) else "",
            "source_prior_sha256":prior.get("content_hash","") if isinstance(prior,dict) else "",
            "x_original_version_and_asof_verified":str(reason in (
                "MATCHED_PIT_ORIGINAL_FEATURES","PIT_SOURCE_PARTIAL_FEATURES")).lower(),
            "training_ready":str(reason=="MATCHED_PIT_ORIGINAL_FEATURES").lower(),
            **{k:formatnum(computed.get(k)) for k in FEATURES},
        }
        stats[reason]+=1
        year_counts[str(cy)][reason]+=1
        for m in missing:miss[m]+=1
        rows.append(output)
    report={
        "schema":"fintrust_phase2_proxy_x_pit_bridge_v1",
        "proxy_label_source_sha256":lab_sha,"financial_sources_sha256":source_sha,
        "proxy_company_year_rows":len(rows),
        "proxy_positive_count":sum(r["y_tej_calendar_proxy"]=="1" for r in rows),
        "proxy_negative_count":sum(r["y_tej_calendar_proxy"]=="0" for r in rows),
        "official_y1_verified_positives":0,"official_y1_verified_negatives":0,
        "x_full_15_ready_rows":sum(r["training_ready"]=="true" for r in rows),
        "x_any_computed_rows":sum(int(r["feature_count"])>0 for r in rows),
        "x_coverage_by_gate":dict(sorted(stats.items())),
        "feature_missing_counts":dict(sorted(miss.items())),
        "by_target_calendar_year":{y:dict(sorted(c.items())) for y,c in sorted(year_counts.items())},
        "no_model_training":True,
        "research_target":"Y2 TEJ calendar-year proxy; NOT official Y1 24-month annual restatement",
        "strict_pit":"As-of CY(t-1) December 31, feature FY<=t-2; require actual official first public at, original consolidated TIFRS, cryptographic archive identity across literature/facts.",
        "source_limitation":"Original XBRL archival state / as-of cannot be inferred from retrospective feature computation or a reporting-period end date.",
        "holdout_1785_excluded":True,
    }
    b=csv_bytes(rows,OUT_COLS)
    report["x_y_join_sha256"]=sha(b)
    target=Path(out)
    immutable(target/"phase2_proxy_x_y_pit_private.csv",b)
    immutable(target/"phase2_x_y_coverage.json",
              (json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode())
    return report

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--proxy-labels",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--acquisition-manifest")
    p.add_argument("--literature")
    p.add_argument("--annual-facts")
    a=p.parse_args()
    print(json.dumps(build(a.proxy_labels,a.out,a.acquisition_manifest,
                           a.literature,a.annual_facts),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
