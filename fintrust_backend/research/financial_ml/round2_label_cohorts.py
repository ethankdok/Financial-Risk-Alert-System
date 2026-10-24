"""Round 2: two mutually non-interchangeable financial ML outcome tracks.

This module creates a *research proxy* for whether the TEJ Information
Transparency monthly-derived calendar-year restatement count was nonzero.
It does NOT create official affected-annual-report restatement labels; these
remain NULL until MOPS original-first-publication and amendment evidence
is independently reviewed. No licensed issuer-year rows go to GitHub.

From fintrust_backend:
python -m research.financial_ml.round2_label_cohorts \
 --tej-year-csv data/financial_ml/round2_tej_transparency/tej_calendar_year_evidence_private.csv \
 --out data/financial_ml/round2_label_cohorts_20261025

Primary exploratory eligibility: all 12 months present, 4-digit numeric IDs,
2016-2023, exclude reserved 1785 and 2014 methodological anomaly.
Features for year t must exist at 31 Dec t-1. FY(t-1) ANNUAL filing is generally
not public at that cutoff; limit annual X to original vintages FY <= t-2.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

REQUIRED = {
    "ticker","calendar_year","observed_months","observed_month_count",
    "max_reported_restatement_count","last_observed_count",
}
HOLDOUT = {"1785"}
START_YEAR, END_YEAR = 2016, 2023
TRAIN = range(2016, 2021)
VALID = range(2021, 2023)
TEST = {2023}
OUTPUT_FIELDS = (
    "ticker","calendar_year","case_key","split",
    "y_tej_calendar_proxy","y_official_annual_24m","label_provenance",
    "observed_month_count","observed_months","tej_positive_count_max",
    "tej_last_observed_count","source_calendar_definition",
    "feature_asof_date","max_safe_annual_financial_fy",
    "source_sha256","point_in_time_features_verified","training_features_ready",
)
EXCLUDED_FIELDS = ("ticker","calendar_year","reason","calendar_nonzero_cue",
                   "observed_month_count")


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _immutable(path, blob):
    path = Path(path)
    if path.exists() and path.read_bytes() != blob:
        raise FileExistsError("round2_cohort_refuse_overwrite:" + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(blob)


def _csv_blob(fields, rows):
    f=io.StringIO(newline="")
    w=csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return f.getvalue().encode("utf-8-sig")


def _strict_months(raw):
    parts = str(raw or "").split(";")
    if parts != [f"{m:02d}" for m in range(1,13)]:
        return False
    return True


def _count(value):
    s = str(value or "").strip()
    if not re.fullmatch(r"\d+(?:\.0+)?", s):
        raise ValueError("restatement_count_not_unsigned_integer")
    n = int(float(s))
    if n < 0 or n > 500:
        raise ValueError("restatement_count_out_of_range")
    return n


def build(yearly_csv, out):
    source = Path(yearly_csv)
    blob = source.read_bytes()
    txt = None
    for encoding in ("utf-8-sig","cp950"):
        try:
            txt = blob.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if txt is None:
        raise ValueError("tej_yearly_csv_unreadable")
    reader=csv.DictReader(io.StringIO(txt))
    if not reader.fieldnames or not REQUIRED.issubset(reader.fieldnames):
        raise ValueError("tej_yearly_required_fields_missing")
    source_hash=_hash(blob)
    eligible=[]
    excluded=[]
    seen=set()
    baseline_2014 = Counter()
    year_tab=Counter()
    for r in reader:
        ticker=(r.get("ticker") or "").strip()
        year=int(r["calendar_year"])
        n=_count(r["max_reported_restatement_count"])
        k=(ticker,year)
        if k in seen:
            raise ValueError("duplicate_ticker_calendar_year")
        seen.add(k)
        nonzero=str(n>0).lower()
        count_observed=int(r["observed_month_count"])
        if year==2014 and re.fullmatch(r"\d{4}",ticker) and _strict_months(r["observed_months"]):
            baseline_2014["company_years"]+=1
            baseline_2014["positive_cues"]+=int(n>0)
        if year not in range(2013,2024):
            reason="OUTSIDE_RESEARCH_YEARS"
        elif not re.fullmatch(r"\d{4}",ticker):
            reason="NOT_FOUR_DIGIT_EQUITY_RESEARCH_ID"
        elif ticker in HOLDOUT:
            reason="RESERVED_HOLDOUT"
        elif count_observed!=12 or not _strict_months(r["observed_months"]):
            reason="INCOMPLETE_MONTH_OBSERVATION"
        elif year < START_YEAR:
            reason="PRE_2016_OR_2014_SENSITIVITY_ONLY"
        else:
            reason=""
        if reason:
            excluded.append({"ticker":ticker,"calendar_year":year,
                             "reason":reason,"calendar_nonzero_cue":nonzero,
                             "observed_month_count":count_observed})
            continue
        split="train" if year in TRAIN else "validation" if year in VALID else "test"
        eligible.append({
            "ticker":ticker, "calendar_year":year,
            "case_key":f"{ticker}-CY{year}", "split":split,
            "y_tej_calendar_proxy":int(n>0),
            "y_official_annual_24m":"",
            "label_provenance":"TEJ_INFORMATION_TRANSPARENCY_PROXY_NOT_TT2",
            "observed_month_count":count_observed,"observed_months":r["observed_months"],
            "tej_positive_count_max":n,
            "tej_last_observed_count":_count(r["last_observed_count"]),
            "source_calendar_definition":"COMPANY_CALENDAR_YEAR_NOT_AFFECTED_FINANCIAL_FY",
            "feature_asof_date":f"{year-1}-12-31",
            "max_safe_annual_financial_fy":year-2,
            "source_sha256":source_hash,
            "point_in_time_features_verified":"false",
            "training_features_ready":"false",
        })
        year_tab[(year,split,int(n>0))]+=1
    eligible.sort(key=lambda r:(r["calendar_year"],r["ticker"]))
    excluded.sort(key=lambda r:(r["reason"],r["calendar_year"],r["ticker"]))
    splits=Counter(x["split"] for x in eligible)
    positives=Counter(x["split"] for x in eligible if x["y_tej_calendar_proxy"]==1)
    summary={
        "schema":"fintrust_proxy_and_official_outcomes_separate_v1",
        "source_tej_calendar_year_sha256":source_hash,
        "source_row_count":len(seen),
        "included_company_years":len(eligible),
        "included_proxy_positive":sum(x["y_tej_calendar_proxy"] for x in eligible),
        "included_proxy_negative":sum(x["y_tej_calendar_proxy"]==0 for x in eligible),
        "split_counts":{part:{"company_years":splits[part],
                               "proxy_positive":positives[part],
                               "proxy_negative":splits[part]-positives[part]}
                        for part in ("train","validation","test")},
        "excluded_reasons":dict(sorted(Counter(x["reason"] for x in excluded).items())),
        "year_2014_reference_only":dict(baseline_2014),
        "training_X_joined":False,
        "official_y_24m_confirmed_positive":0,
        "official_y_24m_confirmed_negative":0,
        "proxy_target_definition":"TEJ monthly information-transparency 'annual restatement count' nonzero in the SAME CALENDAR YEAR. NOT affected FY, 24m outcome, fraud or financial core-delta.",
        "feature_policy":"For proxy CY=t, use only first-vintage financial inputs actually public by Dec31(t-1); annual FY <= t-2 unless filing timestamps prove otherwise; never use TEJ count/CPA/monthly restatement/outcome revised later as X.",
        "sample_selection_warning":"No proof TEJ transparency covers all official restatement filings; zeros are proxy non-event only. Full 12 months is observational completeness, not MOPS event coverage.",
        "year_2014_anomaly":"2014 excluded from primary cohort and reserved for sensitivity analysis; TEJ issuer count spikes and even 2330 shows positive count without matching FinLab keyword event.",
        "holdout":"1785 never in eligible proxy cohort; reserve for independent external case analysis.",
        "silver_vs_gold":"FinLab review cases stay unlabeled. Existing silver labels not automatically merged. Official 24m ledger must pass MOPS evidence gate separately.",
    }
    target=Path(out)
    cohorts=_csv_blob(OUTPUT_FIELDS,eligible)
    rejects=_csv_blob(EXCLUDED_FIELDS,excluded)
    summary["output_sha256"]={"tej_calendar_proxy_cohort_private.csv":_hash(cohorts),
                               "tej_calendar_proxy_excluded_private.csv":_hash(rejects)}
    _immutable(target/"tej_calendar_proxy_cohort_private.csv",cohorts)
    _immutable(target/"tej_calendar_proxy_excluded_private.csv",rejects)
    _immutable(target/"tej_proxy_outcome_report.json",
               (json.dumps(summary,indent=2,ensure_ascii=False,sort_keys=True)+"\n").encode("utf-8"))
    return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tej-year-csv",required=True)
    p.add_argument("--out",required=True)
    a=p.parse_args()
    print(json.dumps(build(a.tej_year_csv,a.out),ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
