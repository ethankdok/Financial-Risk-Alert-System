"""TEJ TT2 research export -> auditable company-year outcome labels.

TT2 is a positive restatement EVENT source, not a list of confirmed fraud.
A valid negative requires an independent annual-filing universe plus an
explicit, dated TEJ-coverage manifest.  All exported outcomes remain
SOURCE_CONDITIONAL (NOT independently audited gold labels).

No TEJ credentials, raw licensed export, or real extracted TT2 rows belong
in Git.  CLI reads user's permitted UTF-8/CP950 CSV export locally.
Use --preflight alone when no licensed data file is available.

From fintrust_backend:
python -m research.financial_ml.round2_tej_tt2 --preflight --out data/financial_ml/round2_tej
python -m research.financial_ml.round2_tej_tt2 --tt2-csv <LOCAL_TT2.csv> --universe-csv <LOCAL_TEJ_ANNUAL.csv> --coverage-json <LOCAL_COVERAGE.json> --out <PRIVATE_FOLDER>
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AS_OF = date(2026, 10, 24)
YEARS = range(2013, 2024)
TT2_EVENT_TARGET = "TEJ_RESTATEMENT_EVENT_WITHIN_24M"
CORE_TARGET = "TEJ_CORE_FINANCIAL_AMOUNT_ADJUSTMENT_WITHIN_24M"
# Chinese fields documented in TEJ's audit/restatement-summary module.
# These are canonicalization candidates, NOT a claim of one fixed TT2 layout.
TT2_ALIASES = {
    "company": ("公司", "公司代碼", "證券代碼", "股票代碼", "ticker"),
    "period": ("年/月", "年月", "財報年月", "財報期別", "period"),
    "event_date": ("重編事件日", "事件日", "event_date"),
    "scope": ("財報類別", "財報類別（1個別2個體3合併）", "合併個體", "scope"),
    "reason": ("重編原因", "原因", "reason"),
    "basis": ("依據", "重編依據", "basis"),
    "event_count": ("重編次數", "event_count"),
    "delta_revenue": ("營業收入_調整金額", "營業收入調整金額", "營收調整金額", "delta_revenue"),
    "delta_operating": ("營業利益_調整金額", "營業利益調整金額", "delta_operating"),
    "delta_net_income": ("稅後淨利_調整金額", "稅後淨利調整金額", "delta_net_income"),
    "delta_assets": ("資產總額_調整金額", "資產總額調整金額", "delta_assets"),
    "delta_equity": ("股東權益_調整金額", "股東權益調整金額", "delta_equity"),
}
UNIVERSE_ALIASES = {
    "company": ("公司", "公司代碼", "證券代碼", "股票代碼", "ticker"),
    "period": ("年/月", "年月", "財報年月", "財報期別", "period"),
    "first_published_at": ("首次公告日", "首次財報公告日", "原始財報公布日", "first_published_at"),
    "scope": ("財報類別", "財報類別（1個別2個體3合併）", "合併個體", "scope"),
    "market": ("市場別", "market"),
    "industry": ("產業別", "industry"),
}
EVENT_COLUMNS = (
    "ticker", "fiscal_year", "event_date", "event_target", "core_change",
    "event_source_row", "event_reason", "event_basis", "scope", "source_sha256",
)
LABEL_COLUMNS = (
    "ticker", "fiscal_year", "first_published_at", "observation_end_at",
    "y_tej_restatement_24m", "y_core_adjustment_24m",
    "last_tt2_event_date", "matching_tt2_event_count",
    "label_grade", "target", "source_tt2_sha256", "source_universe_sha256",
    "source_coverage_sha256", "eligible_for_supervised_tej_target",
    "eligible_for_supervised_core_target", "warning",
)
EXCLUSION_COLUMNS = ("dataset", "source_row", "ticker", "fiscal_year", "reason")


def h(raw):
    return hashlib.sha256(raw).hexdigest()


def immutable(path, payload):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError("tej_round2_immutable_output_mismatch:" + str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def json_blob(o):
    return (json.dumps(o, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def csv_blob(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def load_csv(path):
    raw = Path(path).read_bytes()
    value = None
    for codec in ("utf-8-sig", "cp950"):
        try:
            value = raw.decode(codec)
            break
        except UnicodeDecodeError:
            pass
    if value is None:
        raise ValueError("tej_csv_encoding_unreadable")
    reader = csv.DictReader(io.StringIO(value))
    if not reader.fieldnames:
        raise ValueError("tej_csv_header_missing")
    names = [str(x).strip() for x in reader.fieldnames]
    if len(names) != len(set(names)):
        raise ValueError("tej_csv_duplicate_header")
    return raw, names, list(reader)


def column_map(headers, group, override=None):
    custom = (override or {}).get(group, {})
    if not isinstance(custom, dict):
        raise ValueError("tej_column_mapping_not_object")
    mapping = {}
    for canonical, options in (TT2_ALIASES if group == "tt2" else UNIVERSE_ALIASES).items():
        if canonical in custom:
            name = custom[canonical]
            if name not in headers:
                raise ValueError("tej_column_map_missing_header:" + canonical)
            mapping[canonical] = name
        else:
            match = [x for x in options if x in headers]
            if len(match) > 1:
                raise ValueError("tej_column_ambiguous:" + canonical)
            if match:
                mapping[canonical] = match[0]
    needed = ("company", "period", "event_date", "scope") if group == "tt2" else (
        "company", "period", "first_published_at", "scope")
    missing = set(needed) - mapping.keys()
    if missing:
        raise ValueError("tej_required_column_missing:" + ",".join(sorted(missing)))
    return mapping


def get(row, cols, key):
    return str(row.get(cols[key]) or "").strip() if key in cols else ""


def company_id(x):
    # TEJ UI often uses "1101 台泥", while API exports may use "1101".
    match = re.match(r"^\s*(\d{4})(?!\d)(?:[\s　\-].*)?$", x)
    if not match:
        raise ValueError("tej_bad_company_code")
    return match.group(1)


def period_year_month(x):
    s = re.sub(r"[^\d]", "", x)
    if len(s) == 6 and 1900 <= int(s[:4]) <= 2100:
        return int(s[:4]), int(s[4:])
    if len(s) == 5 and 90 <= int(s[:3]) <= 200:
        return int(s[:3]) + 1911, int(s[3:])
    if len(s) == 4 and 90 <= int(s[:3]) <= 200:
        return int(s[:3]) + 1911, int(s[-1:])
    raise ValueError("tej_bad_period_format")


def parse_date(x):
    s = x.strip().replace("/", "-").replace(".", "-")
    if not s:
        raise ValueError("tej_required_date_missing")
    if re.fullmatch(r"\d{8}", s):
        return date.fromisoformat(s[:4] + "-" + s[4:6] + "-" + s[6:])
    if re.fullmatch(r"\d{7}", s):  # ROC yyyMMdd
        return date(int(s[:3]) + 1911, int(s[3:5]), int(s[5:]))
    if re.fullmatch(r"\d{3,4}-\d{1,2}-\d{1,2}", s):
        y, m, d = map(int, s.split("-"))
        return date(y + 1911 if y < 1911 else y, m, d)
    return date.fromisoformat(s)


def plus24(d):
    y = d.year + 2
    day = 28 if (d.month, d.day) == (2, 29) else d.day
    return date(y, d.month, day)


def scope_ok(x):
    s = x.strip().upper()
    if s in ("3", "合併", "合併財報", "合併報表", "CONSOLIDATED"):
        return True
    if s in ("1", "2", "個別", "個體", "非合併", "STANDALONE", "INDIVIDUAL"):
        return False
    raise ValueError("tej_unknown_report_scope")


def nonzero_adjustment(row, cols):
    amounts = []
    for name in ("delta_revenue", "delta_operating", "delta_net_income",
                 "delta_assets", "delta_equity"):
        s = get(row, cols, name).replace(",", "").replace("，", "").strip()
        if not s or s.upper() in {"N/A", "NA", "-", "NAN"}:
            continue
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        try:
            amounts.append(Decimal(s))
        except InvalidOperation as exc:
            raise ValueError("tej_invalid_adjustment_number:" + name) from exc
    if any(x != 0 for x in amounts):
        return "1"
    # All five financial deltas must be present before declaring "no
    # core amount changed"; one available zero does not prove the rest.
    return "0" if len(amounts) == 5 else ""


def coverage_manifest(blob, tt2_sha, universe_sha):
    data = json.loads(blob.decode("utf-8-sig"))
    must = {
        "schema_version": "fintrust_tej_tt2_coverage_v1",
        "tt2_export_sha256": tt2_sha,
        "universe_export_sha256": universe_sha,
        "closed_event_census_for_exported_universe": True,
        "includes_historical_delisted_firms": True,
        "issuer_and_year_filters_match": True,
    }
    for key, expected in must.items():
        if data.get(key) != expected:
            raise ValueError("tej_coverage_unproven:" + key)
    end = parse_date(str(data.get("tt2_event_coverage_through", "")))
    if end > AS_OF:
        raise ValueError("tej_coverage_future_date")
    years = data.get("covered_fiscal_years")
    if not isinstance(years, list) or not all(type(x) is int and x in YEARS for x in years):
        raise ValueError("tej_coverage_years_invalid")
    if not years or len(years) != len(set(years)):
        raise ValueError("tej_coverage_no_years_or_duplicate")
    return end, set(years), data


def materialize(tt2_csv, universe_csv, coverage_json, out, *, mapping_json=None):
    tt2_raw, tt2_headers, tt2_rows = load_csv(tt2_csv)
    univ_raw, univ_headers, universe_rows = load_csv(universe_csv)
    tt2_sha, universe_sha = h(tt2_raw), h(univ_raw)
    config = json.loads(Path(mapping_json).read_text(encoding="utf-8")) if mapping_json else {}
    tmap = column_map(tt2_headers, "tt2", config)
    umap = column_map(univ_headers, "universe", config)
    coverage_raw = Path(coverage_json).read_bytes()
    coverage_through, covered_fy, coverage_meta = coverage_manifest(
        coverage_raw, tt2_sha, universe_sha)
    excludes, events, annual, unresolved_keys = [], [], {}, set()
    for i, r in enumerate(tt2_rows, 2):
        if not any((v or "").strip() for v in r.values()):
            continue
        try:
            ticker = company_id(get(r, tmap, "company"))
            fy, month = period_year_month(get(r, tmap, "period"))
            if ticker == "1785":
                raise ValueError("tej_reserved_final_holdout")
            if month != 12 or fy not in YEARS or fy not in covered_fy:
                raise ValueError("tej_outside_annual_scope")
            if not scope_ok(get(r, tmap, "scope")):
                raise ValueError("tej_not_consolidated")
            # Some TEJ summary variants include zero-count company-year
            # rows. Such rows MUST NOT become positive restatement events.
            count_str = get(r, tmap, "event_count")
            if count_str:
                try:
                    num = Decimal(count_str.replace(",", ""))
                except InvalidOperation as exc:
                    raise ValueError("tej_invalid_restatement_count") from exc
                if num < 0 or num != num.to_integral_value():
                    raise ValueError("tej_invalid_restatement_count")
                if num == 0 and not get(r, tmap, "event_date"):
                    continue  # explicit zero-event source row; no positive
                if num == 0:
                    raise ValueError("tej_zero_count_with_event_date")
            event_date = parse_date(get(r, tmap, "event_date"))
            if event_date > AS_OF:
                raise ValueError("tej_future_event_date")
            if event_date > coverage_through:
                raise ValueError("tej_event_after_declared_coverage_end")
            core = nonzero_adjustment(r, tmap)
            events.append({
                "ticker": ticker, "fiscal_year": str(fy),
                "event_date": event_date.isoformat(),
                "event_target": TT2_EVENT_TARGET, "core_change": core,
                "event_source_row": str(i),
                "event_reason": get(r, tmap, "reason"),
                "event_basis": get(r, tmap, "basis"),
                "scope": "consolidated", "source_sha256": tt2_sha,
            })
        except (ValueError, TypeError) as exc:
            # Malformed annual TT2 events can never become false "clean"
            # company-years merely because this import could not parse them.
            # Known non-consolidated events and out-of-scope dates are exempt.
            reason = str(exc)
            if reason not in ("tej_not_consolidated", "tej_outside_annual_scope",
                              "tej_reserved_final_holdout"):
                try:
                    maybe_ticker = company_id(get(r, tmap, "company"))
                    maybe_fy, _ = period_year_month(get(r, tmap, "period"))
                    if maybe_fy in covered_fy:
                        unresolved_keys.add((maybe_ticker, maybe_fy))
                except ValueError:
                    pass
            excludes.append({"dataset": "tt2", "source_row": str(i),
                             "ticker": str(r.get(tmap.get("company", ""), "")),
                             "fiscal_year": str(r.get(tmap.get("period", ""), "")),
                             "reason": str(exc)})
    dedup = {}
    for r in events:
        # Several source rows can refer to one event: do not count each
        # adjusted financial line as another independent positive.
        k = (r["ticker"], r["fiscal_year"], r["event_date"])
        if k not in dedup:
            dedup[k] = dict(r)
        else:
            old = dedup[k]
            if old["core_change"] == "" and r["core_change"] != "":
                old["core_change"] = r["core_change"]
            elif old["core_change"] == "0" and r["core_change"] == "1":
                old["core_change"] = "1"
            old["event_source_row"] += ";" + r["event_source_row"]
    events = sorted(dedup.values(), key=lambda r: (r["ticker"], r["fiscal_year"], r["event_date"]))
    keyed_events = defaultdict(list)
    for e in events:
        keyed_events[(e["ticker"], int(e["fiscal_year"]))].append(e)
    for i, r in enumerate(universe_rows, 2):
        if not any((v or "").strip() for v in r.values()):
            continue
        try:
            ticker = company_id(get(r, umap, "company"))
            fy, month = period_year_month(get(r, umap, "period"))
            if ticker == "1785":
                raise ValueError("tej_reserved_final_holdout")
            if month != 12 or fy not in covered_fy:
                raise ValueError("tej_universe_outside_annual_or_covered_year")
            if not scope_ok(get(r, umap, "scope")):
                raise ValueError("tej_universe_not_consolidated")
            first = parse_date(get(r, umap, "first_published_at"))
            if not fy < first.year <= fy + 2:
                raise ValueError("tej_first_publication_time_invalid")
            key = ticker, fy
            if key in annual:
                raise ValueError("tej_duplicate_universe_company_year")
            annual[key] = first
        except (ValueError, TypeError) as exc:
            excludes.append({"dataset": "universe", "source_row": str(i),
                             "ticker": str(r.get(umap.get("company", ""), "")),
                             "fiscal_year": str(r.get(umap.get("period", ""), "")),
                             "reason": str(exc)})
    labels = []
    for (ticker, fy), first in sorted(annual.items()):
        end = plus24(first)
        eligible = end <= coverage_through
        candidates = keyed_events.get((ticker, fy), [])
        unresolved = (ticker, fy) in unresolved_keys
        within = [e for e in candidates if first < parse_date(e["event_date"]) <= end]
        if any(parse_date(e["event_date"]) <= first for e in candidates):
            excludes.append({"dataset": "label", "source_row": "",
                             "ticker": ticker, "fiscal_year": str(fy),
                             "reason": "tej_event_precedes_first_publication"})
            continue
        # Missing complete follow-up means neither class can be assigned.
        y = "" if unresolved else "1" if within else "0" if eligible else ""
        core = ("" if unresolved else
                "1" if any(e["core_change"] == "1" for e in within) else
                "0" if eligible and all(e["core_change"] == "0" for e in within) else
                "0" if eligible and not within else "")
        # A TT2 broad event without financial-delta coverage is NOT a core=0.
        labels.append({
            "ticker": ticker, "fiscal_year": str(fy),
            "first_published_at": first.isoformat(),
            "observation_end_at": end.isoformat(),
            "y_tej_restatement_24m": y,
            "y_core_adjustment_24m": core,
            "last_tt2_event_date": max((e["event_date"] for e in within), default=""),
            "matching_tt2_event_count": str(len(within)),
            "label_grade": ("BLOCKED_UNPARSEABLE_TT2_EVENT" if unresolved else
                            "SOURCE_CONDITIONAL_WITH_MANIFEST" if eligible else
                            "OBSERVED_POSITIVE_IN_OPEN_WINDOW" if within else "CENSORED"),
            "target": TT2_EVENT_TARGET,
            "source_tt2_sha256": tt2_sha, "source_universe_sha256": universe_sha,
            "source_coverage_sha256": h(coverage_raw),
            "eligible_for_supervised_tej_target": str(bool(y)).lower(),
            "eligible_for_supervised_core_target": str(bool(core)).lower(),
            "warning": "TEJ_DEFINED_RESTATEMENT_NOT_PROVEN_FRAUD;ORIGINAL_FINANCIAL_X_NOT_VERIFIED",
        })
    counts = Counter(x["y_tej_restatement_24m"] for x in labels)
    core_counts = Counter(x["y_core_adjustment_24m"] for x in labels)
    event_blob = csv_blob(EVENT_COLUMNS, events)
    label_blob = csv_blob(LABEL_COLUMNS, labels)
    exclusion_blob = csv_blob(EXCLUSION_COLUMNS, excludes)
    report = {
        "schema": "fintrust_round2_tej_tt2_v1",
        "status": "TEJ_SOURCE_CONDITIONAL_LABELS_NEED_INDEPENDENT_AUDIT",
        "as_of": AS_OF.isoformat(),
        "input_tt2_rows": len(tt2_rows),
        "input_universe_rows": len(universe_rows),
        "deduplicated_events": len(events),
        "company_years_with_publication": len(labels),
        "tej_restatement_y_1": counts["1"],
        "tej_restatement_y_0": counts["0"],
        "tej_restatement_unlabeled": counts[""],
        "core_amount_y_1": core_counts["1"],
        "core_amount_y_0": core_counts["0"],
        "core_amount_unlabeled": core_counts[""],
        "excluded_rows": len(excludes),
        "blocked_issuer_years_due_to_unparseable_events": len(unresolved_keys & set(annual)),
        "orphan_tt2_event_issuer_years_not_in_universe": len(
            set(keyed_events) - set(annual)),
        "excluded_reasons": dict(Counter(e["reason"] for e in excludes)),
        "source_sha256": {"tt2": tt2_sha, "annual_universe": universe_sha,
                          "coverage_manifest": h(coverage_raw)},
        "covered_fiscal_years": sorted(covered_fy),
        "coverage_through": coverage_through.isoformat(),
        "label_definition": TT2_EVENT_TARGET,
        "source_reported_not_independently_verified": True,
        "fraud_label_claim_allowed": False,
        "financial_feature_x_present": False,
        "full_coverage_manual_assertion_not_cryptographic_proof": True,
        "original_filing_financial_x_verified": False,
        "important": "TT2 restatement is broader than financial misstatement. Negative only if an independent annual universe and complete TT2 export coverage are documented. No license data should be committed.",
        "output_sha256": {
            "round2_tej_tt2_events.csv": h(event_blob),
            "round2_tej_issuer_year_labels.csv": h(label_blob),
            "round2_tej_exclusions.csv": h(exclusion_blob),
        },
    }
    out = Path(out)
    immutable(out / "round2_tej_tt2_events.csv", event_blob)
    immutable(out / "round2_tej_issuer_year_labels.csv", label_blob)
    immutable(out / "round2_tej_exclusions.csv", exclusion_blob)
    immutable(out / "round2_tej_audit_report.json", json_blob(report))
    return report


def prepare_coverage_template(tt2_csv, universe_csv, out):
    """Create an unapproved local coverage manifest with actual file hashes."""
    tt2_raw, tt2_names, _ = load_csv(tt2_csv)
    univ_raw, univ_names, _ = load_csv(universe_csv)
    record = {
        "schema_version": "fintrust_tej_tt2_coverage_v1",
        "tt2_export_sha256": h(tt2_raw),
        "universe_export_sha256": h(univ_raw),
        "closed_event_census_for_exported_universe": False,
        "includes_historical_delisted_firms": False,
        "issuer_and_year_filters_match": False,
        "tt2_event_coverage_through": "",
        "covered_fiscal_years": [],
        "review_required": "Verify licensed coverage, historic/delisted firms, fiscal filters, event dates and observation window before setting these fields.",
        "tt2_input_headers": tt2_names,
        "universe_input_headers": univ_names,
    }
    immutable(Path(out) / "round2_tej_coverage_REVIEW_REQUIRED.json", json_blob(record))
    return {"status": "UNAPPROVED_COVERAGE_TEMPLATE",
            "file": "round2_tej_coverage_REVIEW_REQUIRED.json",
            "tt2_export_sha256": h(tt2_raw), "universe_export_sha256": h(univ_raw),
            "not_training_ready": True}


def preflight(out):
    report = {
        "schema": "fintrust_round2_tej_tt2_v1",
        "status": "WAITING_FOR_LICENSED_TT2_AND_ANNUAL_UNIVERSE_EXPORTS",
        "as_of": AS_OF.isoformat(),
        "real_tej_tt2_rows_ingested": 0,
        "real_tej_binary_labels_generated": 0,
        "requirements": [
            "Licensed TT2 restatement event CSV",
            "Complete historical annual consolidated filing universe CSV, including delisted issuers and first PUBLICATION dates",
            "Coverage manifest including source hashes and TT2 complete-through date",
        ],
        "source_rows_available_in_current_session": False,
        "synthetic_ci_samples_are_not_real_tej_data": True,
    }
    immutable(Path(out) / "round2_tej_preflight.json", json_blob(report))
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tt2-csv")
    p.add_argument("--universe-csv")
    p.add_argument("--coverage-json")
    p.add_argument("--column-map")
    p.add_argument("--preflight", action="store_true")
    p.add_argument("--prepare-coverage", action="store_true")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    if args.preflight:
        result = preflight(args.out)
    elif args.prepare_coverage and args.tt2_csv and args.universe_csv:
        result = prepare_coverage_template(args.tt2_csv, args.universe_csv, args.out)
    elif args.tt2_csv and args.universe_csv and args.coverage_json:
        result = materialize(args.tt2_csv, args.universe_csv,
                             args.coverage_json, args.out,
                             mapping_json=args.column_map)
    else:
        p.error("Requires --tt2-csv --universe-csv --coverage-json, or --preflight")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
