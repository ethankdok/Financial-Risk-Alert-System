from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.ai_analysis_models import (
    AnalysisDimension,
    AnalysisFeatureValue,
    AnalysisRuleCatalogItem,
    AnalysisRuleCatalogResponse,
    DIMENSION_LABELS,
    MonitoredRuleResult,
    RuleEvaluationStatus,
)
from app.financial_analysis_models import RuleSeverity


class MonitorableFinancialRuleEngine:
    """Config-driven layered rule engine with explicit provenance for monitoring."""

    def __init__(self, *, subindustry: str = "IC 設計") -> None:
        if subindustry != "IC 設計":
            raise ValueError("AI analysis engine v2 currently provides a full layered catalog for IC 設計.")
        rules_dir = Path(__file__).resolve().parents[1] / "rules"
        self.subindustry = subindustry
        self.configs = [
            self._load(rules_dir / "common_analysis_rules.json"),
            self._load(rules_dir / "semiconductor_analysis_rules.json"),
            self._load(rules_dir / "ic_design_analysis_rules.json"),
        ]
        self.rules: list[dict[str, Any]] = []
        for config in self.configs:
            for raw_rule in config["rules"]:
                rule = dict(raw_rule)
                rule["rule_scope"] = config["scope"]
                rule["rule_version"] = config["version"]
                self.rules.append(rule)

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def version(self) -> str:
        return "+".join(str(config["version"]) for config in self.configs)

    @staticmethod
    def _collect_features(condition: dict[str, Any]) -> set[str]:
        if "feature" in condition:
            return {str(condition["feature"])}
        found: set[str] = set()
        for key in ("all", "any"):
            for child in condition.get(key, []):
                found.update(MonitorableFinancialRuleEngine._collect_features(child))
        if "not" in condition:
            found.update(MonitorableFinancialRuleEngine._collect_features(condition["not"]))
        return found

    @staticmethod
    def _compare(actual: float, op: str, expected: float) -> bool:
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        if op == "lte":
            return actual <= expected
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        raise ValueError(f"Unsupported monitorable rule operator: {op}")

    @classmethod
    def _evaluate_condition(cls, condition: dict[str, Any], feature_values: dict[str, float]) -> bool:
        if "feature" in condition:
            return cls._compare(
                feature_values[str(condition["feature"])],
                str(condition["op"]),
                float(condition["value"]),
            )
        if "all" in condition:
            return all(cls._evaluate_condition(child, feature_values) for child in condition["all"])
        if "any" in condition:
            return any(cls._evaluate_condition(child, feature_values) for child in condition["any"])
        if "not" in condition:
            return not cls._evaluate_condition(condition["not"], feature_values)
        raise ValueError("Rule condition must contain feature, all, any, or not.")

    def catalog(self) -> AnalysisRuleCatalogResponse:
        items: list[AnalysisRuleCatalogItem] = []
        scope_counts: dict[str, int] = {}
        for rule in self.rules:
            dimension = AnalysisDimension(rule["dimension"])
            required = sorted(self._collect_features(rule["condition"]))
            scope = str(rule["rule_scope"])
            scope_counts[scope] = scope_counts.get(scope, 0) + 1
            items.append(
                AnalysisRuleCatalogItem(
                    rule_id=rule["rule_id"],
                    name=rule["name"],
                    rule_scope=scope,
                    rule_version=rule["rule_version"],
                    dimension=dimension,
                    dimension_label=DIMENSION_LABELS[dimension],
                    assessment_type=rule["assessment_type"],
                    severity=RuleSeverity(rule["severity"]),
                    logic_expression=rule["logic_expression"],
                    rationale=rule["rationale"],
                    threshold_basis=rule["threshold_basis"],
                    evidence_basis=rule["evidence_basis"],
                    evidence_references=rule.get("evidence_references", []),
                    direct_metrics=rule.get("direct_metrics", []),
                    indirect_metrics=rule.get("indirect_metrics", []),
                    required_features=required,
                )
            )
        return AnalysisRuleCatalogResponse(
            version=self.version,
            subindustry=self.subindustry,
            rule_count=len(items),
            rule_scope_counts=scope_counts,
            dimensions=sorted({item.dimension for item in items}, key=lambda item: item.value),
            rules=items,
        )

    def evaluate(self, features: dict[str, AnalysisFeatureValue]) -> list[MonitoredRuleResult]:
        feature_values = {code: feature.value for code, feature in features.items()}
        results: list[MonitoredRuleResult] = []

        for rule in self.rules:
            dimension = AnalysisDimension(rule["dimension"])
            required = sorted(self._collect_features(rule["condition"]))
            missing = [code for code in required if code not in feature_values]
            actual_values = {code: feature_values.get(code) for code in required}
            common_kwargs = dict(
                rule_id=rule["rule_id"],
                name=rule["name"],
                rule_scope=rule["rule_scope"],
                rule_version=rule["rule_version"],
                dimension=dimension,
                dimension_label=DIMENSION_LABELS[dimension],
                assessment_type=rule["assessment_type"],
                logic_expression=rule["logic_expression"],
                threshold_basis=rule["threshold_basis"],
                evidence_basis=rule["evidence_basis"],
                evidence_references=rule.get("evidence_references", []),
                direct_metrics=rule.get("direct_metrics", []),
                indirect_metrics=rule.get("indirect_metrics", []),
                required_features=required,
                actual_values=actual_values,
            )
            if missing:
                results.append(
                    MonitoredRuleResult(
                        **common_kwargs,
                        severity=RuleSeverity.INSUFFICIENT_DATA,
                        evaluation_status=RuleEvaluationStatus.INSUFFICIENT_DATA,
                        triggered=False,
                        missing_features=missing,
                        rationale=rule["rationale"],
                    )
                )
                continue

            try:
                triggered = self._evaluate_condition(rule["condition"], feature_values)
                severity = RuleSeverity(rule["severity"]) if triggered else RuleSeverity.NORMAL
                status = RuleEvaluationStatus.EVALUATED
                error = None
            except (KeyError, TypeError, ValueError) as exc:
                triggered = False
                severity = RuleSeverity.DATA_ISSUE
                status = RuleEvaluationStatus.ERROR
                error = str(exc)

            results.append(
                MonitoredRuleResult(
                    **common_kwargs,
                    severity=severity,
                    evaluation_status=status,
                    triggered=triggered,
                    missing_features=[],
                    rationale=(rule["rationale"] if error is None else f"規則執行錯誤：{error}"),
                )
            )

        return results
