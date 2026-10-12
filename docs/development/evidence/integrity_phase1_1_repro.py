"""Reviewer reproductions for Phase 1.1 (CR-01..CR-04, CR-06), SYNTHETIC inputs only, no data access.

    (cwd = <checkout>/fintrust_backend) python integrity_phase1_1_repro.py --out <file.json>

Records observed behaviour of whatever code is importable (run before and after the fix); it asserts nothing.
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from app.services.integrity import alignment as al  # noqa: E402
from app.services.integrity import financial_checks as fc  # noqa: E402
from app.services.integrity.adapters import FactsAdapter  # noqa: E402

TICKER = "2454"


def url(host="https://mopsov.twse.com.tw", co_id=TICKER, year=114, extra=""):
    return f"{host}/server-java/FileDownLoad?functionName=t164sb01&step=9&co_id={co_id}&year={year}&season=4&report_id=C{extra}"


def identity(u):
    takes_ticker = "ticker" in inspect.signature(al.mops_filing_identity).parameters
    result = al.mops_filing_identity(u, ticker=TICKER) if takes_ticker else al.mops_filing_identity(u)
    return {k: result.get(k) for k in ("recognised", "scope", "filing_version", "reason")}


def row(metric, period, value, *, is_demo=False, retrieved="2026-09-15T00:00:00+00:00", source_url=None):
    return {"fact_id": f"{metric}:{period}:{is_demo}:{retrieved}", "ticker": TICKER, "company_name": "SYNTHETIC",
            "subindustry": "x", "analysis_type": "historical", "period": period, "metric_code": metric, "value": value,
            "unit": "新台幣元", "source_kind": "mvp_fixture" if is_demo else "mops_xbrl",
            "source_url": source_url or url(year=int(period[:4]) - 1911), "taxonomy_concept": metric,
            "retrieved_at": retrieved, "statement_scope": "unknown", "filed_at": None, "is_demo": int(is_demo),
            "source_field": None}


class Repo:
    def __init__(self, rows):
        self.rows = rows

    def list_facts(self, ticker, limit=500, **_):
        return [r for r in self.rows if r["ticker"] == ticker][:limit]


def collect(rows):
    return FactsAdapter(Repo(rows)).collect(TICKER)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = {}
    # CR-01: forged or mismatched filing identities.
    out["CR01"] = {name: identity(u) for name, u in {
        "legitimate_2454": url(),
        "untrusted_host_review_example": "https://evil.example/untrusted?functionName=t164sb01&year=114&season=4&report_id=C",
        "http_scheme": url(host="http://mopsov.twse.com.tw"),
        "lookalike_host": url(host="https://mopsov.twse.com.tw.evil.example"),
        "wrong_co_id_9999": url(co_id="9999"),
        "duplicate_conflicting_year": url(extra="&year=113"),
        "malformed_year": url(year="11X"),
    }.items()}
    out["CR01"]["facts_adapter_untrusted_row"] = {k: collect([row("revenue", "2025FY", 1.0, source_url=(
        "https://evil.example/untrusted?functionName=t164sb01&year=114&season=4&report_id=C"))])["records"][0].get(k)
        for k in ("scope", "filing_policy", "independence", "source_url")}
    # CR-02: FY2025 has revenue + NI only.
    full = {"revenue": {2023: 1000.0, 2024: 1000.0, 2025: 1100.0}, "accounts_receivable": {2023: 200.0, 2024: 200.0},
            "net_income": {2023: 100.0, 2024: 120.0, 2025: 150.0}, "operating_cash_flow": {2023: 130.0, 2024: 110.0}}
    index = collect([row(m, f"{y}FY", v) for m, ys in full.items() for y, v in ys.items()])["index"]
    f1, f2 = fc.check_revenue_receivables(index), fc.check_net_income_cfo(index)
    keys = ("status", "period", "review_queue", "latest_fact_fiscal_year", "freshness_status", "latest_period_status")
    out["CR02"] = {"F1": {k: f1.get(k) for k in keys}, "F2": {k: f2.get(k) for k in keys}}
    # CR-03: same amount, demo row first (earlier) and a real MOPS row; and the reversed order.
    demo = row("revenue", "2025FY", 1100.0, is_demo=True, retrieved="2026-01-01T00:00:00+00:00")
    real = row("revenue", "2025FY", 1100.0, retrieved="2026-09-15T00:00:00+00:00")
    out["CR03"] = {order: {"indexed": ("revenue", 2025) in (c := collect(rows))["index"],
                           "excluded": c["excluded"], "quality": c["quality"]}
                   for order, rows in (("demo_first", [demo, real]), ("real_first", [real, demo]))}
    # CR-04: existing claim parser on grouped thousands.
    from app.services.claim_parser import extract_claim

    claims = ["聯發科2024年營收530,586百萬元", "聯發科2024年營收新台幣5,305.86億元", "聯發科2024年營收530586百萬元",
              "聯發科2024年淨損-1,234.5億元"]
    out["CR04_parser"] = {text: {"value": (p := extract_claim(text, ticker_hint=TICKER)).claimed_value,
                                 "value_text": p.claimed_value_text, "unit": p.unit} for text in claims}
    # CR-06: F1 gap vs DSRI - 1 on the review's example.
    ar0, ar1, s0, s1 = Decimal(200), Decimal(250), Decimal(1000), Decimal(1100)
    out["CR06"] = {"f1_gap": str((ar1 / ar0 - 1) - (s1 / s0 - 1)), "dsri_minus_1": str(((ar1 / s1) / (ar0 / s0) - 1).quantize(Decimal("0.000001")))}
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
