from __future__ import annotations

import re
from typing import Any

from app.financial_analysis_models import (
    NormalizedFinancialStatement,
    SourceCoverage,
)
from app.models import CompanyProfile
from app.services.twse_openapi import TwseOpenApiClient


INCOME_FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("營業收入", "營業收入合計"),
    "gross_profit": ("營業毛利（毛損）", "營業毛利(毛損)", "營業毛利"),
    "operating_income": ("營業利益（損失）", "營業利益(損失)", "營業利益"),
    "net_income": (
        "本期淨利（淨損）",
        "本期淨利(淨損)",
        "本期淨利",
        "本期稅後淨利（淨損）",
        "稅後淨利",
    ),
    "eps": ("基本每股盈餘（元）", "基本每股盈餘(元)", "基本每股盈餘"),
}

BALANCE_FIELDS: dict[str, tuple[str, ...]] = {
    "cash_and_cash_equivalents": ("現金及約當現金",),
    "inventory": ("存貨",),
    "current_assets": ("流動資產",),
    "total_assets": ("資產總額",),
    "current_liabilities": ("流動負債",),
    "total_liabilities": ("負債總額",),
    "equity": ("權益總額", "權益總計"),
}

MONTHLY_FIELDS: dict[str, tuple[str, ...]] = {
    "monthly_revenue": ("營業收入-當月營收",),
    "previous_month_revenue": ("營業收入-上月營收",),
    "prior_year_month_revenue": ("營業收入-去年當月營收",),
    "monthly_revenue_mom_reported": (
        "營業收入-上月比較增減(%)",
        "營業收入-上月比較增減（%）",
    ),
    "monthly_revenue_yoy_reported": (
        "營業收入-去年同月增減(%)",
        "營業收入-去年同月增減（%）",
    ),
}

MISSING_MARKERS = {"", "-", "--", "－", "—", "N/A", "NA", "null", "None"}


def _first(row: dict[str, Any] | None, aliases: tuple[str, ...]) -> Any | None:
    if row is None:
        return None
    for key in aliases:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def parse_number(value: Any | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if text in MISSING_MARKERS:
        return None

    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").replace("，", "")
    text = text.replace("%", "").replace("％", "").replace("元", "").strip()
    text = re.sub(r"\s+", "", text)
    try:
        parsed = float(text)
    except ValueError:
        return None
    return -parsed if negative else parsed


def _normalize_year(value: Any | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d{2,4}", str(value))
    if not match:
        return None
    year = int(match.group())
    return year + 1911 if year < 1911 else year


def statement_period(row: dict[str, Any] | None) -> str | None:
    if row is None:
        return None
    year = _normalize_year(_first(row, ("年度", "年")))
    quarter_raw = _first(row, ("季別", "季"))
    quarter_match = re.search(r"[1-4]", str(quarter_raw)) if quarter_raw is not None else None
    if year and quarter_match:
        return f"{year}Q{quarter_match.group()}"
    if year:
        return f"{year}FY"
    return None


def monthly_period(row: dict[str, Any] | None) -> str | None:
    raw = _first(row, ("資料年月", "年月"))
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) < 5:
        return None
    roc_year, month = int(digits[:-2]), int(digits[-2:])
    year = roc_year + 1911 if roc_year < 1911 else roc_year
    if not 1 <= month <= 12:
        return None
    return f"{year}-{month:02d}"


def _extract_fields(
    row: dict[str, Any] | None,
    mapping: dict[str, tuple[str, ...]],
) -> tuple[dict[str, float | None], list[str], list[str]]:
    values: dict[str, float | None] = {}
    found: list[str] = []
    missing: list[str] = []
    for canonical, aliases in mapping.items():
        parsed = parse_number(_first(row, aliases))
        values[canonical] = parsed
        (found if parsed is not None else missing).append(canonical)
    return values, found, missing


def normalize_twse_bundle(
    profile: CompanyProfile,
    bundle: dict[str, dict[str, Any] | None],
) -> NormalizedFinancialStatement:
    income = bundle.get("income_statement")
    balance = bundle.get("balance_sheet")
    monthly = bundle.get("monthly_revenue")

    income_values, income_found, income_missing = _extract_fields(income, INCOME_FIELDS)
    balance_values, balance_found, balance_missing = _extract_fields(balance, BALANCE_FIELDS)
    monthly_values, monthly_found, monthly_missing = _extract_fields(monthly, MONTHLY_FIELDS)

    report_period = statement_period(income) or statement_period(balance)
    warnings: list[str] = []
    errors = bundle.get("_errors")
    if isinstance(errors, dict):
        warnings.extend(str(message) for message in errors.get("messages", []))
    if income is None:
        warnings.append("TWSE 綜合損益表資料集未找到該公司資料。")
    if balance is None:
        warnings.append("TWSE 資產負債表資料集未找到該公司資料。")
    if monthly is None:
        warnings.append("TWSE 月營收資料集未找到該公司資料。")

    coverage = [
        SourceCoverage(
            source_name="TWSE 上市公司綜合損益表（一般業）",
            source_url=TwseOpenApiClient.source_url("income_statement"),
            status="available" if income is not None else "missing",
            report_period=statement_period(income),
            fields_found=income_found,
            fields_missing=income_missing,
        ),
        SourceCoverage(
            source_name="TWSE 上市公司資產負債表（一般業）",
            source_url=TwseOpenApiClient.source_url("balance_sheet"),
            status="available" if balance is not None else "missing",
            report_period=statement_period(balance),
            fields_found=balance_found,
            fields_missing=balance_missing,
        ),
        SourceCoverage(
            source_name="TWSE 上市公司每月營業收入彙總表",
            source_url=TwseOpenApiClient.source_url("monthly_revenue"),
            status="available" if monthly is not None else "missing",
            report_period=monthly_period(monthly),
            fields_found=monthly_found,
            fields_missing=monthly_missing,
        ),
    ]

    return NormalizedFinancialStatement(
        ticker=profile.ticker,
        company_name=profile.name,
        subindustry=profile.subindustry,
        report_period=report_period,
        monthly_revenue_period=monthly_period(monthly),
        **income_values,
        **balance_values,
        **monthly_values,
        source_coverage=coverage,
        data_quality_warnings=warnings,
    )
