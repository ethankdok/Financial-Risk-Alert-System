"""Offline MOPS XBRL -> Beneish (8) and Dechow Model 1 (7) literature features.

Reuses source-verified published formula engines and Taiwan input/panel mappings.
This is retrospective research, not a labeled-normal cohort or fraud prediction.
No network, production DB writes, model fitting, or 1785 inclusion.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

BENEISH = ("DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA")
DECHOW = ("rsst_acc", "ch_rec", "ch_inv", "soft_assets", "ch_cs", "ch_roa", "issue")
FEATURES = tuple("b_" + name for name in BENEISH) + tuple("d_" + name for name in DECHOW)
META = ("ticker", "fiscal_year", "analysis_mode", "source_kind",
        "filing_version_id", "filing_version_type", "accounting_framework",
        "statement_scope", "raw_sha256", "beneish_status", "dechow_status",
        "beneish_m_score", "dechow_f_score", "components_computed",
        "components_required", "training_label")


def checked_manifest(path):
    outcomes = json.loads(Path(path).read_text(encoding="utf-8")).get("outcomes")
    if not isinstance(outcomes, dict):
        raise ValueError("Expected acquisition_results.json with outcomes map")
    valid, ignored = [], Counter()
    for key, item in sorted(outcomes.items()):
        if not isinstance(item, dict):
            ignored["invalid_manifest_row"] += 1
            continue
        try:
            ticker, year = str(item["ticker"]), int(item["fiscal_year"])
        except (ValueError, TypeError, KeyError):
            ignored["invalid_identity"] += 1
            continue
        if key != f"{ticker}:{year}":
            ignored["manifest_identity_mismatch"] += 1
        elif ticker == "1785":
            ignored["reserved_case_excluded"] += 1
        elif item.get("status") != "validated":
            ignored["not_validated"] += 1
        elif item.get("statement_scope") != "consolidated" or item.get("accounting_framework") != "TIFRS":
            ignored["scope_or_framework_unverified"] += 1
        elif item.get("source_kind") not in {"mops_xbrl_instance", "mops_inline_xbrl", "mops_xbrl_zip"}:
            ignored["not_official_xbrl"] += 1
        elif not all(item.get(k) for k in ("filing_version_id", "content_hash", "archive_path")):
            ignored["incomplete_provenance"] += 1
        else:
            valid.append(item)
    return valid, ignored


def archive_bytes(folder, item):
    from app.services.historical_audit.archive import RawEvidenceArchive
    ticker, year = str(item["ticker"]), int(item["fiscal_year"])
    path = Path(item["archive_path"])
    if path.parts[:2] != (ticker, f"{year}FY"):
        raise ValueError("archive_path_ticker_year_mismatch")
    content = RawEvidenceArchive(Path(folder) / "raw").read(item["archive_path"])
    if hashlib.sha256(content).hexdigest() != item["content_hash"]:
        raise ValueError("archive_hash_does_not_match_manifest")
    return content


def model_features(item, beneish_result, dechow_result):
    out = {
        "ticker": str(item["ticker"]), "fiscal_year": int(item["fiscal_year"]),
        "analysis_mode": "retrospective", "source_kind": item["source_kind"],
        "filing_version_id": item["filing_version_id"],
        "filing_version_type": item["filing_version_type"],
        "accounting_framework": "TIFRS", "statement_scope": "consolidated",
        "raw_sha256": item["content_hash"],
        "beneish_status": beneish_result["status"],
        "dechow_status": dechow_result["status"],
        "beneish_m_score": beneish_result.get("score") or "",
        "dechow_f_score": dechow_result.get("score") or "",
        "components_required": 15, "training_label": "UNREVIEWED"
    }
    missing = []
    for prefix, names, result in (("b_", BENEISH, beneish_result), ("d_", DECHOW, dechow_result)):
        by_name = {c["variable"]: c for c in result["components"]}
        for name in names:
            component = by_name.get(name)
            if component is None:
                raise ValueError(f"method_missing_component:{prefix}{name}")
            computed = component.get("status") == "computed" and component.get("value_exact") is not None
            out[prefix + name] = component["value_exact"] if computed else ""
            if not computed:
                missing.append({
                    "variable": prefix + name, "status": component.get("status"),
                    "reasons": component.get("reasons", [])
                })
    out["components_computed"] = sum(bool(out[name]) for name in FEATURES)
    return out, missing


def produce(acquisition_results, output, *, min_year=2013, max_year=2025):
    if min_year < 2013 or min_year > max_year:
        raise ValueError("TIFRS year interval must begin from 2013")
    from app.services.financial_research import beneish_1999, dechow_2011
    from app.services.financial_research.literature_extraction import extract_xbrl
    from app.services.financial_research.literature_inputs import FilingLines, Panel

    records, ignored = checked_manifest(acquisition_results)
    archive_root = Path(acquisition_results).parent
    by_company = defaultdict(dict)
    diagnostics = []
    for item in records:
        ticker, year = str(item["ticker"]), int(item["fiscal_year"])
        if not min_year - 1 <= year <= max_year:
            continue
        try:
            raw = archive_bytes(archive_root, item)
            filing = {
                "ticker": ticker, "fiscal_year": year,
                "filing_version_id": item["filing_version_id"],
                "filing_version_type": item["filing_version_type"],
                "statement_scope": "consolidated",
                "source_kind": item["source_kind"], "content_hash": item["content_hash"],
                "accounting_framework": "TIFRS", "available_at": None,
                "availability_status": "unverified",
                "source_url": item.get("source_url")
            }
            observations = extract_xbrl(raw, filing)
            if not observations:
                raise ValueError("no_usable_xbrl_statement_lines")
            by_company[ticker][year] = (item, filing, FilingLines(observations))
        except (ValueError, RuntimeError, OSError, KeyError) as error:
            ignored["extraction_error"] += 1
            diagnostics.append({"ticker": ticker, "fiscal_year": year, "stage": "extract",
                                "reason": type(error).__name__, "detail": str(error)[:240]})
    result_rows = []
    for ticker, years in sorted(by_company.items()):
        filings = {year: filing for year, (_, filing, _) in years.items()}
        lines = {filing["filing_version_id"]: obs for _, filing, obs in years.values()}
        frameworks = {year: "TIFRS" for year in years}
        frameworks[2012] = "TW_GAAP"  # FY2013 IFRS transition opening balance where supported
        for year in sorted(years):
            if not min_year <= year <= max_year:
                continue
            item = years[year][0]
            try:
                bpanel = Panel(year, "TIFRS", filings, lines, {}, frameworks)
                dpanel = Panel(year, "TIFRS", filings, lines, {}, frameworks)
                beneish = beneish_1999.evaluate(bpanel)
                dechow = dechow_2011.evaluate(dpanel)
                row, missing = model_features(item, beneish, dechow)
            except (ValueError, KeyError, ArithmeticError) as error:
                ignored["evaluation_error"] += 1
                diagnostics.append({"ticker": ticker, "fiscal_year": year, "stage": "evaluate",
                                    "reason": type(error).__name__, "detail": str(error)[:240]})
                continue
            result_rows.append(row)
            if missing:
                diagnostics.append({"ticker": ticker, "fiscal_year": year,
                                    "stage": "missing_components", "details": missing})

    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    feature_file = out / "literature_15_features.csv"
    with feature_file.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(META) + list(FEATURES))
        writer.writeheader()
        writer.writerows(result_rows)
    reason_file = out / "literature_missing_reasons.jsonl"
    with reason_file.open("w", encoding="utf-8") as file:
        for detail in diagnostics:
            file.write(json.dumps(detail, ensure_ascii=False, default=str) + "\n")
    coverage = {name: sum(bool(row[name]) for row in result_rows) for name in FEATURES}
    report = {
        "status": "RETROSPECTIVE_LITERATURE_FEATURE_EXTRACTION_ONLY",
        "years_requested": [min_year, max_year],
        "candidate_manifest_records": len(records),
        "company_year_rows": len(result_rows),
        "companies": len({row["ticker"] for row in result_rows}),
        "fully_computed_15_rows": sum(row["components_computed"] == 15 for row in result_rows),
        "full_beneish8_rows": sum(row["beneish_status"] == "computed" for row in result_rows),
        "full_dechow7_rows": sum(row["dechow_status"] == "computed" for row in result_rows),
        "variable_computed_count": coverage,
        "variable_missing_count": {name: len(result_rows) - n for name, n in coverage.items()},
        "excluded_or_failed_counts": dict(sorted(ignored.items())),
        "normal_labels_created": 0,
        "reserved_case_used": False,
        "original_and_asof_verified": False,
        "source": "local_sha256_verified_MOPS_XBRL",
        "method_implementations": ["beneish_1999", "dechow_2011",
                                   "literature_inputs", "literature_extraction"],
        "warnings": [
            "Missing variables and issue evidence remain unavailable; never filled with zero.",
            "Archived source may reflect revised values; scores are retrospective, not ex-ante.",
            "Taiwan COMPUSTAT-item mapping remains pending method-owner review.",
            "Neither a normal reference cohort nor a trained ML model is created here."
        ],
        "outputs": [str(feature_file), str(reason_file)]
    }
    (out / "literature_coverage.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline archived-XBRL Beneish8 + Dechow7 features")
    parser.add_argument("--acquisition-results", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--min-year", type=int, default=2013)
    parser.add_argument("--max-year", type=int, default=2025)
    args = parser.parse_args(argv)
    print(json.dumps(produce(args.acquisition_results, args.output,
                             min_year=args.min_year, max_year=args.max_year),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
