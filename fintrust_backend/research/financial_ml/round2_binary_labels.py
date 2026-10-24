"""Round 2: evidence-linked numeric binary Y table, separate from 24-month audit labels.

The 0/1 sample uses transparent SILVER-tier retrospective issuer-year labels.
The label is DOCUMENTED_ANNUAL_CONSOLIDATED_CORE_FINANCIAL_CORRECTION_OR_
RESTATEMENT_OBSERVED_BY_ASOF, NOT fraud or demonstrated advance prediction.
No financial X is loaded, no imputation/model fit, and no production writes.

Usage (from fintrust_backend):
python -m research.financial_ml.round2_binary_labels --out data/financial_ml/round2_labels
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

from .round1_event_registry import build as round1_build

HOME = Path(__file__).resolve().parent
INPUT = HOME / "round2_reviewed_binary_evidence_20261024.json"
TARGET = "DOCUMENTED_ANNUAL_CONSOLIDATED_CORE_FINANCIAL_CORRECTION_OR_RESTATEMENT_OBSERVED_BY_ASOF"
LABEL_COLS = (
    "ticker", "company", "fiscal_year", "y", "target", "evidence_grade",
    "source_url", "notice_date", "annual_event_id", "reported_period",
    "observation_asof", "first_filed_at", "strict_24m_y",
    "negative_window_complete", "original_xbrl_first_filing_verified",
    "exploratory_label_only", "certified_fraud_label",
    "description",
)
FOLLOWUP_COLS = ("ticker", "fiscal_year", "event_id", "event_family",
                 "source_url", "reason")


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _csv_blob(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="raise",
                            lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _put(path, data):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError("round2_immutable_output_conflict:" + str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_labels(evidence, events, periods):
    if evidence.get("schema_version") != "fintrust_round2_reviewed_issuer_year_binary_v1":
        raise ValueError("round2_bad_input_schema")
    if evidence.get("as_of") != "2026-10-24" or evidence.get("target") != TARGET:
        raise ValueError("round2_target_or_cutoff_mismatch")
    event_by_id = {e["event_id"]: e for e in events}
    if len(event_by_id) != len(events):
        raise ValueError("round1_duplicate_event")
    annual_links = {(p["ticker"], int(p["fiscal_year"]), p["event_id"])
                    for p in periods if p["granularity"] == "annual_candidate_context"
                    and p["annual_target_candidate"] == "true"}
    rows = []
    seen = {}
    expected_counts = Counter()
    for category, expected_y in (("positives", 1), ("negatives", 0)):
        for case in evidence[category]:
            ticker = str(case["ticker"])
            year = int(case["fiscal_year"])
            if (not ticker.isascii() or not ticker.isdecimal()
                    or len(ticker) != 4 or not 2013 <= year <= 2025
                    or case["label"] != expected_y):
                raise ValueError("round2_invalid_issuer_year_or_y")
            if ticker == "1785":
                raise ValueError("round2_reserved_1785_contamination")
            key = (ticker, year)
            if key in seen:
                raise ValueError("round2_duplicate_or_conflicting_y")
            seen[key] = expected_y
            url = case["source_url"]
            if not url.startswith("https://"):
                raise ValueError("round2_evidence_https_required")
            ref_id = ""
            notice = ""
            desc = ""
            grade = case["evidence_grade"]
            if expected_y == 1:
                if grade != "SILVER_ISSUER_NOTICE_REPRINT_EXPLICIT_CONSOLIDATED_AMOUNT_CHANGE":
                    raise ValueError("round2_positive_evidence_grade_not_approved")
                possible = [e for e in events if e["ticker"] == ticker
                            and e["source_url"] == url
                            and e["notice_date"] == case["notice_date"]
                            and e["event_family"] == case["event_family"]]
                if len(possible) != 1:
                    raise ValueError("round2_positive_not_linked_to_round1_event")
                parent = possible[0]
                ref_id = parent["event_id"]
                if (ticker, year, ref_id) not in annual_links:
                    raise ValueError("round2_positive_year_is_not_supported")
                if (parent["reserved_holdout"] != "false" or
                        parent["annual_target_candidate"] != "true"):
                    raise ValueError("round2_positive_not_annual_or_heldout")
                if not case["amount_evidence"].strip():
                    raise ValueError("round2_positive_no_core_amount_evidence")
                if not case["notice_date"] or date.fromisoformat(case["notice_date"]) > date(2026, 10, 24):
                    raise ValueError("round2_future_or_missing_notice")
                notice = case["notice_date"]
                desc = case["amount_evidence"]
            else:
                if grade != "SILVER_THIRD_PARTY_MOPS_DERIVED_STATUS_SNAPSHOT":
                    raise ValueError("round2_negative_evidence_grade_not_approved")
                if (case["observed_period"] != f"{year}Q4"
                        or case["statement_scope"] != "consolidated"
                        or case["correction_indicator"] != "無"
                        or case["negative_window_complete"] is not False
                        or case["review_asof"] != "2026-10-24"):
                    raise ValueError("round2_negative_snapshot_is_not_eligible")
                if not url.endswith(f"/stock/{ticker}/filings"):
                    raise ValueError("round2_negative_source_identity_mismatch")
                if any(p["ticker"] == ticker and int(p["fiscal_year"]) == year
                       and p["annual_target_candidate"] == "true"
                       for p in periods):
                    raise ValueError("round2_known_positive_event_conflicts_with_negative")
                desc = f"{year}Q4 合併財報，更(補)正=無 (secondary current snapshot only)"
            rows.append({
                "ticker": ticker, "company": case["company"],
                "fiscal_year": str(year), "y": str(expected_y),
                "target": TARGET, "evidence_grade": grade,
                "source_url": url, "notice_date": notice,
                "annual_event_id": ref_id,
                "reported_period": f"{year}FY",
                "observation_asof": evidence["as_of"],
                "first_filed_at": "", "strict_24m_y": "",
                "negative_window_complete": "false",
                "original_xbrl_first_filing_verified": "false",
                "exploratory_label_only": "true",
                "certified_fraud_label": "",
                "description": desc,
            })
            expected_counts[expected_y] += 1
    if not expected_counts[1] or not expected_counts[0]:
        raise ValueError("round2_both_binary_classes_required")
    rows.sort(key=lambda r: (r["ticker"], r["fiscal_year"]))
    # The unresolved event-year links are retained as follow-up candidates
    # rather than mass-assigning all other companies 0.
    followups = []
    for p in periods:
        if (p["granularity"] != "annual_candidate_context"
                or p["annual_target_candidate"] != "true"
                or p["ticker"] == "1785"):
            continue
        key = (p["ticker"], int(p["fiscal_year"]))
        if key not in seen:
            followups.append({
                "ticker": p["ticker"], "fiscal_year": p["fiscal_year"],
                "event_id": p["event_id"], "event_family": p["event_family"],
                "source_url": p["source_url"],
                "reason": "Requires explicit annual core-amount evidence, not an issuer-level blanket label",
            })
    followups.sort(key=lambda p: (p["ticker"], int(p["fiscal_year"]), p["event_id"]))
    return rows, followups


def build(out, *, source_dir=HOME, evidence_file=INPUT):
    out = Path(out)
    # Import Round 1 deterministically into the new Round 2 output area.
    event_dir = out / "input_round1"
    base_report = round1_build(event_dir, source_dir=source_dir)
    events = _read_csv(event_dir / "round1_event_registry.csv")
    periods = _read_csv(event_dir / "round1_event_period_links.csv")
    evidence_blob = Path(evidence_file).read_bytes()
    evidence = json.loads(evidence_blob.decode("utf-8-sig"))
    rows, followups = make_labels(evidence, events, periods)
    labeled = _csv_blob(LABEL_COLS, rows)
    pending = _csv_blob(FOLLOWUP_COLS, followups)
    _put(out / "round2_binary_research_labels.csv", labeled)
    _put(out / "round2_targeted_followup_queue.csv", pending)
    counter = Counter(row["y"] for row in rows)
    report = {
        "schema_version": "fintrust_round2_binary_research_v1",
        "status": "ROUND2_REAL_BINARY_SILVER_LABELS_BUILT_NOT_STRICT_24M_GOLD",
        "as_of": "2026-10-24", "target": TARGET,
        "rows_numeric_y": len(rows), "y_1": counter["1"],
        "y_0": counter["0"],
        "positive_issuer_count": len({r["ticker"] for r in rows if r["y"] == "1"}),
        "negative_issuer_count": len({r["ticker"] for r in rows if r["y"] == "0"}),
        "total_issuer_count": len({r["ticker"] for r in rows}),
        "targeted_followup_event_year_rows": len(followups),
        "unassigned_mass_negative_rows": 0,
        "source_evidence_sha256": _sha(evidence_blob),
        "round1_source_input_sha256": base_report["source_file_sha256"],
        "round1_registry_sha256": base_report["output_sha256"],
        "outputs_sha256": {
            "round2_binary_research_labels.csv": _sha(labeled),
            "round2_targeted_followup_queue.csv": _sha(pending),
        },
        "only_silver_labels": True,
        "gold_labels": 0, "strict_24m_evaluable_rows": 0,
        "has_numeric_financial_x": False,
        "allowed_task": "Exploratory supervised research once X sources are separately verified; source-conditional label bias must be reported.",
        "prohibited_claims": [
            "Fraud classification accuracy", "24-month prospective prediction accuracy",
            "No corrections ever occurred for silver negative companies",
            "Original first-filed XBRL was validated",
            "All-market negative controls were screened"
        ],
        "reserved_holdout_1785": True, "no_production_writes": True,
    }
    _put(out / "round2_binary_label_report.json",
         (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--source-dir", default=str(HOME))
    parser.add_argument("--evidence-file", default=str(INPUT))
    args = parser.parse_args(argv)
    print(json.dumps(build(args.out, source_dir=args.source_dir,
                           evidence_file=args.evidence_file),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
