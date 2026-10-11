"""Dechow, Ge, Larson & Sloan (2011) Table 7 Model 1 F-Score, exact Decimal reproduction.

Seven variables per Table 3 (CAR pp. 35-38); coefficients from Table 7 Panel A Model 1 (pp. 55-56); probability
``e^PV / (1 + e^PV)`` (numerically stable, Decimal) and F-Score = probability / 0.0037 (p. 61). ``ch_cs`` and
``ch_roa`` need t-2 balances. RSST accruals use the Richardson et al. (2005) WC / NCO / FIN decomposition, never
net income minus operating cash flow. ``issue`` is 1 only with positive evidence of long-term-debt or share issuance
in year t; without such evidence it is UNKNOWN (never 0), so the score is not computable.

The logistic output is the original US-sample model's value and the F-Score is scaled by that sample's base rate;
neither is a Taiwan-calibrated probability. No recalibration is performed.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research import literature_common as lc
from app.services.financial_research.literature_method_registry import (
    APPROVAL_STATUS,
    DECHOW_MODEL_ID,
    PAPER_SOURCES,
    coefficients,
    model_spec,
    verification_problems,
)

METHOD_VERSION = DECHOW_MODEL_ID
T, T1, T2 = "t", "t-1", "t-2"
ISSUANCE_METRICS = ("long_term_debt_issued", "stock_issued")


def _avg_assets(v, rel_now: str, rel_before: str) -> Decimal:
    return lc.avg(v[("total_assets", rel_now)], v[("total_assets", rel_before)])


def _rsst(v, _):
    def che(rel):
        return lc.add(v[("cash", rel)], v[("short_term_investments", rel)])

    def dlc(rel):
        return lc.add(v[("short_term_debt", rel)], v[("current_maturities_ltd", rel)])

    def wc(rel):
        return lc.sub(lc.sub(v[("current_assets", rel)], che(rel)), lc.sub(v[("current_liabilities", rel)], dlc(rel)))

    def nco(rel):
        operating_assets = lc.sub(lc.sub(v[("total_assets", rel)], v[("current_assets", rel)]),
                                  v[("investments_and_advances", rel)])
        operating_liabilities = lc.sub(lc.sub(v[("total_liabilities", rel)], v[("current_liabilities", rel)]),
                                       v[("long_term_debt", rel)])
        return lc.sub(operating_assets, operating_liabilities)

    def fin(rel):
        financial_assets = lc.add(v[("short_term_investments", rel)], v[("investments_and_advances", rel)])
        financial_liabilities = lc.add(v[("long_term_debt", rel)], dlc(rel), v[("preferred_stock", rel)])
        return lc.sub(financial_assets, financial_liabilities)

    change = lc.add(lc.sub(wc(T), wc(T1)), lc.sub(nco(T), nco(T1)), lc.sub(fin(T), fin(T1)))
    return lc.div(change, _avg_assets(v, T, T1), "average_total_assets_t", positive=True)


def _ch_rec(v, _):
    return lc.div(lc.sub(v[("receivables", T)], v[("receivables", T1)]), _avg_assets(v, T, T1),
                  "average_total_assets_t", positive=True)


def _ch_inv(v, _):
    return lc.div(lc.sub(v[("inventory", T)], v[("inventory", T1)]), _avg_assets(v, T, T1),
                  "average_total_assets_t", positive=True)


def _soft_assets(v, _):
    cash = lc.add(v[("cash", T)], v[("short_term_investments", T)])  # COMPUSTAT #1
    return lc.div(lc.sub(lc.sub(v[("total_assets", T)], v[("ppe_net", T)]), cash), v[("total_assets", T)],
                  "total_assets_t", positive=True)


def _ch_cs(v, _):
    cash_sales_t = lc.sub(v[("sales", T)], lc.sub(v[("receivables", T)], v[("receivables", T1)]))
    cash_sales_t1 = lc.sub(v[("sales", T1)], lc.sub(v[("receivables", T1)], v[("receivables", T2)]))
    return lc.div(lc.sub(cash_sales_t, cash_sales_t1), cash_sales_t1, "cash_sales_t-1", positive=True)


def _ch_roa(v, _):
    roa_t = lc.div(v[("earnings", T)], _avg_assets(v, T, T1), "average_total_assets_t", positive=True)
    roa_t1 = lc.div(v[("earnings", T1)], _avg_assets(v, T1, T2), "average_total_assets_t-1", positive=True)
    return lc.sub(roa_t, roa_t1)


def _issue(panel: Any) -> tuple[Decimal | None, dict[str, Any]]:
    """Issuance indicator from each issuance line separately (a net sum could mask a positive issuance line)."""
    evidence, problems = [], []
    for metric in ISSUANCE_METRICS:
        item = panel.value(metric, T)
        if item.status != "computed":
            problems.append({"metric": metric, "status": item.status, "reasons": item.reasons})
            continue
        for obs in item.observations:
            amount = dm.parse_decimal(obs["value"])
            if amount is not None and amount > 0:
                evidence.append({"metric": metric, "line_key": obs["line_key"], "source_concept": obs["source_concept"],
                                 "value_twd": obs["value"], "observation_id": obs["observation_id"],
                                 "raw_sha256": obs["raw_sha256"], "locator": obs["locator"]})
    entry = {"variable": "issue", "inputs": [], "evidence": evidence, "warnings": []}
    if evidence:
        entry.update(status="computed", value="1", value_exact="1", reasons=[],
                     basis="positive issuance proceeds / increase reported in the year-t cash-flow statement")
        return Decimal(1), entry
    entry.update(status="not_computable", value=None,
                 reasons=[lc.reason("issuance_absence_not_evidenced",
                                    detail="no positive issuance line in year t; absence is UNKNOWN, not 0")]
                 + [lc.reason(p["status"], metric=p["metric"]) for p in problems])
    return None, entry


COMPONENTS: dict[str, tuple[list[tuple[str, str]], Any]] = {
    "rsst_acc": ([(m, r) for m in ("current_assets", "cash", "short_term_investments", "current_liabilities",
                                   "short_term_debt", "current_maturities_ltd", "total_assets", "investments_and_advances",
                                   "total_liabilities", "long_term_debt", "preferred_stock") for r in (T, T1)], _rsst),
    "ch_rec": ([(m, r) for m in ("receivables", "total_assets") for r in (T, T1)], _ch_rec),
    "ch_inv": ([(m, r) for m in ("inventory", "total_assets") for r in (T, T1)], _ch_inv),
    "soft_assets": ([("total_assets", T), ("ppe_net", T), ("cash", T), ("short_term_investments", T)], _soft_assets),
    "ch_cs": ([("sales", T), ("sales", T1), ("receivables", T), ("receivables", T1), ("receivables", T2)], _ch_cs),
    "ch_roa": ([("earnings", T), ("earnings", T1), ("total_assets", T), ("total_assets", T1), ("total_assets", T2)],
               _ch_roa),
}
VARIABLES = (*COMPONENTS, "issue")


def score(values: dict[str, Decimal], spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """Predicted value, probability and F-Score from seven variable values (pure; used by golden tests)."""
    spec = spec or model_spec(DECHOW_MODEL_ID)
    problems = verification_problems(spec)
    if problems:
        return {"status": "model_formula_unverified", "score": None, "verification_problems": problems}
    intercept, coefs = coefficients(spec)
    if set(coefs) != set(VARIABLES) or set(values) != set(VARIABLES):
        return {"status": "model_formula_unverified", "score": None,
                "verification_problems": ["coefficient_set_does_not_match_the_seven_model1_variables"]}
    predicted = lc.linear_index(intercept, coefs, values)
    probability = lc.logistic(predicted)
    base_rate = Decimal(spec["scaling"]["unconditional_probability"])
    f_score = lc.div(probability, base_rate, "unconditional_probability", positive=True)
    return {"status": "computed", "predicted_value": lc.q(predicted), "predicted_value_exact": lc.decimal_text(predicted),
            "probability_original_model": lc.q(probability), "probability_exact": lc.decimal_text(probability),
            "score": lc.q(f_score), "score_exact": lc.decimal_text(f_score),
            "unconditional_probability": spec["scaling"]["unconditional_probability"],
            "contributions": {name: lc.q(lc.mul(coefs[name], values[name])) for name in VARIABLES},
            "intercept": lc.decimal_text(intercept)}


def evaluate(panel: Any, *, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = spec or model_spec(DECHOW_MODEL_ID)
    evaluated = lc.evaluate_components(panel, COMPONENTS)
    issue_value, issue_entry = _issue(panel)
    components = evaluated["components"] + [issue_entry]
    values = dict(evaluated["values"])
    missing = list(evaluated["missing_inputs"])
    if issue_value is not None:
        values["issue"] = issue_value
    else:
        missing.append({"component": "issue", "metric": "issuance_evidence", "relative_period": T,
                        "fiscal_year": panel.year, "status": "issuance_absence_not_evidenced",
                        "reasons": [r["code"] for r in issue_entry["reasons"]]})
    computed = [c for c in components if c["status"] == "computed"]
    result: dict[str, Any] = {
        "model_id": DECHOW_MODEL_ID, "formula_version": spec["formula_version"], "paper_variant": spec["paper_variant"],
        "paper_doi": PAPER_SOURCES["dechow_2011"]["doi"], "approval_status": APPROVAL_STATUS,
        "components": components, "missing_inputs": missing,
        "component_coverage": {"computed": len(computed), "required": len(VARIABLES)},
        "score": None, "score_kind": "f_score_scaled_probability", "numerical_precision": lc.NUMERICAL_PRECISION,
        "scaling_provenance": {"transformation": spec["transformation"], "scaling": spec["scaling"],
                               "benchmark": spec["benchmark"]},
    }
    if len(computed) < len(VARIABLES):
        result.update(status="not_computable", component_panel_note=(
            "Descriptive component panel only: not all seven Model 1 variables are computable, so no F-Score is "
            "produced."))
        return result
    scored = score(values, spec)
    if scored["status"] != "computed":
        result.update(status=scored["status"], verification_problems=scored["verification_problems"])
        return result
    result.update(status="computed", **{k: v for k, v in scored.items() if k != "status"},
                  benchmark_reference={"f_score_one": spec["benchmark"]["f_score_one"],
                                       "applicability": spec["benchmark"]["applicability"]})
    return result
