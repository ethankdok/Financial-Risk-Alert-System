"""Bounded MOPS public announcement keyword discovery (Round 2).

Historical MOPS query HTML changes often: fetch, preserve raw bytes and SHA,
extract coarse issuer/title *review leads* only. Never assign annual Y from
keyword, query failure, no-results message, or possible incomplete pagination.

This is intentionally limited to two recent reporting years x two words;
it is NOT all-market/all-year completeness certification.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
import time
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://mops.twse.com.tw/mops/web/ajax_t51sb10"
AS_OF = "2026-10-24"
YEARS = (113, 114)  # ROC 113=2024, ROC 114=2025, query dates not fiscal years
KEYWORDS = ("重編", "更正財務報告")
COLUMNS = ("query_roc_year", "query_keyword", "ticker", "company",
           "title_candidate", "row_excerpt", "request_source_url",
           "report_fiscal_year_verified", "original_notice_verified",
           "issuer_year_y", "status")


def sha(blob):
    return hashlib.sha256(blob).hexdigest()


def immutable_write(p, blob):
    p = Path(p)
    if p.exists():
        if p.read_bytes() != blob:
            raise FileExistsError("mops_snapshot_digest_conflict:" + str(p))
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(blob)


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.tr = None
        self.td = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.tr = []
        elif tag in ("td", "th") and self.tr is not None:
            self.td = []
        elif tag == "input" and self.tr is not None:
            a = dict(attrs)
            if a.get("value"):
                self.tr.append(str(a["value"]).strip())

    def handle_data(self, data):
        if self.td is not None:
            self.td.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.td is not None:
            v = " ".join(" ".join(self.td).split())
            if v and self.tr is not None:
                self.tr.append(v)
            self.td = None
        elif tag == "tr" and self.tr is not None:
            if self.tr:
                self.rows.append(self.tr)
            self.tr = None
            self.td = None


def parse_html(raw, roc_year, keyword):
    content = None
    for enc in ("utf-8", "cp950"):
        try:
            content = raw.decode(enc)
            break
        except UnicodeDecodeError:
            pass
    if content is None:
        raise ValueError("unreadable_mops_html")
    if any(x in content for x in ("系統忙碌", "Access Denied",
                                  "Captcha", "驗證碼", "error/error.html")):
        return "BLOCKED_OR_ERROR_PAGE", []
    if "<table" not in content.lower():
        return "NO_DOCUMENT_TABLE_NOT_COVERED", []
    parser = TableReader()
    parser.feed(content)
    records = []
    for row in parser.rows:
        ticker = next((x for x in row if re.fullmatch(r"[0-9]{4}", x)), "")
        if not ticker:
            continue
        excerpt = " | ".join(row)[:1000]
        if keyword not in excerpt and not re.search("重編|更正|更補正", excerpt):
            continue
        name = ""
        for i, val in enumerate(row):
            if val == ticker and i + 1 < len(row):
                name = row[i + 1][:60]
                break
        records.append({
            "query_roc_year": str(roc_year), "query_keyword": keyword,
            "ticker": ticker, "company": name, "title_candidate": excerpt[:300],
            "row_excerpt": excerpt, "request_source_url": API_URL,
            "report_fiscal_year_verified": "false",
            "original_notice_verified": "false",
            "issuer_year_y": "",
            "status": "UNVERIFIED_SUBJECT_QUERY_CANDIDATE",
        })
    # Zero matched rows does NOT imply historical negative event coverage.
    return "HTML_TABLE_QUERY_RESULT_UNVERIFIED", records


def post_once(roc_year, keyword, timeout=15):
    if roc_year not in YEARS or keyword not in KEYWORDS:
        raise ValueError("out_of_scope_query")
    values = {
        "encodeURIComponent": "1", "step": "1", "firstin": "true",
        "id": "", "key": "", "TYPEK": "", "Stp": "4",
        "go": "false", "co_id": "", "r1": "1", "KIND": "C",
        "CODE": "", "keyWord": keyword, "Condition2": "1", "keyWord2": "",
        "year": str(roc_year), "month1": "0", "begin_day": "1",
        "end_day": "31", "Orderby": "1",
    }
    req = Request(API_URL, data=urlencode(values).encode("utf-8"),
                  headers={"Content-Type": "application/x-www-form-urlencoded",
                           "User-Agent": "FinTrust-Research/1.0 public-archive"},
                  method="POST")
    with urlopen(req, timeout=timeout) as response:
        blob = response.read(2_000_001)
        if len(blob) > 2_000_000:
            raise ValueError("oversize_mops_keyword_response")
        return blob


def run(out, *, delay=2.0):
    out = Path(out)
    findings, results = [], []
    for iy, year in enumerate(YEARS):
        for ik, keyword in enumerate(KEYWORDS):
            try:
                raw = post_once(year, keyword)
                state, parsed = parse_html(raw, year, keyword)
                name = f"mops_keyword_{year}_{ik}.html"
                immutable_write(out / "raw" / name, raw)
                findings.extend(parsed)
                results.append({"year_roc": year, "keyword": keyword,
                                "status": state, "raw_sha256": sha(raw),
                                "raw_bytes": len(raw),
                                "unverified_issuer_rows": len(parsed)})
            except (OSError, ValueError, TimeoutError) as exc:
                results.append({"year_roc": year, "keyword": keyword,
                                "status": "FETCH_FAILED",
                                "error_class": type(exc).__name__,
                                "error_summary": str(exc)[:170],
                                "unverified_issuer_rows": 0})
            # No high-frequency requests; no retry loops or captcha bypass.
            if (iy, ik) != (len(YEARS)-1, len(KEYWORDS)-1):
                time.sleep(delay)
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(findings)
    lead_blob = output.getvalue().encode("utf-8")
    immutable_write(out / "round2_mops_keyword_candidates.csv", lead_blob)
    report = {
        "schema": "fintrust_round2_mops_keyword_probe_v1",
        "as_of": AS_OF, "source": API_URL,
        "status": "BOUNDED_SUBJECT_SEARCH_ONLY_NOT_COMPLETE_OUTCOME_HISTORY",
        "requests": results,
        "query_count": len(results),
        "unverified_candidate_rows": len(findings),
        "new_approved_binary_y": 0,
        "negative_annual_windows_covered": 0,
        "output_sha256": sha(lead_blob),
        "notes": "Query subject may miss descriptions, pagination and older formats. No original notice or FY mapping is certified. 0 rows NEVER means 0 events.",
    }
    immutable_write(out / "round2_mops_keyword_report.json",
                    (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
                     + "\n").encode())
    return report


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    print(json.dumps(run(args.out), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
