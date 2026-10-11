"""Beneish (1999) eight-variable M-Score (unweighted probit, Table 3 Panel A), exact Decimal reproduction.

Component definitions follow Table 2 of the source (COMPUSTAT items in ``literature_method_registry``); inputs come
from the version-consistent period panel (``literature_inputs.Panel``). The published score is produced only when
all eight components are computable *and* the registry marks every coefficient and the transformation as
source-verified. Otherwise the result is ``not_computable`` (or ``model_formula_unverified``) with a descriptive
component panel; a partial sum is never reported as an M-Score. The original-sample cutoff (-1.78) is reported as a
US benchmark only and is never applied as a label.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.financial_research import literature_common as lc
from app.services.financial_research.literature_method_registry import (
    APPROVAL_STATUS,
    BENEISH_MODEL_ID,
    PAPER_SOURCES,
    coefficients,
    model_spec,
    verification_problems,
)

METHOD_VERSION = BENEISH_MODEL_ID
ONE = Decimal(1)
T, T1 = "t", "t-1"


def _dsri(v, _):
    now = lc.div(v[("receivables", T)], v[("sales", T)], "sales_t", positive=True)
    before = lc.div(v[("receivables", T1)], v[("sales", T1)], "sales_t-1", positive=True)
    return lc.div(now, before, "receivables_t-1/sales_t-1")


def _gmi(v, _):
    gm_now = lc.div(lc.sub(v[("sales", T)], v[("cogs", T)]), v[("sales", T)], "sales_t", positive=True)
    gm_before = lc.div(lc.sub(v[("sales", T1)], v[("cogs", T1)]), v[("sales", T1)], "sales_t-1", positive=True)
    return lc.div(gm_before, gm_now, "gross_margin_t")


def _aqi(v, _):
    quality = []
    for rel in (T, T1):
        hard = lc.div(lc.add(v[("current_assets", rel)], v[("ppe_net", rel)]), v[("total_assets", rel)],
                      f"total_assets_{rel}", positive=True)
        quality.append(lc.sub(ONE, hard))
    return lc.div(quality[0], quality[1], "asset_quality_t-1")


def _sgi(v, _):
    return lc.div(v[("sales", T)], v[("sales", T1)], "sales_t-1", positive=True)


def _depi(v, _):
    rates = [lc.div(v[("depreciation", rel)], lc.add(v[("depreciation", rel)], v[("ppe_net", rel)]),
                    f"depreciation_plus_ppe_{rel}", positive=True) for rel in (T, T1)]
    return lc.div(rates[1], rates[0], "depreciation_rate_t")


def _sgai(v, _):
    ratios = [lc.div(lc.add(v[("selling_expense", rel)], v[("administrative_expense", rel)]), v[("sales", rel)],
                     f"sales_{rel}", positive=True) for rel in (T, T1)]
    return lc.div(ratios[0], ratios[1], "sga_to_sales_t-1")


def _lvgi(v, _):
    ratios = [lc.div(lc.add(v[("long_term_debt", rel)], v[("current_liabilities", rel)]), v[("total_assets", rel)],
                     f"total_assets_{rel}", positive=True) for rel in (T, T1)]
    return lc.div(ratios[0], ratios[1], "leverage_t-1")


def _tata(v, _):
    def delta(metric):
        return lc.sub(v[(metric, T)], v[(metric, T1)])

    cash_delta = lc.add(delta("cash"), delta("short_term_investments"))  # COMPUSTAT #1 = cash and short-term investments
    accruals = lc.sub(lc.sub(lc.sub(delta("current_assets"), cash_delta),
                             lc.sub(lc.sub(delta("current_liabilities"), delta("current_maturities_ltd")),
                                    delta("income_tax_payable"))),
                      lc.add(v[("depreciation", T)], v[("amortization", T)]))
    return lc.div(accruals, v[("total_assets", T)], "total_assets_t", positive=True)


def _both(*metrics: str) -> list[tuple[str, str]]:
    return [(metric, rel) for metric in metrics for rel in (T, T1)]


COMPONENTS: dict[str, tuple[list[tuple[str, str]], Any]] = {
    "DSRI": (_both("receivables", "sales"), _dsri),
    "GMI": (_both("sales", "cogs"), _gmi),
    "AQI": (_both("current_assets", "ppe_net", "total_assets"), _aqi),
    "SGI": (_both("sales"), _sgi),
    "DEPI": (_both("depreciation", "ppe_net"), _depi),
    "SGAI": (_both("selling_expense", "administrative_expense", "sales"), _sgai),
    "LVGI": (_both("long_term_debt", "current_liabilities", "total_assets"), _lvgi),
    "TATA": (_both("current_assets", "cash", "short_term_investments", "current_liabilities",
                   "current_maturities_ltd", "income_tax_payable") + [("depreciation", T), ("amortization", T),
                                                                      ("total_assets", T)], _tata),
}


def score(values: dict[str, Decimal], spec: dict[str, Any] | None = None) -> dict[str, Any]:
    """M-Score and probit probability from eight component values (pure; used by golden tests)."""
    spec = spec or model_spec(BENEISH_MODEL_ID)
    problems = verification_problems(spec)
    if problems:
        return {"status": "model_formula_unverified", "score": None, "verification_problems": problems}
    intercept, coefs = coefficients(spec)
    if set(coefs) != set(COMPONENTS) or set(values) != set(COMPONENTS):
        return {"status": "model_formula_unverified", "score": None,
                "verification_problems": ["coefficient_set_does_not_match_the_eight_beneish_variables"]}
    m_score = lc.linear_index(intercept, coefs, values)
    probability, underflow = lc.normal_cdf(m_score)
    return {"status": "computed", "score": lc.q(m_score), "score_exact": lc.decimal_text(m_score),
            "probit_probability_original_sample": probability, "probability_underflow": underflow,
            "contributions": {name: lc.q(lc.mul(coefs[name], values[name])) for name in COMPONENTS},
            "intercept": lc.decimal_text(intercept)}


def evaluate(panel: Any, *, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = spec or model_spec(BENEISH_MODEL_ID)
    evaluated = lc.evaluate_components(panel, COMPONENTS)
    computed = [c for c in evaluated["components"] if c["status"] == "computed"]
    result: dict[str, Any] = {
        "model_id": BENEISH_MODEL_ID, "formula_version": spec["formula_version"], "paper_variant": spec["paper_variant"],
        "paper_doi": PAPER_SOURCES["beneish_1999"]["doi"], "approval_status": APPROVAL_STATUS,
        "components": evaluated["components"], "missing_inputs": evaluated["missing_inputs"],
        "component_coverage": {"computed": len(computed), "required": len(COMPONENTS)},
        "score": None, "score_kind": "probit_index_m_score", "numerical_precision": lc.NUMERICAL_PRECISION,
        "scaling_provenance": {"transformation": spec["transformation"], "benchmark": spec["benchmark"]},
    }
    if len(computed) < len(COMPONENTS):
        result.update(status="not_computable", component_panel_note=(
            "Descriptive component panel only: fewer than eight components are computable, so no M-Score is "
            "produced (a partial sum is not an M-Score)."))
        return result
    scored = score(evaluated["values"], spec)
    if scored["status"] != "computed":
        result.update(status=scored["status"], verification_problems=scored["verification_problems"])
        return result
    result.update(status="computed", **{k: v for k, v in scored.items() if k != "status"},
                  benchmark_reference={"original_us_sample_score_cutoff": spec["benchmark"]["score_cutoff"],
                                       "applicability": spec["benchmark"]["applicability"]})
    return result
