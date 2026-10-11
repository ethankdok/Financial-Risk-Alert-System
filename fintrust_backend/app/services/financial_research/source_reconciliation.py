"""M3 — current official cross-source reconciliation (CURRENT_EVIDENCE_RECONCILIATION only), v2.

Every dependency is frozen into the input snapshot first (``freeze_dependencies``): facts, restatement comparisons,
board-disclosed values, the TPEx summary rows and the audited-PDF statement evidence (identity, content SHA-256,
extracted lines, parser version, or an explicit ``unavailable`` record). ``reconcile`` then reads only the frozen
snapshot, so identical inputs give identical outputs and any changed dependency changes the input digest and run id.

Pairs are compared only on exact identity — fiscal period (full year), statement scope, accounting framework
(consistent with the fiscal year's regime), canonical metric (fixed, verified mappings only), convertible unit,
valid sign factor, compatible document version and verified source availability. Any uncertainty is fail-closed:

- ``match``: comparable and identical exact Decimal values;
- ``mismatch_unresolved``: comparable, values differ; the cause is not established by the sources;
- ``not_comparable``: one or more explicit ``reasons``; never a match or a mismatch.

A mismatch is evidence to review — never a proven restatement, misstatement or fraud — and it is never routed into
fraud labels or risk scores (``routes_to_risk_score`` is always false).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.case_knowledge import accounting_regime
from app.services.financial_research.input_snapshot import InputSnapshot, digest, safe_official_url
from app.services.financial_research.modes import AnalysisMode, AnalysisRequestError, ModeNotSupportedError
from app.services.financial_research.pdf_evidence import EXTRACTOR_VERSION, unavailable

METHOD_ID = "source_reconciliation"
METHOD_VERSION = "source_reconciliation_v2"
SUMMARY_VIEW_VERSION = "summary_view_v1"
BOARD_NOTICE_KIND = "annual_financial_report_board_approval"
EXPLANATION_LIMITS = (
    "The sources establish only that the stated figures differ. They do not state why. The difference is not "
    "described as a reclassification, correction, restatement, misstatement or fraud; no fraud label or risk score "
    "is derived from it.")
_SUMMARY_FIELDS = ("period", "fiscal_year", "report_period", "observation_role", "statement_scope",
                   "statement_scope_basis", "accounting_framework", "source_label", "source_metric_code",
                   "canonical_metric", "mapping_status", "normalized_value", "normalized_unit", "content_hash")


# ---------------------------------------------------------------------------------------------- frozen inputs
def summary_view(row: dict[str, Any]) -> dict[str, Any]:
    """Model-independent view of one TPEx summary row (no retrieval / creation metadata)."""
    return {**{key: row.get(key) for key in _SUMMARY_FIELDS}, "source_url": safe_official_url(row.get("source_url"))}


def freeze_dependencies(snapshot: InputSnapshot, backend: Any, pdf_provider: Any) -> InputSnapshot:
    """Freeze summary rows and the PDF evidence the reconciliation will use into the snapshot (and its digest)."""
    if snapshot.context.mode is not AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
        raise ModeNotSupportedError("analysis_mode_not_supported",
                                    "Reconciliation dependencies are frozen only in CURRENT_EVIDENCE_RECONCILIATION.")
    snapshot.summary_observations = sorted(
        (summary_view(row) for row in backend.list_summary_observations(snapshot.ticker)
         if snapshot.start_year <= row["fiscal_year"] <= snapshot.end_year
         and row["observation_role"] == "current_period" and row.get("canonical_metric")),
        key=lambda r: (r["fiscal_year"], r["period"], r["statement_scope"], r["source_metric_code"] or "",
                       r["canonical_metric"], r["content_hash"]))
    snapshot.dependency_versions = {"pdf_extractor": EXTRACTOR_VERSION, "summary_view": SUMMARY_VIEW_VERSION,
                                    "reconciliation_method": METHOD_VERSION}
    snapshot.reconciliation_frozen = True
    # PDF evidence is needed exactly for the fiscal years with an unresolved board-notice mismatch; that set is a
    # pure function of the frozen facts and notices, so the evidence set is deterministic.
    years: dict[int, str | None] = {}
    for row in compare_board_notices(snapshot):
        if row["outcome"] == "mismatch_unresolved":
            years[row["fiscal_year"]] = row["source_b"]["filing_version_type"]
    evidence = []
    for year, version_type in sorted(years.items()):
        if pdf_provider is None:
            evidence.append(unavailable(year, "pdf_evidence_not_available_in_this_deployment", xbrl_version_type=version_type))
        else:
            evidence.append(pdf_provider.statement_evidence(snapshot.ticker, year, xbrl_version_type=version_type))
    snapshot.pdf_evidence = evidence
    return snapshot


# ---------------------------------------------------------------------------------------------- comparisons
def _fact_index(snapshot: InputSnapshot) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {(f["period"], f["statement_scope"], f["metric_code"]): f for f in snapshot.facts}


def _outcome(a: Decimal | None, b: Decimal | None) -> str:
    if a is None or b is None:
        return "not_comparable"
    return "match" if a == b else "mismatch_unresolved"


def _fact_source(fact: dict[str, Any]) -> dict[str, Any]:
    return {"source_type": "filed_xbrl_fact", "fact_id": fact["fact_id"], "filing_version_id": fact["filing_version_id"],
            "filing_version_type": fact["filing_version_type"], "taxonomy_concept": fact.get("taxonomy_concept"),
            "accounting_framework": fact["accounting_framework"], "value_twd": fact["value"], "unit": fact["unit"],
            "artifact_sha256": fact.get("artifact_sha256"), "artifact_url": fact.get("artifact_url"),
            "artifact_evidence_status": fact["artifact_evidence_status"]}


def _common_reasons(ticker: str, *, period: str, fiscal_year: int, framework: str, fact: dict[str, Any]) -> list[str]:
    reasons = []
    if period != f"{fiscal_year}FY" or fact["period"] != period:
        reasons.append("period_not_same_full_year")
    if fact["accounting_framework"] in (None, "", "unknown"):
        reasons.append("filed_fact_framework_unknown")
    elif fact["accounting_framework"] != framework:
        reasons.append("framework_mismatch")
    expected = accounting_regime(ticker, fiscal_year)
    if expected is None or framework != expected:
        reasons.append("framework_inconsistent_with_fiscal_year_regime")
    return reasons


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
        reasons = _common_reasons(snapshot.ticker, period=value["period"], fiscal_year=value["fiscal_year"],
                                  framework=value["accounting_framework"], fact=fact)
        if value.get("disclosure_kind") != BOARD_NOTICE_KIND:
            reasons.append("notice_kind_not_annual_board_approval")
        if value.get("availability_status") != "verified":
            reasons.append("notice_availability_unverified")
        if fact["unit"] != value["normalized_unit"]:
            reasons.append("unit_mismatch")
        if fact["filing_version_type"] == "restated":
            reasons.append("filed_version_restated_vs_original_approval_notice")
        a, b = dm.parse_decimal(value["normalized_value"]), dm.parse_decimal(fact["value"])
        if a is None or b is None:
            reasons.append("value_missing")
        outcome = "not_comparable" if reasons else _outcome(a, b)
        rows.append({**base, "outcome": outcome, "reasons": reasons, "source_b": _fact_source(fact),
                     "difference": dm.text(dm.sub(a, b)) if outcome == "mismatch_unresolved" else None,
                     "difference_unit": value["normalized_unit"] if outcome == "mismatch_unresolved" else None})
    return rows


def compare_restatement_post_side(snapshot: InputSnapshot) -> list[dict[str, Any]]:
    """Post-restatement notice values vs the restated filed facts. Every mapped comparison row is reported; rows with
    no filed fact or any compatibility uncertainty are ``not_comparable`` with reasons. The pre side is a different
    version by construction and is never compared with the restated filing."""
    facts = _fact_index(snapshot)
    rows = []
    for comparison in snapshot.comparisons:
        metric = comparison["canonical_metric"]
        if not metric:
            continue
        source_a = {"source_type": "restatement_comparison_notice", "announcement_key": comparison["announcement_key"],
                    "notice_published_at": comparison["disclosed_at"], "notice_sha256": comparison["content_hash"],
                    "source_url": comparison.get("source_url"), "source_label": comparison["post_label"], "side": "post",
                    "value_published": comparison["post_restatement_value"], "published_unit": comparison["published_unit"],
                    "sign_factor": comparison["sign_factor"]}
        base = {"comparison_type": "restatement_notice_post_vs_restated_xbrl", "period": comparison["period"],
                "fiscal_year": comparison["fiscal_year"], "statement_scope": comparison["statement_scope"],
                "accounting_framework": comparison["accounting_framework"], "metric": metric}
        fact = facts.get((comparison["period"], comparison["statement_scope"], metric))
        if fact is None:
            rows.append({**base, "source_a": source_a, "source_b": None, "outcome": "not_comparable",
                         "reasons": ["no_filed_fact_same_period_scope_metric"], "difference": None})
            continue
        reasons = _common_reasons(snapshot.ticker, period=comparison["period"], fiscal_year=comparison["fiscal_year"],
                                  framework=comparison["accounting_framework"], fact=fact)
        if fact["filing_version_type"] != "restated":
            reasons.append("filing_version_not_restated")
        if comparison.get("availability_status") != "verified":
            reasons.append("notice_availability_unverified")
        if comparison["published_unit"] not in dm.UNIT_SCALE:
            reasons.append("notice_unit_not_convertible")
        if fact["unit"] != "TWD":
            reasons.append("unit_mismatch")
        if comparison["sign_factor"] not in (1, -1):
            reasons.append("sign_factor_invalid")
        if not comparison.get("post_label"):
            reasons.append("post_side_label_missing")
        post = dm.parse_decimal(comparison["post_restatement_value"])
        if post is None:
            reasons.append("post_side_value_missing")
        post_twd = None
        if not reasons:
            post_twd = dm.mul(dm.to_twd(post, comparison["published_unit"]), Decimal(comparison["sign_factor"]))
        source_a["value_twd"] = dm.text(post_twd)
        outcome = "not_comparable" if reasons else _outcome(post_twd, dm.parse_decimal(fact["value"]))
        rows.append({**base, "source_a": source_a, "source_b": _fact_source(fact), "outcome": outcome, "reasons": reasons,
                     "difference": dm.text(dm.sub(post_twd, dm.parse_decimal(fact["value"])))
                     if outcome == "mismatch_unresolved" else None})
    return rows


def compare_summaries(snapshot: InputSnapshot) -> list[dict[str, Any]]:
    """TPEx summary workbooks state no scope; the archive infers it by matching XBRL revenue, so comparing them back
    to XBRL would be circular. They are recorded as not_comparable (scope not declared by the source)."""
    return [{"comparison_type": "tpex_summary_vs_filed_xbrl", "period": row["period"], "fiscal_year": row["fiscal_year"],
             "statement_scope": row["statement_scope"], "accounting_framework": row["accounting_framework"],
             "metric": row["canonical_metric"],
             "source_a": {"source_type": "tpex_summary_workbook", "source_label": row["source_label"],
                          "value_normalized": row["normalized_value"], "normalized_unit": row["normalized_unit"],
                          "source_sha256": row["content_hash"], "source_url": row["source_url"],
                          "statement_scope_basis": row["statement_scope_basis"]},
             "source_b": None, "outcome": "not_comparable",
             "reasons": ["scope_inferred_from_value_match_not_declared_by_source"]} for row in snapshot.summary_observations]


# ---------------------------------------------------------------------------------------------- PDF and findings
def pdf_check(finding_rows: list[dict[str, Any]], pdf: dict[str, Any] | None) -> dict[str, Any]:
    """Equality with the audited PDF is claimed only when the evidence was extracted and its unit, fiscal year and
    consolidated scope are all verified; otherwise the check is ``not_comparable`` with the failing reasons."""
    if pdf is None or pdf.get("status") != "extracted":
        reason = (pdf or {}).get("reason", "pdf_evidence_not_frozen")
        return {"status": "unavailable", "reason": reason, "checks": [
            {"metric": r["metric"], "status": "not_comparable", "reasons": [reason]} for r in finding_rows]}
    failing = [f"{name}:{state}" for name, state in pdf["checks"].items() if state != "verified"]
    checks = []
    for row in finding_rows:
        total = pdf["totals"].get(row["metric"])
        if failing or total is None:
            checks.append({"metric": row["metric"], "status": "not_comparable",
                           "reasons": failing + ([] if total else ["account_code_line_not_found"]),
                           "pdf_line": total["line"] if total else None,
                           "equals_filed_xbrl": None, "equals_board_notice": None})
            continue
        pdf_twd = dm.to_twd(dm.parse_decimal(total["value_thousand_twd"]), "TWD_thousand")
        checks.append({"metric": row["metric"], "status": "compared", "pdf_value_thousand_twd": total["value_thousand_twd"],
                       "account_code": total["account_code"], "pdf_line": total["line"],
                       "equals_filed_xbrl": pdf_twd == dm.parse_decimal(row["source_b"]["value_twd"]),
                       "equals_board_notice": pdf_twd == dm.parse_decimal(row["source_a"]["value_normalized"])})
    return {"status": "extracted", "identity_checks": pdf["checks"], "filing_version_id": pdf["filing_version_id"],
            "filing_version_type": pdf["filing_version_type"], "selection_basis": pdf["selection_basis"],
            "pdf_sha256": pdf["pdf_sha256"], "content_sha256_verified": pdf["content_sha256_verified"],
            "pdf_page_index": pdf["pdf_page_index"], "printed_page_label": pdf["printed_page_label"], "unit": pdf["unit"],
            "reporting_roc_year": pdf["reporting_roc_year"], "extractor": pdf["extractor"],
            "extractor_version": pdf["extractor_version"], "source_url": safe_official_url(pdf["source_url"]),
            "artifact_available_at": pdf["artifact_available_at"],
            "artifact_availability_status": pdf["artifact_availability_status"], "checks": checks,
            "other_lines": {k: v for k, v in pdf["totals"].items() if k not in {r["metric"] for r in finding_rows}}}


def discrepancy_findings(rows: list[dict[str, Any]], snapshot: InputSnapshot) -> list[dict[str, Any]]:
    evidence = {e["fiscal_year"]: e for e in snapshot.pdf_evidence}
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if row["outcome"] == "mismatch_unresolved" and row["comparison_type"] == "board_notice_vs_filed_xbrl":
            groups.setdefault((row["period"], row["statement_scope"], row["source_a"]["announcement_key"]), []).append(row)
    findings = []
    for (period, scope, announcement), members in sorted(groups.items()):
        items = [{"metric": r["metric"], "board_notice_value": r["source_a"]["value_published"],
                  "board_notice_unit": r["source_a"]["published_unit"],
                  "filed_value_thousand_twd": dm.text(dm.parse_decimal(r["source_b"]["value_twd"]) / 1000),
                  "difference_twd": r["difference"],
                  "difference_thousand_twd": dm.text(dm.parse_decimal(r["difference"]) / 1000)}
                 for r in sorted(members, key=lambda r: r["metric"])]
        findings.append({
            "issue_id": "srcd_" + digest([snapshot.ticker, period, scope, announcement, sorted(i["metric"] for i in items)])[:24],
            "ticker": snapshot.ticker, "period": period, "fiscal_year": members[0]["fiscal_year"], "statement_scope": scope,
            "status": "mismatch_unresolved", "cause": "unverified", "items": items,
            "board_notice": {k: members[0]["source_a"][k] for k in ("announcement_key", "notice_published_at",
                                                                     "notice_sha256", "source_url")},
            "filed_report": {k: members[0]["source_b"][k] for k in ("filing_version_id", "filing_version_type",
                                                                     "artifact_sha256", "artifact_url",
                                                                     "artifact_evidence_status")},
            "audited_pdf": pdf_check(sorted(members, key=lambda r: r["metric"]), evidence.get(members[0]["fiscal_year"])),
            "explanation_limits": EXPLANATION_LIMITS, "routes_to_risk_score": False, "fraud_label": None,
            "review_status": "open_unresolved",
        })
    return findings


def consistency(counts: dict[str, dict[str, int]]) -> str:
    """INCONSISTENT if any comparable pair differs; CONSISTENT only if at least one pair was comparable and all
    comparable pairs match; otherwise INCONCLUSIVE_NOT_COMPARABLE (nothing could be compared)."""
    mismatches = sum(c["mismatch_unresolved"] for c in counts.values())
    matches = sum(c["match"] for c in counts.values())
    return "INCONSISTENT" if mismatches else "CONSISTENT" if matches else "INCONCLUSIVE_NOT_COMPARABLE"


def reconcile(snapshot: InputSnapshot) -> dict[str, Any]:
    if snapshot.context.mode is not AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
        raise ModeNotSupportedError("analysis_mode_not_supported",
                                    "Source reconciliation runs only in CURRENT_EVIDENCE_RECONCILIATION.")
    if not snapshot.reconciliation_frozen:
        raise AnalysisRequestError("reconciliation_inputs_not_frozen",
                                   "freeze_dependencies() must run before reconcile(); no unfrozen source is queried.")
    rows = compare_board_notices(snapshot) + compare_restatement_post_side(snapshot) + compare_summaries(snapshot)
    findings = discrepancy_findings(rows, snapshot)
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = counts.setdefault(row["comparison_type"], {"match": 0, "mismatch_unresolved": 0, "not_comparable": 0})
        bucket[row["outcome"]] += 1
    return {"method": {"method_id": METHOD_ID, "method_version": METHOD_VERSION,
                       "approval_status": "DRAFT_PENDING_METHOD_OWNER_REVIEW",
                       "dependency_versions": snapshot.dependency_versions},
            **snapshot.context.as_dict(), "ticker": snapshot.ticker, "input_digest": snapshot.input_digest,
            "dependency_digests": snapshot.dependency_digests(),
            "status": "READY", "consistency": consistency(counts),
            "counts": counts, "comparisons": rows,
            "discrepancies": findings, "explanation_limits": EXPLANATION_LIMITS,
            "routes_to_risk_score": False}
