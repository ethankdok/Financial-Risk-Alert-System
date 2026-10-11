"""M3 — current official cross-source reconciliation (CURRENT_EVIDENCE_RECONCILIATION only).

Pairs are compared only on exact identity: ticker, fiscal period (full year), statement scope, accounting framework,
canonical metric (fixed, verified mappings only) and normalized unit. Outcomes:

- ``match``: identical exact Decimal values;
- ``mismatch_unresolved``: comparable, values differ; the cause is not established by the sources;
- ``not_comparable``: different scope / unit / period / version semantics, or no verified metric mapping.

A mismatch is evidence to review — never a proven restatement, misstatement or fraud — and it is never routed into
fraud labels or risk scores (``routes_to_risk_score`` is always false).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.input_snapshot import InputSnapshot, digest, safe_official_url
from app.services.financial_research.modes import AnalysisMode, ModeNotSupportedError

METHOD_ID = "source_reconciliation"
METHOD_VERSION = "source_reconciliation_v1"
EXPLANATION_LIMITS = (
    "The sources establish only that the stated figures differ. They do not state why. The difference is not "
    "described as a reclassification, correction, restatement, misstatement or fraud; no fraud label or risk score "
    "is derived from it.")


def _fact_index(snapshot: InputSnapshot) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {(f["period"], f["statement_scope"], f["metric_code"]): f for f in snapshot.facts}


def _outcome(a: Decimal | None, b: Decimal | None) -> str:
    if a is None or b is None:
        return "not_comparable"
    return "match" if a == b else "mismatch_unresolved"


def _fact_source(fact: dict[str, Any]) -> dict[str, Any]:
    return {"source_type": "filed_xbrl_fact", "fact_id": fact["fact_id"], "filing_version_id": fact["filing_version_id"],
            "filing_version_type": fact["filing_version_type"], "taxonomy_concept": fact.get("taxonomy_concept"),
            "value_twd": fact["value"], "unit": fact["unit"], "artifact_sha256": fact.get("artifact_sha256"),
            "artifact_url": fact.get("artifact_url"), "artifact_evidence_status": fact["artifact_evidence_status"]}


def compare_board_notices(snapshot: InputSnapshot) -> list[dict[str, Any]]:
    facts = _fact_index(snapshot)
    rows = []
    for value in snapshot.disclosed_values:
        notice = {"source_type": "board_approval_notice", "announcement_key": value["announcement_key"],
                  "notice_published_at": value["disclosed_at"], "notice_sha256": value["content_hash"],
                  "source_url": value.get("source_url"), "source_label": value["source_label"],
                  "value_published": value["value"], "published_unit": value["published_unit"],
                  "value_normalized": value["normalized_value"], "normalized_unit": value["normalized_unit"]}
        base = {"comparison_type": "board_notice_vs_filed_xbrl", "period": value["period"],
                "fiscal_year": value["fiscal_year"], "statement_scope": value["statement_scope"],
                "accounting_framework": value["accounting_framework"], "metric": value["canonical_metric"],
                "source_a": notice}
        metric = value["canonical_metric"]
        if not metric:
            rows.append({**base, "outcome": "not_comparable", "reasons": ["no_verified_canonical_metric_mapping"],
                         "source_b": None})
            continue
        fact = facts.get((value["period"], value["statement_scope"], metric))
        if fact is None:
            rows.append({**base, "outcome": "not_comparable", "reasons": ["no_filed_fact_same_period_scope_metric"],
                         "source_b": None})
            continue
        reasons = []
        if fact["unit"] != value["normalized_unit"]:
            reasons.append("unit_mismatch")
        if fact["accounting_framework"] != value["accounting_framework"]:
            reasons.append("framework_mismatch")
        a, b = dm.parse_decimal(value["normalized_value"]), dm.parse_decimal(fact["value"])
        outcome = "not_comparable" if reasons else _outcome(a, b)
        rows.append({**base, "outcome": outcome, "reasons": reasons, "source_b": _fact_source(fact),
                     "difference": dm.text(dm.sub(a, b)) if outcome == "mismatch_unresolved" else None,
                     "difference_unit": value["normalized_unit"] if outcome == "mismatch_unresolved" else None})
    return rows


def compare_restatement_post_side(snapshot: InputSnapshot) -> list[dict[str, Any]]:
    """Post-restatement notice values vs the restated filed facts (same period/scope/metric). The pre side is a
    different version by construction and is excluded."""
    facts = _fact_index(snapshot)
    rows = []
    for comparison in snapshot.comparisons:
        metric = comparison["canonical_metric"]
        if not metric or (comparison["period"], comparison["statement_scope"], metric) not in facts:
            continue
        fact = facts[(comparison["period"], comparison["statement_scope"], metric)]
        post = dm.parse_decimal(comparison["post_restatement_value"])
        post_twd = dm.mul(dm.to_twd(post, comparison["published_unit"]), Decimal(comparison["sign_factor"])) if post is not None else None
        reasons = [] if fact["filing_version_type"] == "restated" else ["filing_version_not_restated"]
        outcome = "not_comparable" if reasons else _outcome(post_twd, dm.parse_decimal(fact["value"]))
        rows.append({"comparison_type": "restatement_notice_post_vs_restated_xbrl", "period": comparison["period"],
                     "fiscal_year": comparison["fiscal_year"], "statement_scope": comparison["statement_scope"],
                     "accounting_framework": comparison["accounting_framework"], "metric": metric,
                     "source_a": {"source_type": "restatement_comparison_notice", "announcement_key": comparison["announcement_key"],
                                  "notice_published_at": comparison["disclosed_at"], "notice_sha256": comparison["content_hash"],
                                  "source_url": comparison.get("source_url"), "source_label": comparison["post_label"],
                                  "side": "post", "value_twd": dm.text(post_twd)},
                     "source_b": _fact_source(fact), "outcome": outcome, "reasons": reasons,
                     "difference": dm.text(dm.sub(post_twd, dm.parse_decimal(fact["value"]))) if outcome == "mismatch_unresolved" else None})
    return rows


def compare_summaries(backend: Any, ticker: str, start_year: int, end_year: int) -> list[dict[str, Any]]:
    """TPEx summary workbooks state no scope; the archive infers it by matching XBRL revenue, so comparing them back
    to XBRL would be circular. They are recorded as not_comparable (scope not declared by the source)."""
    rows = []
    for row in backend.list_summary_observations(ticker):
        if not start_year <= row["fiscal_year"] <= end_year or row["observation_role"] != "current_period":
            continue
        if not row.get("canonical_metric"):
            continue
        rows.append({"comparison_type": "tpex_summary_vs_filed_xbrl", "period": row["period"],
                     "fiscal_year": row["fiscal_year"], "statement_scope": row["statement_scope"],
                     "accounting_framework": row["accounting_framework"], "metric": row["canonical_metric"],
                     "source_a": {"source_type": "tpex_summary_workbook", "source_label": row["source_label"],
                                  "value_normalized": row["normalized_value"], "normalized_unit": row["normalized_unit"],
                                  "source_sha256": row["content_hash"], "source_url": safe_official_url(row["source_url"]),
                                  "statement_scope_basis": row.get("statement_scope_basis")},
                     "source_b": None, "outcome": "not_comparable",
                     "reasons": ["scope_inferred_from_value_match_not_declared_by_source"]})
    return rows


def pdf_check(finding_rows: list[dict[str, Any]], pdf: dict[str, Any] | None) -> dict[str, Any]:
    if pdf is None:
        return {"status": "pdf_evidence_unavailable_in_this_deployment"}
    checks = []
    for row in finding_rows:
        total = pdf["totals"].get(row["metric"])
        if total is None:
            checks.append({"metric": row["metric"], "status": "line_not_found"})
            continue
        pdf_twd = dm.to_twd(dm.parse_decimal(total["value_thousand_twd"]), "TWD_thousand")
        checks.append({"metric": row["metric"], "pdf_value_thousand_twd": total["value_thousand_twd"],
                       "account_code": total["account_code"], "pdf_line": total["line"],
                       "equals_filed_xbrl": pdf_twd == dm.parse_decimal(row["source_b"]["value_twd"]),
                       "equals_board_notice": pdf_twd == dm.parse_decimal(row["source_a"]["value_normalized"])})
    return {"status": "extracted", "pdf_sha256": pdf["pdf_sha256"], "pdf_page_index": pdf["pdf_page_index"],
            "printed_page_label": pdf["printed_page_label"], "unit": pdf["unit"], "extractor": pdf["extractor"],
            "extractor_version": pdf["extractor_version"], "source_url": safe_official_url(pdf["source_url"]),
            "artifact_available_at": pdf["artifact_available_at"],
            "artifact_availability_status": pdf["artifact_availability_status"], "checks": checks,
            "other_lines": {k: v for k, v in pdf["totals"].items() if k not in {r["metric"] for r in finding_rows}}}


def discrepancy_findings(rows: list[dict[str, Any]], pdf_provider: Any, ticker: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row["outcome"] == "mismatch_unresolved":
            groups.setdefault((row["period"], row["statement_scope"], row["source_a"]["announcement_key"]), []).append(row)
    findings = []
    for (period, scope, announcement), members in sorted(groups.items()):
        pdf = pdf_provider.statement_totals(ticker, members[0]["fiscal_year"]) if pdf_provider is not None else None
        items = [{"metric": r["metric"], "board_notice_value": r["source_a"]["value_published"],
                  "board_notice_unit": r["source_a"]["published_unit"],
                  "filed_value_thousand_twd": dm.text(dm.parse_decimal(r["source_b"]["value_twd"]) / 1000),
                  "difference_twd": r["difference"],
                  "difference_thousand_twd": dm.text(dm.parse_decimal(r["difference"]) / 1000)} for r in members]
        findings.append({
            "issue_id": "srcd_" + digest([ticker, period, scope, announcement, sorted(i["metric"] for i in items)])[:24],
            "ticker": ticker, "period": period, "fiscal_year": members[0]["fiscal_year"], "statement_scope": scope,
            "status": "mismatch_unresolved", "cause": "unverified", "items": items,
            "board_notice": {k: members[0]["source_a"][k] for k in ("announcement_key", "notice_published_at",
                                                                     "notice_sha256", "source_url")},
            "filed_report": {k: members[0]["source_b"][k] for k in ("filing_version_id", "artifact_sha256", "artifact_url",
                                                                     "artifact_evidence_status")},
            "audited_pdf": pdf_check(members, pdf),
            "explanation_limits": EXPLANATION_LIMITS, "routes_to_risk_score": False, "fraud_label": None,
            "review_status": "open_unresolved",
        })
    return findings


def reconcile(snapshot: InputSnapshot, backend: Any, *, pdf_provider: Any = None) -> dict[str, Any]:
    if snapshot.context.mode is not AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
        raise ModeNotSupportedError("analysis_mode_not_supported",
                                    "Source reconciliation runs only in CURRENT_EVIDENCE_RECONCILIATION.")
    rows = (compare_board_notices(snapshot) + compare_restatement_post_side(snapshot)
            + compare_summaries(backend, snapshot.ticker, snapshot.start_year, snapshot.end_year))
    findings = discrepancy_findings(rows, pdf_provider, snapshot.ticker)
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = counts.setdefault(row["comparison_type"], {"match": 0, "mismatch_unresolved": 0, "not_comparable": 0})
        bucket[row["outcome"]] += 1
    return {"method": {"method_id": METHOD_ID, "method_version": METHOD_VERSION,
                       "approval_status": "DRAFT_PENDING_METHOD_OWNER_REVIEW"},
            **snapshot.context.as_dict(), "ticker": snapshot.ticker, "input_digest": snapshot.input_digest,
            "status": "READY", "consistency": "INCONSISTENT" if findings else "CONSISTENT",
            "counts": counts, "comparisons": rows,
            "discrepancies": findings, "explanation_limits": EXPLANATION_LIMITS,
            "routes_to_risk_score": False}
