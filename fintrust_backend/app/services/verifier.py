from __future__ import annotations

from app.models import (
    ClaimDirection,
    ClaimVerificationResult,
    ComparisonKind,
    EvidenceCalculation,
    ExtractedFinancialClaim,
    VerificationVerdict,
)
from app.services.analysis_repository import AnalysisRepository


MONEY_SCALES = {
    "元": 1.0,
    "千": 1_000.0,
    "仟": 1_000.0,
    "千元": 1_000.0,
    "仟元": 1_000.0,
    "新台幣千元": 1_000.0,
    "新台幣仟元": 1_000.0,
    "萬": 10_000.0,
    "萬元": 10_000.0,
    "百萬": 1_000_000.0,
    "百萬元": 1_000_000.0,
    "億": 100_000_000.0,
    "億元": 100_000_000.0,
    "兆": 1_000_000_000_000.0,
    "兆元": 1_000_000_000_000.0,
}


def _direction_matches(direction: ClaimDirection, calculated: float) -> bool:
    if direction in {ClaimDirection.INCREASE, ClaimDirection.HIGHER_THAN}:
        return calculated > 0
    if direction in {ClaimDirection.DECREASE, ClaimDirection.LOWER_THAN}:
        return calculated < 0
    if direction == ClaimDirection.EQUAL:
        return calculated == 0
    return True


def _signed_expected(value: float | None, direction: ClaimDirection) -> float | None:
    if value is None:
        return None
    if direction in {ClaimDirection.DECREASE, ClaimDirection.LOWER_THAN}:
        return -abs(value)
    if direction in {ClaimDirection.INCREASE, ClaimDirection.HIGHER_THAN}:
        return abs(value)
    return value


def _convert_claimed_value(
    value: float,
    claimed_unit: str | None,
    official_unit: str,
) -> float | None:
    if claimed_unit in {None, official_unit}:
        return value
    # EPS claims usually say「元」while the official evidence unit is 元／股.
    if claimed_unit == "元" and official_unit == "元／股":
        return value
    from_scale = MONEY_SCALES.get(claimed_unit)
    to_scale = MONEY_SCALES.get(official_unit)
    if from_scale is None or to_scale is None:
        return None
    return value * from_scale / to_scale


def verify_claim(
    claim: ExtractedFinancialClaim,
    repository: AnalysisRepository,
    tolerance_percentage_points: float = 2.0,
) -> ClaimVerificationResult:
    if not claim.ticker or not claim.metric:
        return ClaimVerificationResult(
            claim=claim,
            verdict=VerificationVerdict.NOT_APPLICABLE,
            explanation="無法辨識半導體公司或財務指標，因此不適用財報量化查證。",
            limitations=["需要公司／股票代號與可對應的財務指標。"],
        )

    if not claim.period:
        return ClaimVerificationResult(
            claim=claim,
            verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
            explanation="主張缺少明確財報期間，系統不會自行猜測『今年』或『最近』所指的期間。",
            limitations=["請提供年度或季度，例如 2025 年全年或 2025 年第 2 季。"],
        )

    current = repository.get_fact(claim.ticker, claim.metric, claim.period)
    if current is None:
        return ClaimVerificationResult(
            claim=claim,
            verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
            explanation="資料庫尚未取得此公司、指標與期間的官方財報欄位。",
            limitations=["需先完成 MOPS Inline XBRL／TWSE 官方資料匯入。"],
        )

    comparison = None
    if claim.comparison_period:
        comparison = repository.get_fact(claim.ticker, claim.metric, claim.comparison_period)
        if comparison is None:
            return ClaimVerificationResult(
                claim=claim,
                verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                explanation="已找到本期數值，但缺少比較期間的官方資料，無法重新計算變化幅度。",
                limitations=[f"缺少比較期間：{claim.comparison_period}"],
            )

    formula: str | None = None
    calculated: float | None = None
    expected: float | None = None
    value_comparison = False

    if claim.comparison_kind in {ComparisonKind.YOY, ComparisonKind.QOQ}:
        if comparison is None or comparison.value == 0:
            return ClaimVerificationResult(
                claim=claim,
                verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                explanation="比較期數值不存在或為零，無法計算成長率。",
            )
        calculated = (current.value - comparison.value) / abs(comparison.value) * 100
        expected = _signed_expected(claim.claimed_change_percent, claim.direction)
        formula = (
            f"({current.value:g} - {comparison.value:g}) / "
            f"abs({comparison.value:g}) * 100 = {calculated:.2f}%"
        )
    elif claim.comparison_kind == ComparisonKind.PERCENTAGE_POINT:
        if comparison is None:
            return ClaimVerificationResult(
                claim=claim,
                verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                explanation="缺少比較期比率，無法計算百分點差異。",
            )
        calculated = current.value - comparison.value
        expected = _signed_expected(claim.claimed_percentage_points, claim.direction)
        formula = f"{current.value:g} - {comparison.value:g} = {calculated:.2f} 個百分點"
    elif claim.claimed_value is not None:
        converted = _convert_claimed_value(claim.claimed_value, claim.unit, current.unit)
        if converted is None:
            return ClaimVerificationResult(
                claim=claim,
                verdict=VerificationVerdict.INSUFFICIENT_EVIDENCE,
                explanation="主張單位與官方資料單位無法可靠換算，系統不進行數值比較。",
                limitations=[f"主張單位：{claim.unit or '未提供'}；官方單位：{current.unit}"],
            )
        calculated = current.value
        expected = converted
        value_comparison = True
        formula = f"官方值 = {current.value:g} {current.unit}"
    elif claim.direction != ClaimDirection.UNSPECIFIED and comparison is not None:
        calculated = current.value - comparison.value
        formula = f"{current.value:g} - {comparison.value:g} = {calculated:.2f} {current.unit}"
    else:
        return ClaimVerificationResult(
            claim=claim,
            verdict=VerificationVerdict.NOT_APPLICABLE,
            explanation="句子雖提及財務資訊，但沒有可執行的數值或方向主張。",
        )

    evidence = EvidenceCalculation(
        metric=claim.metric,
        period=claim.period,
        comparison_period=claim.comparison_period,
        current_value=current.value,
        comparison_value=comparison.value if comparison else None,
        unit=current.unit,
        formula=formula,
        calculated_value=round(calculated, 4) if calculated is not None else None,
        tolerance_percentage_points=tolerance_percentage_points,
        source_urls=list(
            dict.fromkeys(
                [current.source_url] + ([comparison.source_url] if comparison else [])
            )
        ),
        is_demo=current.is_demo or bool(comparison and comparison.is_demo),
    )

    if expected is None:
        assert calculated is not None
        matches = _direction_matches(claim.direction, calculated)
        return ClaimVerificationResult(
            claim=claim,
            verdict=(
                VerificationVerdict.SUPPORTED
                if matches
                else VerificationVerdict.CONTRADICTED
            ),
            explanation=(
                "官方數值的變化方向與主張一致。"
                if matches
                else "官方數值的變化方向與主張相反。"
            ),
            evidence=evidence,
        )

    assert calculated is not None
    difference = abs(calculated - expected)
    # Percentage changes and percentage-point claims use an absolute point
    # tolerance.  Money/EPS values use the same input as a relative percentage,
    # avoiding a meaningless fixed tolerance of two thousand dollars.
    strict_tolerance = (
        max(abs(calculated) * tolerance_percentage_points / 100.0, 1e-9)
        if value_comparison and current.unit not in {"%", "百分點"}
        else tolerance_percentage_points
    )
    if difference <= strict_tolerance:
        verdict = VerificationVerdict.SUPPORTED
        explanation = "重新計算結果落在設定的容許誤差內。"
    elif difference <= strict_tolerance * 2:
        verdict = VerificationVerdict.PARTIALLY_SUPPORTED
        explanation = "主張方向大致一致，但數值差異超過嚴格容許誤差。"
    else:
        verdict = VerificationVerdict.CONTRADICTED
        explanation = "重新計算結果與主張的數值差異明顯，超出容許誤差。"

    return ClaimVerificationResult(
        claim=claim,
        verdict=verdict,
        explanation=explanation,
        difference=round(difference, 4),
        evidence=evidence,
        limitations=(
            ["目前使用 demo fixture；正式結果必須由官方 XBRL／OpenAPI 資料取代。"]
            if evidence.is_demo
            else []
        ),
    )
