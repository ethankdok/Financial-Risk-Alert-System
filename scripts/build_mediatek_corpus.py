"""Build second-company corpus from official MediaTek transcript PDFs.

The publisher URL must itself encode YYYYQx. Only URLs appearing in the
company's financial-information webpage are accepted. No inferred periods.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import re
import time
from pathlib import Path
from urllib.parse import unquote,urlparse
import pandas as pd
import requests
from pypdf import PdfReader

from discover_mediatek_transcripts import BASE,find_candidates,valid
from build_tsmc_corpus import FIELDS,INDEX_FIELDS,extract_pdf

RE_PERIOD=re.compile(r"(?<!\d)(20(?:1\d|2\d))Q([1-4])(?!\d)",re.I)
def period_from_official_url(url):
    if not valid(url) or not urlparse(url).path.lower().endswith(".pdf"):
        return None
    matches=RE_PERIOD.findall(unquote(url))
    if len(set(matches))!=1:return None
    year,q=matches[0]
    return f"{year}Q{q}"

def collect(start=2022,end=2025,out=Path("data/mediatek_corpus"),delay=.8):
    out.mkdir(parents=True,exist_ok=True)
    sess=requests.Session()
    sess.headers["User-Agent"]="Coursework-official-corpus-reader/1.0"
    listing=BASE+"/investor-relations/financial-information"
    response=sess.get(listing,timeout=30)
    response.raise_for_status()
    links={}
    for source_page in (listing, BASE+"/zh-tw/investor-relations/financial-information", BASE+"/zh-cn/investor-relations/financial-information"):
        try:
            page_response = response if source_page == listing else sess.get(source_page,timeout=30)
            page_response.raise_for_status()
            for candidate in find_candidates(page_response.text,source_page):
                period=period_from_official_url(candidate["href"])
                if not period or not start <= int(period[:4]) <= end:continue
                links.setdefault(period,[]).append((candidate["href"],source_page))
        except requests.RequestException as exc:
            print("ALTERNATE_LISTING_UNAVAILABLE",source_page,str(exc)[:100])
    # Independently indexed official 3Q24 PDF (correct quarter printed on cover).
    # Original English listing currently serves byte-identical 2023Q3 PDF.
    fallback_2024q3 = ("https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/"
                       "Quarterly%20Earnings%20Release/2024/"
                       "Quarterly%20Earnings%20Release-2024Q3/"
                       "%E8%AF%B4%E6%98%8E%E4%BC%9A%E9%80%90%E5%AD%97%E7%A8%BF.pdf")
    if period_from_official_url(fallback_2024q3)=="2024Q3":
        links.setdefault("2024Q3",[]).append((fallback_2024q3,fallback_2024q3))
    docs,index=[],[]
    seen_sha={}
    for y in range(start,end+1):
        for q in range(1,5):
            p=f"{y}Q{q}"
            urls=links.get(p,set())
            meta={"period":p,"source_page":listing,"source_pdf":"",
                  "status":"","note":"","sha256":"","text_length":""}
            try:
                if not urls:
                    raise ValueError("No listed official PDF for period")
                # Prefer English-listing version; only fall back to a verified
                # alternative from the publisher's Traditional Chinese page.
                failure_notes=[]
                chosen=None
                for url,source_page in dict.fromkeys(urls):
                    try:
                        if not valid(url) or period_from_official_url(url)!=p:
                            raise ValueError("PDF provenance/period mismatch")
                        r=sess.get(url,timeout=80)
                        r.raise_for_status()
                        text=extract_pdf(r.content)
                        if p=="2024Q3" and url==fallback_2024q3 and not re.search(
                            r"MediaTek\s+3Q24\s+Earnings\s+Call", text[:1200], re.I
                        ):
                            raise ValueError("Alternate PDF cover does not confirm 3Q24 call")
                        sha=hashlib.sha256(r.content).hexdigest()
                        if sha in seen_sha:
                            print("DUPLICATE_PDF",p,"same_as",seen_sha[sha],
                                  "current_url",url)
                            raise ValueError(f"Same PDF bytes as {seen_sha[sha]}")
                        chosen=(url,source_page,text,sha)
                        break
                    except (ValueError,requests.RequestException) as error:
                        failure_notes.append(f"{url}: {error}")
                if chosen is None:
                    raise ValueError("; ".join(failure_notes)[:250])
                url,source_page,text,sha=chosen
                if p in ("2023Q3","2024Q3"):
                    markers=re.findall(r"\b[1-4]Q2\d\b",text[:1800],flags=re.I)
                    print("Q3_PDF_COVER_AUDIT",p,
                          "first_period_markers",markers[:4],
                          "extracted_text_sha256",hashlib.sha256(text.encode()).hexdigest())
                    expected=f"3Q{p[2:4]}"
                    if expected.lower() not in [m.lower() for m in markers[:3]]:
                        raise ValueError(f"Cover text does not confirm {expected}; quarantine")
                meta.update(status="ok",source_pdf=url,source_page=source_page,
                            sha256=sha,text_length=len(text))
                seen_sha[sha]=p
                docs.append({
                    "ticker":"2454","company":"MediaTek",
                    "industry":"semiconductor_fabless","year":y,"quarter":q,
                    "period":p,"document_type":"full_earnings_transcript",
                    "language":"en_may_include_translation","text":text,
                    "source_page":source_page,"source_pdf":url,
                    "sha256":sha,"text_length":len(text),
                })
                print("OK",p,len(text))
            except (ValueError,requests.RequestException) as e:
                meta.update(status="needs_manual_review",note=str(e)[:300])
                print("REVIEW",p,meta["note"])
            index.append(meta)
            time.sleep(delay)
    pd.DataFrame(docs,columns=FIELDS).to_csv(out/"mediatek_quarterly_text.csv",index=False,encoding="utf-8-sig")
    if docs:
        pd.DataFrame(docs,columns=FIELDS).to_parquet(out/"mediatek_quarterly_text.parquet",index=False)
    with (out/"mediatek_source_index.csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=INDEX_FIELDS);w.writeheader();w.writerows(index)
    print("SOURCE_STATUS",{k:sum(i["status"]==k for i in index) for k in {"ok","needs_manual_review"}})
    print("DOCUMENTS",len(docs),"OF",len(index))
if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--start",type=int,default=2022)
    a.add_argument("--end",type=int,default=2025)
    a.add_argument("--out",type=Path,default=Path("data/mediatek_corpus"))
    args=a.parse_args()
    collect(args.start,args.end,args.out)
