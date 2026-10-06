"""User-facing presentation of the financial narrative.

The deterministic evidence keeps its rule IDs, feature codes and signal values for
traceability. The narrative a user reads must not: this module rewrites those
identifiers into the Chinese labels the same payload already carries (feature
label + unit, rule name, dimension label). It only re-labels and re-formats values
that are already in the text; it never computes or adds a number.

It runs when a narrative is generated and again when a stored snapshot is served,
so narratives persisted before this layer existed are shown the same way.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

from app.ai_analysis_models import DIMENSION_LABELS, LLMNarrative

SIGNAL_LABELS: dict[str, str] = {
    "positive": "正向觀察",
    "normal": "未見明顯異常",
    "attention": "需注意",
    "high_attention": "高度關注",
    "mixed": "訊號分歧",
    "insufficient_data": "資料不足",
    "insufficient": "資料不足",
    "data_issue": "資料需確認",
}
# Engineering field names an LLM may echo from the evidence payload.
FIELD_PHRASES: dict[str, str] = {
    "actual_values": "實際數值",
    "evaluated_rules": "納入評估的規則數",
    "total_rules": "規則總數",
    "triggered_rule_ids": "觸發的規則",
    "rule_id": "規則",
    "coverage_ratio": "規則涵蓋比例",
    "rule_coverage_status": "規則涵蓋狀態",
    "rule_scope": "規則範圍",
    "official_text_evidence": "官方文字證據",
    "narrative_shift": "文字敘事變化",
}

_ASCII_BEFORE = r"(?<![A-Za-z0-9_])"
_ASCII_AFTER = r"(?![A-Za-z0-9_])"
_NUMBER = r"[-+]?\d+(?:\.\d+)?"
_VALUE_SEPARATOR = r"\s*(?:為|=|:|：|是)\s*"
_UNIT_SUFFIX = r"(?:\s*(?:%|％|pp|個百分點|百分點|天|倍))?"
RULE_ID_RE = re.compile(_ASCII_BEFORE + r"[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*_\d{3}" + _ASCII_AFTER)
SNAKE_CASE_RE = re.compile(_ASCII_BEFORE + r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+" + _ASCII_AFTER)
_SIGNAL_TOKEN_RE = re.compile(
    _ASCII_BEFORE + r"(" + "|".join(sorted(SIGNAL_LABELS, key=len, reverse=True)) + r")" + _ASCII_AFTER
)
# "營收成長但獲利成長未跟上（attention／common）" -> "營收成長但獲利成長未跟上（需注意）"
_SEVERITY_SCOPE_RE = re.compile(r"（\s*([a-z_]+)\s*／\s*[a-z_]+\s*）")
_CJK_GAP_RE = re.compile(r"(?<=[一-鿿）」，。、])\s+(?=[一-鿿（「，。、])")
_PAREN_SIGNAL_RE = re.compile(r"[（(]\s*(" + "|".join(sorted(SIGNAL_LABELS, key=len, reverse=True)) + r")\s*[）)]")


@dataclass(frozen=True)
class PresentationGlossary:
    metrics: dict[str, tuple[str, str]] = field(default_factory=dict)
    rules: dict[str, str] = field(default_factory=dict)
    dimensions: dict[str, str] = field(default_factory=dict)

    def as_prompt_payload(self) -> dict[str, Any]:
        return {
            "metrics": {code: {"label": label, "unit": unit} for code, (label, unit) in self.metrics.items()},
            "rules": dict(self.rules),
            "dimensions": dict(self.dimensions),
            "signals": dict(SIGNAL_LABELS),
        }


def _value(item: Any, key: str) -> Any:
    return item.get(key) if isinstance(item, dict) else getattr(item, key, None)


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "")


def build_presentation_glossary(*, features: Any = (), rules: Any = (), dimensions: Any = ()) -> PresentationGlossary:
    """Labels from the payload itself: feature code/label/unit, rule id/name, dimension key/label."""
    if isinstance(features, dict):
        features = list(features.values())
    metrics = {
        _text(_value(item, "code")): (_text(_value(item, "label")), _text(_value(item, "unit")))
        for item in features or []
        if _value(item, "code") and _value(item, "label")
    }
    rule_names = {
        _text(_value(item, "rule_id")): _text(_value(item, "name"))
        for item in rules or []
        if _value(item, "rule_id") and _value(item, "name")
    }
    dimension_labels = {key.value: label for key, label in DIMENSION_LABELS.items()}
    for item in dimensions or []:
        if _value(item, "dimension") and _value(item, "label"):
            dimension_labels[_text(_value(item, "dimension"))] = _text(_value(item, "label"))
    return PresentationGlossary(metrics=metrics, rules=rule_names, dimensions=dimension_labels)


def format_metric_value(value: float, unit: str) -> str:
    """Format a value already present in the text; rounding only, no new numbers."""
    if unit in {"%", "％"}:
        return f"{value:.2f}%"
    if unit == "百分點":
        return f"{value:.2f} 個百分點"
    if unit == "新台幣元":
        return f"{value:,.0f} 元"
    if unit in {"天", "倍", "項"}:
        return f"{value:.2f} {unit}"
    if unit == "元／股":
        return f"{value:.2f} 元／股"
    return f"{value:.2f}{(' ' + unit) if unit else ''}"


def _token(code: str) -> str:
    return _ASCII_BEFORE + re.escape(code) + _ASCII_AFTER


def humanize_text(value: str, glossary: PresentationGlossary) -> str:
    if not value:
        return value
    text = _SEVERITY_SCOPE_RE.sub(lambda match: f"（{SIGNAL_LABELS.get(match.group(1), match.group(1))}）", value)
    # Longest codes first so "gross_margin_change_pp" is not split by "gross_margin".
    for code in sorted(glossary.metrics, key=len, reverse=True):
        label, unit = glossary.metrics[code]
        text = re.sub(
            _token(code) + _VALUE_SEPARATOR + "(" + _NUMBER + ")" + _UNIT_SUFFIX,
            lambda match, label=label, unit=unit: f"{label}為 {format_metric_value(float(match.group(1)), unit)}",
            text,
        )
        text = re.sub(_token(code), label, text)
    for rule_id in sorted(glossary.rules, key=len, reverse=True):
        text = re.sub(_token(rule_id), f"「{glossary.rules[rule_id]}」", text)
    text = RULE_ID_RE.sub("相關規則", text)
    for key in sorted(glossary.dimensions, key=len, reverse=True):
        text = re.sub(_token(key), glossary.dimensions[key], text)
    text = re.sub(_token("evaluated_rules") + _VALUE_SEPARATOR + r"(\d+)", lambda match: f"共檢視 {match.group(1)} 項規則", text)
    text = re.sub(_token("actual_values") + r"\s*顯示", "數據顯示", text)
    for phrase in sorted(FIELD_PHRASES, key=len, reverse=True):
        text = re.sub(_token(phrase), FIELD_PHRASES[phrase], text)
    text = _PAREN_SIGNAL_RE.sub(lambda match: f"（{SIGNAL_LABELS[match.group(1)]}）", text)
    text = _SIGNAL_TOKEN_RE.sub(lambda match: f"「{SIGNAL_LABELS[match.group(1)]}」", text)
    # Anything still in snake_case is an internal key with no label in this payload.
    text = SNAKE_CASE_RE.sub("相關指標", text)
    text = _CJK_GAP_RE.sub("", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def humanize_narrative(narrative: Any, glossary: PresentationGlossary) -> Any:
    """Return the narrative (LLMNarrative or dict) with user-facing text humanized; keys are kept."""
    if narrative is None:
        return None
    data = narrative.model_dump() if isinstance(narrative, LLMNarrative) else dict(narrative)
    data["executive_summary"] = humanize_text(str(data.get("executive_summary") or ""), glossary)
    data["dimension_insights"] = {
        key: humanize_text(str(value or ""), glossary)
        for key, value in (data.get("dimension_insights") or {}).items()
    }
    data["watch_items"] = [humanize_text(str(item), glossary) for item in data.get("watch_items") or []]
    data["limitations"] = [humanize_text(str(item), glossary) for item in data.get("limitations") or []]
    return LLMNarrative(**data) if isinstance(narrative, LLMNarrative) else data


def dimension_summary_text(rule_name: str, severity: str) -> str:
    return f"{rule_name}（{SIGNAL_LABELS.get(severity, severity)}）"


def present_snapshot_payload(snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """Humanize the narrative and dimension summaries of a stored snapshot (JSON dict) for display."""
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("ai_analysis"), dict):
        return snapshot
    presented = copy.deepcopy(snapshot)
    analysis = presented["ai_analysis"]
    glossary = build_presentation_glossary(
        features=analysis.get("features") or [],
        rules=analysis.get("rule_monitoring") or [],
        dimensions=analysis.get("dimension_assessments") or [],
    )
    if isinstance(analysis.get("llm_narrative"), dict):
        analysis["llm_narrative"] = humanize_narrative(analysis["llm_narrative"], glossary)
    for dimension in analysis.get("dimension_assessments") or []:
        if isinstance(dimension, dict) and dimension.get("summary"):
            dimension["summary"] = humanize_text(str(dimension["summary"]), glossary)
    return presented


def internal_identifiers(text: str, glossary: PresentationGlossary | None = None) -> list[str]:
    """Identifiers a user should not see: rule IDs, snake_case keys and bare signal values."""
    found = RULE_ID_RE.findall(text) + SNAKE_CASE_RE.findall(text)
    found += [match.group(1) for match in _SIGNAL_TOKEN_RE.finditer(text)]
    if glossary is not None:
        found += [code for code in glossary.metrics if re.search(_token(code), text)]
    return sorted(set(found))
