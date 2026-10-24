"""Scale Round2 issuer-year sampling with live official TWSE/TPEx *current* rosters.

Two official HTTPS data endpoints; immutable SHA-backed raw snapshots.
Avoids inventing historical listed status or numeric 0 labels from membership.
The current roster is NOT an archived 2013-2023 census, and the panel
below contains candidates, not training observations.

Run from fintrust_backend:
python -m research.financial_ml.round2_marketwide_universe --out data/financial_ml/round2_marketwide
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from .round2_binary_labels import build as build_round2

TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O"
TPEX_CSV_FALLBACK = "https://mopsfin.twse.com.tw/opendata/t187ap03_O.csv"
SOURCE_URLS = {"TWSE": TWSE_URL, "TPEX": TPEX_URL}
YEARS = tuple(range(2013, 2024))
ROOT = Path(__file__).resolve().parent
ROSTER = ROOT / "round10_user_confirmed_120_tickers.txt"
ADDITIONAL = ROOT / "round2_reviewed_binary_evidence_20261024.json"
COMPANY_COLUMNS = ("ticker", "name", "industry", "market", "listing_date",
                   "current_asof_source", "source_status", "historical_market_membership_verified")
PANEL_COLUMNS = ("ticker", "fiscal_year", "name", "market", "industry",
                 "universe_membership", "historical_listing_verified",
                 "financial_x_verified", "y", "y_evidence_grade", "y_source_url",
                 "y_target", "binary_research_eligible", "required_next_evidence")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_csv(cols, rows):
    s = io.StringIO(newline="")
    w = csv.DictWriter(s, fieldnames=cols, extrasaction="raise", lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return s.getvalue().encode("utf-8")


def immutable_write(path, content):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != content:
            raise FileExistsError("round2_marketwide_conflicting_snapshot:" + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def fetch_official(url, *, timeout=25):
    if url not in {TWSE_URL, TPEX_URL, TPEX_CSV_FALLBACK}:
        raise ValueError("unapproved_official_roster_source")
    req = Request(url, headers={"User-Agent": "FinTrust-Research/1.0 academic-public-data",
                                "Accept": "application/json,text/csv"})
    with urlopen(req, timeout=timeout) as response:
        payload = response.read(5_000_001)
        if len(payload) > 5_000_000:
            raise ValueError("oversize_official_roster_response")
        if response.status != 200 or len(payload) < 100:
            raise ValueError("invalid_official_roster_response")
        return payload


def parse_official(blob, market, *, csv_input=False):
    if csv_input:
        text = None
        for enc in ("utf-8-sig", "cp950"):
            try:
                text = blob.decode(enc)
                break
            except UnicodeError:
                continue
        if text is None:
            raise ValueError("unreadable_official_roster_csv")
        obj = list(csv.DictReader(io.StringIO(text)))
    else:
        obj = json.loads(blob.decode("utf-8-sig"))
    if not isinstance(obj, list):
        raise ValueError("official_roster_not_an_array")
    result = {}
    for row in obj:
        ticker = str(row.get("公司代號", row.get("SecuritiesCompanyCode", ""))).strip()
        if len(ticker) != 4 or not ticker.isascii() or not ticker.isdecimal():
            continue
        name = str(row.get("公司簡稱", row.get("CompanyAbbreviation",
                   row.get("公司名稱", row.get("CompanyName", ""))))).strip()
        if not name:
            raise ValueError("official_company_name_missing:" + ticker)
        if ticker in result:
            raise ValueError("duplicate_official_roster_ticker:" + ticker)
        result[ticker] = {
            "ticker": ticker, "name": name,
            "industry": str(row.get("產業別", row.get("SecuritiesIndustryCode", ""))).strip(),
            "market": market,
            "listing_date": str(row.get("上市日期" if market == "TWSE" else "上櫃日期",
                                         row.get("DateOfListing", ""))).strip(),
            "current_asof_source": SOURCE_URLS[market] if not csv_input else TPEX_CSV_FALLBACK,
            "source_status": "CURRENT_ONLY_OFFICIAL_ROSTER",
            "historical_market_membership_verified": "false",
        }
    if len(result) < 10:
        raise ValueError("official_roster_too_small_for_market")
    return result


def load_seed():
    tickers = [p.strip() for p in ROSTER.read_text(encoding="utf-8-sig").splitlines() if p.strip()]
    if len(tickers) != 120 or len(set(tickers)) != 120:
        raise ValueError("frozen_120_seed_invalid")
    evidence = json.loads(ADDITIONAL.read_text(encoding="utf-8"))
    cases = {str(x["ticker"]): x["company"] for kind in ("positives", "negatives")
             for x in evidence[kind]}
    return sorted(set(tickers) | set(cases)), cases


def construct_panel(rosters, labels, *, include_seed=True):
    by_company = {}
    duplicate_market = []
    for market in ("TWSE", "TPEX"):
        for ticker, entry in rosters.get(market, {}).items():
            if ticker in by_company:
                duplicate_market.append(ticker)
                continue
            by_company[ticker] = entry
    if duplicate_market:
        raise ValueError("ticker_listed_in_two_markets:" + ",".join(duplicate_market))
    seed, names = load_seed() if include_seed else ([], {})
    # Previously selected 120 firms and explicit reviewed cases remain present
    # even if absent from *today's* official roster (e.g. delisted issuers).
    for ticker in seed:
        if ticker not in by_company:
            by_company[ticker] = {
                "ticker": ticker, "name": names.get(ticker, ""),
                "industry": "", "market": "HISTORICAL_RESEARCH_CANDIDATE",
                "listing_date": "", "current_asof_source": "",
                "source_status": "SEED_NOT_CURRENT_OFFICIAL_ROSTER",
                "historical_market_membership_verified": "false",
            }
    labels_by = {}
    for r in labels:
        pair = (r["ticker"], int(r["fiscal_year"]))
        if pair in labels_by or r["y"] not in {"0", "1"}:
            raise ValueError("invalid_previous_round2_label")
        labels_by[pair] = r
        if r["ticker"] not in by_company:
            raise ValueError("round2_label_issuer_missing_from_seed")
    if not by_company:
        raise ValueError("empty_company_roster")
    panel = []
    for ticker, entry in sorted(by_company.items()):
        for fy in YEARS:
            y = labels_by.get((ticker, fy))
            panel.append({
                "ticker": ticker, "fiscal_year": str(fy),
                "name": entry["name"], "market": entry["market"],
                "industry": entry["industry"],
                "universe_membership": entry["source_status"],
                "historical_listing_verified": "false",
                "financial_x_verified": "false",
                "y": y["y"] if y else "",
                "y_evidence_grade": y["evidence_grade"] if y else "",
                "y_source_url": y["source_url"] if y else "",
                "y_target": y["target"] if y else "",
                "binary_research_eligible": "false",
                "required_next_evidence": "VALID_FINANCIAL_X;HISTORIC_FILING_ASOF;FULL_OUTCOME_COVERAGE",
            })
    if any(x["ticker"] == "1785" and x["y"] for x in panel):
        raise ValueError("reserved_holdout_in_training_labels")
    return sorted(by_company.values(), key=lambda x: x["ticker"]), panel


def run(out, *, offline_paths=None):
    out = Path(out)
    raw_dir = out / "source_snapshots"
    prior = build_round2(out / "round2_labeled_input")
    source_status = {}
    roster = {}
    raw_sha = {}
    for market in ("TWSE", "TPEX"):
        candidates = [SOURCE_URLS[market]]
        if market == "TPEX":
            candidates.append(TPEX_CSV_FALLBACK)
        errors = []
        for url in candidates:
            try:
                if offline_paths and market in offline_paths:
                    blob = Path(offline_paths[market]).read_bytes()
                    is_csv = str(offline_paths[market]).endswith(".csv")
                else:
                    blob = fetch_official(url)
                    is_csv = url.endswith(".csv")
                parsed = parse_official(blob, market, csv_input=is_csv)
                immutable_write(raw_dir / (market.lower() + ("_official.csv" if is_csv else "_official.json")),
                                blob)
                roster[market] = parsed
                raw_sha[market] = sha(blob)
                source_status[market] = {"status": "FETCHED", "count": len(parsed),
                                         "url": url, "sha256": sha(blob)}
                break
            except (OSError, ValueError, json.JSONDecodeError, UnicodeError) as exc:
                errors.append(str(exc)[:150])
        else:
            source_status[market] = {"status": "UNAVAILABLE", "attempts": len(candidates),
                                     "errors": errors, "count": 0}
    labels = list(csv.DictReader((out / "round2_labeled_input" /
                                  "round2_binary_research_labels.csv").open(
                                      encoding="utf-8", newline="")))
    companies, panel = construct_panel(roster, labels)
    company_blob = make_csv(COMPANY_COLUMNS, companies)
    panel_blob = make_csv(PANEL_COLUMNS, panel)
    immutable_write(out / "round2_market_company_roster.csv", company_blob)
    immutable_write(out / "round2_market_issuer_year_candidates.csv", panel_blob)
    counts = Counter(x["y"] for x in panel)
    report = {
        "schema": "fintrust_round2_marketwide_v1",
        "as_of": "2026-10-24",
        "status": "CURRENT_OFFICIAL_COMPANY_ROSTER_WITH_UNLABELED_HISTORICAL_YEAR_GRID",
        "sources": source_status,
        "current_official_issuer_count": len(set().union(*(set(v) for v in roster.values()))),
        "issuer_rows_total_including_historical_seeds": len(companies),
        "candidate_issuer_year_positions": len(panel),
        "actual_binary_y_1": counts["1"],
        "actual_binary_y_0": counts["0"],
        "not_yet_labeled": counts[""],
        "model_eligible_x_y_pairs": 0,
        "historical_listing_verification_complete": False,
        "comprehensive_historical_mops_event_coverage_complete": False,
        "every_unknown_is_negative": False,
        "positive_and_negative_not_inferred_from_roster": True,
        "round2_silver_source_sha256": prior["source_evidence_sha256"],
        "raw_official_roster_sha256": raw_sha,
        "output_sha256": {"round2_market_company_roster.csv": sha(company_blob),
                          "round2_market_issuer_year_candidates.csv": sha(panel_blob)},
        "research_warning": (
            "Large issuer-year grid is NOT a machine-learning training set. "
            "Today-listed issuer lists omit delisted firms; 2013-2023 membership not proven. "
            "Official event history and complete negative coverage not supplied."
        ),
    }
    immutable_write(out / "round2_marketwide_report.json",
                    (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
                     + "\n").encode("utf-8"))
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--twse-file", default="")
    p.add_argument("--tpex-file", default="")
    a = p.parse_args(argv)
    offline = {}
    if a.twse_file:
        offline["TWSE"] = a.twse_file
    if a.tpex_file:
        offline["TPEX"] = a.tpex_file
    print(json.dumps(run(a.out, offline_paths=offline or None), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
