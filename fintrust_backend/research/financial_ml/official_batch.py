"""Bounded official annual-XBRL research acquisition, isolated from live FinTrust.

Run from fintrust_backend. Dry run by default, 2013-2015 only, <=12 company-years.
Every filing is a CANDIDATE, not a verified historical-original/normal sample.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import os
from pathlib import Path

MAX_REQUESTS = 12
FIELDS = ["ticker", "fiscal_year", "period", "metric_code", "value", "unit",
          "statement_scope", "filing_version_id", "filing_version_type",
          "quality_status", "validation_status", "point_in_time_eligible",
          "effective_available_at", "source_kind", "accounting_framework",
          "source_url", "retrieved_at", "content_hash", "taxonomy_concept"]


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def load_candidates(path):
    required = {"ticker", "fiscal_year", "historical_listing_status",
                "historical_industry_status", "normal_label_status"}
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not required.issubset(reader.fieldnames or []):
            raise ValueError("Unsupported historical candidate CSV schema")
        result = {}
        for row in reader:
            ticker = row["ticker"].strip()
            year = int(row["fiscal_year"])
            if not ticker.isdigit() or not 4 <= len(ticker) <= 6:
                raise ValueError("Invalid ticker")
            key = ticker, year
            if key in result:
                raise ValueError(f"Duplicate company-year: {key}")
            result[key] = row
    return result


def request_plan(candidates, tickers, years):
    from app.services.historical_audit.sources import mops_annual_url
    if not tickers or not years:
        raise ValueError("Explicit --ticker and --year required")
    if len(tickers) != len(set(tickers)) or len(years) != len(set(years)):
        raise ValueError("Duplicate flags")
    if "1785" in tickers:
        raise ValueError("1785 is held out of normal candidate acquisition")
    if any(y not in (2013, 2014, 2015) for y in years):
        raise ValueError("2011-2012 need a separate original-report/PDF workflow")
    if len(tickers) * len(years) > MAX_REQUESTS:
        raise ValueError("Hard request cap: 12 company-years per execution")
    items = []
    for ticker in tickers:
        for year in years:
            row = candidates.get((ticker, year))
            if row is None:
                raise ValueError(f"Not in candidate inventory: {ticker}/{year}")
            items.append({
                "ticker": ticker, "fiscal_year": year, "source_url": mops_annual_url(ticker, year),
                "historical_listing_status": row["historical_listing_status"],
                "historical_industry_status": row["historical_industry_status"],
                "normal_label_status": "UNREVIEWED", "training_admitted": False})
    return items


def parse_candidate(content, ticker, year):
    from app.services.historical_audit.xbrl_document import parse_xbrl_document
    from app.services.historical_audit.normalization import normalize_annual_filing
    from app.services.historical_audit.backfill import classify_version
    from app.services.historical_audit.models import decimal_text
    doc = parse_xbrl_document(content)
    scope, proof = doc.statement_scope()
    revision, evidence, version_warnings = classify_version(doc, year)
    tifrs = any("tifrs" in str(ref).lower() for ref in doc.schema_refs)
    result = {"statement_scope": scope, "scope_evidence": proof,
              "filing_version_type": revision, "revision_evidence": evidence,
              "accounting_framework": "TIFRS" if tifrs else "UNVERIFIED",
              "warnings": version_warnings, "facts": []}
    if scope != "consolidated" or not tifrs:
        result.update(status="quarantined", reason="scope_or_framework_not_verified")
        return result
    normalized = normalize_annual_filing(doc, ticker=ticker, fiscal_year=year)
    result["validation_status"] = normalized.validation_status
    result["warnings"] += normalized.warnings
    result["fields_found"] = len(normalized.fields_found)
    if normalized.validation_status not in ("validated", "validated_with_warnings"):
        result.update(status="quarantined", reason=normalized.quarantine_reason)
        return result
    result["status"] = "validated"
    result["facts"] = [{
        "metric_code": f.metric_code, "value": decimal_text(f.value),
        "unit": f.unit, "quality_status": f.quality_status,
        "taxonomy_concept": f.taxonomy_concept} for f in normalized.facts]
    return result


def export_facts(outcomes, target):
    with Path(target).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for item in sorted(outcomes.values(), key=lambda x: (x["ticker"], x["fiscal_year"])):
            if item.get("status") != "validated":
                continue
            for fact in item["facts"]:
                writer.writerow({
                    "ticker": item["ticker"], "fiscal_year": item["fiscal_year"],
                    "period": f'{item["fiscal_year"]}FY',
                    "metric_code": fact["metric_code"], "value": fact["value"],
                    "unit": fact["unit"], "statement_scope": item["statement_scope"],
                    "filing_version_id": item["filing_version_id"],
                    "filing_version_type": item["filing_version_type"],
                    "quality_status": fact["quality_status"],
                    "validation_status": item["validation_status"],
                    "point_in_time_eligible": "false", "effective_available_at": "",
                    "source_kind": item["source_kind"],
                    "accounting_framework": item["accounting_framework"],
                    "source_url": item["source_url"], "retrieved_at": item["retrieved_at"],
                    "content_hash": item["content_hash"],
                    "taxonomy_concept": fact["taxonomy_concept"]})


async def acquire(plan, output_dir, execute=False, fetcher=None, processor=None):
    """Only --execute performs network I/O. Source/production DBs are never opened."""
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    atomic_json(folder / "request_plan.json", {"requests": plan, "execute": execute,
                "warning": "Candidate only; no historical listing, original-version or normal label verified."})
    if not execute:
        return {"mode": "dry_run", "requests_planned": len(plan),
                "network_requests": 0, "database_writes": 0,
                "normal_labels_created": 0}
    if len(plan) > MAX_REQUESTS:
        raise ValueError("Batch request cap exceeded")
    from app.services.historical_audit.archive import RawEvidenceArchive
    from app.services.historical_audit.models import filing_version_id
    from app.services.historical_audit.sources import OfficialSourceFetcher, ensure_official_url
    from app.services.historical_audit.xbrl_document import detect_format
    archive = RawEvidenceArchive(folder / "raw")
    fetcher = fetcher or OfficialSourceFetcher(min_interval_seconds=2.0, max_attempts=2)
    processor = processor or parse_candidate
    manifest = folder / "acquisition_results.json"
    outcomes = json.loads(manifest.read_text(encoding="utf-8")).get("outcomes", {}) if manifest.exists() else {}
    count = 0
    for item in plan:
        ticker, year = item["ticker"], int(item["fiscal_year"])
        if ticker == "1785":
            raise ValueError("Reserved case forbidden")
        key = f"{ticker}:{year}"
        previous = outcomes.get(key, {})
        if previous.get("status") == "validated" and previous.get("archive_path"):
            try:
                raw = archive.read(previous["archive_path"])
                if hashlib.sha256(raw).hexdigest() == previous.get("content_hash"):
                    continue
            except (OSError, ValueError, RuntimeError):
                pass
        ensure_official_url(item["source_url"])
        fetched = await fetcher.fetch(item["source_url"], expect=("xbrl_instance", "inline_xbrl", "zip"))
        count += 1
        state = {"ticker": ticker, "fiscal_year": year,
                 "source_url": item["source_url"],
                 "historical_listing_status": item["historical_listing_status"],
                 "normal_label_status": "UNREVIEWED", "training_admitted": False,
                 "source_status": fetched.status, "status": "source_unavailable"}
        if fetched.status == "ok" and fetched.content:
            format_name = detect_format(fetched.content)
            stored = archive.store(ticker=ticker, period=f"{year}FY",
                                   content=fetched.content, detected_format=format_name,
                                   retrieval=fetched.metadata())
            state.update(content_hash=stored.content_hash, archive_path=stored.relative_path,
                         retrieved_at=fetched.retrieved_at.isoformat() if fetched.retrieved_at else "",
                         source_kind={"zip": "mops_xbrl_zip", "inline_xbrl": "mops_inline_xbrl",
                                      "xbrl_instance": "mops_xbrl_instance"}.get(format_name, "unknown"))
            try:
                state.update(processor(fetched.content, ticker, year))
                state["filing_version_id"] = filing_version_id(
                    ticker, f"{year}FY", state.get("statement_scope", "unknown"), stored.content_hash)
            except Exception as exc:
                state.update(status="parse_failed", error_kind=type(exc).__name__)
        outcomes[key] = state
        atomic_json(manifest, {"outcomes": outcomes, "note": "No ex-ante/PIT or normal labels."})
    export_facts(outcomes, folder / "candidate_facts.csv")
    stats = {}
    for value in outcomes.values():
        stats[value["status"]] = stats.get(value["status"], 0) + 1
    summary = {"mode": "execute", "network_requests": count,
               "outcome_counts": stats, "database_writes": 0,
               "normal_labels_created": 0, "retrospective_only": True,
               "output_dir": str(folder)}
    atomic_json(folder / "acquisition_summary.json", summary)
    return summary


def main(argv=None):
    p = argparse.ArgumentParser(description="Bounded official annual XBRL research acquisition")
    p.add_argument("--candidate-csv", default="data/financial_ml/historical_candidate_coverage/historical_candidate_gap_plan.csv")
    p.add_argument("--ticker", action="append", required=True)
    p.add_argument("--year", action="append", type=int, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--output-dir", default="data/financial_ml/official_batch")
    args = p.parse_args(argv)
    plan = request_plan(load_candidates(args.candidate_csv), args.ticker, args.year)
    print(json.dumps(asyncio.run(acquire(plan, args.output_dir, execute=args.execute)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
