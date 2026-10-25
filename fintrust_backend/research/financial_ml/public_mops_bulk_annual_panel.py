"""Acquire publicly available MOPS *all-market quarterly report summaries*.

NOT original filing XBRL; later adjustments may have revised historical values.
No TEJ/FinLab data; outputs contain publicly posted aggregate financials only.
Read FY2013-FY2021, Q4 annual P&L and cashflow + 12/31 balance, both TWSE/TPEx.
Each successful response preserved with official URL, query, SHA256.
No dodging blocks/rate limits; request only public old-MOPS documented endpoint.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
import time
import unicodedata
from collections import Counter,defaultdict
from datetime import datetime,timezone
from pathlib import Path

ENDPOINT="https://mopsov.twse.com.tw/mops/web/ajax_"
KINDS={"income":"t163sb04","balance":"t163sb05","cashflow":"t163sb20"}
MEASURES=("revenue","cogs","operating_income","net_income",
          "assets","current_assets","current_liabilities","liabilities",
          "noncurrent_assets","noncurrent_liabilities","cfo")
# Annual generic-industry summary tables (non-financials); avoid misusing banks'
# entirely different accounting concepts as if the same 11 features.
ALIASES={
 "income":{
  "revenue":("營業收入",),"cogs":("營業成本",),
  "operating_income":("營業利益(損失)","營業利益(損)","營業利益"),
  "net_income":("本期淨利(淨損)","本期淨利(淨損)","本期稅後淨利(淨損)"),
 },
 "balance":{
  "assets":("資產總計",),"current_assets":("流動資產",),
  "current_liabilities":("流動負債",),"liabilities":("負債總計",),
  "noncurrent_assets":("非流動資產",),
  "noncurrent_liabilities":("非流動負債",)
 },
 "cashflow":{"cfo":("營業活動之淨現金流入(流出)","營業活動之淨現金流量","營業活動淨現金流量")},
}
BASE=("roa","current_ratio","debt_assets","cfo_assets","cfo_net_income",
      "gross_margin","operating_margin","net_margin",
      "accruals_ni_minus_cfo_assets","working_capital_assets",
      "noncurrent_assets_ratio","revenue_yoy","beneish_SGI","beneish_GMI",
      "debt_assets_change","current_ratio_change","operating_cashflow_growth")
HEADERS=("ticker","issuer_name","financial_fy","market","sector_schema",
         "period_end","vintage_download_utc","source_income_sha256",
         "source_balance_sha256","source_cashflow_sha256",
         "annual_income_unit","annual_balance_unit","annual_cashflow_unit",
         *MEASURES,*BASE)


def normalize(x):
    s=unicodedata.normalize("NFKC",str(x or "")).replace(" ","").replace("\n","")
    return s.replace("–","-").replace("−","-").replace("：",":")

def number(s):
    t=normalize(s).replace(",","")
    if t in ("","--","-","NaN","nan","None","不適用"):return None
    if t.startswith("(") and t.endswith(")"):t="-"+t[1:-1]
    try:
        v=float(t)
        return v if math.isfinite(v) else None
    except ValueError:return None

def div(a,b):
    if a is None or b is None or b==0:return None
    result=a/b
    return result if math.isfinite(result) else None

def diff(a,b):
    return a-b if a is not None and b is not None else None

def formatval(v):
    return "" if v is None else format(v,".12g")

def company_table(df,kind):
    names={normalize(c):c for c in df.columns}
    tid=names.get("公司代號")
    if tid is None or "公司名稱" not in names or df.shape[0]<30:
        return None
    if kind=="income" and not {"營業收入","營業成本"}.issubset(names):
        return None
    if kind=="balance" and not {"資產總計","流動資產"}.issubset(names):
        return None
    if kind=="cashflow" and not any("營業活動之淨現金" in k for k in names):
        return None
    return names

def parse_html(html,year,market,kind,sha):
    import pandas as pd
    try:
        tables=pd.read_html(io.StringIO(html.decode("utf-8","replace")))
    except ValueError:return {},{"status":"NO_HTML_TABLES"}
    found={}
    scanned=0
    conflicts=set()
    for table in tables:
        cols=company_table(table,kind)
        if cols is None:continue
        scanned+=1
        for _,line in table.iterrows():
            ticker=str(line[cols["公司代號"]]).strip()
            if ticker.endswith(".0"):ticker=ticker[:-2]
            if not re.fullmatch(r"\d{4}",ticker):
                continue
            values={}
            for metric,aliases in ALIASES[kind].items():
                hits=[]
                for alias in aliases:
                    col=cols.get(normalize(alias))
                    if col is not None:
                        n=number(line[col])
                        if n is not None:hits.append(n)
                values[metric]=hits[0] if hits and all(v==hits[0] for v in hits) else None
            name=str(line[cols["公司名稱"]]).strip()
            key=(ticker,year)
            if key in found:
                conflicts.add(key)
                continue
            found[key]={"ticker":ticker,"issuer_name":name,"financial_fy":year,
                        "market":market,"sector_schema":"general_summary",
                        "period_end":f"{year}-12-31",**values,
                        "source_"+kind+"_sha256":sha}
    for k in conflicts:found.pop(k,None)
    return found,{"status":"OK","tables_in_html":len(tables),
                  "matched_general_tables":scanned,"general_issuer_rows":len(found),
                  "duplicate_ticker_years_blocked":len(conflicts)}


def score(row,prior):
    a=row.get
    feats={
        "roa":div(a("net_income"),a("assets")),
        "current_ratio":div(a("current_assets"),a("current_liabilities")),
        "debt_assets":div(a("liabilities"),a("assets")),
        "cfo_assets":div(a("cfo"),a("assets")),
        "cfo_net_income":div(a("cfo"),a("net_income")),
        "gross_margin":div(diff(a("revenue"),a("cogs")),a("revenue")),
        "operating_margin":div(a("operating_income"),a("revenue")),
        "net_margin":div(a("net_income"),a("revenue")),
        "accruals_ni_minus_cfo_assets":div(diff(a("net_income"),a("cfo")),a("assets")),
        "working_capital_assets":div(diff(a("current_assets"),a("current_liabilities")),a("assets")),
        "noncurrent_assets_ratio":div(a("noncurrent_assets"),a("assets")),
        "revenue_yoy":None,
        "beneish_SGI":None,
        "beneish_GMI":None,
        "debt_assets_change":None,
        "current_ratio_change":None,
        "operating_cashflow_growth":None,
    }
    if prior is not None:
        p=prior.get
        sgi=div(a("revenue"),p("revenue"))
        feats["beneish_SGI"]=sgi
        feats["revenue_yoy"]=sgi-1 if sgi is not None else None
        gm=feats["gross_margin"]
        gm_pre=div(diff(p("revenue"),p("cogs")),p("revenue"))
        feats["beneish_GMI"]=div(gm_pre,gm)
        oldlev=div(p("liabilities"),p("assets"))
        oldcur=div(p("current_assets"),p("current_liabilities"))
        feats["debt_assets_change"]=diff(feats["debt_assets"],oldlev)
        feats["current_ratio_change"]=diff(feats["current_ratio"],oldcur)
        feats["operating_cashflow_growth"]=div(diff(a("cfo"),p("cfo")),abs(p("cfo")) if p("cfo") is not None else None)
    return feats


def build(start,end,out,markets=("sii","otc"),delay=3.1):
    import requests
    out=Path(out)
    (out/"raw_official_html").mkdir(parents=True,exist_ok=True)
    session=requests.Session()
    session.headers.update({
        "User-Agent":"Mozilla/5.0 (compatible; Financial research historical public summary)",
        "Referer":"https://mopsov.twse.com.tw/mops/web/index",
        "Accept-Language":"zh-TW,zh;q=0.9"})
    per_kind=defaultdict(dict)
    evidence=[]
    failure=Counter()
    for fy in range(start,end+1):
        for market in markets:
            for kind,resource in KINDS.items():
                url=ENDPOINT+resource
                params={"encodeURIComponent":"1","step":"1","firstin":"1",
                    "off":"1","isQuery":"Y","TYPEK":market,
                    "year":str(fy-1911),"season":"04"}
                dst=out/"raw_official_html"/f"{fy}_{market}_{kind}.html"
                if dst.exists():
                    content=dst.read_bytes()
                    source="RESUMED_EXISTING_SHA_ARCHIVE"
                else:
                    try:
                        r=session.post(url,data=params,timeout=65)
                        r.raise_for_status()
                        content=r.content
                    except requests.RequestException as exc:
                        failure[f"{kind}:http_error"]+=1
                        print("HTTP_FAILED",fy,market,kind,str(exc)[:160],flush=True)
                        evidence.append({"financial_fy":fy,"market":market,"source_kind":kind,
                            "source_url":url,"status":"HTTP_FAILED"})
                        time.sleep(max(delay,3))
                        continue
                    source="HTTP_POST_HISTORICAL_SUMMARY"
                    if len(content)<10000 or b"FOR SECURITY" in content:
                        failure[f"{kind}:blocked_or_empty"]+=1
                        evidence.append({"financial_fy":fy,"market":market,"source_kind":kind,
                            "source_url":url,"status":"BLOCKED_OR_EMPTY",
                            "size_bytes":len(content)})
                        print("BLOCKED",fy,market,kind,len(content),flush=True)
                        time.sleep(max(delay,3))
                        continue
                    dst.write_bytes(content)
                digest=hashlib.sha256(content).hexdigest()
                found,diag=parse_html(content,fy,market,kind,digest)
                per_kind[kind].update(found)
                event={"financial_fy":fy,"market":market,"source_kind":kind,
                    "source_url":url,"http_form":params,"sha256":digest,"size_bytes":len(content),
                    "filename":dst.name,"download_provenance":source,
                    "fetched_on_utc":datetime.now(timezone.utc).isoformat(),**diag}
                evidence.append(event)
                if not found:
                    failure[f"{kind}:no_company_rows"]+=1
                print("FETCH",fy,market,kind,len(found),diag.get("status"),len(content),flush=True)
                time.sleep(delay)
    allkeys=set().union(*(set(d) for d in per_kind.values()))
    merged=[]
    for key in sorted(allkeys):
        kind_data={k:per_kind[k].get(key,{}) for k in KINDS}
        base=next((v for v in kind_data.values() if v),{})
        if not base:continue
        outrow={k:base.get(k,"") for k in ("ticker","issuer_name","financial_fy","market","sector_schema","period_end")}
        for metric in MEASURES:
            source="income" if metric in ALIASES["income"] else "balance" if metric in ALIASES["balance"] else "cashflow"
            outrow[metric]=kind_data[source].get(metric)
        for kind in KINDS:outrow["source_"+kind+"_sha256"]=kind_data[kind].get("source_"+kind+"_sha256","")
        outrow["vintage_download_utc"]=datetime.now(timezone.utc).isoformat()
        for kind in KINDS:outrow["annual_"+kind+"_unit"]="TWD_1000_ASSUMED_VERIFY_TABLE_NOTE"
        merged.append(outrow)
    panel_index={(r["ticker"],r["financial_fy"]):r for r in merged}
    for row in merged:
        pre=panel_index.get((row["ticker"],row["financial_fy"]-1))
        row.update(score(row,pre))
    with (out/"all_market_public_annual_financial_features_2013_2021.csv").open(
        "w",newline="",encoding="utf-8-sig") as fp:
        wr=csv.DictWriter(fp,fieldnames=HEADERS)
        wr.writeheader()
        for row in merged:
            wr.writerow({k:formatval(row.get(k)) if k in MEASURES or k in BASE else row.get(k,"") for k in HEADERS})
    (out/"official_retrieval_manifest.json").write_text(
        json.dumps({"schema":"mops_marketwide_summary_nonfinancial_v1",
            "periods":[start,end],"markets":list(markets),"requests":evidence,
            "failures":dict(failure),"company_fy_rows":len(merged),
            "companies":len({r["ticker"] for r in merged}),
            "feature_nonmissing":{m:sum(r[m] is not None for r in merged) for m in BASE},
            "warning":"NOT original-vintage XBRL. Current historical MOPS summary can be revised. Quarterly Q4 P&L/cashflow expected cumulative annual; check official disclosure footnotes. General-sector only; financial companies excluded from comparable feature panel."},
            ensure_ascii=False,indent=2),encoding="utf-8")
    print("SUMMARY",json.dumps({"rows":len(merged),
        "companies":len({r["ticker"] for r in merged}),
        "fy_range":[start,end],"issues":dict(failure),
        "available_features":{k:sum(r[k] is not None for r in merged) for k in BASE}},ensure_ascii=False),flush=True)
    return len(merged)

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--start",type=int,default=2013)
    p.add_argument("--end",type=int,default=2021)
    p.add_argument("--out",default="out/public_mops_marketwide")
    p.add_argument("--markets",nargs="+",default=["sii","otc"])
    p.add_argument("--delay",type=float,default=3.1)
    args=p.parse_args()
    if not 2013<=args.start<=args.end<=2025:raise ValueError("invalid_fiscal_year_range")
    if set(args.markets)-{"sii","otc"}:raise ValueError("markets_not_allowed")
    build(args.start,args.end,args.out,args.markets,args.delay)
if __name__=="__main__":main()
