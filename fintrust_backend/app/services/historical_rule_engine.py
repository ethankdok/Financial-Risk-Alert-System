from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

from app.financial_analysis_models import RuleSeverity
from app.historical_analysis_models import (
    HistoricalPeriodRecord,
    HistoricalRuleResult,
    HistoricalTrendMetric,
)


SUBINDUSTRY_RULE_FILES = {
    "晶圓代工": "foundry_historical_rules.json",
    "IC 設計": "ic_design_historical_rules.json",
    "封裝測試": "packaging_testing_historical_rules.json",
}


class HistoricalFinancialRuleEngine:
    def __init__(
        self,
        rules_path: str | Path | None = None,
        *,
        subindustry: str | None = None,
    ) -> None:
        rules_dir = Path(__file__).resolve().parents[1] / "rules"
        default_path = rules_dir / "semiconductor_historical_rules.json"
        selected_path = Path(rules_path) if rules_path else default_path
        common = json.loads(selected_path.read_text(encoding="utf-8"))
        combined_rules = list(common["rules"])
        versions = [str(common["version"])]
        threshold_bases = [str(common["threshold_basis"])]

        if rules_path is None and subindustry in SUBINDUSTRY_RULE_FILES:
            subindustry_config = json.loads(
                (rules_dir / SUBINDUSTRY_RULE_FILES[subindustry]).read_text(encoding="utf-8")
            )
            combined_rules.extend(subindustry_config["rules"])
            versions.append(str(subindustry_config["version"]))
            threshold_bases.append(str(subindustry_config["threshold_basis"]))

        self.rules_path = selected_path
        self.config = {
            **common,
            "version": "+".join(versions),
            "threshold_basis": "；".join(threshold_bases),
            "rules": combined_rules,
        }
        self.subindustry = subindustry

    @property
    def version(self) -> str:
        return str(self.config["version"])

    @property
    def threshold_basis(self) -> str:
        return str(self.config["threshold_basis"])

    @staticmethod
    def _values(metric: HistoricalTrendMetric | None) -> list[tuple[str, float]]:
        if metric is None:
            return []
        return sorted(metric.period_values.items())

    @staticmethod
    def _rule_metadata(rule: dict[str, Any]) -> dict[str, Any]:
        return {
            "credibility_level": rule.get("credibility_level", "mvp_heuristic"),
            "calibration_status": rule.get("calibration_status", "mvp_threshold"),
            "evidence_basis": rule.get("evidence_basis"),
            "evidence_references": list(rule.get("evidence_references", [])),
            "llm_interpretation_guardrail": rule.get(
                "llm_interpretation_guardrail",
                "LLM may summarize and connect this rule with official evidence, but may not change the deterministic verdict or invent missing financial values.",
            ),
        }

    @classmethod
    def _result(
        cls,
        rule: dict[str, Any],
        severity: RuleSeverity,
        explanation: str,
        threshold_description: str,
        periods: list[str],
        *,
        actual_values: dict[str, float | None] | None = None,
    ) -> HistoricalRuleResult:
        return HistoricalRuleResult(
            rule_id=rule["rule_id"],
            name=rule["name"],
            category=rule["category"],
            severity=severity,
            triggered=severity
            in {
                RuleSeverity.ATTENTION,
                RuleSeverity.HIGH_ATTENTION,
                RuleSeverity.DATA_ISSUE,
            },
            explanation=explanation,
            threshold_description=threshold_description,
            evidence_periods=periods,
            evidence_metrics=list(rule.get("metrics", [])),
            rule_scope=str(rule.get("rule_scope", "semiconductor_common")),
            logic_expression=rule.get("logic_expression"),
            actual_values=actual_values or {},
            **cls._rule_metadata(rule),
        )

    def _insufficient(self, rule: dict[str, Any], message: str) -> HistoricalRuleResult:
        return self._result(
            rule,
            RuleSeverity.INSUFFICIENT_DATA,
            message,
            "缺少規則所需的連續年度或財報欄位。",
            [],
        )

    def evaluate(
        self,
        periods: list[HistoricalPeriodRecord],
        metrics: list[HistoricalTrendMetric],
    ) -> list[HistoricalRuleResult]:
        available_periods = [period for period in periods if period.status == "available"]
        metric_map = {metric.code: metric for metric in metrics}
        results: list[HistoricalRuleResult] = []

        for rule in self.config["rules"]:
            operator = rule["operator"]
            thresholds = rule.get("thresholds", {})
            required = [metric_map.get(code) for code in rule.get("metrics", [])]

            if operator == "minimum_available_years":
                minimum = int(thresholds["minimum"])
                count = len(available_periods)
                severity = RuleSeverity.DATA_ISSUE if count < minimum else RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        (
                            f"目前取得 {count} 個完整年度；至少需要 {minimum} 年才能形成長期趨勢。"
                            if count < minimum
                            else f"目前取得 {count} 個完整年度，已達最低歷史資料涵蓋要求。"
                        ),
                        f"可用完整年度至少 {minimum} 年",
                        [period.period for period in available_periods],
                        actual_values={"available_years": float(count)},
                    )
                )
                continue

            if any(metric is None or not metric.period_values for metric in required):
                results.append(self._insufficient(rule, "缺少此規則需要的歷史指標資料，暫不判斷。"))
                continue

            if operator == "two_consecutive_below":
                metric = required[0]
                values = self._values(metric)
                if len(values) < 2:
                    results.append(self._insufficient(rule, "至少需要兩個連續可比較年度。"))
                    continue
                latest_two = values[-2:]
                high = float(thresholds["high"])
                attention = float(thresholds["attention"])
                latest_values = [value for _, value in latest_two]
                if all(value <= high for value in latest_values):
                    severity = RuleSeverity.HIGH_ATTENTION
                elif all(value < attention for value in latest_values):
                    severity = RuleSeverity.ATTENTION
                else:
                    severity = RuleSeverity.NORMAL
                text = "、".join(f"{period} {value:.2f}{metric.unit}" for period, value in latest_two)
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"最近兩期為 {text}。{rule['rationale']}",
                        f"連續兩期低於 {attention}{metric.unit}；高關注門檻 {high}{metric.unit}",
                        [period for period, _ in latest_two],
                        actual_values={period: value for period, value in latest_two},
                    )
                )
                continue

            if operator == "latest_change_below":
                metric = required[0]
                change = metric.change_percentage_points
                if change is None:
                    results.append(self._insufficient(rule, "缺少兩個年度的比率資料，無法計算百分點變化。"))
                    continue
                if change <= float(thresholds["high"]):
                    severity = RuleSeverity.HIGH_ATTENTION
                elif change <= float(thresholds["attention"]):
                    severity = RuleSeverity.ATTENTION
                else:
                    severity = RuleSeverity.NORMAL
                periods_used = [period for period, _ in self._values(metric)[-2:]]
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"{metric.label}最新年度較前一年度變化 {change:.2f} 個百分點。{rule['rationale']}",
                        f"需注意 ≤ {thresholds['attention']}；高關注 ≤ {thresholds['high']} 個百分點",
                        periods_used,
                        actual_values={"change_percentage_points": change},
                    )
                )
                continue

            if operator == "latest_gap_above":
                left, right = required
                left_values = dict(self._values(left))
                right_values = dict(self._values(right))
                common = sorted(set(left_values) & set(right_values))
                if not common:
                    results.append(self._insufficient(rule, "兩項成長率沒有共同年度。"))
                    continue
                latest_period = common[-1]
                left_value = left_values[latest_period]
                right_value = right_values[latest_period]
                gap = left_value - right_value
                if gap >= float(thresholds["high"]):
                    severity = RuleSeverity.HIGH_ATTENTION
                elif gap >= float(thresholds["attention"]):
                    severity = RuleSeverity.ATTENTION
                else:
                    severity = RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"{latest_period} {left.label} 與 {right.label} 差距為 {gap:.2f} 個百分點。{rule['rationale']}",
                        f"差距 ≥ {thresholds['attention']} 個百分點需注意；≥ {thresholds['high']} 高關注",
                        [latest_period],
                        actual_values={
                            "left_value": left_value,
                            "right_value": right_value,
                            "gap_percentage_points": gap,
                        },
                    )
                )
                continue

            if operator == "positive_profit_negative_ocf":
                net_margin, ocf = required
                net_values = dict(self._values(net_margin))
                ocf_values = dict(self._values(ocf))
                common = sorted(set(net_values) & set(ocf_values))
                if not common:
                    results.append(self._insufficient(rule, "淨利率與營業現金流沒有共同年度。"))
                    continue
                latest = common[-1]
                condition = net_values[latest] > 0 and ocf_values[latest] < 0
                severity = RuleSeverity.ATTENTION if condition else RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"{latest} 淨利率 {net_values[latest]:.2f}%、營業現金流 {ocf_values[latest]:,.0f}{ocf.unit}。{rule['rationale']}",
                        "淨利率為正但營業現金流為負",
                        [latest],
                        actual_values={"net_margin": net_values[latest], "operating_cash_flow": ocf_values[latest]},
                    )
                )
                continue

            if operator == "latest_or_two_negative":
                metric = required[0]
                values = self._values(metric)
                if not values:
                    results.append(self._insufficient(rule, "缺少自由現金流資料。"))
                    continue
                latest_period, latest_value = values[-1]
                latest_two = values[-2:]
                if len(latest_two) >= 2 and all(value < 0 for _, value in latest_two):
                    severity = RuleSeverity.HIGH_ATTENTION
                elif latest_value < 0:
                    severity = RuleSeverity.ATTENTION
                else:
                    severity = RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"最新年度 {latest_period} 自由現金流 {latest_value:,.0f}{metric.unit}。{rule['rationale']}",
                        "單年度為負需注意；連續兩年為負提高關注",
                        [period for period, _ in latest_two],
                        actual_values={period: value for period, value in latest_two},
                    )
                )
                continue

            if operator == "latest_above_median_with_negative":
                ratio_metric, cash_metric = required
                ratio_values = self._values(ratio_metric)
                cash_values = dict(self._values(cash_metric))
                if len(ratio_values) < 2:
                    results.append(self._insufficient(rule, "至少需要兩年以上資本支出強度資料。"))
                    continue
                latest_period, latest_ratio = ratio_values[-1]
                historical_baseline = median(value for _, value in ratio_values[:-1])
                gap = latest_ratio - historical_baseline
                cash_value = cash_values.get(latest_period)
                if cash_value is None:
                    results.append(self._insufficient(rule, "缺少同年度自由現金流資料。"))
                    continue
                if gap >= float(thresholds["high_gap"]) and cash_value < 0:
                    severity = RuleSeverity.HIGH_ATTENTION
                elif gap >= float(thresholds["attention_gap"]) and cash_value < 0:
                    severity = RuleSeverity.ATTENTION
                else:
                    severity = RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        (
                            f"{latest_period} {ratio_metric.label} {latest_ratio:.2f}{ratio_metric.unit}，"
                            f"較歷史中位數高 {gap:.2f} 個百分點；自由現金流 {cash_value:,.0f}{cash_metric.unit}。{rule['rationale']}"
                        ),
                        f"高於歷史中位數 {thresholds['attention_gap']} 個百分點且自由現金流為負需注意",
                        [latest_period],
                        actual_values={
                            "latest_ratio": latest_ratio,
                            "historical_median": historical_baseline,
                            "gap_percentage_points": gap,
                            "free_cash_flow": cash_value,
                        },
                    )
                )
                continue

            if operator == "latest_level_and_change_above":
                metric = required[0]
                values = self._values(metric)
                if len(values) < 2:
                    results.append(self._insufficient(rule, "至少需要兩年資料計算水準與變化。"))
                    continue
                previous_period, previous_value = values[-2]
                latest_period, latest_value = values[-1]
                change = latest_value - previous_value
                if latest_value >= float(thresholds["level_high"]) and change >= float(thresholds["change_attention"]):
                    severity = RuleSeverity.HIGH_ATTENTION
                elif latest_value >= float(thresholds["level_attention"]) and change >= float(thresholds["change_attention"]):
                    severity = RuleSeverity.ATTENTION
                else:
                    severity = RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"{latest_period} {metric.label} {latest_value:.2f}{metric.unit}，較 {previous_period} 變化 {change:.2f} 個百分點。{rule['rationale']}",
                        f"水準 ≥ {thresholds['level_attention']} 且增加 ≥ {thresholds['change_attention']} 個百分點需注意",
                        [previous_period, latest_period],
                        actual_values={
                            "latest_value": latest_value,
                            "previous_value": previous_value,
                            "change_percentage_points": change,
                        },
                    )
                )
                continue

            if operator == "informational_trend":
                metric = required[0]
                values = self._values(metric)
                if not values:
                    results.append(self._insufficient(rule, "缺少研發投入資料。"))
                    continue
                latest_period, latest_value = values[-1]
                change = metric.change_percentage_points
                explanation = f"{latest_period} {metric.label} {latest_value:.2f}{metric.unit}。"
                if change is not None:
                    explanation += f"較前期變化 {change:.2f} 個百分點。"
                explanation += rule["rationale"]
                results.append(
                    self._result(
                        rule,
                        RuleSeverity.NORMAL,
                        explanation,
                        "資訊性趨勢，不直接列為風險",
                        [period for period, _ in values[-2:]],
                        actual_values={"latest_value": latest_value, "change_percentage_points": change},
                    )
                )
                continue

            if operator == "foundry_capex_margin_pressure":
                capex, fcf, gross_margin = required
                capex_values = self._values(capex)
                fcf_values = dict(self._values(fcf))
                margin_change = gross_margin.change_percentage_points
                if len(capex_values) < 2 or margin_change is None:
                    results.append(self._insufficient(rule, "缺少晶圓代工資本支出或毛利率變化資料。"))
                    continue
                latest_period, latest_capex = capex_values[-1]
                capex_baseline = median(value for _, value in capex_values[:-1])
                capex_gap = latest_capex - capex_baseline
                fcf_latest = fcf_values.get(latest_period)
                if fcf_latest is None:
                    results.append(self._insufficient(rule, "缺少同年度自由現金流資料。"))
                    continue
                high_condition = (
                    capex_gap >= float(thresholds["high_capex_gap"])
                    and fcf_latest < 0
                    and margin_change <= float(thresholds["high_margin_drop"])
                )
                attention_condition = (
                    capex_gap >= float(thresholds["attention_capex_gap"])
                    and fcf_latest < 0
                    and margin_change <= float(thresholds["attention_margin_drop"])
                )
                severity = RuleSeverity.HIGH_ATTENTION if high_condition else RuleSeverity.ATTENTION if attention_condition else RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"{latest_period} 資本支出強度較自身歷史中位數高 {capex_gap:.2f} 個百分點，自由現金流 {fcf_latest:,.0f}{fcf.unit}，毛利率變化 {margin_change:.2f} 個百分點。{rule['rationale']}",
                        "資本支出高於自身歷史基準，且自由現金流為負、毛利率同步下滑",
                        [latest_period],
                        actual_values={
                            "capex_gap_percentage_points": capex_gap,
                            "free_cash_flow": fcf_latest,
                            "gross_margin_change_percentage_points": margin_change,
                        },
                    )
                )
                continue

            if operator == "ic_design_rd_conversion_pressure":
                rd, revenue_growth, inventory_growth, cash_conversion = required
                common = sorted(
                    set(rd.period_values)
                    & set(revenue_growth.period_values)
                    & set(inventory_growth.period_values)
                    & set(cash_conversion.period_values)
                )
                if not common or rd.change_percentage_points is None:
                    results.append(self._insufficient(rule, "缺少 IC 設計研發、營收、存貨或現金轉換資料。"))
                    continue
                latest = common[-1]
                inventory_gap = inventory_growth.period_values[latest] - revenue_growth.period_values[latest]
                cash_value = cash_conversion.period_values[latest]
                rd_change = rd.change_percentage_points
                high_condition = (
                    rd_change >= float(thresholds["rd_change_min"])
                    and revenue_growth.period_values[latest] < 0
                    and inventory_gap >= float(thresholds["high_inventory_gap"])
                    and cash_value < float(thresholds["high_cash_conversion_max"])
                )
                attention_condition = (
                    rd_change >= float(thresholds["rd_change_min"])
                    and revenue_growth.period_values[latest] < 0
                    and inventory_gap >= float(thresholds["attention_inventory_gap"])
                    and cash_value < float(thresholds["attention_cash_conversion_max"])
                )
                severity = RuleSeverity.HIGH_ATTENTION if high_condition else RuleSeverity.ATTENTION if attention_condition else RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"{latest} 研發強度變化 {rd_change:.2f} 個百分點、營收年增率 {revenue_growth.period_values[latest]:.2f}%、存貨與營收成長差距 {inventory_gap:.2f} 個百分點、現金轉換比 {cash_value:.2f}。{rule['rationale']}",
                        "研發強度提高時，若營收下滑、存貨增速明顯高於營收且現金轉換偏弱，才提高關注",
                        [latest],
                        actual_values={
                            "rd_intensity_change_percentage_points": rd_change,
                            "revenue_growth_yoy": revenue_growth.period_values[latest],
                            "inventory_revenue_gap_percentage_points": inventory_gap,
                            "cash_conversion_ratio": cash_value,
                        },
                    )
                )
                continue

            if operator == "packaging_working_capital_pressure":
                inventory_growth, revenue_growth, ocf, debt_ratio = required
                common = sorted(
                    set(inventory_growth.period_values)
                    & set(revenue_growth.period_values)
                    & set(ocf.period_values)
                    & set(debt_ratio.period_values)
                )
                if len(common) < 2:
                    results.append(self._insufficient(rule, "封裝測試規則至少需要兩年共同資料。"))
                    continue
                previous, latest = common[-2], common[-1]
                inventory_gap = inventory_growth.period_values[latest] - revenue_growth.period_values[latest]
                ocf_change = ocf.period_values[latest] - ocf.period_values[previous]
                debt_change = debt_ratio.period_values[latest] - debt_ratio.period_values[previous]
                high_condition = (
                    inventory_gap >= float(thresholds["high_inventory_gap"])
                    and ocf_change < 0
                    and debt_change >= float(thresholds["high_debt_change"])
                )
                attention_condition = (
                    inventory_gap >= float(thresholds["attention_inventory_gap"])
                    and ocf_change < 0
                    and debt_change >= float(thresholds["attention_debt_change"])
                )
                severity = RuleSeverity.HIGH_ATTENTION if high_condition else RuleSeverity.ATTENTION if attention_condition else RuleSeverity.NORMAL
                results.append(
                    self._result(
                        rule,
                        severity,
                        f"{latest} 存貨與營收成長差距 {inventory_gap:.2f} 個百分點，營業現金流較前期變化 {ocf_change:,.0f}{ocf.unit}，負債比變化 {debt_change:.2f} 個百分點。{rule['rationale']}",
                        "存貨相對營收壓力、營業現金流惡化與負債比上升同步出現才提高關注",
                        [previous, latest],
                        actual_values={
                            "inventory_revenue_gap_percentage_points": inventory_gap,
                            "operating_cash_flow_change": ocf_change,
                            "debt_ratio_change_percentage_points": debt_change,
                        },
                    )
                )
                continue

            results.append(self._insufficient(rule, f"尚未支援的規則運算子：{operator}"))

        return results
