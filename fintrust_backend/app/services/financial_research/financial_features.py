"""Pure Decimal computation of registered features over a frozen ``InputSnapshot``.

Inputs are the snapshot's canonical facts only. In ``STRICT_AS_OF`` the snapshot already excludes everything not
verifiably public before the cutoff, so a missing input stays missing (``no_verified_observation_before_cutoff``);
nothing is re-read from the full archive. Results are informational research evidence: they never feed risk
thresholds, trusted scores, notifications or model weights.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.feature_registry import (
    APPROVAL_STATUS,
    FEATURES,
    PRIOR_PERIOD_FEATURES,
    REGISTRY_VERSION,
    FeatureDefinition,
)
from app.services.financial_research.input_snapshot import InputSnapshot, latest_time
from app.services.financial_research.modes import AnalysisMode
from app.services.financial_research.version_selection import FactIndex, build_index

ENGINE_VERSION = "financial_features_v1"
_INPUT_FIELDS = ("fact_id", "metric_code", "value", "unit", "period", "fiscal_year", "statement_scope",
                 "accounting_framework", "filing_version_id", "filing_version_type", "effective_available_at",
                 "availability_scope", "availability_evidence_kind", "availability_evidence_ref",
                 "availability_evidence_hash", "availability_evidence_url", "observation_evidence_status",
                 "artifact_evidence_status", "artifact_reference_status", "artifact_sha256", "artifact_url")


class AmbiguousInputError(ValueError):
    pass


def index_facts(facts: list[dict[str, Any]]) -> FactIndex:
    """One fact per (fiscal_year, scope, metric); keys with several identities are ``ambiguous`` (F05), never
    resolved by input order."""
    return build_index(facts, key=lambda fact: (fact["fiscal_year"], fact["statement_scope"], fact["metric_code"]))


def _reason(code: str, metric: str | None = None, detail: str | None = None) -> dict[str, Any]:
    return {key: value for key, value in (("code", code), ("metric", metric), ("detail", detail)) if value is not None}


def _missing(strict: bool, metric: str, year: int) -> dict[str, Any]:
    code = "no_verified_observation_before_cutoff" if strict else "missing_input"
    return _reason(code, metric, f"FY{year}")


class _Inputs:
    def __init__(self, index, scope: str, strict: bool) -> None:
        self.index, self.scope, self.strict = index, scope, strict
        self.used: list[dict[str, Any]] = []
        self.reasons: list[dict[str, Any]] = []

    def get(self, year: int, metric: str) -> Decimal | None:
        key = (year, self.scope, metric)
        if key in getattr(self.index, "ambiguous", {}):
            self.reasons.append(_reason("ambiguous_version", metric, f"FY{year}"))
            return None
        fact = self.index.get(key)
        if fact is None:
            self.reasons.append(_missing(self.strict, metric, year))
            return None
        if fact["unit"] != "TWD":
            self.reasons.append(_reason("unit_mismatch", metric, fact["unit"]))
            return None
        self.used.append(fact)
        return dm.parse_decimal(fact["value"])


def _checks(inputs: _Inputs, year: int) -> list[dict[str, Any]]:
    reasons = []
    current = [f for f in inputs.used if f["fiscal_year"] == year]
    if len({f["filing_version_id"] for f in current}) > 1:
        reasons.append(_reason("version_mismatch", detail=f"FY{year}"))
    frameworks = {f["accounting_framework"] for f in inputs.used}
    if "unknown" in frameworks:
        reasons.append(_reason("framework_unknown"))
    elif len(frameworks) > 1:
        reasons.append(_reason("accounting_regime_break", detail=",".join(sorted(frameworks))))
    return reasons


def _divide(numerator: Decimal, denominator: Decimal, positive: bool) -> tuple[str | None, list[dict[str, Any]]]:
    if denominator == 0:
        return None, [_reason("zero_denominator")]
    if positive and denominator < 0:
        return None, [_reason("negative_denominator")]
    return dm.ratio_text(numerator, denominator), []


def compute_feature(definition: FeatureDefinition, year: int, scope: str, index, context) -> dict[str, Any]:
    strict = context.mode is AnalysisMode.STRICT_AS_OF
    base = {"feature_id": definition.feature_id, "formula": definition.formula,
            "formula_version": definition.formula_version, "fiscal_year": year, "period": f"{year}FY",
            "statement_scope": scope, "analysis_mode": context.mode.value, "unit": definition.unit,
            "original_vs_proxy": definition.original_vs_proxy, "approval_status": APPROVAL_STATUS}
    if context.mode not in definition.allowed_modes:
        return {**base, "status": "not_applicable", "value": None, "inputs": [],
                "missing_reasons": [_reason("feature_not_applicable_in_mode", detail=context.mode.value)]}
    inputs = _Inputs(index, scope, strict)
    fid, prior = definition.feature_id, year - 1
    numerator = denominator = None
    if fid in ("gross_margin", "cogs_sales_ratio", "operating_margin", "net_margin", "inventory_to_assets",
               "receivables_sales_ratio", "debt_asset_ratio"):
        top, bottom = {"gross_margin": ("gross_profit", "revenue"), "cogs_sales_ratio": ("cost_of_goods_sold", "revenue"),
                       "operating_margin": ("operating_income", "revenue"), "net_margin": ("net_income", "revenue"),
                       "inventory_to_assets": ("inventory", "total_assets"),
                       "receivables_sales_ratio": ("accounts_receivable", "revenue"),
                       "debt_asset_ratio": ("total_liabilities", "total_assets")}[fid]
        numerator, denominator = inputs.get(year, top), inputs.get(year, bottom)
    elif fid == "inventory_turnover":
        cogs, inv, inv_prior = inputs.get(year, "cost_of_goods_sold"), inputs.get(year, "inventory"), inputs.get(prior, "inventory")
        if inv_prior is None and not any(r["code"] == "unit_mismatch" for r in inputs.reasons):
            inputs.reasons.append(_reason("missing_prior_period", "inventory", f"FY{prior}"))
        if None not in (cogs, inv, inv_prior):
            numerator, denominator = cogs, dm.average(inv, inv_prior)
    elif fid in ("inventory_growth_assets", "receivables_growth_assets"):
        metric = "inventory" if fid == "inventory_growth_assets" else "accounts_receivable"
        now, before = inputs.get(year, metric), inputs.get(prior, metric)
        assets, assets_prior = inputs.get(year, "total_assets"), inputs.get(prior, "total_assets")
        if before is None or assets_prior is None:
            inputs.reasons.append(_reason("missing_prior_period", detail=f"FY{prior}"))
        if None not in (now, before, assets, assets_prior):
            numerator, denominator = dm.sub(now, before), dm.average(assets, assets_prior)
    elif fid == "earnings_cashflow_gap_proxy":
        income, cash = inputs.get(year, "net_income"), inputs.get(year, "operating_cash_flow")
        assets, assets_prior = inputs.get(year, "total_assets"), inputs.get(prior, "total_assets")
        if assets_prior is None:
            inputs.reasons.append(_reason("missing_prior_period", "total_assets", f"FY{prior}"))
        if None not in (income, cash, assets, assets_prior):
            numerator, denominator = dm.sub(income, cash), dm.average(assets, assets_prior)
    reasons = inputs.reasons + _checks(inputs, year)
    value = None
    if not reasons and numerator is not None and denominator is not None:
        value, reasons = _divide(numerator, denominator, definition.positive_denominator)
    used = [{key: fact.get(key) for key in _INPUT_FIELDS} for fact in inputs.used]
    warnings = []
    if {f["filing_version_type"] for f in inputs.used} & {"restated"}:
        warnings.append("Computed on restated (post-2016) figures; not the originally published figures.")
    if fid in PRIOR_PERIOD_FEATURES and len({f["filing_version_id"] for f in inputs.used}) > 1:
        warnings.append("t−1 values come from the t−1 filing, not from the comparative column of the FY t filing.")
    result = {**base, "status": "computed" if value is not None else "not_computable", "value": value,
              "numerator": dm.text(numerator) if value is not None else None,
              "denominator": dm.text(denominator) if value is not None else None,
              "inputs": used, "missing_reasons": reasons if value is None else [], "warnings": warnings,
              "available_at": latest_time([f["effective_available_at"] for f in inputs.used]) if strict else None}
    return result


def compute_features(snapshot: InputSnapshot, *, scope: str = "consolidated",
                     feature_ids: list[str] | None = None) -> dict[str, Any]:
    context = snapshot.context
    index = index_facts(snapshot.facts)
    definitions = [f for f in FEATURES if feature_ids is None or f.feature_id in feature_ids]
    results = [compute_feature(definition, year, scope, index, context)
               for year in range(snapshot.start_year, snapshot.end_year + 1) for definition in definitions]
    computed = sum(r["status"] == "computed" for r in results)
    if context.mode is AnalysisMode.STRICT_AS_OF and not snapshot.facts:
        status = "insufficient_point_in_time_evidence"
    elif context.mode is AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
        status = "NOT_APPLICABLE"
    elif computed == 0:
        status = "NOT_COMPUTABLE"
    elif computed < sum(r["status"] != "not_applicable" for r in results):
        status = "PARTIAL"
    else:
        status = "READY"
    return {
        "engine_version": ENGINE_VERSION, "registry_version": REGISTRY_VERSION, "approval_status": APPROVAL_STATUS,
        **context.as_dict(), "ticker": snapshot.ticker, "statement_scope": scope, "status": status,
        "input_snapshot": snapshot.describe(),
        "counts": {"computed": computed, "not_computable": sum(r["status"] == "not_computable" for r in results),
                   "not_applicable": sum(r["status"] == "not_applicable" for r in results)},
        "features": results,
        "usage_policy": ("Informational research evidence only; does not change risk thresholds, trusted scores, "
                         "notifications, model weights or trading recommendations."),
        "strict_note": ("No verified point-in-time financial input exists before this cutoff; early-warning ability "
                        "cannot be evaluated (this is not a low-risk result).")
        if status == "insufficient_point_in_time_evidence" else None,
    }
