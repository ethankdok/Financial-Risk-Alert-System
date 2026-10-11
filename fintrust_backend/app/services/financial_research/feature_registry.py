"""Versioned registry of explainable single financial features (M2).

Each definition states its formula, required canonical metrics, period alignment, accounting-framework / scope /
version / availability policies, zero policy, missing-reason catalog, literature reference, whether it is an original
literature variable or a proxy, and the analysis modes it may run in. All definitions are method specifications
awaiting the method owner's (Yu-Jing) approval: the arithmetic is descriptive and exact, the research interpretation
is DRAFT.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from app.services.financial_research.modes import AnalysisMode

APPROVAL_STATUS = "DRAFT_PENDING_METHOD_OWNER_REVIEW"
REGISTRY_VERSION = "feature_registry_v1"

MISSING_REASONS = {
    "missing_input": "A required canonical metric is not present for this period/scope.",
    "no_verified_observation_before_cutoff": "No observation of a required metric is verifiably available before cutoff_at.",
    "missing_prior_period": "The formula needs t−1 and no comparable prior-period observation exists.",
    "zero_denominator": "The denominator is exactly zero.",
    "negative_denominator": "The denominator is negative where the formula requires a positive base.",
    "version_mismatch": "Same-period components come from different filing versions.",
    "ambiguous_version": "Several filing versions with different identities exist for one input; none is chosen by order.",
    "scope_mismatch": "Components are not all from the same statement scope.",
    "unit_mismatch": "Components are not all in TWD.",
    "accounting_regime_break": "t and t−1 are under different accounting frameworks; no comparison policy approved.",
    "framework_unknown": "The accounting framework of an input is not established.",
    "feature_not_applicable_in_mode": "This feature is not defined for the requested analysis mode.",
}

_RATIO_MODES = (AnalysisMode.RETROSPECTIVE_FORENSIC, AnalysisMode.STRICT_AS_OF)
_COMMON = dict(
    accounting_framework_policy="all inputs share one framework; t and t−1 must share it (no cross-regime comparison policy)",
    scope_policy="single statement_scope (consolidated in the canonical facts); scopes never mixed",
    version_policy="same-period inputs must come from one filing version; version selection is the explicit request policy",
    source_availability_policy="STRICT_AS_OF: every input effective_available_at < cutoff_at; others: full archive",
    unit="ratio",
    zero_policy="denominator 0 → not_computable(zero_denominator); a reported 0 numerator is a real zero, never 'missing'",
)


@dataclass(frozen=True)
class FeatureDefinition:
    feature_id: str
    formula: str
    required_metrics: tuple[str, ...]
    period_alignment: str
    literature_reference: str
    original_vs_proxy: str
    allowed_modes: tuple[AnalysisMode, ...]
    interpretation_limit: str
    formula_version: str = "v1"
    accounting_framework_policy: str = _COMMON["accounting_framework_policy"]
    scope_policy: str = _COMMON["scope_policy"]
    version_policy: str = _COMMON["version_policy"]
    source_availability_policy: str = _COMMON["source_availability_policy"]
    unit: str = _COMMON["unit"]
    zero_policy: str = _COMMON["zero_policy"]
    positive_denominator: bool = True
    approval_status: str = APPROVAL_STATUS

    def as_dict(self) -> dict:
        data = asdict(self)
        data["allowed_modes"] = [mode.value for mode in self.allowed_modes]
        data["required_metrics"] = list(self.required_metrics)
        data["missing_reason_catalog"] = sorted(MISSING_REASONS)
        return data


FEATURES: tuple[FeatureDefinition, ...] = (
    FeatureDefinition("gross_margin", "gross_profit_t / revenue_t", ("gross_profit", "revenue"), "t",
                      "Descriptive ratio; cf. Beneish (1999) GMI uses gross margin (DOI 10.2469/faj.v55.n5.2296)",
                      "descriptive_ratio", _RATIO_MODES, "Gross-margin level is not by itself evidence of misstatement."),
    FeatureDefinition("cogs_sales_ratio", "cost_of_goods_sold_t / revenue_t", ("cost_of_goods_sold", "revenue"), "t",
                      "Descriptive ratio (case mechanism focus: COGS)", "descriptive_ratio", _RATIO_MODES,
                      "COGS share is a structural indicator, not a fraud signal."),
    FeatureDefinition("operating_margin", "operating_income_t / revenue_t", ("operating_income", "revenue"), "t",
                      "Descriptive ratio", "descriptive_ratio", _RATIO_MODES, "Descriptive only."),
    FeatureDefinition("net_margin", "net_income_t / revenue_t", ("net_income", "revenue"), "t",
                      "Descriptive ratio", "descriptive_ratio", _RATIO_MODES, "Descriptive only."),
    FeatureDefinition("inventory_to_assets", "inventory_t / total_assets_t", ("inventory", "total_assets"), "t",
                      "Descriptive ratio", "descriptive_ratio", _RATIO_MODES,
                      "A change in inventory share is not a valuation loss."),
    FeatureDefinition("inventory_turnover", "cost_of_goods_sold_t / average(inventory_t, inventory_t−1)",
                      ("cost_of_goods_sold", "inventory"), "t and t−1 (comparable)",
                      "Descriptive ratio", "descriptive_ratio", _RATIO_MODES,
                      "Requires comparable beginning and ending inventory; first TIFRS year has no comparable t−1."),
    FeatureDefinition("inventory_growth_assets", "(inventory_t − inventory_t−1) / average(total_assets_t, total_assets_t−1)",
                      ("inventory", "total_assets"), "t and t−1 (comparable)",
                      "Dechow et al. (2011) ΔINV scaled by average total assets (DOI 10.1111/j.1911-3846.2010.01041.x)",
                      "original_component_definition", _RATIO_MODES,
                      "A single component of the F-Score model; not the F-Score."),
    FeatureDefinition("receivables_sales_ratio", "accounts_receivable_t / revenue_t", ("accounts_receivable", "revenue"), "t",
                      "Descriptive ratio; DSRI building block in Beneish (1999)", "descriptive_ratio", _RATIO_MODES,
                      "Receivable definitions must be consistent across years."),
    FeatureDefinition("receivables_growth_assets", "(accounts_receivable_t − accounts_receivable_t−1) / average(total_assets_t, total_assets_t−1)",
                      ("accounts_receivable", "total_assets"), "t and t−1 (comparable)",
                      "Dechow et al. (2011) ΔREC scaled by average total assets", "original_component_definition",
                      _RATIO_MODES, "A single component of the F-Score model; not the F-Score."),
    FeatureDefinition("earnings_cashflow_gap_proxy", "(net_income_t − operating_cash_flow_t) / average(total_assets_t, total_assets_t−1)",
                      ("net_income", "operating_cash_flow", "total_assets"), "t and t−1 (assets)",
                      "PROXY — not RSST accruals (Dechow et al. 2011) and not Beneish TATA", "proxy", _RATIO_MODES,
                      "Explicitly a proxy; never substituted for a published accrual measure."),
    FeatureDefinition("debt_asset_ratio", "total_liabilities_t / total_assets_t", ("total_liabilities", "total_assets"), "t",
                      "Descriptive leverage ratio", "descriptive_ratio", _RATIO_MODES,
                      "Background context; no single-item fraud inference."),
    FeatureDefinition("source_value_gap", "value_from_notice − value_from_filed_report (same period/scope/unit/metric)",
                      (), "same period", "Cross-source reconciliation (architecture v2 §2.3)", "reconciliation_measure",
                      (AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION,),
                      "A source gap is unresolved evidence, never a risk label.", unit="TWD", positive_denominator=False),
)
FEATURE_INDEX = {feature.feature_id: feature for feature in FEATURES}
PRIOR_PERIOD_FEATURES = {"inventory_turnover", "inventory_growth_assets", "receivables_growth_assets",
                         "earnings_cashflow_gap_proxy"}


def registry_payload() -> dict:
    return {"registry_version": REGISTRY_VERSION, "approval_status": APPROVAL_STATUS,
            "features": [feature.as_dict() for feature in FEATURES], "missing_reasons": MISSING_REASONS}
