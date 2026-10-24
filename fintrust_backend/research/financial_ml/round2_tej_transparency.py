"""FinTrust Round2: TEJ Information Transparency XLSX calendar-year evidence.

Reads user's LOCAL licensed TEJ Pro Excel export using streaming stdlib XML.
"當年度財報重編次數" is a company/calendar-year observation; it is NOT
the affected annual fiscal year, TT2 event data, a 24-month target, or fraud.
Never train on this indicator as a 0/1 target. Never upload raw/derived rows
to a public repository. Cross-reference locally with FinLab review cases only.

python -m research.financial_ml.round2_tej_transparency \
 --tej-xlsx data/financial_ml/20261025034613DataExport.xlsx \
 --finlab-cases-csv data/financial_ml/round2_finlab_evidence/finlab_issuer_fy_review_private.csv \
 --out data/financial_ml/round2_tej_transparency
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
EXPECTED = {"代號", "名稱", "年月", "當年度財報重編次數"}
YEAR_COLUMNS = ("ticker", "issuer_name", "calendar_year", "observed_months",
    "observed_month_count", "max_reported_restatement_count",
    "earliest_positive_month", "latest_positive_month", "distinct_observed_counts",
    "last_observed_month", "last_observed_count", "max_reported_cpa_3y",
    "tej_calendar_year_positive_cue", "training_y")
MONTH_COLUMNS = ("ticker", "issuer_name", "year_month", "calendar_year",
                 "reported_restatement_count", "reported_cpa_3y")
JOIN_COLUMNS = ("tej_notice_calendar_year", "tej_notice_year_observed",
    "tej_notice_year_max_count", "tej_notice_year_first_positive_month",
    "tej_fy_calendar_year_observed", "tej_fy_calendar_year_max_count",
    "tej_indicator_interpretation", "tej_match_review_status", "training_y_tej")


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _immutable(path, blob):
    path = Path(path)
    if path.exists() and path.read_bytes() != blob:
        raise FileExistsError("immutable_existing_output:" + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(blob)


def _csv_blob(headers, records):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    return out.getvalue().encode("utf-8-sig")


def _cell(c, shared):
    if c.attrib.get("t") == "inlineStr":
        node = c.find(NS + "is")
        return "".join(node.itertext()) if node is not None else ""
    v = c.find(NS + "v")
    if v is None:
        return ""
    if c.attrib.get("t") == "s":
        return shared[int(v.text)]
    return v.text or ""


def iterate_tej_rows(xlsx):
    """Stream Excel XML: avoids loading the 170MB+ expanded TEJ sheet."""
    with ZipFile(xlsx) as z:
        sheets = [i for i in z.infolist()
                  if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", i.filename)]
        if len(sheets) != 1:
            raise ValueError("tej_expected_one_sheet")
        if sheets[0].file_size > 300_000_000:
            raise ValueError("tej_sheet_exceeds_size_limit")
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            si = z.getinfo("xl/sharedStrings.xml")
            if si.file_size > 10_000_000:
                raise ValueError("tej_shared_strings_exceed_size_limit")
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(n.itertext()) for n in root.findall(NS + "si")]
        with z.open(sheets[0]) as f:
            stream = ET.iterparse(f, events=("start", "end"))
            _, root = next(stream)
            column_names = None
            nrows = 0
            for event, row in stream:
                if event != "end" or row.tag != NS + "row":
                    continue
                cells = {}
                for c in row.findall(NS + "c"):
                    m = re.match(r"[A-Z]+", c.attrib.get("r", ""))
                    if m:
                        cells[m.group()] = _cell(c, shared).strip()
                if column_names is None:
                    column_names = cells
                    if len(set(cells.values())) != len(cells):
                        raise ValueError("tej_duplicate_headers")
                    if not EXPECTED.issubset(set(cells.values())):
                        raise ValueError("tej_information_transparency_columns_missing")
                else:
                    nrows += 1
                    if nrows > 750_000:
                        raise ValueError("tej_row_limit")
                    yield {label: cells.get(col, "") for col, label in
                           column_names.items()}
                row.clear()
                root.clear()
            if column_names is None:
                raise ValueError("tej_empty_sheet")


def import_tej(xlsx):
    annual = {}
    nonzero = []
    years = defaultdict(lambda: {"rows": 0, "tickers": set(),
                                 "positive_rows": 0, "positive_tickers": set()})
    seen = set()
    invalid = Counter()
    nrows = 0
    tickers = set()
    for r in iterate_tej_rows(xlsx):
        nrows += 1
        ticker = r.get("代號", "").strip()
        name = r.get("名稱", "").strip()
        try:
            if not re.fullmatch(r"[A-Z0-9]{4,6}", ticker):
                raise ValueError("ticker")
            m = re.fullmatch(r"(20\d{2})[/\-](0?[1-9]|1[012])", r["年月"])
            if not m:
                raise ValueError("year_month")
            yy, mm = int(m.group(1)), int(m.group(2))
            count_raw = r["當年度財報重編次數"]
            if not re.fullmatch(r"\d+(?:\.0+)?", count_raw):
                raise ValueError("restatement_count")
            val = int(float(count_raw))
            if val > 500:
                raise ValueError("implausible_count")
        except (ValueError, KeyError):
            invalid["invalid_row"] += 1
            continue
        key = (ticker, yy, mm)
        if key in seen:
            raise ValueError("duplicate_tej_company_year_month")
        seen.add(key)
        tickers.add(ticker)
        yr = years[yy]
        yr["rows"] += 1
        yr["tickers"].add(ticker)
        try:
            cpa = int(float(r.get("3年內CPA異動次數", "")))
        except ValueError:
            cpa = None
        x = annual.setdefault((ticker, yy), {"name": name,
            "months": set(), "values": set(), "max": 0, "positive": [],
            "last_month": 0, "last_value": None, "max_cpa": None})
        x["months"].add(mm)
        x["values"].add(val)
        x["max"] = max(x["max"], val)
        if cpa is not None:
            x["max_cpa"] = max(x["max_cpa"] or 0, cpa)
        if mm > x["last_month"]:
            x["last_month"] = mm
            x["last_value"] = val
        if val > 0:
            x["positive"].append(mm)
            yr["positive_rows"] += 1
            yr["positive_tickers"].add(ticker)
            nonzero.append({"ticker": ticker, "issuer_name": name,
                "year_month": f"{yy:04d}/{mm:02d}", "calendar_year": yy,
                "reported_restatement_count": val,
                "reported_cpa_3y": cpa if cpa is not None else ""})
    annual_rows = []
    for (ticker, yy), x in sorted(annual.items()):
        p = sorted(x["positive"])
        annual_rows.append({"ticker": ticker, "issuer_name": x["name"],
            "calendar_year": yy, "observed_months": ";".join(
                f"{m:02d}" for m in sorted(x["months"])),
            "observed_month_count": len(x["months"]),
            "max_reported_restatement_count": x["max"],
            "earliest_positive_month": f"{yy}/{p[0]:02d}" if p else "",
            "latest_positive_month": f"{yy}/{p[-1]:02d}" if p else "",
            "distinct_observed_counts": ";".join(
                map(str, sorted(x["values"]))),
            "last_observed_month": f"{yy}/{x['last_month']:02d}",
            "last_observed_count": x["last_value"],
            "max_reported_cpa_3y": x["max_cpa"] if x["max_cpa"] is not None else "",
            "tej_calendar_year_positive_cue": str(bool(p)).lower(),
            "training_y": ""})
    nonzero.sort(key=lambda r: (r["ticker"], r["year_month"]))
    report = {"input_monthly_rows": nrows, "distinct_tickers": len(tickers),
        "distinct_company_calendar_years": len(annual_rows),
        "positive_month_rows": len(nonzero),
        "nonzero_company_calendar_years_2013_2023": sum(
            2013 <= x["calendar_year"] <= 2023 and
            x["max_reported_restatement_count"] > 0 for x in annual_rows),
        "year_stats": {str(y): {
            "rows": v["rows"], "companies": len(v["tickers"]),
            "nonzero_months": v["positive_rows"],
            "companies_with_nonzero": len(v["positive_tickers"])}
            for y, v in sorted(years.items())},
        "excluded": dict(invalid), "y_positive_assigned": 0,
        "y_negative_assigned": 0}
    return annual_rows, nonzero, report


def join_finlab(annual_rows, csv_path):
    bykey = {(r["ticker"], int(r["calendar_year"])): r for r in annual_rows}
    with Path(csv_path).open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        if not {"ticker", "fiscal_year", "first_notice_date", "training_y",
                "rank", "holdout"}.issubset(headers):
            raise ValueError("finlab_review_columns_missing")
        cases = list(reader)
    metrics = Counter()
    priorities = defaultdict(Counter)
    out = []
    for c in cases:
        if str(c.get("training_y") or "").strip():
            raise ValueError("refuse_join_preapproved_training_y")
        notice_year_match = re.match(r"20\d{2}", c["first_notice_date"])
        if not notice_year_match:
            raise ValueError("finlab_announcement_date_missing")
        year = int(notice_year_match.group())
        fy = int(c["fiscal_year"])
        a = bykey.get((c["ticker"], year))
        b = bykey.get((c["ticker"], fy))
        v = dict(c)
        v.update({"tej_notice_calendar_year": year,
            "tej_notice_year_observed": str(a is not None).lower(),
            "tej_notice_year_max_count":
                a["max_reported_restatement_count"] if a else "",
            "tej_notice_year_first_positive_month":
                a["earliest_positive_month"] if a else "",
            "tej_fy_calendar_year_observed": str(b is not None).lower(),
            "tej_fy_calendar_year_max_count":
                b["max_reported_restatement_count"] if b else "",
            "tej_indicator_interpretation":
                "CALENDAR_YEAR_CUE_NOT_AFFECTED_FINANCIAL_FY",
            "tej_match_review_status":
                "VERIFY_MOPS_EVENT_DATE_AND_AFFECTED_FY"
                if a and a["max_reported_restatement_count"] > 0 else
                "NO_TEJ_POSITIVE_CUE_NOT_A_NEGATIVE",
            "training_y_tej": ""})
        out.append(v)
        metrics["cases"] += 1
        if a:
            metrics["notice_calendar_year_observed"] += 1
            if a["max_reported_restatement_count"] > 0:
                metrics["notice_calendar_year_positive_cue"] += 1
                if 2013 <= year <= 2023:
                    metrics["notice_calendar_year_positive_cue_2013_2023"] += 1
                priorities[c["rank"]]["positive_cue"] += 1
        if b:
            metrics["fiscal_calendar_year_observed_not_affected_fy"] += 1
            if b["max_reported_restatement_count"] > 0:
                metrics["fy_calendar_year_positive_cue_not_y"] += 1
    return out, headers + list(JOIN_COLUMNS), {
        "metrics": dict(metrics),
        "priority_counts": {k: dict(v) for k, v in priorities.items()}}


def build(tej_xlsx, out, finlab_cases_csv=None):
    data = Path(tej_xlsx)
    annual, months, report = import_tej(data)
    report.update({"schema": "round2_tej_information_transparency_v1",
        "source_sha256": _hash(data.read_bytes()),
        "target_source": "TEJ Information Transparency",
        "semantic_caveat": "Monthly company/calendar-year count; not affected fiscal year, TT2 event, 24m label or fraud",
        "coverage_caveat": "2014 unusual count; 2026 partial/zero does not imply negative",
        "license": "Licensed raw/derived individual company rows remain private",
        "training_0_or_1_issued": 0})
    files = {"tej_calendar_year_evidence_private.csv":
                _csv_blob(YEAR_COLUMNS, annual),
             "tej_nonzero_months_private.csv":
                _csv_blob(MONTH_COLUMNS, months)}
    if finlab_cases_csv:
        joined, headers, join_report = join_finlab(annual, finlab_cases_csv)
        report["finlab_join"] = join_report
        report["finlab_source_sha256"] = _hash(Path(finlab_cases_csv).read_bytes())
        files["finlab_tej_join_review_private.csv"] = _csv_blob(headers, joined)
    report["outputs_sha256"] = {name: _hash(blob) for name, blob in files.items()}
    files["tej_finlab_evidence_summary.json"] = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) +
        "\n").encode("utf-8")
    for name, blob in files.items():
        _immutable(Path(out) / name, blob)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tej-xlsx", required=True)
    p.add_argument("--finlab-cases-csv")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    r = build(args.tej_xlsx, args.out, args.finlab_cases_csv)
    print(json.dumps({k: v for k, v in r.items() if k != "year_stats"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
