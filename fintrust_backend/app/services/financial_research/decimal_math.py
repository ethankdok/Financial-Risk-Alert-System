"""Exact Decimal arithmetic for official financial values (never float)."""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Context, Decimal, InvalidOperation, localcontext

CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)
RATIO_QUANTUM = Decimal("0.000001")  # ratios are reported to 6 decimal places (half-even); exact operands are kept
UNIT_SCALE = {"TWD": Decimal(1), "TWD_thousand": Decimal(1000)}

_NUMBER = re.compile(r"^[+-]?\d+(\.\d+)?$")


class DecimalParseError(ValueError):
    pass


def parse_decimal(value: object) -> Decimal | None:
    """Parse an official numeric text: commas, parenthesized negatives and a leading minus are accepted.

    ``None`` / empty / dash placeholders mean *not reported* and return ``None`` (never zero). Floats are refused so
    binary rounding can never enter a financial value.
    """
    if value is None:
        return None
    if isinstance(value, float):
        raise DecimalParseError("float values are not accepted; use the exact decimal text")
    if isinstance(value, (int, Decimal)):
        return Decimal(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if text in {"", "-", "--", "—", "N/A", "n/a"}:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if not _NUMBER.match(text):
        raise DecimalParseError(f"not an exact decimal: {value!r}")
    number = Decimal(text)
    return -number if negative else number


def to_twd(value: Decimal, unit: str) -> Decimal:
    if unit not in UNIT_SCALE:
        raise DecimalParseError(f"unsupported monetary unit {unit!r}")
    with localcontext(CONTEXT):
        return value * UNIT_SCALE[unit]


def text(value: Decimal | None) -> str | None:
    """Plain decimal string, never scientific notation."""
    if value is None:
        return None
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return "0" if normalized in {"-0", ""} else normalized


def ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        return (numerator / denominator).quantize(RATIO_QUANTUM)


def ratio_text(numerator: Decimal, denominator: Decimal) -> str:
    return format(ratio(numerator, denominator), "f")


def sub(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        return a - b


def add(*values: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        total = Decimal(0)
        for value in values:
            total += value
        return total


def mul(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        return a * b


def average(a: Decimal, b: Decimal) -> Decimal:
    with localcontext(CONTEXT):
        return (a + b) / 2


def is_exact(value: object) -> bool:
    try:
        return parse_decimal(value) is not None
    except (DecimalParseError, InvalidOperation):
        return False
