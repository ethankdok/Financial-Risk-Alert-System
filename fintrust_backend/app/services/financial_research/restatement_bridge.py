"""M1 — official pre/post restatement bridge (FY2011–FY2015) from the 2016-11-13 MOPS comparison notices.

Unit of analysis: (ticker, fiscal_year, statement_scope, accounting_framework, source label, announcement, side).
Each comparison row is used exactly as the official notice states it; pairs are formed only *within* one row (same
announcement, scope, year, statement and label). Values are sign-normalized with the row's own ``sign_factor`` and
converted from thousand TWD to TWD. ``delta = post − pre``. A percentage change is reported only when the
denominator is stable (see ``denominator_status``).

The pre side is "as previously reported according to the 2016 notice" — not proven to be the first-published filing.
Results are retrospective descriptive findings (hindsight=true when computed in RETROSPECTIVE_FORENSIC).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.case_knowledge import accounting_regime, knowledge
from app.services.financial_research.input_snapshot import InputSnapshot, digest
from app.services.financial_research.modes import AnalysisMode

METHOD_ID = "restatement_bridge"
METHOD_VERSION = "restatement_bridge_v1"
METHOD_STATUS = "DRAFT_PENDING_METHOD_OWNER_REVIEW"
EXPECTED_BASELINE_ROWS = 158  # Phase 2C approved baseline (verified, not a target)
# DRAFT parameter (method owner to approve): a pre value smaller than this share of the same notice/scope/year
# pre-restatement revenue is treated as a near-zero denominator.
NEAR_ZERO_SHARE_OF_REVENUE = Decimal("0.01")
PRE_SIDE_SEMANTICS = "pre_side_as_disclosed_in_2016"
BRIDGE_METRICS = ("revenue", "cost_of_goods_sold", "gross_profit", "operating_income", "net_income")
BALANCE_METRICS = ("current_assets", "total_assets", "current_liabilities", "total_liabilities", "equity")
MARGINS = {
    "gross_margin": ("gross_profit", "revenue"),
    "cogs_sales_ratio": ("cost_of_goods_sold", "revenue"),
    "operating_margin": ("operating_income", "revenue"),
    "net_margin": ("net_income", "revenue"),
}
INVENTORY_NOTE = ("The 2016-11-13 comparison notices contain no inventory line; inventory-related before/after "
                  "comparisons are not computable from official restatement disclosures.")
WARNING = ("依 2016-11-13 公告回溯重述：重編前後數值於 2016 年 11 月才公開，不可作為 2016-05-13 以前的預警特徵。"
           " Published retrospectively in Nov 2016; not usable as pre-May-2016 early-warning input.")


def _value(raw: Any, unit: str, sign: int) -> Decimal | None:
    parsed = dm.parse_decimal(raw)
    if parsed is None:
        return None
    return dm.mul(dm.to_twd(parsed, unit), Decimal(sign))


def denominator_status(pre: Decimal | None, post: Decimal | None, revenue_pre: Decimal | None) -> str:
    if pre is None or post is None:
        return "missing_side"
    if pre == 0:
        return "zero_denominator"
    if post != 0 and (pre > 0) != (post > 0):
        return "sign_reversal"
    if revenue_pre is None:
        return "stability_unknown_no_revenue_reference"
    if abs(pre) < dm.mul(abs(revenue_pre), NEAR_ZERO_SHARE_OF_REVENUE):
        return "near_zero_denominator"
    return "stable"


def comparison_key(row: dict[str, Any]) -> str:
    return "rcmp_" + digest([row["announcement_key"], row["period"], row["statement_scope"], row["statement_type"],
                             row["pre_label"], row["post_label"]])[:24]


def bridge_rows(comparisons: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    revenue_pre: dict[tuple[str, str, str], Decimal | None] = {}
    for row in comparisons:
        if row["canonical_metric"] == "revenue":
            revenue_pre[(row["announcement_key"], row["period"], row["statement_scope"])] = _value(
                row["pre_restatement_value"], row["published_unit"], row["sign_factor"])
    result = []
    for row in comparisons:
        unit, sign = row["published_unit"], int(row["sign_factor"])
        pre_raw, post_raw = dm.parse_decimal(row["pre_restatement_value"]), dm.parse_decimal(row["post_restatement_value"])
        diff_raw = dm.parse_decimal(row["difference"])
        pre, post = _value(row["pre_restatement_value"], unit, sign), _value(row["post_restatement_value"], unit, sign)
        delta = dm.sub(post, pre) if pre is not None and post is not None else None
        status = denominator_status(pre, post, revenue_pre.get((row["announcement_key"], row["period"], row["statement_scope"])))
        delta_pct = dm.ratio_text(delta, abs(pre)) if status == "stable" and delta is not None else None
        if pre_raw is None or post_raw is None or diff_raw is None:
            difference_check = "not_checkable"
        else:
            difference_check = "consistent" if dm.sub(post_raw, pre_raw) == diff_raw else "inconsistent"
        expected = accounting_regime(ticker, row["fiscal_year"])
        result.append({
            "comparison_key": comparison_key(row), "announcement_key": row["announcement_key"],
            "notice_published_at": row["disclosed_at"], "notice_sha256": row["content_hash"],
            "source_url": row.get("source_url"), "period": row["period"], "fiscal_year": row["fiscal_year"],
            "statement_scope": row["statement_scope"], "accounting_framework": row["accounting_framework"],
            "regime_check": "consistent" if expected == row["accounting_framework"] else "inconsistent",
            "statement_type": row["statement_type"], "source_label": row["pre_label"] or row["post_label"],
            "source_label_pre": row["pre_label"], "source_label_post": row["post_label"],
            "label_changed": (row["pre_label"] or "") != (row["post_label"] or ""),
            "canonical_metric": row["canonical_metric"], "sign_factor": sign, "published_unit": unit,
            "notice_reported_pre": row["pre_restatement_value"], "notice_reported_post": row["post_restatement_value"],
            "notice_reported_difference": row["difference"], "difference_check": difference_check,
            "pre_twd": dm.text(pre), "post_twd": dm.text(post), "delta_twd": dm.text(delta), "delta_pct": delta_pct,
            "denominator_status": status, "pre_side_semantics": PRE_SIDE_SEMANTICS,
            "row_verification": row["availability_status"],
        })
    return result


def _margin(components: dict[str, dict[str, Any]], side: str, numerator: str, denominator: str) -> dict[str, Any]:
    num, den = components.get(numerator), components.get(denominator)
    if num is None or den is None:
        missing = [m for m, r in ((numerator, num), (denominator, den)) if r is None]
        return {"status": "not_computable", "value": None, "missing_reasons": [f"missing_component:{m}" for m in missing]}
    n, d = dm.parse_decimal(num[f"{side}_twd"]), dm.parse_decimal(den[f"{side}_twd"])
    if n is None or d is None:
        return {"status": "not_computable", "value": None, "missing_reasons": ["missing_side_value"]}
    if d == 0:
        return {"status": "not_computable", "value": None, "missing_reasons": ["zero_denominator"]}
    if d < 0:
        return {"status": "not_computable", "value": None, "missing_reasons": ["negative_denominator"]}
    return {"status": "computed", "value": dm.ratio_text(n, d), "numerator_twd": dm.text(n), "denominator_twd": dm.text(d),
            "missing_reasons": []}


def year_bridges(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["period"], row["statement_scope"], row["announcement_key"]), []).append(row)
    result = []
    for (period, scope, announcement), members in sorted(groups.items()):
        mapped = {r["canonical_metric"]: r for r in members if r["canonical_metric"]}
        get = lambda m, side: dm.parse_decimal(mapped[m][f"{side}_twd"]) if m in mapped else None  # noqa: E731
        identity = {}
        for side in ("pre", "post"):
            rev, cogs, gp = get("revenue", side), get("cost_of_goods_sold", side), get("gross_profit", side)
            identity[side] = ("not_checkable" if None in (rev, cogs, gp)
                              else "holds" if dm.sub(rev, cogs) == gp else "does_not_hold")
        margins = {}
        for name, (numerator, denominator) in MARGINS.items():
            pre, post = _margin(mapped, "pre", numerator, denominator), _margin(mapped, "post", numerator, denominator)
            change = None
            if pre["status"] == post["status"] == "computed":
                change = format(dm.sub(dm.parse_decimal(post["value"]), dm.parse_decimal(pre["value"])), "f")
            margins[name] = {"pre": pre, "post": post, "change": change,
                             "status": "computed" if change is not None else "not_computable"}
        deltas = {m: dm.parse_decimal(mapped[m]["delta_twd"]) if m in mapped else None
                  for m in BRIDGE_METRICS + BALANCE_METRICS}
        decomposition = {"delta_revenue_twd": dm.text(deltas["revenue"]),
                         "delta_cost_of_goods_sold_twd": dm.text(deltas["cost_of_goods_sold"]),
                         "delta_gross_profit_twd": dm.text(deltas["gross_profit"]),
                         "delta_operating_income_twd": dm.text(deltas["operating_income"]),
                         "delta_net_income_twd": dm.text(deltas["net_income"])}
        if None not in (deltas["revenue"], deltas["cost_of_goods_sold"], deltas["gross_profit"]):
            decomposition["gross_profit_bridge_check"] = (
                "holds" if dm.sub(deltas["revenue"], deltas["cost_of_goods_sold"]) == deltas["gross_profit"] else "does_not_hold")
        if None not in (deltas["operating_income"], deltas["gross_profit"]):
            decomposition["residual_operating_items_twd"] = dm.text(dm.sub(deltas["operating_income"], deltas["gross_profit"]))
        if None not in (deltas["net_income"], deltas["operating_income"]):
            decomposition["residual_non_operating_and_tax_twd"] = dm.text(dm.sub(deltas["net_income"], deltas["operating_income"]))
        result.append({
            "period": period, "fiscal_year": members[0]["fiscal_year"], "statement_scope": scope,
            "announcement_key": announcement, "notice_sha256": members[0]["notice_sha256"],
            "notice_published_at": members[0]["notice_published_at"],
            "accounting_framework": members[0]["accounting_framework"], "rows": len(members),
            "metrics": {m: {k: mapped[m][k] for k in ("pre_twd", "post_twd", "delta_twd", "delta_pct", "denominator_status",
                                                     "source_label", "comparison_key")}
                        for m in BRIDGE_METRICS + BALANCE_METRICS if m in mapped},
            "accounting_identity_gross_profit": identity, "margins": margins, "decomposition": decomposition,
            "inventory": {"status": "not_computable", "missing_reasons": ["inventory_line_not_in_restatement_notice"]},
        })
    return result


def heatmap(rows: list[dict[str, Any]]) -> dict[str, Any]:
    years = sorted({r["fiscal_year"] for r in rows})
    cells = []
    for row in rows:
        if row["canonical_metric"]:
            cells.append({"statement_scope": row["statement_scope"], "metric": row["canonical_metric"],
                          "fiscal_year": row["fiscal_year"], "accounting_framework": row["accounting_framework"],
                          "delta_twd": row["delta_twd"], "delta_pct": row["delta_pct"],
                          "denominator_status": row["denominator_status"], "comparison_key": row["comparison_key"]})
    regimes = sorted({(r["fiscal_year"], r["accounting_framework"]) for r in rows})
    breaks = [b for (a, fa), (b, fb) in zip(regimes, regimes[1:]) if fa != fb]
    return {"fiscal_years": years, "cells": cells, "accounting_regime_break_before_years": breaks,
            "note": "Cells compare figures within one notice/scope/year; years across a regime break are not comparable."}


def hypothesis_links(bridges: list[dict[str, Any]], ticker: str) -> list[dict[str, Any]]:
    case = knowledge(ticker) or {}
    links = []
    for hypothesis in case.get("hypotheses", []):
        observations = []
        for bridge in bridges:
            for metric, direction in hypothesis["expected_restatement_direction"].items():
                cell = bridge["metrics"].get(metric)
                delta = dm.parse_decimal(cell["delta_twd"]) if cell else None
                if delta is None:
                    continue
                observed = "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged"
                observations.append({"period": bridge["period"], "statement_scope": bridge["statement_scope"],
                                     "metric": metric, "expected_direction": direction, "observed_direction": observed,
                                     "delta_twd": cell["delta_twd"], "direction_consistent": observed == direction})
        links.append({"hypothesis_id": hypothesis["hypothesis_id"], "statement": hypothesis["statement"],
                      "source_class": case["hypothesis_source"]["source_class"],
                      "legal_status": case["hypothesis_source"]["legal_status"],
                      "linkage_status": "descriptive_direction_only" if observations else "no_directional_expectation",
                      "observations": observations,
                      "interpretation_limit": ("Direction consistency is descriptive. It does not establish the mechanism, "
                                               "intent or legal responsibility, and is not a fraud label.")})
    return links


def build_bridge(snapshot: InputSnapshot, *, scope: str = "all") -> dict[str, Any]:
    if scope not in {"all", "consolidated", "individual"}:
        raise ValueError("scope must be all, consolidated or individual")
    context = snapshot.context
    rows = bridge_rows(snapshot.comparisons, snapshot.ticker)
    all_rows = len(rows)
    if scope != "all":
        rows = [r for r in rows if r["statement_scope"] == scope]
    bridges = year_bridges(rows)
    integrity = {
        "rows_total": all_rows,
        "expected_baseline_rows": EXPECTED_BASELINE_ROWS,
        "baseline_check": ("not_applicable_strict_subset" if context.mode is AnalysisMode.STRICT_AS_OF else
                           "match" if all_rows == EXPECTED_BASELINE_ROWS else "mismatch"),
        "difference_inconsistent": sum(r["difference_check"] == "inconsistent" for r in rows),
        "regime_inconsistent": sum(r["regime_check"] == "inconsistent" for r in rows),
        "identity_failures": sum(b["accounting_identity_gross_profit"][s] == "does_not_hold"
                                 for b in bridges for s in ("pre", "post")),
    }
    inconsistent = integrity["difference_inconsistent"] or integrity["regime_inconsistent"] or integrity["baseline_check"] == "mismatch"
    if not rows:
        status = "insufficient_point_in_time_evidence" if context.mode is AnalysisMode.STRICT_AS_OF else "not_computable"
    else:
        status = "INCONSISTENT" if inconsistent else "READY"
    return {
        "method": {"method_id": METHOD_ID, "method_version": METHOD_VERSION, "approval_status": METHOD_STATUS,
                   "near_zero_share_of_revenue": str(NEAR_ZERO_SHARE_OF_REVENUE),
                   "delta_definition": "post − pre (TWD, sign-normalized with the row sign_factor)",
                   "percent_definition": "delta / |pre| when denominator_status == stable"},
        **context.as_dict(), "ticker": snapshot.ticker, "scope": scope, "status": status,
        "warning": WARNING, "inventory_note": INVENTORY_NOTE, "input_digest": snapshot.input_digest,
        "integrity": integrity, "rows": rows, "year_bridges": bridges, "heatmap": heatmap(rows),
        "hypothesis_links": hypothesis_links(bridges, snapshot.ticker) if context.mode is AnalysisMode.RETROSPECTIVE_FORENSIC else [],
        "interpretation": ("Retrospective descriptive forensic reconstruction of officially disclosed restatements. "
                           "Not a single-case AUC, not predictive success and not a fraud determination."),
    }
