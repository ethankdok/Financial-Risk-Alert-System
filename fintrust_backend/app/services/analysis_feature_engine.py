from __future__ import annotations

from app.ai_analysis_models import AnalysisFeatureValue
from app.historical_analysis_models import HistoricalTrendMetric


class AnalysisFeatureEngine:
    """Build monitorable direct and derived features from historical metrics."""

    @staticmethod
    def _add(
        features: dict[str, AnalysisFeatureValue],
        *,
        code: str,
        value: float | None,
        unit: str,
        label: str,
        source_metrics: list[str],
        formula: str,
    ) -> None:
        if value is None:
            return
        features[code] = AnalysisFeatureValue(
            code=code,
            value=round(float(value), 4),
            unit=unit,
            label=label,
            source_metrics=source_metrics,
            formula=formula,
        )

    def build(self, metrics: list[HistoricalTrendMetric]) -> dict[str, AnalysisFeatureValue]:
        features: dict[str, AnalysisFeatureValue] = {}

        for metric in metrics:
            self._add(
                features,
                code=metric.code,
                value=metric.latest_value,
                unit=metric.unit,
                label=metric.label,
                source_metrics=[metric.code],
                formula=f"最新年度值；{metric.formula}",
            )
            self._add(
                features,
                code=f"{metric.code}_change_percent",
                value=metric.change_percent,
                unit="%",
                label=f"{metric.label}較前期變化率",
                source_metrics=[metric.code],
                formula="（最新值－前期值）÷｜前期值｜×100",
            )
            self._add(
                features,
                code=f"{metric.code}_change_pp",
                value=metric.change_percentage_points,
                unit="百分點",
                label=f"{metric.label}較前期百分點變化",
                source_metrics=[metric.code],
                formula="最新比率－前期比率",
            )
            absolute_change = (
                metric.latest_value - metric.previous_value
                if metric.latest_value is not None and metric.previous_value is not None
                else None
            )
            self._add(
                features,
                code=f"{metric.code}_change_absolute",
                value=absolute_change,
                unit=metric.unit,
                label=f"{metric.label}較前期絕對變化",
                source_metrics=[metric.code],
                formula="最新值－前期值",
            )

        def value(code: str) -> float | None:
            feature = features.get(code)
            return feature.value if feature else None

        revenue_growth = value("revenue_growth_yoy")
        inventory_growth = value("inventory_growth_yoy")
        if revenue_growth is not None and inventory_growth is not None:
            self._add(
                features,
                code="inventory_revenue_gap",
                value=inventory_growth - revenue_growth,
                unit="百分點",
                label="存貨與營收成長差距",
                source_metrics=["inventory_growth_yoy", "revenue_growth_yoy"],
                formula="存貨年增率－營收年增率",
            )

        net_income_growth = value("net_income_growth_yoy")
        ocf_change = value("operating_cash_flow_change_percent")
        if net_income_growth is not None and ocf_change is not None:
            self._add(
                features,
                code="profit_cash_growth_gap",
                value=net_income_growth - ocf_change,
                unit="百分點",
                label="淨利與營業現金流成長差距",
                source_metrics=["net_income_growth_yoy", "operating_cash_flow"],
                formula="淨利年增率－營業活動現金流變化率",
            )

        rd_growth = value("rd_expense_growth_yoy")
        if rd_growth is not None and revenue_growth is not None:
            self._add(
                features,
                code="rd_revenue_growth_gap",
                value=rd_growth - revenue_growth,
                unit="百分點",
                label="研發費用與營收成長差距",
                source_metrics=["rd_expense_growth_yoy", "revenue_growth_yoy"],
                formula="研發費用年增率－營收年增率",
            )

        margin_changes = [
            value("gross_margin_change_pp"),
            value("operating_margin_change_pp"),
            value("net_margin_change_pp"),
        ]
        available_margin_changes = [item for item in margin_changes if item is not None]
        if available_margin_changes:
            self._add(
                features,
                code="profitability_decline_count",
                value=sum(item < 0 for item in available_margin_changes),
                unit="項",
                label="獲利率下降指標數",
                source_metrics=["gross_margin", "operating_margin", "net_margin"],
                formula="毛利率、營業利益率、淨利率中下降者的數量",
            )
            self._add(
                features,
                code="profitability_improve_count",
                value=sum(item > 0 for item in available_margin_changes),
                unit="項",
                label="獲利率改善指標數",
                source_metrics=["gross_margin", "operating_margin", "net_margin"],
                formula="毛利率、營業利益率、淨利率中改善者的數量",
            )

        growth_codes = [
            "revenue_growth_yoy",
            "operating_income_growth_yoy",
            "net_income_growth_yoy",
            "eps_growth_yoy",
        ]
        growth_values = [value(code) for code in growth_codes]
        available_growth_values = [item for item in growth_values if item is not None]
        if available_growth_values:
            self._add(
                features,
                code="growth_positive_count",
                value=sum(item > 0 for item in available_growth_values),
                unit="項",
                label="主要成長指標正成長數",
                source_metrics=growth_codes,
                formula="營收、營業利益、淨利、EPS 成長率中大於零者的數量",
            )
            self._add(
                features,
                code="growth_negative_count",
                value=sum(item < 0 for item in available_growth_values),
                unit="項",
                label="主要成長指標負成長數",
                source_metrics=growth_codes,
                formula="營收、營業利益、淨利、EPS 成長率中小於零者的數量",
            )

        return features
