"""Literature-model readiness gates (Beneish 1999 M-Score, Dechow et al. 2011 F-Score, accrual panels).

These gates decide whether a *published* model could be reproduced from authentic, complete inputs. No coefficients
are shipped: even with complete inputs a score would require a verified formula/coefficient version approved by the
method owner, and US-calibrated thresholds are never presented as Taiwan fraud probabilities. With missing inputs the
full model is ``not_computable`` and no partial score is produced. Individually computable components are reported
as descriptive indices only.
"""

from __future__ import annotations

from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.feature_registry import APPROVAL_STATUS
from app.services.financial_research.financial_features import index_facts
from app.services.financial_research.input_snapshot import InputSnapshot
from app.services.financial_research.modes import AnalysisMode

GATE_VERSION = "literature_gates_v1"
CANONICAL_AVAILABLE = ("revenue", "cost_of_goods_sold", "gross_profit", "operating_income", "net_income", "eps",
                       "total_assets", "total_liabilities", "equity", "current_assets", "current_liabilities",
                       "cash_and_cash_equivalents", "inventory", "accounts_receivable", "operating_cash_flow",
                       "investing_cash_flow", "capital_expenditure", "research_and_development_expense")

BENEISH_VARIABLES = {
    "DSRI": ("accounts_receivable", "revenue"),
    "GMI": ("revenue", "cost_of_goods_sold"),
    "AQI": ("current_assets", "property_plant_equipment_net", "securities", "total_assets"),
    "SGI": ("revenue",),
    "DEPI": ("depreciation_expense", "property_plant_equipment_net"),
    "SGAI": ("selling_general_administrative_expense", "revenue"),
    "LVGI": ("current_liabilities", "long_term_debt", "total_assets"),
    "TATA": ("current_assets", "cash_and_cash_equivalents", "current_liabilities", "current_maturities_of_long_term_debt",
             "income_tax_payable", "depreciation_and_amortization", "total_assets"),
}
DECHOW_MODEL1_VARIABLES = {
    "rsst_accruals": ("working_capital_components", "non_current_operating_assets", "non_current_operating_liabilities",
                      "financial_assets", "financial_liabilities", "total_assets"),
    "ch_rec": ("accounts_receivable", "total_assets"),
    "ch_inv": ("inventory", "total_assets"),
    "soft_assets": ("total_assets", "property_plant_equipment_net", "cash_and_cash_equivalents"),
    "ch_cs": ("revenue", "accounts_receivable"),
    "ch_roa": ("net_income", "total_assets"),
    "issue": ("debt_or_equity_issuance_indicator",),
}
ACCRUAL_PANEL_MODELS = ("jones_1991", "modified_jones_dechow_1995", "kothari_2005")


def _component_index(index, scope: str, year: int, name: str) -> dict[str, Any]:
    """Descriptive Beneish component indices that need only canonical metrics (DSRI, GMI, SGI)."""
    def value(y, metric):
        fact = index.get((y, scope, metric))
        return dm.parse_decimal(fact["value"]) if fact and fact["unit"] == "TWD" else None

    rev, rev_p = value(year, "revenue"), value(year - 1, "revenue")
    try:
        if name == "SGI":
            if None in (rev, rev_p) or rev_p == 0:
                raise ValueError
            result = dm.ratio_text(rev, rev_p)
        elif name == "DSRI":
            ar, ar_p = value(year, "accounts_receivable"), value(year - 1, "accounts_receivable")
            if None in (rev, rev_p, ar, ar_p) or 0 in (rev, rev_p, ar_p):
                raise ValueError
            result = dm.ratio_text(dm.parse_decimal(dm.ratio_text(ar, rev)), dm.parse_decimal(dm.ratio_text(ar_p, rev_p)))
        elif name == "GMI":
            cogs, cogs_p = value(year, "cost_of_goods_sold"), value(year - 1, "cost_of_goods_sold")
            if None in (rev, rev_p, cogs, cogs_p) or 0 in (rev, rev_p):
                raise ValueError
            gm, gm_p = dm.parse_decimal(dm.ratio_text(dm.sub(rev, cogs), rev)), dm.parse_decimal(dm.ratio_text(dm.sub(rev_p, cogs_p), rev_p))
            if gm == 0:
                raise ValueError
            result = dm.ratio_text(gm_p, gm)
        else:
            raise ValueError
    except ValueError:
        return {"component": name, "fiscal_year": year, "status": "not_computable", "value": None,
                "missing_reasons": ["missing_or_zero_input_for_t_or_t-1"]}
    return {"component": name, "fiscal_year": year, "status": "computed", "value": result,
            "note": "Descriptive component index (ratio of 6-dp ratios); NOT an M-Score."}


def model_readiness(snapshot: InputSnapshot, *, scope: str = "consolidated") -> dict[str, Any]:
    present = {fact["metric_code"] for fact in snapshot.facts if fact["statement_scope"] == scope}
    index = index_facts(snapshot.facts)

    def gate(variables: dict[str, tuple[str, ...]]) -> dict[str, Any]:
        out = {}
        for name, required in variables.items():
            missing = [m for m in required if m not in present]
            not_canonical = [m for m in missing if m not in CANONICAL_AVAILABLE]
            out[name] = {"required_inputs": list(required), "missing_inputs": missing,
                         "inputs_not_in_canonical_dataset": not_canonical,
                         "status": "inputs_present" if not missing else "not_computable"}
        return out

    beneish, dechow = gate(BENEISH_VARIABLES), gate(DECHOW_MODEL1_VARIABLES)
    years = range(snapshot.start_year + 1, snapshot.end_year + 1)
    components = ([_component_index(index, scope, y, name) for y in years for name in ("DSRI", "GMI", "SGI")]
                  if snapshot.context.mode is not AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION else [])
    return {
        "gate_version": GATE_VERSION, "approval_status": APPROVAL_STATUS, **snapshot.context.as_dict(),
        "ticker": snapshot.ticker, "statement_scope": scope,
        "models": [
            {"model_id": "beneish_1999_m_score_8_variable", "reference": "Beneish (1999), Financial Analysts Journal 55(5), DOI 10.2469/faj.v55.n5.2296",
             "variables": beneish, "full_model_status": "not_computable" if any(v["status"] != "inputs_present" for v in beneish.values())
             else "inputs_present_coefficients_not_loaded",
             "coefficients_status": "not_shipped_pending_verified_formula_version_and_method_owner_approval",
             "threshold_policy": "US-sample cut-offs are not Taiwan fraud probabilities and are not applied."},
            {"model_id": "dechow_2011_f_score_model_1", "reference": "Dechow, Ge, Larson & Sloan (2011), CAR 28(1), DOI 10.1111/j.1911-3846.2010.01041.x",
             "variables": dechow, "full_model_status": "not_computable" if any(v["status"] != "inputs_present" for v in dechow.values())
             else "inputs_present_coefficients_not_loaded",
             "coefficients_status": "not_shipped_pending_verified_formula_version_and_method_owner_approval",
             "threshold_policy": "SEC-enforcement calibration is not a local probability.",
             "proxy_note": "earnings_cashflow_gap_proxy (NI − CFO) is never used as RSST accruals."},
            *({"model_id": model, "full_model_status": "not_computable",
               "missing_inputs": ["multi_company_industry_panel", "property_plant_equipment_net"],
               "note": "Cross-sectional accrual models need a comparable multi-company panel; a single case cannot estimate them."}
              for model in ACCRUAL_PANEL_MODELS),
        ],
        "descriptive_components": components,
        "summary": "No published fraud model is computable from the authentic canonical inputs; no partial score is produced.",
    }
