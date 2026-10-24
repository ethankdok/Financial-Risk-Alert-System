"""Round 1: reproducible Taiwanese financial-disclosure event registry.

Reads only the existing, provenance-bearing lead JSONs plus a small vetted
supplement. DOES NOT assign supervised Y labels, certify original filings,
download MOPS, or claim a complete all-market event census.

Run from fintrust_backend:
python -m research.financial_ml.round1_event_registry --out data/financial_ml/round1_events
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

HOME = Path(__file__).resolve().parent
SCHEMA_VERSION = "fintrust_round1_events_v1"
SOURCES = {
    "round10": "round10_user_cohort_20261020_disclosure_leads.json",
    "round9": "round9_official_case_source_leads.json",
    "outside120": "FY1315_EXTERNAL_OFFICIAL_RESTATEMENT_LEADS_NOT_IN_COHORT.json",
    "supplement": "round1_current_event_supplement_20261024.json",
}
ANNUAL_TARGET_FAMILIES = {
    "ANNUAL_CORE_CORRECTION", "ANNUAL_FINANCIAL_CORRECTION_LEAD",
    "ANNUAL_RESTATEMENT_LEAD", "ANNUAL_JUDICIAL_MISSTATEMENT_LEAD",
    "RESTATEMENT_ORDER_OR_EXTENSION",
}
COLUMNS = (
    "event_id", "ticker", "company_name", "notice_date", "event_family",
    "evidence_tier", "period_scope", "annual_years", "quarter_periods",
    "source_url", "supplementary_url", "origin_record_ids", "source_notes",
    "official_original_bytes_verified", "first_filing_verified",
    "reserved_holdout", "annual_target_candidate", "training_label",
    "training_admitted", "review_status",
)
PERIOD_COLUMNS = (
    "event_id", "ticker", "fiscal_year", "period", "granularity",
    "event_family", "annual_target_candidate", "reserved_holdout",
    "source_url", "training_admitted",
)


def digest(obj):
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def secure_url(value):
    raw = str(value or "").strip()
    x = urlsplit(raw)
    if x.scheme != "https" or not x.hostname or x.username or x.password:
        raise ValueError("invalid_https_evidence_url")
    return urlunsplit((x.scheme, x.netloc.lower(), x.path.rstrip("/") or "/",
                       x.query, ""))


def clean_years(value):
    years = sorted({int(y) for y in value})
    if any(y < 2011 or y > 2026 for y in years):
        raise ValueError("year_outside_supported_archive")
    return years


def clean_quarters(value):
    quarters = sorted(set(value))
    for period in quarters:
        if (not isinstance(period, str) or len(period) != 6
                or not period[:4].isdigit() or period[4:] not in
                ("Q1", "Q2", "Q3", "Q4")):
            raise ValueError("bad_fiscal_quarter")
    return quarters


def record(ticker, company, notice, family, tier, years, quarters, url, *,
           source_id, note, supplementary="", holdout=False, scope=""):
    ticker = str(ticker).strip()
    if not (len(ticker) == 4 and ticker.isascii() and ticker.isdigit()):
        raise ValueError("invalid_ticker")
    if notice:
        date.fromisoformat(notice)
    if family not in ALL_FAMILIES:
        raise ValueError("unknown_event_family")
    if not str(company).strip() or not str(source_id).strip():
        raise ValueError("missing_company_or_origin")
    years = clean_years(years)
    quarters = clean_quarters(quarters)
    if not years and not quarters:
        raise ValueError("period_evidence_missing")
    return {
        "ticker": ticker, "company_name": str(company).strip(),
        "notice_date": notice, "event_family": family, "evidence_tier": tier,
        "period_scope": scope or ("ANNUAL_AND_QUARTER" if years and quarters else
                                  "ANNUAL" if years else "QUARTER"),
        "annual_years": years, "quarter_periods": quarters,
        "source_url": secure_url(url),
        "supplementary_url": secure_url(supplementary) if supplementary else "",
        "origin_record_ids": [source_id],
        "source_notes": [str(note).strip()],
        "official_original_bytes_verified": False,
        "first_filing_verified": False,
        "reserved_holdout": bool(holdout),
        "annual_target_candidate": family in ANNUAL_TARGET_FAMILIES,
        "training_label": "", "training_admitted": False,
        "review_status": "OFFICIAL_WEB_NOTICE_REFERENCE_REVIEWED" if (
            family == "ANNUAL_RESTATEMENT_LEAD" and ticker == "1785") else
            "SOURCE_LEAD_NEEDS_PERIOD_AND_DOCUMENT_AUDIT",
    }


ROUND10_TYPES = {
    "MAIN_STATEMENT_CORRECTION": "ANNUAL_CORE_CORRECTION",
    "BALANCE_CASHFLOW_AND_NOTES_CORRECTION": "ANNUAL_FINANCIAL_CORRECTION_LEAD",
    "QUARTER_RESTATEMENT_AND_OTHERS_CORRECTION": "QUARTER_MIXED_CORRECTION",
    "RELATED_PARTY_FILING_NOTE_CORRECTION": "NON_TARGET_NOTICE",
    "INVESTMENT_DISCLOSURE_NOTE_CORRECTION": "NON_TARGET_NOTICE",
    "PRIOR_PERIOD_NOTE_CORRECTION": "NON_TARGET_NOTICE",
    "IXBRL_TAG_CORRECTION": "NON_TARGET_NOTICE",
    "MONTHLY_REVENUE_CORRECTION_NOT_FINANCIAL_STATEMENT": "NON_TARGET_NOTICE",
    "REVENUE_ANNOUNCEMENT_NOT_NET_PROFIT_CORRECTION": "NON_TARGET_NOTICE",
    "AFFILIATE_BUSINESS_REPORT_NON_TARGET": "NON_TARGET_NOTICE",
    "BOARD_RESULTS_DISCLOSURE_NOT_RESTATEMENT": "NON_TARGET_NOTICE",
    "BOARD_MEETING_DATE_NON_TARGET": "NON_TARGET_NOTICE",
}
ALL_FAMILIES = set(ROUND10_TYPES.values()) | {
    "ANNUAL_RESTATEMENT_LEAD", "ANNUAL_JUDICIAL_MISSTATEMENT_LEAD",
    "QUARTER_JUDICIAL_OR_LITIGATION_LEAD", "RESTATEMENT_ORDER_OR_EXTENSION",
    "INVESTIGATION_ALLEGATION",
}


def load_sources(source_dir=HOME):
    source_dir = Path(source_dir)
    raw = {}
    hashes = {}
    for name, filename in SOURCES.items():
        file = source_dir / filename
        blob = file.read_bytes()
        raw[name] = json.loads(blob.decode("utf-8-sig"))
        hashes[filename] = hashlib.sha256(blob).hexdigest()
    if raw["round10"].get("schema") != "FINTRUST_ROUND10_EVENT_SCREENING_V1":
        raise ValueError("round10_schema_mismatch")
    if raw["round9"].get("schema_version") != "fintrust_manual_outcome_source_leads_v1":
        raise ValueError("round9_schema_mismatch")
    if raw["outside120"].get("schema") != "FINTRUST_FY2013_15_OUTCOME_RESEARCH_SOURCE_LEADS_V1":
        raise ValueError("outside120_schema_mismatch")
    if raw["supplement"].get("schema_version") != "fintrust_round1_supplement_v1":
        raise ValueError("round1_supplement_schema_mismatch")
    return raw, hashes


def prepare_events(raw):
    candidates = []
    for e in raw["round10"]["events"]:
        family = ROUND10_TYPES[e["event_class"]]
        candidates.append(record(
            e["ticker"], e["company"], e["notice_date"], family,
            "COMPANY_NOTICE_REPRINT", e["candidate_fiscal_years"],
            e["candidate_quarters"], e["document_url"],
            source_id="round10:" + e["event_id"],
            note=e["finding"], scope="QUARTER_ONLY_EVENT_EVIDENCE" if
            family == "QUARTER_MIXED_CORRECTION" else "",
        ))
    for e in raw["round9"]["cases"]:
        ticker = e["ticker"]
        if ticker == "1785":
            family = "ANNUAL_RESTATEMENT_LEAD"
            tier = "TPEX_PRIMARY_WEB"
            years = e["affected_fiscal_years"]
            notice = "2016-12-29"  # Date on the identified TPEx notice.
        elif ticker == "3027":
            family = "ANNUAL_JUDICIAL_MISSTATEMENT_LEAD"
            tier = "COURT_PRIMARY_WEB"
            years = e["proposed_positive_case_years"]
            notice = "2025-04-30"
        elif ticker == "8299":
            family = "QUARTER_JUDICIAL_OR_LITIGATION_LEAD"
            tier = "COURT_PRIMARY_WEB"
            years = e["proposed_positive_case_years"]
            notice = "2024-05-03"
        elif ticker == "6452":
            family = "QUARTER_JUDICIAL_OR_LITIGATION_LEAD"
            tier = "INVESTOR_PROTECTION_CENTER_WEB"
            years = e["proposed_positive_case_years"]
            notice = ""
        else:
            raise ValueError("unknown_round9_case")
        candidates.append(record(
            ticker, e["company_name"], notice, family, tier, years, [],
            e["primary_url"], source_id="round9:" + ticker,
            note=e["reviewed_issue"], holdout=(ticker == "1785"),
            supplementary=e.get("secondary_primary_url", ""),
            scope="QUARTER_SPECIFIC_FY_CONTEXT" if family ==
            "QUARTER_JUDICIAL_OR_LITIGATION_LEAD" else "",
        ))
    for e in raw["outside120"]["noncohort_not_admitted"]:
        ticker = e["ticker"]
        family = ("ANNUAL_RESTATEMENT_LEAD" if ticker == "2305" else
                  "RESTATEMENT_ORDER_OR_EXTENSION")
        candidates.append(record(
            ticker, e["company"], e["disclosure_date"], family,
            "COMPANY_NOTICE_REPRINT", [e["fiscal_year"]], [],
            e["source_url"],
            source_id=f"outside120:{ticker}:{e['fiscal_year']}",
            note=e["research_event"],
        ))
    for e in raw["supplement"]["events"]:
        candidates.append(record(
            e["ticker"], e["company"], e["notice_date"],
            e.get("event_family", "INVESTIGATION_ALLEGATION"),
            e.get("evidence_tier", "MEDIA_REPORT_WITH_ISSUER_RESPONSE"),
            e["candidate_fiscal_years"], e.get("candidate_quarters", []),
            e["source_url"], source_id="supplement:" + e["id"],
            note=e["description"],
            supplementary=e.get("issuer_statement_url", ""),
        ))
    # One notice can mention multiple years. Merge same issuer, notice,
    # source URL and category WITHOUT discarding the referenced fiscal years.
    combined = {}
    for e in candidates:
        key = (e["ticker"], e["notice_date"], e["event_family"], e["source_url"])
        if key not in combined:
            combined[key] = e
        else:
            old = combined[key]
            for field in ("annual_years", "quarter_periods", "origin_record_ids",
                          "source_notes"):
                old[field] = sorted(set(old[field]) | set(e[field]))
            if old["reserved_holdout"] != e["reserved_holdout"]:
                raise ValueError("conflicting_case_holdout")
    out = []
    for key, e in sorted(combined.items()):
        e["event_id"] = "E" + hashlib.sha256(
            "|".join(key).encode("utf-8")).hexdigest()[:14]
        out.append(e)
    if len({e["event_id"] for e in out}) != len(out):
        raise ValueError("event_id_collision")
    return out, len(candidates)


def csv_rows(events):
    notices, periods = [], []
    for event in events:
        e = dict(event)
        e["annual_years"] = ";".join(map(str, e["annual_years"]))
        e["quarter_periods"] = ";".join(e["quarter_periods"])
        e["origin_record_ids"] = ";".join(e["origin_record_ids"])
        e["source_notes"] = " | ".join(e["source_notes"])
        for flag in ("official_original_bytes_verified", "first_filing_verified",
                     "reserved_holdout", "annual_target_candidate",
                     "training_admitted"):
            e[flag] = str(e[flag]).lower()
        notices.append({k: e[k] for k in COLUMNS})
        for y in event["annual_years"]:
            periods.append({
                "event_id": event["event_id"], "ticker": event["ticker"],
                "fiscal_year": y, "period": f"{y}FY",
                "granularity": "annual_candidate_context",
                "event_family": event["event_family"],
                "annual_target_candidate": str(event["annual_target_candidate"]).lower(),
                "reserved_holdout": str(event["reserved_holdout"]).lower(),
                "source_url": event["source_url"], "training_admitted": "false",
            })
        for q in event["quarter_periods"]:
            periods.append({
                "event_id": event["event_id"], "ticker": event["ticker"],
                "fiscal_year": int(q[:4]), "period": q,
                "granularity": "quarterly_candidate_context",
                "event_family": event["event_family"],
                "annual_target_candidate": "false",
                "reserved_holdout": str(event["reserved_holdout"]).lower(),
                "source_url": event["source_url"], "training_admitted": "false",
            })
    periods.sort(key=lambda x: (x["ticker"], x["period"], x["event_id"]))
    return notices, periods


def csv_bytes(fields, rows):
    from io import StringIO
    fp = StringIO(newline="")
    writer = csv.DictWriter(fp, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return fp.getvalue().encode("utf-8")


def write_immutable(path, blob):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != blob:
            raise FileExistsError(f"round1_refuses_overwrite:{path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)


def build(output, *, source_dir=HOME):
    raw, sha = load_sources(source_dir)
    events, raw_count = prepare_events(raw)
    notices, periods = csv_rows(events)
    notice_bytes = csv_bytes(COLUMNS, notices)
    period_bytes = csv_bytes(PERIOD_COLUMNS, periods)
    status_counts = Counter(e["event_family"] for e in events)
    result = {
        "schema_version": SCHEMA_VERSION, "as_of": "2026-10-24",
        "status": "ROUND1_EVENT_LEADS_REGISTRY_BUILT_NOT_FULL_MARKET_CENSUS",
        "input_record_count": raw_count, "unique_notices": len(events),
        "unique_issuers": len({e["ticker"] for e in events}),
        "event_year_or_quarter_links": len(periods),
        "annual_links": sum(p["granularity"] == "annual_candidate_context"
                            for p in periods),
        "quarter_links": sum(p["granularity"] == "quarterly_candidate_context"
                             for p in periods),
        "annual_target_screening_links": sum(
            p["annual_target_candidate"] == "true" for p in periods),
        "family_counts": dict(sorted(status_counts.items())),
        "heldout_tickers": ["1785"],
        "source_file_sha256": sha,
        "output_sha256": {
            "round1_event_registry.csv": hashlib.sha256(notice_bytes).hexdigest(),
            "round1_event_period_links.csv": hashlib.sha256(period_bytes).hexdigest(),
        },
        "official_original_document_bytes_certified": 0,
        "official_full_market_census_completed": False,
        "positive_training_labels_issued": 0,
        "negative_training_labels_issued": 0,
        "no_production_data_mutation": True,
        "note": ("This is an evidence-linked event candidate index. "
                 "A notice is not automatically annual financial misstatement; "
                 "Round2 must use original source/version and a fixed observation "
                 "horizon to assign actual binary outcomes."),
    }
    out = Path(output)
    write_immutable(out / "round1_event_registry.csv", notice_bytes)
    write_immutable(out / "round1_event_period_links.csv", period_bytes)
    report = (json.dumps(result, ensure_ascii=False, sort_keys=True,
                         indent=2) + "\n").encode("utf-8")
    write_immutable(out / "round1_event_registry_report.json", report)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="New isolated research folder")
    parser.add_argument("--source-dir", default=str(HOME))
    args = parser.parse_args(argv)
    print(json.dumps(build(args.out, source_dir=args.source_dir),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
