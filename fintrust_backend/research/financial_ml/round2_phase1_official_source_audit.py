"""FinTrust Phase1 Y1: reproducible source-ledger verification triage, NOT binary labels.

Combine a 145-case research sprint with a LOCAL user's licensed FinLab announcement
export. Each positive candidate must match its exact notice title and company ID,
and retains full text hash, market, clause and source sequence. Never infer Y1=0
from TEJ=0, FinLab silence, or an overdue restatement notice. Cross-checked
issuer source for 1203 is reference evidence, not original MOPS first-filed proof.

python -m research.financial_ml.round2_phase1_official_source_audit \
 --sprint-csv data/financial_ml/round2_official_sprint_20261025/official_y1_evidence_review_sprint_private.csv \
 --finlab-csv data/financial_ml/finlab_restatement_candidates.csv \
 --out data/financial_ml/round2_phase1_source_audit
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
from pathlib import Path

COMPANY_1203_2017_REPORT = "https://www.vewong.com/ecmas0069/store/F4/ANN_REP_2017.pdf"
COMPANY_1203_2018_REPORT = "https://www.vewong.com/ecmas0069/store/F4/ANN_REP_2018.pdf"
FIELDS = (
    "case_id", "ticker", "issuer_name", "fiscal_year", "candidate_type",
    "rank", "source_notice_title", "notice_date", "finlab_record_matched",
    "finlab_record_count", "finlab_source_sha256", "source_market",
    "source_clause", "source_sequence", "title_scope_risk",
    "ordinary_deadline_24m_check", "issuer_primary_source_url",
    "issuer_board_original_approval_date", "issuer_board_amended_approval_date",
    "issuer_amount_delta_crosscheck", "verified_original_MOPS_first_public_at",
    "verified_MOPS_revised_filing_url", "verified_MOPS_original_filing_url",
    "verified_MOPS_amendment_notice_url", "verified_mops_24m_coverage",
    "label", "audit_status", "missing_evidence",
)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _load(path):
    raw = Path(path).read_bytes()
    decoded = None
    for enc in ("utf-8-sig", "cp950"):
        try:
            decoded = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if decoded is None:
        raise ValueError("unsupported_csv_encoding")
    reader = csv.DictReader(io.StringIO(decoded))
    if not reader.fieldnames:
        raise ValueError("source_headers_missing")
    return list(reader), _sha(raw)


def _csv(rows, fields):
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue().encode("utf-8-sig")


def _preserve(path, blob):
    path = Path(path)
    if path.exists() and path.read_bytes() != blob:
        raise FileExistsError("phase1_refuse_overwrite:" + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(blob)


def _finlab_sha(row):
    return _sha((str(row["stock_id"]) + "\n" + str(row["date"]) + "\n"
                 + str(row["title"]) + "\n" + str(row["info"])).encode("utf-8"))


def _check_vw_amounts(info):
    """Explicit FY2017 consolidated restatement table copied into the issuer's notice."""
    # Thousands of TWD, not raw dollars. Do not mistake individual-only note changes.
    s = ["9,079,372", "9,192,281", "633,605", "746,401",
         "4,287,711", "4,174,915"]
    if not all(v in info for v in s):
        return ""
    if not ("106年度合併財務報告" in info and "重編" in info):
        return ""
    if not (9192281 - 9079372 == 112909
            and 746401 - 633605 == 112796
            and 4174915 - 4287711 == -112796):
        return ""
    return (
        "CROSSCHECKED_NOTICE_TABLE_NT1000:"
        "assets_9079372_to_9192281_delta_112909;"
        "netincome_633605_to_746401_delta_112796;"
        "cogs_4287711_to_4174915_delta_minus112796"
    )


def build(sprint_csv, finlab_csv, out):
    cases, sprint_hash = _load(sprint_csv)
    notices, source_hash = _load(finlab_csv)
    required_cases = {
        "case_id", "ticker", "issuer_name", "fiscal_year", "candidate_type",
        "rank", "notice_title", "training_y",
    }
    required_notices = {"stock_id", "title", "date", "info", "source_market",
                        "source_clause", "source_sequence"}
    if not cases or not required_cases.issubset(cases[0]):
        raise ValueError("sprint_columns_missing")
    if not notices or not required_notices.issubset(notices[0]):
        raise ValueError("finlab_columns_missing")
    lookup = defaultdict(list)
    for notice in notices:
        lookup[(notice["stock_id"], notice["title"])].append(notice)
    for matches in lookup.values():
        matches.sort(key=lambda r: (r["date"], r["source_sequence"]))
    ledger = []
    seen = set()
    for c in cases:
        caseid = c["case_id"]
        if caseid in seen:
            raise ValueError("duplicate_sprint_case")
        seen.add(caseid)
        if (c.get("training_y") or "").strip() not in ("",):
            raise ValueError("cannot_overwrite_existing_official_outcome")
        ticker = c["ticker"]
        fy = int(c["fiscal_year"])
        is_positive = c["candidate_type"] == "POSITIVE_EVENT_REVIEW"
        if c["candidate_type"] not in ("POSITIVE_EVENT_REVIEW",
                                        "UNLABELED_CONTROL_REVIEW"):
            raise ValueError("unexpected_sprint_candidate_type")
        matches = lookup.get((ticker, c["notice_title"]), []) if is_positive else []
        n = matches[-1] if matches else None
        d = ""
        deadline = "NO_NOTICE"
        scope = ""
        if n:
            d = n["date"][:10]
            when = date.fromisoformat(d)
            # Securities and Exchange Act sec.36 generally requires FY filing
            # by following Mar31. THIS IS NOT first actual public filing date.
            if when > date(fy + 3, 3, 31):
                deadline = "NOTICE_AFTER_ORDINARY_FY_FILING_LIMIT_PLUS_24M_CHECK_EXCEPTION"
            elif when < date(fy + 1, 1, 1):
                deadline = "NOTICE_BEFORE_ANNUAL_PERIOD_COMPLETED_CHECK_SCOPE"
            else:
                deadline = "NOTICE_TIMING_PLAUSIBLE_NOT_VERIFIED"
            title = c["notice_title"]
            if ("個體" in title or "個別" in title) and "合併" not in title:
                scope = "ONLY_INDIVIDUAL_MENTIONED_REQUIRE_CONSOLIDATED_PROOF"
            elif "合併" in title:
                scope = "CONSOLIDATED_MENTIONED_NOT_OFFICIAL_VERSION_VERIFIED"
            else:
                scope = "SCOPE_UNCLEAR_FROM_TITLE"
        vw = ""
        first_doc = ""
        first_board = ""
        changed_board = ""
        if caseid == "1203-FY2017" and n:
            vw = _check_vw_amounts(n["info"])
            if vw:
                first_doc = COMPANY_1203_2017_REPORT + ";" + COMPANY_1203_2018_REPORT
                first_board = "2018-03-29"
                changed_board = "2018-05-11"
        ledger.append({
            "case_id": caseid, "ticker": ticker, "issuer_name": c["issuer_name"],
            "fiscal_year": fy, "candidate_type": c["candidate_type"],
            "rank": c["rank"], "source_notice_title": c["notice_title"],
            "notice_date": d, "finlab_record_matched": str(bool(n)).lower(),
            "finlab_record_count": len(matches),
            "finlab_source_sha256": _finlab_sha(n) if n else "",
            "source_market": n.get("source_market", "") if n else "",
            "source_clause": n.get("source_clause", "") if n else "",
            "source_sequence": n.get("source_sequence", "") if n else "",
            "title_scope_risk": scope, "ordinary_deadline_24m_check": deadline,
            "issuer_primary_source_url": first_doc,
            "issuer_board_original_approval_date": first_board,
            "issuer_board_amended_approval_date": changed_board,
            "issuer_amount_delta_crosscheck": vw,
            "verified_original_MOPS_first_public_at": "",
            "verified_MOPS_revised_filing_url": "",
            "verified_MOPS_original_filing_url": "",
            "verified_MOPS_amendment_notice_url": "",
            "verified_mops_24m_coverage": "",
            "label": "",
            "audit_status": "UNKNOWN_PENDING_MOPS_VERSIONED_EVIDENCE",
            "missing_evidence": (
                "FULL_OFFICIAL_24M_COVERAGE_AND_ORIGINAL_PUBLICATION"
                if not is_positive else
                "OFFICIAL_ORIGINAL_FIRST_PUBLICATION_AND_BOTH_REPORT_VERSIONS"
            ),
        })
    rank_count = Counter(r["rank"] for r in ledger)
    timing = Counter(r["ordinary_deadline_24m_check"] for r in ledger if
                     r["candidate_type"] == "POSITIVE_EVENT_REVIEW")
    matches = sum(r["finlab_record_matched"] == "true"
                  for r in ledger if r["candidate_type"] == "POSITIVE_EVENT_REVIEW")
    summary = {
        "schema": "fintrust_phase1_official_source_audit_v1",
        "source_sprint_sha256": sprint_hash, "source_finlab_sha256": source_hash,
        "case_count": len(ledger), "positive_candidates": sum(
            r["candidate_type"] == "POSITIVE_EVENT_REVIEW" for r in ledger),
        "negative_control_candidates": sum(
            r["candidate_type"] == "UNLABELED_CONTROL_REVIEW" for r in ledger),
        "matched_exact_company_and_title_positive_notice_count": matches,
        "notice_timing_flags": dict(sorted(timing.items())),
        "rank_count": dict(sorted(rank_count.items())),
        "issuer_core_amounts_independently_arithmetically_crosschecked": sum(
            bool(r["issuer_amount_delta_crosscheck"]) for r in ledger),
        "official_MOPS_first_annual_publication_verified": 0,
        "official_MOPS_original_and_revised_versions_verified": 0,
        "complete_negative_24m_query_coverage_verified": 0,
        "approved_y_1": 0, "approved_y_0": 0,
        "y_unknown": len(ledger),
        "warning": (
            "Company board approval is not MOPS first publication. Actual "
            "official dated original and amended filing versions and a 24-month "
            "observation certificate are needed. No fake 0/1 from FinLab/TEJ cues."
        ),
    }
    output = Path(out)
    csv_data = _csv(ledger, FIELDS)
    summary["ledger_sha256"] = _sha(csv_data)
    _preserve(output / "phase1_145_case_evidence_ledger_private.csv", csv_data)
    _preserve(output / "phase1_quality_summary.json",
              (json.dumps(summary, ensure_ascii=False, sort_keys=True,
                          indent=2) + "\n").encode("utf-8"))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sprint-csv", required=True)
    parser.add_argument("--finlab-csv", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.sprint_csv, args.finlab_csv, args.out),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
