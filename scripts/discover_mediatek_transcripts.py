"""Read-only discovery of official MediaTek 2022–2025 transcript links.

Only reports URL and nearby structural context, does not guess fiscal periods,
download PDFs or classify MediaTek using TSMC thresholds.
"""
from __future__ import annotations
import csv
import re
import time
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

BASE="https://www.mediatek.com"
PAGES=[
    BASE+"/investor-relations/financial-information",
    "https://corp.mediatek.com/investor-relations/financial-information/quarterly-earnings/2025",
    "https://corp.mediatek.com/investor-relations/financial-information/quarterly-earnings/2024",
    "https://corp.mediatek.com/investor-relations/financial-information/quarterly-earnings/2023",
    "https://corp.mediatek.com/investor-relations/financial-information/quarterly-earnings/2022",
]
FIELDS=["source_page","anchor_text","href","parent_text_snippet","prev_heading",
        "prev_year","proposed_period","status","note"]
def valid(url:str)->bool:
    p=urlparse(url)
    return p.scheme=="https" and (p.hostname=="mediatek.com" or
            (p.hostname and p.hostname.endswith(".mediatek.com")))

def find_candidates(html,page):
    soup=BeautifulSoup(html,"html.parser")
    result=[]
    for anchor in soup.select("a"):
        label=anchor.get_text(" ",strip=True)
        href=anchor.get("href","")
        if not href:continue
        if not ("transcript" in label.lower() or "逐字稿" in label or
                ("transcript" in href.lower() and ".pdf" in href.lower())):
            continue
        url=urljoin(page,href)
        parent=anchor.parent.get_text(" ",strip=True)[:160] if anchor.parent else ""
        heading=anchor.find_previous(re.compile("^(?:h[1-6])$"))
        heading_text=heading.get_text(" ",strip=True)[:90] if heading else ""
        year=re.search(r"20(?:1[5-9]|2[0-6])",page)
        result.append({
            "source_page":page,"anchor_text":label[:90],"href":url,
            "parent_text_snippet":parent,"prev_heading":heading_text,
            "prev_year":year.group() if year else "",
            # Do not map quarters from page order alone: dynamic site layout.
            "proposed_period":"",
            "status":"unverified_needs_period_mapping" if valid(url) else "non_official_link",
            "note":"Period must be verified against neighboring Qx and PDF cover before use.",
        })
    return result

def discover(out):
    rows=[]
    sess=requests.Session()
    sess.headers["User-Agent"]="Coursework-corpus-discovery/1.0"
    for page in PAGES:
        try:
            r=sess.get(page,timeout=25)
            r.raise_for_status()
            found=find_candidates(r.text,page)
            rows.extend(found)
            print("SOURCE",page,"status",r.status_code,"transcript_link_candidates",len(found))
            for row in found[:8]:
                print("CANDIDATE",row["prev_heading"],row["parent_text_snippet"],
                      row["href"][:200])
        except requests.RequestException as exc:
            print("SOURCE_ERROR",page,type(exc).__name__,str(exc)[:140])
        time.sleep(0.8)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print("TOTAL_CANDIDATES",len(rows),"unique",len({r["href"] for r in rows}))

if __name__=="__main__":
    discover(Path("data/mediatek_corpus/official_link_candidates.csv"))
