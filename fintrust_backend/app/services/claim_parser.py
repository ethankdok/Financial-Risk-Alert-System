from __future__ import annotations

import re

from app.models import (
    ClaimDirection,
    ComparisonKind,
    ExtractedFinancialClaim,
)
from app.services.company_registry import find_company
from app.services.periods import normalize_period, previous_quarter, previous_year_same_period


# Put more specific expressions before generic ones so, for example, 自由現金流
# is not consumed by the 營業現金流 pattern.  YoY phrases deliberately map to
# the underlying fact (revenue/inventory), because the verifier must recompute
# the growth rate from the current and comparison periods rather than compare a
# precomputed growth rate to another growth rate.
METRIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("capex_intensity", re.compile(r"資本支出(?:占營收)?比(?:率)?|資本支出強度")),
    ("rd_intensity", re.compile(r"研發(?:費用)?占營收比(?:率)?|研發強度")),
    ("cash_conversion_ratio", re.compile(r"現金轉換比|營業現金流(?:／|/|除以)淨利")),
    ("free_cash_flow", re.compile(r"自由現金流")),
    ("operating_cash_flow", re.compile(r"營業活動(?:淨)?現金流|營業現金流")),
    ("gross_margin", re.compile(r"毛利率")),
    ("operating_margin", re.compile(r"營業利益率|營益率")),
    ("net_margin", re.compile(r"淨利率")),
    ("current_ratio", re.compile(r"流動比率")),
    ("debt_ratio", re.compile(r"負債比(?:率)?")),
    ("research_and_development_expense", re.compile(r"研發費用|研究發展費用")),
    ("capital_expenditure", re.compile(r"資本支出")),
    ("inventory", re.compile(r"存貨")),
    ("eps", re.compile(r"EPS|每股盈餘", re.I)),
    ("net_income", re.compile(r"稅後淨利|本期淨利|淨利")),
    ("revenue", re.compile(r"營業收入|月營收|營收")),
]

PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:%|％)")
PERCENTAGE_POINT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*個?百分點")
AMOUNT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(兆|億|百萬|萬|千|仟|元)(?:元)?")


def _detect_metric(text: str) -> str | None:
    for metric, pattern in METRIC_PATTERNS:
        if pattern.search(text):
            return metric
    return None


def _detect_direction(text: str) -> ClaimDirection:
    if re.search(r"年減|季減|衰退|下降|減少|下滑", text):
        return ClaimDirection.DECREASE
    if re.search(r"年增|季增|成長|增加|上升|暴增", text):
        return ClaimDirection.INCREASE
    if re.search(r"高於|優於|超過", text):
        return ClaimDirection.HIGHER_THAN
    if re.search(r"低於|不及|少於", text):
        return ClaimDirection.LOWER_THAN
    if re.search(r"等於|持平", text):
        return ClaimDirection.EQUAL
    return ClaimDirection.UNSPECIFIED


def _detect_comparison_kind(text: str) -> ComparisonKind | None:
    if PERCENTAGE_POINT_RE.search(text):
        return ComparisonKind.PERCENTAGE_POINT
    if re.search(r"年增|年減|去年同期|較去年|YoY", text, re.I):
        return ComparisonKind.YOY
    if re.search(r"季增|季減|上季|較上季|QoQ", text, re.I):
        return ComparisonKind.QOQ
    if re.search(r"增加|下降|上升|減少", text):
        return ComparisonKind.DIRECTION_ONLY
    return ComparisonKind.VALUE


def _number_with_unit(text: str) -> tuple[float | None, str | None]:
    matches = list(AMOUNT_RE.finditer(text))
    if not matches:
        return None, None
    # Prefer the last explicit amount so a year or stock ticker near the start of
    # the sentence cannot be mistaken for the claimed financial value.
    match = matches[-1]
    return float(match.group(1)), match.group(2)


def extract_claim(
    text: str,
    ticker_hint: str | None = None,
    period_hint: str | None = None,
    comparison_period_hint: str | None = None,
) -> ExtractedFinancialClaim:
    company = find_company(text, ticker_hint)
    metric = _detect_metric(text)
    period = period_hint or normalize_period(text)
    kind = _detect_comparison_kind(text)
    direction = _detect_direction(text)

    comparison_period = comparison_period_hint
    if not comparison_period and period and kind == ComparisonKind.YOY:
        comparison_period = previous_year_same_period(period)
    elif not comparison_period and period and kind == ComparisonKind.QOQ:
        comparison_period = previous_quarter(period)
    elif not comparison_period and period and kind == ComparisonKind.PERCENTAGE_POINT:
        if re.search(r"去年同期|較去年|年增|年減|YoY", text, re.I):
            comparison_period = previous_year_same_period(period)
        elif re.search(r"上季|較上季|季增|季減|QoQ", text, re.I):
            comparison_period = previous_quarter(period)

    pp_match = PERCENTAGE_POINT_RE.search(text)
    percent_match = PERCENT_RE.search(text)

    claimed_percentage_points = float(pp_match.group(1)) if pp_match else None
    claimed_change_percent = (
        float(percent_match.group(1))
        if percent_match and kind in {ComparisonKind.YOY, ComparisonKind.QOQ}
        else None
    )

    claimed_value: float | None = None
    unit: str | None = None
    if percent_match and claimed_change_percent is None:
        claimed_value = float(percent_match.group(1))
        unit = "%"
    elif not percent_match and not pp_match:
        claimed_value, unit = _number_with_unit(text)

    if claimed_change_percent is not None:
        unit = "%"
    elif claimed_percentage_points is not None:
        unit = "百分點"

    missing: list[str] = []
    if not company:
        missing.append("company")
    if not metric:
        missing.append("metric")
    if not period:
        missing.append("period")
    if kind in {ComparisonKind.YOY, ComparisonKind.QOQ, ComparisonKind.PERCENTAGE_POINT} and not comparison_period:
        missing.append("comparison_period")
    if (
        claimed_value is None
        and claimed_change_percent is None
        and claimed_percentage_points is None
        and direction == ClaimDirection.UNSPECIFIED
    ):
        missing.append("claim_value_or_direction")

    found = 4 - min(len(missing), 4)
    confidence = round(found / 4, 2)

    return ExtractedFinancialClaim(
        original_text=text,
        ticker=company.ticker if company else ticker_hint,
        company_name=company.name if company else None,
        semiconductor_subindustry=company.subindustry if company else None,
        metric=metric,
        period=period,
        comparison_period=comparison_period,
        comparison_kind=kind,
        direction=direction,
        claimed_value=claimed_value,
        claimed_change_percent=claimed_change_percent,
        claimed_percentage_points=claimed_percentage_points,
        unit=unit,
        extraction_confidence=confidence,
        missing_fields=missing,
    )
