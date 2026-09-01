from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.financial_analysis_models import (
    CalculatedMetric,
    RuleCatalogItem,
    RuleCatalogResponse,
    RuleResult,
    RuleSeverity,
)


class FinancialRuleEngine:
    def __init__(self, rules_path: str | Path | None = None) -> None:
        default_path = Path(__file__).resolve().parents[1] / "rules" / "semiconductor_rules.json"
        self.rules_path = Path(rules_path) if rules_path else default_path
        self.config = json.loads(self.rules_path.read_text(encoding="utf-8"))

    @property
    def version(self) -> str:
        return str(self.config["version"])

    @property
    def threshold_basis(self) -> str:
        return str(self.config["threshold_basis"])

    def catalog(self) -> RuleCatalogResponse:
        return RuleCatalogResponse(
            version=self.version,
            threshold_basis=self.threshold_basis,
            rules=[RuleCatalogItem(**rule) for rule in self.config["rules"]],
        )

    @staticmethod
    def _threshold_description(rule: dict[str, Any]) -> str:
        thresholds = rule.get("thresholds", {})
        operator = rule["operator"]
        if operator == "decline_band":
            return (
                f"高關注 ≤ {thresholds['high']}；需注意 ≤ {thresholds['attention']}；"
                f"正向訊號 ≥ {thresholds['positive']} {rule['unit']}"
            )
        if operator == "min":
            return (
                f"高關注 ≤ {thresholds['high']}；需注意 < {thresholds['attention']} "
                f"{rule['unit']}"
            )
        if operator == "max":
            return (
                f"高關注 ≥ {thresholds['high']}；需注意 ≥ {thresholds['attention']} "
                f"{rule['unit']}"
            )
        if operator == "abs_max":
            return (
                f"資料問題：絕對值 ≥ {thresholds['attention']}；"
                f"重大差異 ≥ {thresholds['high']} {rule['unit']}"
            )
        return str(thresholds)

    @staticmethod
    def _evaluate_value(rule: dict[str, Any], value: float) -> RuleSeverity:
        thresholds = rule["thresholds"]
        operator = rule["operator"]

        if operator == "decline_band":
            if value <= thresholds["high"]:
                return RuleSeverity.HIGH_ATTENTION
            if value <= thresholds["attention"]:
                return RuleSeverity.ATTENTION
            if value >= thresholds["positive"]:
                return RuleSeverity.POSITIVE
            return RuleSeverity.NORMAL

        if operator == "min":
            if value <= thresholds["high"]:
                return RuleSeverity.HIGH_ATTENTION
            if value < thresholds["attention"]:
                return RuleSeverity.ATTENTION
            return RuleSeverity.NORMAL

        if operator == "max":
            if value >= thresholds["high"]:
                return RuleSeverity.HIGH_ATTENTION
            if value >= thresholds["attention"]:
                return RuleSeverity.ATTENTION
            return RuleSeverity.NORMAL

        if operator == "abs_max":
            if abs(value) >= thresholds["attention"]:
                return RuleSeverity.DATA_ISSUE
            return RuleSeverity.NORMAL

        raise ValueError(f"Unsupported rule operator: {operator}")

    @staticmethod
    def _explanation(rule: dict[str, Any], metric: CalculatedMetric, severity: RuleSeverity) -> str:
        actual = f"{metric.value:.2f}{metric.unit}"
        if severity == RuleSeverity.POSITIVE:
            return f"{metric.label}為 {actual}，達到此規則設定的正向觀察區間。"
        if severity == RuleSeverity.HIGH_ATTENTION:
            return f"{metric.label}為 {actual}，已觸發高關注門檻。{rule['rationale']}"
        if severity == RuleSeverity.ATTENTION:
            return f"{metric.label}為 {actual}，已觸發需注意門檻。{rule['rationale']}"
        if severity == RuleSeverity.DATA_ISSUE:
            return f"{metric.label}為 {actual}，超出資料一致性容許範圍，應先檢查欄位、期間與單位。"
        return f"{metric.label}為 {actual}，未觸發此規則的注意門檻。"

    def evaluate(self, metrics: list[CalculatedMetric]) -> list[RuleResult]:
        metric_map = {metric.code: metric for metric in metrics}
        results: list[RuleResult] = []

        for rule in self.config["rules"]:
            metric = metric_map.get(rule["metric"])
            threshold_description = self._threshold_description(rule)
            if metric is None:
                results.append(
                    RuleResult(
                        rule_id=rule["rule_id"],
                        name=rule["name"],
                        category=rule["category"],
                        severity=RuleSeverity.INSUFFICIENT_DATA,
                        triggered=False,
                        metric_code=rule["metric"],
                        unit=rule["unit"],
                        threshold_description=threshold_description,
                        explanation="缺少此規則需要的財報欄位或分母為零，暫不做判斷。",
                        evidence_metrics=[rule["metric"]],
                    )
                )
                continue

            severity = self._evaluate_value(rule, metric.value)
            results.append(
                RuleResult(
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
                    metric_code=metric.code,
                    actual_value=metric.value,
                    unit=metric.unit,
                    threshold_description=threshold_description,
                    explanation=self._explanation(rule, metric, severity),
                    evidence_metrics=[metric.code],
                )
            )

        return results
