"""Round2: turn locally exported FinLab announcements into an auditable REVIEW queue.

No login/token required: use the existing CSV stored under fintrust_backend/data,
which is gitignored. This program DOES NOT label Y=0 or Y=1. It only classifies
announcement *leads* and candidate fiscal years. MOPS original version and
financial-amount verification are mandatory before supervised admission.

python -m research.financial_ml.round2_finlab_events \
  --input-csv data/financial_ml/finlab_restatement_candidates.csv \
  --out data/financial_ml/round2_finlab_review
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

SCHEMA = "fintrust_round2_finlab_notice_triage_v1"
REQUIRED = {"stock_id", "date", "title", "info"}
AS_OF = datetime.fromisoformat("2026-10-24T23:59:59")
RESTATE = re.compile("重編|重行編製|重新編製")
FINANCIAL = re.compile("財務報告|財務報表|財報|損益表|資產負債表|現金流量表")
CORRECT_FINANCIAL = re.compile(
    r"更正.{0,40}(?:財務報告|財務報表|財報|合併財務|個體財務)|"
    r"(?:財務報告|財務報表|財報|合併財務|個體財務).{0,40}更正"
)
PROCESS_ONLY = re.compile(
    "展延|延期|申報期限|申報日期|預計|預定|擬重編|將予重編|"
    "未依限|尚未完成|董事會召開日期|預計提報|更正主旨.*董事會"
)
SUBSIDIARY = re.compile("代子公司|子公司.*重編|子公司.*更正")
STANDALONE_ONLY = re.compile("個體|個別|母公司")
CONSOLIDATED = re.compile("合併")
FOURTH_QUARTER = re.compile(r"第\s*[4四]\s*季|Q4|12\s*月|十二月")
YEAR_TOKEN = r"(?:19\d{2}|20\d{2}|\d{2,3}|[〇○零一二三四五六七八九十百]{2,6})"
ANNUAL_YEAR = re.compile(
    rf"(?<![A-Za-z0-9])(?P<y>{YEAR_TOKEN})\s*"
    r"(?:年度(?!\s*(?:第\s*[123一二三]\s*季|上半|前三))|"
    r"年\s*(?:第\s*[4四]\s*季|12\s*月|十二月)|Q4)"
)
YEAR_SPAN = re.compile(r"\d{2,3}\s*(?:年)?\s*(?:至|到|~|～|-)\s*\d{2,3}\s*年")
Q4_RANGE = re.compile(r"\d{2,3}\s*Q4\s*(?:至|到|~|～|-)\s*\d{2,3}\s*Q4", re.I)
CONTEXT_ONLY = re.compile("更正.{0,30}重編後|重編後.{0,35}(?:附註|附表|iXBRL|更正)", re.I)
FY_TOKEN = re.compile(r"(?<![A-Za-z0-9])FY\s*(20\d{2})\b", re.I)
DIGIT_MAP = str.maketrans("〇○零一二三四五六七八九","000123456789")
CHINESE = {"十":10, "百":100}

COLS = (
    "source_notice_id","ticker","issuer_name","announcement_date",
    "announcement_year","title","event_group","priority",
    "fiscal_year_candidates","annual_year_extraction_status",
    "subsidiary_flag","consolidated_in_title","standalone_in_title",
    "procedural_notice_flag","source_content_sha256","source_dataset",
    "event_date_verified","core_amount_changed_verified",
    "official_mops_filing_verified","training_y","next_review_action",
)
FY_COLS = ("source_notice_id","ticker","announcement_date","candidate_fiscal_year",
           "event_group","priority","statement_scope_review_required",
           "training_y","source_content_sha256")


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def fiscal_year(token):
    x = token.translate(DIGIT_MAP)
    if x.isdigit():
        y = int(x)
    elif all(ch in "0123456789" for ch in x):
        y = int(x)
    else:
        # Supports 九十五 (95), 一百零八 (108), 一十六 (16).
        n, acc = 0, 0
        for ch in x:
            if ch.isdigit():
                n = int(ch)
            elif ch in CHINESE:
                acc += (n or 1) * CHINESE[ch]
                n = 0
            else:
                return None
        y = acc + n
    if 1900 <= y <= 2100:
        return y
    if 80 <= y <= 200:
        return 1911 + y
    return None


def annual_years(title):
    out = {fiscal_year(m.group("y")) for m in ANNUAL_YEAR.finditer(title)}
    out.update(int(m.group(1)) for m in FY_TOKEN.finditer(title))
    return sorted(y for y in out if y and 2000 <= y <= AS_OF.year)


def classify(title):
    is_restate = bool(RESTATE.search(title))
    is_fin = bool(FINANCIAL.search(title))
    is_correction = bool(CORRECT_FINANCIAL.search(title))
    procedural = bool(PROCESS_ONLY.search(title))
    subsidiary = bool(SUBSIDIARY.search(title))
    years = annual_years(title)
    consolidated = bool(CONSOLIDATED.search(title))
    standalone = bool(STANDALONE_ONLY.search(title)) and not consolidated
    if is_restate and is_fin and years and not procedural and not subsidiary and not CONTEXT_ONLY.search(title):
        group = "A_RESTATEMENT_ANNUAL_REVIEW"
        priority = "HIGH" if consolidated and not standalone else "MEDIUM"
    elif is_restate and is_fin:
        group, priority = "B_RESTATEMENT_CONTEXT_REVIEW", "MEDIUM"
    elif is_correction and years and not procedural and not subsidiary:
        group, priority = "C_ANNUAL_CORRECTION_REVIEW", "MEDIUM"
    elif is_correction or (is_restate and is_fin):
        group, priority = "D_QUARTER_OR_YEAR_UNCLEAR", "LOW"
    else:
        group, priority = "E_ADMIN_OR_NONFINANCIAL_REVIEW", "LOW"
    status = ("YEAR_RANGE_REVIEW" if (YEAR_SPAN.search(title) or Q4_RANGE.search(title)) else
              "CANDIDATE_YEAR_ONLY" if years else "NO_EXPLICIT_ANNUAL_YEAR")
    return group, priority, years, status, procedural, subsidiary, consolidated, standalone


def emit_csv(columns, rows):
    f=io.StringIO(newline="")
    w=csv.DictWriter(f, fieldnames=columns, lineterminator="\n",
                     extrasaction="raise")
    w.writeheader()
    w.writerows(rows)
    return f.getvalue().encode("utf-8")


def preserve(path, blob):
    path=Path(path)
    if path.exists():
        if path.read_bytes()!=blob:
            raise FileExistsError("finlab_round2_refuse_overwrite:" + str(path))
    else:
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(blob)


def build(input_csv, out, *, allow_post_2023=True):
    """Keep actual 2024-2026 records visible; never infer entitlement completeness."""
    blob=Path(input_csv).read_bytes()
    text=None
    for encoding in ("utf-8-sig","cp950"):
        try:
            text=blob.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if text is None:
        raise ValueError("finlab_input_encoding_unreadable")
    reader=csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
        raise ValueError("finlab_required_columns_missing")
    rows=[]; fy_links=[]; seen=set(); invalid=[]; future=0
    for line,r in enumerate(reader,2):
        ticker=str(r.get("stock_id") or "").strip()
        title=str(r.get("title") or "").strip()
        dt=str(r.get("date") or "").strip()
        if len(ticker)!=4 or not ticker.isascii() or not ticker.isdecimal() or not title:
            invalid.append({"row":line,"reason":"INVALID_TICKER_OR_TITLE"})
            continue
        try:
            when=datetime.fromisoformat(dt)
        except ValueError:
            invalid.append({"row":line,"reason":"INVALID_ANNOUNCEMENT_DATETIME"})
            continue
        if when>AS_OF:
            future+=1
            continue
        if not allow_post_2023 and when.year>2023:
            continue
        # Include original info in hash to identify corrected versions;
        # licensed announcement body is NOT written to the public repo.
        content_hash=_sha((ticker+"\n"+dt+"\n"+title+"\n"+str(r.get("info") or "")).encode("utf-8"))
        event_id=content_hash[:24]
        if event_id in seen:
            continue
        seen.add(event_id)
        group,priority,years,status,procedural,subsidiary,consolidated,standalone=classify(title)
        fields={
            "source_notice_id":event_id, "ticker":ticker,
            "issuer_name":str(r.get("name") or "").strip(),
            "announcement_date":dt, "announcement_year":str(when.year),
            "title":title,"event_group":group,"priority":priority,
            "fiscal_year_candidates":";".join(map(str,years)),
            "annual_year_extraction_status":status,
            "subsidiary_flag":str(subsidiary).lower(),
            "consolidated_in_title":str(consolidated).lower(),
            "standalone_in_title":str(standalone).lower(),
            "procedural_notice_flag":str(procedural).lower(),
            "source_content_sha256":content_hash,
            "source_dataset":"finlab:important_info_announcement",
            "event_date_verified":"false","core_amount_changed_verified":"false",
            "official_mops_filing_verified":"false","training_y":"",
            "next_review_action":("CHECK_ORIGINAL_MOPS_AND_FINANCIAL_AMOUNTS"
                 if group in ("A_RESTATEMENT_ANNUAL_REVIEW",
                              "C_ANNUAL_CORRECTION_REVIEW") else
                 "CONFIRM_EVENT_SCOPE_AND_FISCAL_YEAR"),
        }
        rows.append(fields)
        if group in ("A_RESTATEMENT_ANNUAL_REVIEW","C_ANNUAL_CORRECTION_REVIEW"):
            for fy in years:
                if 2013<=fy<=2023 and fy<=when.year:
                    fy_links.append({
                        "source_notice_id":event_id,"ticker":ticker,
                        "announcement_date":dt,"candidate_fiscal_year":str(fy),
                        "event_group":group,"priority":priority,
                        "statement_scope_review_required":"true",
                        "training_y":"","source_content_sha256":content_hash,
                    })
    rows.sort(key=lambda r:(r["ticker"],r["announcement_date"],r["source_notice_id"]))
    fy_links.sort(key=lambda r:(r["ticker"],r["candidate_fiscal_year"],
                                 r["announcement_date"],r["source_notice_id"]))
    family=Counter(r["event_group"] for r in rows)
    group_companies={k:len({r["ticker"] for r in rows if r["event_group"]==k})
                     for k in sorted(family)}
    annual_pairs={(r["ticker"],r["candidate_fiscal_year"]) for r in fy_links}
    notice_csv=emit_csv(COLS,rows)
    fy_csv=emit_csv(FY_COLS,fy_links)
    report={
        "schema":SCHEMA,"source_file_sha256":_sha(blob),
        "source_total_candidate_rows":len(rows),
        "unique_issuers_in_filtered_input":len({r["ticker"] for r in rows}),
        "title_restatement_word_rows":sum(
            bool(RESTATE.search(r["title"])) for r in rows),
        "family_count":dict(sorted(family.items())),
        "family_issuer_count":group_companies,
        "priority_high_rows":sum(r["priority"]=="HIGH" for r in rows),
        "fy2013_2023_review_event_links":len(fy_links),
        "fy2013_2023_unique_review_issuer_years":len(annual_pairs),
        "fy2013_2023_unique_review_issuers":len({p[0] for p in annual_pairs}),
        "unparseable_input_rows":len(invalid),
        "future_rows_excluded":future,
        "y_positive_assigned":0,"y_negative_assigned":0,
        "source_date_warning":"key_date is FinLab ingestion metadata, not an announcement date. Use date.",
        "free_plan_warning":"Free cutoff reported as 2023-12-31, yet this actual local CSV may include later records; do not equate observed records with complete licensed coverage.",
        "not_a_training_dataset":True,
        "outputs_sha256":{
            "round2_finlab_review_notices.csv":_sha(notice_csv),
            "round2_finlab_annual_year_review_links.csv":_sha(fy_csv),
        },
        "review_label_condition":"Requires affected consolidated annual report, original public statement date, original MOPS correction evidence and actual core amount adjustment.",
    }
    out=Path(out)
    preserve(out/"round2_finlab_review_notices.csv",notice_csv)
    preserve(out/"round2_finlab_annual_year_review_links.csv",fy_csv)
    preserve(out/"round2_finlab_triage_report.json",
             (json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2)+"\n").encode("utf-8"))
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-csv",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--cutoff-2023",action="store_true",
                   help="Exclude records newer than FinLab's published free cutoff")
    a=p.parse_args(argv)
    print(json.dumps(build(a.input_csv,a.out,allow_post_2023=not a.cutoff_2023),
                     ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
