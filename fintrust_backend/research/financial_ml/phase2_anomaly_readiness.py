"""Offline Phase 2 X/Y2 anomaly enrichment and TRAINING-PREFLIGHT ONLY.

Consumes the existing source-locked PIT join; never downloads data, trains models,
changes databases or converts Y2 into Y1. Industry peers use only X visible at
each prediction cutoff (no outcome/labels in their calculations). All outputs
are local/ignored by Git. Run from fintrust_backend.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from research.financial_ml.phase2_pit_x_y_bridge import (
    FEATURES, OUT_COLS, csv_load, csv_bytes, immutable, number, published
)

EXTRA = (
    "delta_roa", "delta_current_ratio", "delta_debt_assets",
    "delta_cfo_assets", "cfo_profit_divergence",
    "streak_roa_down_2y", "streak_cfo_assets_down_2y",
    "streak_debt_assets_up_2y",
)
PEER = tuple(f + suffix for f in FEATURES for suffix in (
    "_industry_year_percentile", "_industry_year_robust_z"))
SAFE_FEATURES = tuple(FEATURES) + EXTRA + PEER
FINAL_COLS = tuple(OUT_COLS) + ("industry_code", "industry_asof_verified",
    "candidate_eligible", "exclusion_reason", *EXTRA, *PEER)
INDUSTRY_REQUIRED = {"ticker", "industry_code", "valid_from", "valid_to", "known_at"}
HASH = re.compile(r"^[a-fA-F0-9]{64}$")
RISK_MINIMUM = {"train": (1000, 30, 30), "validation": (200, 10, 10),
                "test": (200, 10, 10)}
BAD_INPUT_FIELDS = ("restatement_count", "future_", "outcome_known",
                    "tej_last", "tej_positive", "fraud_label")

def iso(value):
    s = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        raise ValueError("invalid_iso_date")
    return date.fromisoformat(s)

def expected_split(y):
    if 2016 <= y <= 2020:
        return "train"
    if y in (2021, 2022):
        return "validation"
    if y == 2023:
        return "test"
    raise ValueError("unexpected_proxy_target_year")

def load_industries(path):
    if path is None:
        return {}, None
    rows, digest = csv_load(path, INDUSTRY_REQUIRED)
    lookup = defaultdict(list)
    for r in rows:
        tick = r["ticker"].strip()
        name = r["industry_code"].strip()
        if not re.fullmatch(r"\d{4}", tick) or not name:
            raise ValueError("invalid_industry_identity")
        begin = iso(r["valid_from"])
        end = iso(r["valid_to"]) if r["valid_to"].strip() else date.max
        known = iso(r["known_at"])
        if begin > end:
            raise ValueError("invalid_industry_validity_window")
        lookup[tick].append((begin, end, known, name))
    return lookup, digest

def industry_at(lookup, ticker, asof):
    eligible = [v[3] for v in lookup.get(ticker, [])
                if v[0] <= asof <= v[1] and v[2] <= asof]
    if len(eligible) > 1:
        raise ValueError("overlapping_asof_industry:" + ticker)
    return eligible[0] if eligible else ""

def _fmt(v):
    return "" if v is None else format(v, ".12g")

def _parsed(row):
    values = {}
    for f in FEATURES:
        values[f] = number(row[f])
    return values

def _valid_provenance(row, manifest):
    ticker = row["ticker"].strip()
    cy = int(row["target_calendar_year"])
    cutoff = iso(row["asof_date"])
    fy = int(row["feature_fy"])
    if cutoff != date(cy - 1, 12, 31) or fy != cy - 2 or int(row["prior_feature_fy"]) != cy - 3:
        raise ValueError("x_y_fiscal_cutoff_mismatch:" + ticker)
    current = manifest.get(f"{ticker}:{fy}")
    prior = manifest.get(f"{ticker}:{fy-1}")
    for label, record in (("CURRENT", current), ("PRIOR", prior)):
        error = published(record, cutoff)
        if error:
            return label + "_" + error
        if record.get("ticker") != ticker or int(record.get("fiscal_year", -1)) != (fy if label == "CURRENT" else fy-1):
            return label + "_MANIFEST_FY_IDENTITY_MISMATCH"
    if row["source_current_sha256"] != current["content_hash"] or row["source_prior_sha256"] != prior["content_hash"]:
        return "JOIN_MANIFEST_SOURCE_HASH_MISMATCH"
    if not HASH.fullmatch(row["source_current_sha256"]) or not HASH.fullmatch(row["source_prior_sha256"]):
        return "INVALID_SOURCE_HASH"
    if row["x_original_version_and_asof_verified"] != "true":
        return "JOIN_PIT_NOT_VERIFIED"
    if row["x_gate"] not in ("MATCHED_PIT_ORIGINAL_FEATURES", "PIT_SOURCE_PARTIAL_FEATURES"):
        return "JOIN_GATE_NOT_ADMITTED"
    return ""

def _streak(a, b, c, direction):
    if a is None or b is None or c is None:
        return None
    return float((a < b < c) if direction == "down" else (a > b > c))

def _peer_features(rows, min_peer, counters):
    groups = defaultdict(list)
    for row in rows:
        if row["_valid"] and row["industry_code"]:
            groups[(row["target_calendar_year"], row["industry_code"])].append(row)
    for (year, ind), members in groups.items():
        for feature in FEATURES:
            observed = sorted(r["_x"][feature] for r in members if r["_x"][feature] is not None)
            if len(observed) < min_peer:
                counters["INSUFFICIENT_PEER_COUNT"] += len(members)
                continue
            median = statistics.median(observed)
            mad = statistics.median(abs(x - median) for x in observed)
            for r in members:
                v = r["_x"][feature]
                if v is None:
                    continue
                # Midrank/ECDF percentile; no target labels or future-year input.
                left, right = bisect.bisect_left(observed, v), bisect.bisect_right(observed, v)
                r[feature + "_industry_year_percentile"] = _fmt(100 * (left + right) / (2 * len(observed)))
                if mad:
                    r[feature + "_industry_year_robust_z"] = _fmt(.67448975 * (v - median) / mad)
                else:
                    counters["ZERO_PEER_MAD"] += 1

def build(join_csv, manifest_json, out, industry_csv=None, *, min_row_features=8,
          min_peer=20, min_enhanced_peer_coverage=.5, verify_archives=False):
    if not 1 <= min_row_features <= len(FEATURES) or min_peer < 5:
        raise ValueError("invalid_coverage_or_peer_threshold")
    src, join_sha = csv_load(join_csv, OUT_COLS)
    for disallowed in BAD_INPUT_FIELDS:
        # Never admit additional outcome-derived numeric inputs masquerading as X.
        header = next(csv.DictReader(Path(join_csv).open(encoding="utf-8-sig", newline="")))
        if any(disallowed in col.lower() for col in header if col not in OUT_COLS):
            raise ValueError("unapproved_outcome_derived_input_field")
        break
    source_raw = Path(manifest_json).read_bytes()
    manifest = json.loads(source_raw).get("outcomes")
    if not isinstance(manifest, dict):
        raise ValueError("invalid_manifest_outcomes")
    industries, industry_sha = load_industries(industry_csv)
    rows = []
    counts, exclude_counts = Counter(), Counter()
    seen = set()
    year_counts, split_counts = defaultdict(Counter), defaultdict(Counter)
    missing_by_year = defaultdict(Counter)
    per_feature_counts = Counter()
    valid_by_ticker_year = {}
    for r in src:
        ticker = r["ticker"].strip()
        year = int(r["target_calendar_year"])
        if ticker == "1785" or not re.fullmatch(r"\d{4}", ticker):
            raise ValueError("heldout_or_invalid_ticker")
        key = (ticker, year)
        if key in seen:
            raise ValueError("duplicate_company_target_year")
        seen.add(key)
        if r["split"] != expected_split(year):
            raise ValueError("incorrect_temporal_split:" + ticker)
        if r["case_key"] != f"{ticker}-CY{year}":
            raise ValueError("incorrect_case_key")
        if r["y_official_annual_24m"].strip():
            raise ValueError("official_y1_must_remain_null")
        if r["y_tej_calendar_proxy"] not in ("0", "1"):
            raise ValueError("invalid_y2_binary")
        x = _parsed(r)
        n = sum(v is not None for v in x.values())
        if int(r["feature_count"]) != n:
            raise ValueError("feature_count_does_not_match_actual_features")
        expected_missing = {f for f, v in x.items() if v is None}
        if set(filter(None, r["missing_feature_names"].split(";"))) != expected_missing:
            raise ValueError("feature_missing_list_mismatch")
        err = _valid_provenance(r, manifest)
        admissible = not err
        reason = err or ("INSUFFICIENT_BASE_FEATURES" if n < min_row_features else "")
        ok = not reason
        cutoff = iso(r["asof_date"])
        ind = industry_at(industries, ticker, cutoff)
        outrow = dict(r)
        outrow.update({"industry_code": ind,
                       "industry_asof_verified": str(bool(ind)).lower(),
                       "candidate_eligible": str(ok).lower(),
                       "exclusion_reason": reason,
                       **{f: "" for f in EXTRA + PEER},
                       "_valid": admissible, "_x": x})
        rows.append(outrow)
        if admissible:
            valid_by_ticker_year[(ticker, year)] = outrow
        year_counts[str(year)]["total"] += 1
        split_counts[r["split"]]["total"] += 1
        split_counts[r["split"]]["y2_positive_total"] += int(r["y_tej_calendar_proxy"])
        if ok:
            counts["candidate_rows"] += 1
            split_counts[r["split"]]["candidate"] += 1
            split_counts[r["split"]]["candidate_positive"] += int(r["y_tej_calendar_proxy"])
            year_counts[str(year)]["candidate"] += 1
            year_counts[str(year)]["candidate_positive"] += int(r["y_tej_calendar_proxy"])
            if ind:
                counts["candidate_with_asof_industry"] += 1
            for f in FEATURES:
                if x[f] is None:
                    missing_by_year[str(year)][f] += 1
                else:
                    per_feature_counts[f] += 1
        else:
            exclude_counts[reason] += 1
            year_counts[str(year)]["excluded"] += 1
    # Historical YoY follows the same ticker and consecutive target CY only.
    for r in rows:
        if not r["_valid"]:
            continue
        ticker = r["ticker"]
        year = int(r["target_calendar_year"])
        p = valid_by_ticker_year.get((ticker, year - 1))
        q = valid_by_ticker_year.get((ticker, year - 2))
        x, xp, xq = r["_x"], p["_x"] if p else {}, q["_x"] if q else {}
        for f in ("roa", "current_ratio", "debt_assets", "cfo_assets"):
            now, before = x[f], xp.get(f)
            if now is not None and before is not None:
                r["delta_" + f] = _fmt(now - before)
        if x["roa"] is not None and x["cfo_assets"] is not None:
            r["cfo_profit_divergence"] = _fmt(x["roa"] - x["cfo_assets"])
        for f, outname, direction in (
            ("roa", "streak_roa_down_2y", "down"),
            ("cfo_assets", "streak_cfo_assets_down_2y", "down"),
            ("debt_assets", "streak_debt_assets_up_2y", "up"),
        ):
            r[outname] = _fmt(_streak(x[f], xp.get(f), xq.get(f), direction))
    peer_diag = Counter()
    _peer_features(rows, min_peer, peer_diag)
    extended_counts = Counter()
    for r in rows:
        if r["candidate_eligible"] == "true":
            for f in EXTRA + PEER:
                if r[f] != "":
                    extended_counts[f] += 1
    for r in rows:
        del r["_valid"]
        del r["_x"]
    total = len(rows)
    cand = counts["candidate_rows"]
    blockers = []
    if total < 2000:
        blockers.append("COHORT_TOO_SMALL")
    for split, (min_n, min_pos, min_neg) in RISK_MINIMUM.items():
        st = split_counts[split]
        if st["candidate"] < min_n:
            blockers.append(split.upper() + "_SAMPLE_COUNT_LOW")
        if st["candidate_positive"] < min_pos:
            blockers.append(split.upper() + "_POSITIVE_COUNT_LOW")
        if st["candidate"] - st["candidate_positive"] < min_neg:
            blockers.append(split.upper() + "_NEGATIVE_COUNT_LOW")
    if cand == 0:
        blockers.append("NO_PIT_VERIFIED_MATCHED_X_Y")
    # The complete XBRL archive is rehashed in upstream extraction; this module
    # alone does not independently authenticate MOPS contents or publication.
    if not verify_archives:
        blockers.append("UPSTREAM_ARCHIVE_AND_PUBLICATION_AUDIT_NOT_ATTESTED")
    baseline = not blockers
    peer_cols = [f + "_industry_year_percentile" for f in FEATURES]
    peer_ready = sum(r["candidate_eligible"] == "true" and
                     any(r[f] != "" for f in peer_cols) for r in rows)
    enhanced_blockers = list(blockers)
    if not cand or peer_ready / max(cand, 1) < min_enhanced_peer_coverage:
        enhanced_blockers.append("INDUSTRY_PEER_COVERAGE_LOW")
    report = {
        "schema": "fintrust_phase2_anomaly_readiness_v1",
        "source_sha256": {"join": join_sha,
            "manifest": hashlib.sha256(source_raw).hexdigest(),
            "industry": industry_sha},
        "y2_target": "TEJ_CALENDAR_YEAR_PROXY_NOT_OFFICIAL_Y1",
        "y1_verified": False, "heldout_1785_excluded": True,
        "raw_join_rows": total, "candidate_rows": cand,
        "full_15_feature_rows": sum(int(r["feature_count"]) == 15 and
             r["candidate_eligible"] == "true" for r in rows),
        "partial_8_to_14_feature_rows": sum(8 <= int(r["feature_count"]) < 15 and
             r["candidate_eligible"] == "true" for r in rows),
        "year_counts": {y: dict(c) for y, c in sorted(year_counts.items())},
        "split_counts": {s: dict(split_counts[s]) for s in ("train", "validation", "test")},
        "exclusion_reasons": dict(sorted(exclude_counts.items())),
        "base_feature_coverage": {f: {"nonmissing": per_feature_counts[f],
            "among_candidates": cand} for f in FEATURES},
        "missing_features_by_target_year": {y: dict(c) for y,c in sorted(missing_by_year.items())},
        "enhanced_feature_nonmissing": {f: extended_counts[f] for f in EXTRA + PEER},
        "peer_diagnostics": dict(peer_diag),
        "peer_reference": "Same target-year, as-of-verified industry cohort X only; no Y values. Transductive covariate-only, not an inductive learned transformation.",
        "baseline_blockers": blockers,
        "enhanced_blockers": enhanced_blockers,
        "baseline_training_preflight_pass": baseline,
        "enhanced_training_preflight_pass": not enhanced_blockers,
        "min_base_features_per_row": min_row_features,
        "min_industry_peer_rows": min_peer,
        "safe_model_feature_allowlist": list(SAFE_FEATURES),
        "fit_or_train_performed": False,
        "warning": "verify_archives is an OPERATOR ATTESTATION after independent original MOPS first-publication/version and local raw SHA review; flag alone is not evidence. No official Y1, no future/revised X, no production changes."
    }
    dest = Path(out)
    result = csv_bytes(rows, FINAL_COLS)
    report["output_sha256"] = hashlib.sha256(result).hexdigest()
    immutable(dest / "phase2_x_y_anomaly_private.csv", result)
    immutable(dest / "phase2_training_readiness_report.json",
        (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return report

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--join", required=True)
    p.add_argument("--manifest", required=True)
    p.add_argument("--industry", help="Private as-of industry history CSV (optional)")
    p.add_argument("--out", required=True)
    p.add_argument("--min-row-features", type=int, default=8)
    p.add_argument("--min-peer", type=int, default=20)
    p.add_argument("--verify-archives", action="store_true",
                   help="Operator asserts upstream raw SHA plus independent actual first publication/version audit; not automated.")
    a = p.parse_args(argv)
    report = build(a.join, a.manifest, a.out, a.industry,
                   min_row_features=a.min_row_features, min_peer=a.min_peer,
                   verify_archives=a.verify_archives)
    print(json.dumps(report, ensure_ascii=False, indent=2))
if __name__ == "__main__":
    main()
