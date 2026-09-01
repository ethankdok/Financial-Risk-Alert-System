from __future__ import annotations

from collections.abc import Callable

from app.historical_analysis_models import HistoricalPeriodRecord, HistoricalTrendMetric


def _safe_ratio(numerator: float | None, denominator: float | None, multiplier: float = 100.0) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * multiplier


def _growth(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100


def _previous_value(available: list[HistoricalPeriodRecord], period: HistoricalPeriodRecord, field: str) -> float | None:
    previous = next((item for item in available if item.fiscal_year == period.fiscal_year - 1), None)
    return getattr(previous, field) if previous is not None else None


def _average_balance(available: list[HistoricalPeriodRecord], period: HistoricalPeriodRecord, field: str) -> float | None:
    current = getattr(period, field)
    previous = _previous_value(available, period, field)
    if current is None or previous is None:
        return None
    return (current + previous) / 2


def _metric(
    *,
    code: str,
    label: str,
    category: str,
    unit: str,
    periods: list[HistoricalPeriodRecord],
    calculate: Callable[[HistoricalPeriodRecord], float | None],
    formula: str,
    source_fields: list[str],
    percentage_point_change: bool = False,
) -> HistoricalTrendMetric:
    values: dict[str, float] = {}
    for period in periods:
        value = calculate(period)
        if value is not None:
            values[period.period] = round(value, 4)

    ordered = [values[period.period] for period in periods if period.period in values]
    latest = ordered[-1] if ordered else None
    previous = ordered[-2] if len(ordered) >= 2 else None
    change_percent = _growth(latest, previous)
    change_pp = latest - previous if percentage_point_change and latest is not None and previous is not None else None

    return HistoricalTrendMetric(
        code=code,
        label=label,
        category=category,
        unit=unit,
        period_values=values,
        latest_value=latest,
        previous_value=previous,
        change_percent=round(change_percent, 4) if change_percent is not None else None,
        change_percentage_points=round(change_pp, 4) if change_pp is not None else None,
        formula=formula,
        source_fields=source_fields,
    )


def calculate_historical_metrics(periods: list[HistoricalPeriodRecord]) -> list[HistoricalTrendMetric]:
    available = [period for period in periods if period.status == "available"]
    currency_unit = available[-1].currency_unit if available else "新台幣元"
    metrics = [
        _metric(code="revenue", label="營業收入", category="成長性", unit=currency_unit, periods=available,
                calculate=lambda p: p.revenue, formula="MOPS iXBRL 年度營業收入欄位", source_fields=["revenue"]),
        _metric(code="revenue_growth_yoy", label="營收年增率", category="成長性", unit="%", periods=available[1:],
                calculate=lambda p: _growth(p.revenue, _previous_value(available, p, "revenue")),
                formula="（本年度營收－前一年度營收）÷｜前一年度營收｜×100", source_fields=["revenue"]),
        _metric(code="cost_of_goods_sold", label="營業成本", category="獲利能力", unit=currency_unit, periods=available,
                calculate=lambda p: p.cost_of_goods_sold, formula="MOPS iXBRL 年度營業成本欄位", source_fields=["cost_of_goods_sold"]),
        _metric(code="operating_income", label="營業利益", category="成長性", unit=currency_unit, periods=available,
                calculate=lambda p: p.operating_income, formula="MOPS iXBRL 年度營業利益欄位", source_fields=["operating_income"]),
        _metric(code="operating_income_growth_yoy", label="營業利益年增率", category="成長性", unit="%", periods=available[1:],
                calculate=lambda p: _growth(p.operating_income, _previous_value(available, p, "operating_income")),
                formula="（本年度營業利益－前一年度營業利益）÷｜前一年度營業利益｜×100", source_fields=["operating_income"]),
        _metric(code="net_income", label="本期淨利", category="成長性", unit=currency_unit, periods=available,
                calculate=lambda p: p.net_income, formula="MOPS iXBRL 本期淨利欄位", source_fields=["net_income"]),
        _metric(code="net_income_growth_yoy", label="淨利年增率", category="成長性", unit="%", periods=available[1:],
                calculate=lambda p: _growth(p.net_income, _previous_value(available, p, "net_income")),
                formula="（本年度淨利－前一年度淨利）÷｜前一年度淨利｜×100", source_fields=["net_income"]),
        _metric(code="eps", label="每股盈餘", category="成長性", unit="元／股", periods=available,
                calculate=lambda p: p.eps, formula="MOPS iXBRL 每股盈餘欄位", source_fields=["eps"]),
        _metric(code="eps_growth_yoy", label="EPS 年增率", category="成長性", unit="%", periods=available[1:],
                calculate=lambda p: _growth(p.eps, _previous_value(available, p, "eps")),
                formula="（本年度 EPS－前一年度 EPS）÷｜前一年度 EPS｜×100", source_fields=["eps"]),
        _metric(code="gross_margin", label="毛利率", category="獲利能力", unit="%", periods=available,
                calculate=lambda p: _safe_ratio(p.gross_profit, p.revenue), formula="營業毛利÷營業收入×100",
                source_fields=["gross_profit", "revenue"], percentage_point_change=True),
        _metric(code="operating_margin", label="營業利益率", category="獲利能力", unit="%", periods=available,
                calculate=lambda p: _safe_ratio(p.operating_income, p.revenue), formula="營業利益÷營業收入×100",
                source_fields=["operating_income", "revenue"], percentage_point_change=True),
        _metric(code="net_margin", label="淨利率", category="獲利能力", unit="%", periods=available,
                calculate=lambda p: _safe_ratio(p.net_income, p.revenue), formula="本期淨利÷營業收入×100",
                source_fields=["net_income", "revenue"], percentage_point_change=True),
        _metric(code="accounts_receivable", label="應收帳款", category="營運效率", unit=currency_unit, periods=available,
                calculate=lambda p: p.accounts_receivable, formula="MOPS iXBRL 年末應收帳款淨額", source_fields=["accounts_receivable"]),
        _metric(code="receivable_turnover_days", label="應收帳款週轉天數", category="營運效率", unit="天", periods=available[1:],
                calculate=lambda p: _safe_ratio(_average_balance(available, p, "accounts_receivable"), p.revenue, 365.0),
                formula="平均應收帳款÷年度營收×365", source_fields=["accounts_receivable", "revenue"]),
        _metric(code="inventory", label="存貨", category="營運效率", unit=currency_unit, periods=available,
                calculate=lambda p: p.inventory, formula="MOPS iXBRL 年末存貨欄位", source_fields=["inventory"]),
        _metric(code="inventory_growth_yoy", label="存貨年增率", category="營運效率", unit="%", periods=available[1:],
                calculate=lambda p: _growth(p.inventory, _previous_value(available, p, "inventory")),
                formula="（本年度末存貨－前一年度末存貨）÷｜前一年度末存貨｜×100", source_fields=["inventory"]),
        _metric(code="inventory_turnover_days", label="存貨週轉天數", category="營運效率", unit="天", periods=available[1:],
                calculate=lambda p: _safe_ratio(_average_balance(available, p, "inventory"), abs(p.cost_of_goods_sold) if p.cost_of_goods_sold is not None else None, 365.0),
                formula="平均存貨÷｜年度營業成本｜×365", source_fields=["inventory", "cost_of_goods_sold"]),
        _metric(code="operating_cash_flow", label="營業活動現金流", category="現金流品質", unit=currency_unit, periods=available,
                calculate=lambda p: p.operating_cash_flow, formula="MOPS iXBRL 營業活動淨現金流量欄位", source_fields=["operating_cash_flow"]),
        _metric(code="cash_conversion_ratio", label="營業現金流／淨利", category="現金流品質", unit="倍", periods=available,
                calculate=lambda p: _safe_ratio(p.operating_cash_flow, p.net_income, 1.0), formula="營業活動現金流÷本期淨利",
                source_fields=["operating_cash_flow", "net_income"]),
        _metric(code="free_cash_flow", label="自由現金流", category="現金流品質", unit=currency_unit, periods=available,
                calculate=lambda p: (p.operating_cash_flow - abs(p.capital_expenditure) if p.operating_cash_flow is not None and p.capital_expenditure is not None else None),
                formula="營業活動現金流－｜取得不動產、廠房及設備現金流出｜", source_fields=["operating_cash_flow", "capital_expenditure"]),
        _metric(code="capex_intensity", label="資本支出占營收比", category="半導體資本投入", unit="%", periods=available,
                calculate=lambda p: _safe_ratio(abs(p.capital_expenditure) if p.capital_expenditure is not None else None, p.revenue),
                formula="｜取得不動產、廠房及設備現金流出｜÷營業收入×100", source_fields=["capital_expenditure", "revenue"], percentage_point_change=True),
        _metric(code="research_and_development_expense", label="研究發展費用", category="半導體研發投入", unit=currency_unit, periods=available,
                calculate=lambda p: p.research_and_development_expense, formula="MOPS iXBRL 研究發展費用欄位", source_fields=["research_and_development_expense"]),
        _metric(code="rd_expense_growth_yoy", label="研發費用年增率", category="半導體研發投入", unit="%", periods=available[1:],
                calculate=lambda p: _growth(p.research_and_development_expense, _previous_value(available, p, "research_and_development_expense")),
                formula="（本年度研發費用－前一年度研發費用）÷｜前一年度研發費用｜×100", source_fields=["research_and_development_expense"]),
        _metric(code="rd_intensity", label="研發費用占營收比", category="半導體研發投入", unit="%", periods=available,
                calculate=lambda p: _safe_ratio(p.research_and_development_expense, p.revenue), formula="研究發展費用÷營業收入×100",
                source_fields=["research_and_development_expense", "revenue"], percentage_point_change=True),
        _metric(code="debt_ratio", label="負債比", category="財務結構", unit="%", periods=available,
                calculate=lambda p: _safe_ratio(p.total_liabilities, p.total_assets), formula="負債總額÷資產總額×100",
                source_fields=["total_liabilities", "total_assets"], percentage_point_change=True),
        _metric(code="current_ratio", label="流動比率", category="流動性", unit="%", periods=available,
                calculate=lambda p: _safe_ratio(p.current_assets, p.current_liabilities), formula="流動資產÷流動負債×100",
                source_fields=["current_assets", "current_liabilities"], percentage_point_change=True),
    ]
    return metrics
