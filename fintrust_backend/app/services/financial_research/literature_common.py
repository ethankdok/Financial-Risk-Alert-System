"""Shared exact arithmetic and result shapes for the literature-model engines (no model knowledge here)."""

from __future__ import annotations

import math
from decimal import Context, Decimal, localcontext
from typing import Any

from app.services.financial_research import decimal_math as dm

PRECISION = Context(prec=50)
REPORT_QUANTUM = Decimal("0.000001")
NUMERICAL_PRECISION = {
    "operands": "exact Decimal (TWD, from official line values)",
    "intermediate": "Decimal, 50 significant digits, no intermediate rounding",
    "reported_components": "6 decimal places, half-even (display only; the score uses unrounded components)",
    "reported_score": "6 decimal places, half-even",
    "coefficients": "exactly as printed in the source (3 decimals)",
}


class ComponentError(ValueError):
    """A component is undefined for these inputs (carries an explicit reason code)."""

    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code, self.detail = code, detail


def q(value: Decimal | None) -> str | None:
    if value is None:
        return None
    with localcontext(PRECISION):
        return format(value.quantize(REPORT_QUANTUM), "f")


def div(numerator: Decimal, denominator: Decimal, name: str, *, positive: bool = False) -> Decimal:
    if denominator == 0:
        raise ComponentError("invalid_denominator_zero", name)
    if positive and denominator < 0:
        raise ComponentError("invalid_denominator_negative", name)
    with localcontext(PRECISION):
        return numerator / denominator


def add(*values: Decimal) -> Decimal:
    with localcontext(PRECISION):
        total = Decimal(0)
        for value in values:
            total += value
        return total


def sub(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(PRECISION):
        return a - b


def mul(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(PRECISION):
        return a * b


def avg(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(PRECISION):
        return (a + b) / 2


def linear_index(intercept: Decimal, coefficients: dict[str, Decimal], values: dict[str, Decimal]) -> Decimal:
    with localcontext(PRECISION):
        total = intercept
        for name, coefficient in coefficients.items():
            total += coefficient * values[name]
        return total


def logistic(value: Decimal) -> Decimal:
    """Numerically stable logistic e^v / (1 + e^v) in Decimal (no overflow for large |v|)."""
    with localcontext(PRECISION):
        if value >= 0:
            return Decimal(1) / (Decimal(1) + (-value).exp())
        exp = value.exp()
        return exp / (Decimal(1) + exp)


def normal_cdf(value: Decimal) -> tuple[str, bool]:
    """Standard normal CDF via ``erfc`` (IEEE-754 double). Returns (text, underflow)."""
    result = 0.5 * math.erfc(-float(value) / math.sqrt(2.0))
    if result == 0.0:
        return "<1e-300", True
    return f"{result:.6g}", False


def reason(code: str, **detail: Any) -> dict[str, Any]:
    return {"code": code, **{k: v for k, v in detail.items() if v is not None}}


def decimal_text(value: Decimal | None) -> str | None:
    return dm.text(value) if value is not None else None


# ------------------------------------------------------------------------------------------- component evaluation
def evaluate_components(panel: Any, definitions: dict[str, tuple[list[tuple[str, str]], Any]]) -> dict[str, Any]:
    """Evaluate every component independently; a missing input or undefined ratio makes only that component
    ``not_computable`` (with all of its missing inputs listed), never a zero."""
    components, values, missing = [], {}, []
    for name, (requires, function) in definitions.items():
        fetched, problems = {}, []
        for metric, relative in requires:
            item = panel.value(metric, relative)
            if item.status != "computed":
                problems.append({"metric": metric, "relative_period": relative, "fiscal_year": item.fiscal_year,
                                 "status": item.status, "reasons": item.reasons})
            else:
                fetched[(metric, relative)] = item
        entry: dict[str, Any] = {"variable": name, "inputs": [fetched[k].provenance() for k in sorted(fetched)]}
        if problems:
            entry.update(status="not_computable", value=None,
                         reasons=[reason(p["status"], metric=p["metric"], relative_period=p["relative_period"],
                                         fiscal_year=p["fiscal_year"]) for p in problems])
            missing.extend({**p, "component": name} for p in problems)
        else:
            try:
                value = function({key: item.value for key, item in fetched.items()}, fetched)
            except ComponentError as exc:
                entry.update(status="not_computable", value=None, reasons=[reason(exc.code, detail=exc.detail)])
            else:
                values[name] = value
                entry.update(status="computed", value=q(value), value_exact=decimal_text(value), reasons=[])
        entry["warnings"] = sorted({w for item in fetched.values() for w in item.warnings})
        components.append(entry)
    return {"components": components, "values": values, "missing_inputs": missing}
