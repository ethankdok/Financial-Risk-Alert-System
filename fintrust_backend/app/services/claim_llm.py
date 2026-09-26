"""Bounded Gemini assistance for claim verification.

Two narrow, optional helpers over the existing server-side
``GeminiFinancialAnalyst.generate_structured``:

* ``extract``: fill claim fields the deterministic parser could not find;
* ``relate``: classify a company-statement claim against at most five
  already-retrieved evidence items.

The model never supplies evidence. A proposed number must literally appear in
the user's claim; a proposed period must be spelled out in the claim; a
relation may reference only the evidence IDs it was given. Any provider,
JSON, or schema problem returns ``None`` so the deterministic path continues.
"""

from __future__ import annotations

import asyncio
import json
import re
import unicodedata
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.periods import normalize_period

KNOWN_METRICS = (
    "gross_margin", "operating_margin", "net_margin", "revenue", "eps", "roe", "current_ratio",
    "debt_ratio", "free_cash_flow", "operating_cash_flow", "capital_expenditure", "inventory",
    "net_income", "wafer_shipment",
)
_EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "metric": {"type": ["string", "null"], "enum": [*KNOWN_METRICS, None]},
        "period_text": {"type": ["string", "null"]},
        "value_text": {"type": ["string", "null"]},
        "unit": {"type": ["string", "null"], "enum": ["%", "元", "千", "萬", "百萬", "億", "兆", None]},
        "direction": {"type": "string", "enum": ["increase", "decrease", "unspecified"]},
    },
    "required": ["metric", "period_text", "value_text", "unit", "direction"],
    "additionalProperties": False,
}
_RELATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_id": {"type": "string"},
                    "relation": {"type": "string", "enum": ["supports", "conflicts", "neutral", "unclear"]},
                    "reason": {"type": "string"},
                },
                "required": ["evidence_id", "relation", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["relations"],
    "additionalProperties": False,
}
_EXTRACT_PROMPT = (
    "Extract the structure of one financial claim about a Taiwanese listed company. "
    "Copy period_text and value_text exactly as written in the claim; never compute, convert, or guess. "
    "If the claim does not state a field explicitly, return null for it. Do not give investment advice."
)
_RELATE_PROMPT = (
    "Decide whether each supplied official evidence item supports, conflicts with, or is neutral to the claim. "
    "Use only the supplied evidence text; do not use outside knowledge. Reference only the supplied evidence_id "
    "values. Use 'unclear' when the evidence does not directly address the claim. Do not give investment advice."
)


class _Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str | None
    period_text: str | None
    value_text: str | None = Field(default=None, max_length=32)
    unit: str | None
    direction: Literal["increase", "decrease", "unspecified"]


class _Relation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    relation: Literal["supports", "conflicts", "neutral", "unclear"]
    reason: str = Field(max_length=600)


class _Relations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relations: list[_Relation] = Field(max_length=10)


def _normalize(text: str) -> str:
    return re.sub(r"[\s,]", "", unicodedata.normalize("NFKC", text or ""))


class ClaimLLM:
    def __init__(self, provider: Any | None = None) -> None:
        if provider is None:
            from app.services.gemini_financial_analyst import GeminiFinancialAnalyst

            provider = GeminiFinancialAnalyst()
        self.provider = provider
        self.calls = 0

    @property
    def configured(self) -> bool:
        return bool(getattr(self.provider, "configured", False))

    def _generate(self, prompt: dict[str, Any], *, system: str, schema: dict[str, Any]) -> dict[str, Any] | None:
        if not self.configured:
            return None
        self.calls += 1
        try:
            payload, _model = asyncio.run(self.provider.generate_structured(
                json.dumps(prompt, ensure_ascii=False), system_instruction=system, schema=schema,
                max_output_tokens=800,
            ))
            return payload
        except Exception:
            return None
        finally:
            # The provider's async client is bound to the loop asyncio.run just closed.
            if hasattr(self.provider, "_client"):
                self.provider._client = None

    def extract(self, claim_text: str) -> dict[str, Any] | None:
        payload = self._generate({"claim": claim_text}, system=_EXTRACT_PROMPT, schema=_EXTRACT_SCHEMA)
        if payload is None:
            return None
        try:
            result = _Extraction(**payload)
        except (ValidationError, TypeError):
            return None
        normalized_claim = _normalize(claim_text)
        out: dict[str, Any] = {}
        if result.metric in KNOWN_METRICS:
            out["metric"] = result.metric
        if result.period_text and _normalize(result.period_text) in normalized_claim:
            period = normalize_period(result.period_text)
            if period:
                out["period"] = period
        if result.value_text:
            value_text = _normalize(result.value_text).rstrip("%")
            if value_text and value_text in normalized_claim:
                try:
                    out["value"] = float(value_text)
                    out["value_text"] = value_text
                    out["unit"] = result.unit
                except ValueError:
                    pass
        if result.direction != "unspecified":
            out["direction"] = result.direction
        return out

    def relate(self, claim: dict[str, Any], evidence: list[dict[str, Any]]) -> dict[str, tuple[str, str]] | None:
        supplied = {item["evidence_id"] for item in evidence[:5]}
        payload = self._generate({"claim": claim, "evidence": evidence[:5]}, system=_RELATE_PROMPT,
                                 schema=_RELATE_SCHEMA)
        if payload is None:
            return None
        try:
            result = _Relations(**payload)
        except (ValidationError, TypeError):
            return None
        if any(item.evidence_id not in supplied for item in result.relations):
            return None  # an invented reference invalidates the whole answer
        return {item.evidence_id: (item.relation, item.reason) for item in result.relations}
