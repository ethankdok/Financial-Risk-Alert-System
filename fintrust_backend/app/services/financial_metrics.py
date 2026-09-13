from __future__ import annotations

from app.financial_analysis_models import CalculatedMetric, NormalizedFinancialStatement


def _ratio(
    *,
    code: str,
    label: str,
    category: str,
    numerator_label: str,
    numerator: float | None,
    denominator_label: str,
    denominator: float | None,
    source_fields: list[str],
) -> CalculatedMetric | None:
    if numerator is None or denominator in (None, 0):
        return None
    value = numerator / denominator * 100
    return CalculatedMetric(
        code=code,
        label=label,
        category=category,
        value=round(value, 4),
        unit="%",
        formula=f"{numerator_label} ÷ {denominator_label} × 100",
        inputs={numerator_label: numerator, denominator_label: denominator},
        source_fields=source_fields,
    )


def _direct(
    code: str,
    label: str,
    category: str,
    value: float | None,
    unit: str,
    source_field: str,
) -> CalculatedMetric | None:
    if value is None:
        return None
    return CalculatedMetric(
        code=code,
        label=label,
        category=category,
        value=round(value, 4),
        unit=unit,
        formula="官方財報欄位",
        inputs={source_field: value},
        source_fields=[source_field],
    )


def calculate_financial_metrics(
    statement: NormalizedFinancialStatement,
) -> list[CalculatedMetric]:
    metrics: list[CalculatedMetric] = []

    candidates = [
        _ratio(
            code="gross_margin",
            label="毛利率",
            category="獲利能力",
            numerator_label="營業毛利",
            numerator=statement.gross_profit,
            denominator_label="營業收入",
            denominator=statement.revenue,
            source_fields=["gross_profit", "revenue"],
        ),
        _ratio(
            code="operating_margin",
            label="營業利益率",
            category="獲利能力",
            numerator_label="營業利益",
            numerator=statement.operating_income,
            denominator_label="營業收入",
            denominator=statement.revenue,
            source_fields=["operating_income", "revenue"],
        ),
        _ratio(
            code="net_margin",
            label="淨利率",
            category="獲利能力",
            numerator_label="本期淨利",
            numerator=statement.net_income,
            denominator_label="營業收入",
            denominator=statement.revenue,
            source_fields=["net_income", "revenue"],
        ),
        _ratio(
            code="debt_ratio",
            label="負債比",
            category="財務結構",
            numerator_label="負債總額",
            numerator=statement.total_liabilities,
            denominator_label="資產總額",
            denominator=statement.total_assets,
            source_fields=["total_liabilities", "total_assets"],
        ),
        _ratio(
            code="equity_ratio",
            label="權益比率",
            category="財務結構",
            numerator_label="權益總額",
            numerator=statement.equity,
            denominator_label="資產總額",
            denominator=statement.total_assets,
            source_fields=["equity", "total_assets"],
        ),
        _ratio(
            code="current_ratio",
            label="流動比率",
            category="流動性",
            numerator_label="流動資產",
            numerator=statement.current_assets,
            denominator_label="流動負債",
            denominator=statement.current_liabilities,
            source_fields=["current_assets", "current_liabilities"],
        ),
        _ratio(
            code="inventory_to_assets",
            label="存貨占資產比",
            category="營運效率",
            numerator_label="存貨",
            numerator=statement.inventory,
            denominator_label="資產總額",
            denominator=statement.total_assets,
            source_fields=["inventory", "total_assets"],
        ),
        _direct(
            "equity_value",
            "權益總額",
            "財務結構",
            statement.equity,
            statement.currency_unit,
            "equity",
        ),
        _direct(
            "eps",
            "基本每股盈餘",
            "獲利能力",
            statement.eps,
            "元",
            "eps",
        ),
    ]
    metrics.extend(metric for metric in candidates if metric is not None)

    if statement.total_assets not in (None, 0) and statement.total_liabilities is not None and statement.equity is not None:
        gap = statement.total_assets - statement.total_liabilities - statement.equity
        gap_percent = gap / abs(statement.total_assets) * 100
        metrics.append(
            CalculatedMetric(
                code="accounting_equation_gap_percent",
                label="會計恆等式差異率",
                category="資料品質",
                value=round(gap_percent, 4),
                unit="%",
                formula="（資產總額－負債總額－權益總額）÷｜資產總額｜×100",
                inputs={
                    "資產總額": statement.total_assets,
                    "負債總額": statement.total_liabilities,
                    "權益總額": statement.equity,
                },
                source_fields=["total_assets", "total_liabilities", "equity"],
            )
        )

    if statement.monthly_revenue is not None and statement.prior_year_month_revenue not in (None, 0):
        yoy = (
            (statement.monthly_revenue - statement.prior_year_month_revenue)
            / abs(statement.prior_year_month_revenue)
            * 100
        )
        metrics.append(
            CalculatedMetric(
                code="monthly_revenue_yoy",
                label="單月營收年增率",
                category="成長性",
                value=round(yoy, 4),
                unit="%",
                formula="（當月營收－去年同月營收）÷｜去年同月營收｜×100",
                inputs={
                    "當月營收": statement.monthly_revenue,
                    "去年同月營收": statement.prior_year_month_revenue,
                },
                source_fields=["monthly_revenue", "prior_year_month_revenue"],
            )
        )
        if statement.monthly_revenue_yoy_reported is not None:
            metrics.append(
                CalculatedMetric(
                    code="monthly_revenue_yoy_reported_gap",
                    label="營收年增率揭露差異",
                    category="資料品質",
                    value=round(yoy - statement.monthly_revenue_yoy_reported, 4),
                    unit="百分點",
                    formula="系統重算年增率－交易所揭露年增率",
                    inputs={
                        "系統重算年增率": yoy,
                        "交易所揭露年增率": statement.monthly_revenue_yoy_reported,
                    },
                    source_fields=[
                        "monthly_revenue",
                        "prior_year_month_revenue",
                        "monthly_revenue_yoy_reported",
                    ],
                )
            )

    if statement.monthly_revenue is not None and statement.previous_month_revenue not in (None, 0):
        mom = (
            (statement.monthly_revenue - statement.previous_month_revenue)
            / abs(statement.previous_month_revenue)
            * 100
        )
        metrics.append(
            CalculatedMetric(
                code="monthly_revenue_mom",
                label="單月營收月增率",
                category="成長性",
                value=round(mom, 4),
                unit="%",
                formula="（當月營收－上月營收）÷｜上月營收｜×100",
                inputs={
                    "當月營收": statement.monthly_revenue,
                    "上月營收": statement.previous_month_revenue,
                },
                source_fields=["monthly_revenue", "previous_month_revenue"],
            )
        )

    return metrics
