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
    ("free_cash_flow", re.compile(r"自由現金流|free\s+cash\s+flow", re.I)),
    ("operating_cash_flow", re.compile(
        r"營業活動(?:淨)?現金流|營業現金流|營運活動之現金流入|operating\s+cash\s+flow|cash\s+from\s+operating", re.I)),
    ("gross_margin", re.compile(r"毛利率|gross\s+(?:profit\s+)?margin", re.I)),
    ("operating_margin", re.compile(r"營業利益率|營益率|營業淨利率|operating\s+(?:profit\s+)?margin", re.I)),
    ("net_margin", re.compile(r"淨利率|純益率|net\s+(?:profit\s+)?margin", re.I)),
    ("roe", re.compile(r"股東權益報酬率|(?<![A-Za-z])ROE(?![A-Za-z])|return\s+on\s+equity", re.I)),
    ("current_ratio", re.compile(r"流動比率|current\s+ratio", re.I)),
    ("debt_ratio", re.compile(r"負債比(?:率)?|debt\s+ratio", re.I)),
    ("research_and_development_expense", re.compile(r"研發費用|研究發展費用")),
    ("capital_expenditure", re.compile(r"資本支出|capital\s+expenditures?|(?<![A-Za-z])capex(?![A-Za-z])", re.I)),
    ("inventory", re.compile(r"存貨|inventor(?:y|ies)", re.I)),
    ("eps", re.compile(r"EPS|每股盈餘|earnings\s+per\s+share", re.I)),
    ("wafer_shipment", re.compile(r"晶圓出貨量|wafer\s+shipments?", re.I)),
    ("net_income", re.compile(r"稅後淨利|本期淨利|淨利|net\s+income", re.I)),
    ("revenue", re.compile(r"營業收入|月營收|營收|(?:net\s+)?revenue", re.I)),
]

OPERATIONAL_METRICS = frozenset({"wafer_shipment"})
UNSUPPORTED_RE = re.compile(
    r"保證|穩賺|飆股|目標價|買進|賣出|加碼|減碼|投資網站|冒名|假冒|詐騙|代操|投顧老師|"
    r"guarantee|scam|impersonat|target\s+price|\bbuy\b|\bsell\b",
    re.I,
)
MIX_RE = re.compile(r"占|佔|比重|accounts?\s+for|share\s+of|of\s+(?:total\s+)?(?:wafer\s+)?revenue", re.I)
MIX_CATEGORY_RE = re.compile(
    r"(?<![0-9A-Za-z.])(\d+(?:/\d+)?\s?nm|0\.\d+(?:/0\.\d+)?\s?um|HPC|Smartphone|IoT|Automotive|DCE|"
    r"高效能運算|智慧型手機|物聯網|車用電子|消費性電子)",
    re.I,
)
STATEMENT_RE = re.compile(
    r"宣布|表示|公告|決議|取消|設廠|庫藏股|買回|發放|澄清|announce|cancel|repurchase|buyback|clarif",
    re.I,
)
COMPARATOR_RE = (
    ("lt", re.compile(r"低於|少於|不到|未達|less\s+than|below|under", re.I)),
    ("gt", re.compile(r"高於|超過|多於|more\s+than|above", re.I)),
)

PERCENT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(?:%|％)")
PERCENTAGE_POINT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*個?百分點")
AMOUNT_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(兆|億|百萬|萬|千|仟|元)(?:元)?")


def _detect_metric(text: str) -> str | None:
    for metric, pattern in METRIC_PATTERNS:
        if pattern.search(text):
            return metric
    return None


def _detect_direction(text: str) -> ClaimDirection:
    if re.search(r"年減|季減|衰退|下降|減少|下滑|decreas|declin|fell|dropp", text, re.I):
        return ClaimDirection.DECREASE
    if re.search(r"年增|季增|成長|增加|上升|暴增|increas|grew|rose", text, re.I):
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
    if re.search(r"年增|年減|去年同期|較去年|YoY|year[\s-]+over[\s-]+year", text, re.I):
        return ComparisonKind.YOY
    if re.search(r"季增|季減|上季|較上季|QoQ|quarter[\s-]+over[\s-]+quarter|sequential", text, re.I):
        return ComparisonKind.QOQ
    if re.search(r"增加|下降|上升|減少|increas|decreas|grew|rose|declin|fell", text, re.I):
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
    claimed_value_text: str | None = None
    unit: str | None = None
    if percent_match and claimed_change_percent is None:
        claimed_value = float(percent_match.group(1))
        claimed_value_text = percent_match.group(1)
        unit = "%"
    elif not percent_match and not pp_match:
        claimed_value, unit = _number_with_unit(text)
        amounts = list(AMOUNT_RE.finditer(text))
        claimed_value_text = amounts[-1].group(1) if amounts else None
    elif claimed_change_percent is not None:
        claimed_value_text = percent_match.group(1)
    elif pp_match:
        claimed_value_text = pp_match.group(1)

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
        claimed_value_text=claimed_value_text,
        claimed_change_percent=claimed_change_percent,
        claimed_percentage_points=claimed_percentage_points,
        unit=unit,
        extraction_confidence=confidence,
        missing_fields=missing,
    )


def classify_claim(text: str, claim: ExtractedFinancialClaim) -> dict[str, object]:
    """Bounded claim typing on top of the deterministic extraction.

    Returns claim_type, metric_or_topic, comparator, and keywords. Anything the
    official-evidence engine cannot check (advice, scams, impersonation, price
    predictions) is typed ``unsupported`` rather than forced into a metric.
    """
    comparator = next((name for name, pattern in COMPARATOR_RE if pattern.search(text)), None)
    category = MIX_CATEGORY_RE.search(text)
    keywords = sorted(
        {match.group(0) for match in MIX_CATEGORY_RE.finditer(text)}
        | set(re.findall(r"[一-鿿]{2,}|[A-Za-z][A-Za-z&-]{2,}", text))
    )[:16]
    has_number = any(
        value is not None
        for value in (claim.claimed_value, claim.claimed_change_percent, claim.claimed_percentage_points)
    )
    if UNSUPPORTED_RE.search(text):
        claim_type, topic = "unsupported", None
    elif MIX_RE.search(text) and has_number and claim.unit == "%":
        if category:
            subject = category.group(0)
        else:
            before = re.search(
                r"([A-Za-z][A-Za-z0-9 &-]{1,40}?|[一-鿿A-Za-z0-9]{2,20}?)\s*(?:營收)?(?:占比|比重|占|佔|accounts?\s+for)",
                text, re.I,
            )
            subject = before.group(1).strip() if before else "unspecified"
        claim_type, topic = "percentage_mix", "revenue_share:" + re.sub(r"\s+", "", subject)
    elif claim.metric in OPERATIONAL_METRICS:
        claim_type, topic = "operational_metric", claim.metric
    elif claim.metric and has_number:
        claim_type, topic = "numeric_metric", claim.metric
    elif claim.metric and claim.direction != ClaimDirection.UNSPECIFIED:
        claim_type, topic = "trend", claim.metric
    elif STATEMENT_RE.search(text):
        claim_type, topic = "company_statement", None
    else:
        claim_type, topic = "unsupported", claim.metric
    return {"claim_type": claim_type, "metric_or_topic": topic, "comparator": comparator, "keywords": keywords}
