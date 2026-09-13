from __future__ import annotations

import json
import os
import time
from typing import Any

from anthropic import AsyncAnthropic

from app.ai_analysis_models import DimensionAssessment, LLMAnalysisTrace, LLMNarrative, MonitoredRuleResult


_DEFAULT_MODEL = "claude-sonnet-5"
_DIMENSION_KEYS = [
    "growth",
    "profitability",
    "rd_innovation",
    "operating_efficiency",
    "cash_flow",
    "financial_structure",
    "earnings_quality",
    "investment_efficiency",
]
_LLM_NARRATIVE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "dimension_insights": {
            "type": "object",
            "properties": {key: {"type": "string"} for key in _DIMENSION_KEYS},
            "required": _DIMENSION_KEYS,
            "additionalProperties": False,
        },
        "watch_items": {"type": "array", "items": {"type": "string"}},
        "limitations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["executive_summary", "dimension_insights", "watch_items", "limitations"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "你是金融資訊可信度系統中的財報分析 AI。只能使用使用者提供的官方財報衍生 evidence、"
    "八大面向 assessment 與 deterministic rule results。不得自行補數字、不得重新計算官方會計數值、"
    "不得修改規則結果、不得臆測未提供的原因或因果關係、不得預測股價、不得提供買進、賣出、加碼、減碼、"
    "目標價或任何投資建議。你的任務是做跨面向的受約束整合：指出一致訊號、mixed signals、資料不足與限制。"
    "dimension_insights 必須涵蓋八個固定面向；若某面向 evidence 不足，直接說明資料不足，不得補造內容。"
)


class AnthropicFinancialAnalyst:
    """Anthropic-native Claude provider over deterministic financial evidence."""

    provider_name = "anthropic"
    prompt_version = "financial-analysis-anthropic-v2"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv("ANTHROPIC_API_KEY", "")).strip()
        raw_model = model if model is not None else os.getenv("FINANCIAL_LLM_MODEL", "")
        self.model = (raw_model or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self.model)

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": self.configured,
            "provider_configured": self.configured,
            "endpoint_configured": False,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "structured_output": True,
        }

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = AsyncAnthropic(api_key=self._api_key, timeout=60.0)
        return self._client

    @staticmethod
    def _evidence_payload(
        dimensions: list[DimensionAssessment],
        rules: list[MonitoredRuleResult],
    ) -> dict[str, Any]:
        return {
            "dimensions": [item.model_dump(mode="json") for item in dimensions],
            "rule_results": [
                item.model_dump(mode="json")
                for item in rules
                if item.triggered or item.evaluation_status.value != "evaluated"
            ],
        }

    async def analyze(
        self,
        *,
        company_name: str,
        ticker: str,
        subindustry: str,
        dimensions: list[DimensionAssessment],
        rules: list[MonitoredRuleResult],
    ) -> tuple[LLMNarrative | None, LLMAnalysisTrace]:
        used_rule_ids = [item.rule_id for item in rules if item.triggered]
        if not self.configured:
            return None, LLMAnalysisTrace(
                enabled=False,
                status="not_configured",
                endpoint_configured=False,
                provider=self.provider_name,
                provider_configured=False,
                model=self.model,
                prompt_version=self.prompt_version,
                used_rule_ids=used_rule_ids,
            )

        evidence = self._evidence_payload(dimensions, rules)
        user_prompt = json.dumps(
            {
                "company": {"name": company_name, "ticker": ticker, "subindustry": subindustry},
                "evidence": evidence,
            },
            ensure_ascii=False,
        )
        started = time.perf_counter()
        try:
            response = await self._get_client().messages.create(
                model=self.model,
                max_tokens=2500,
                temperature=0.1,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                output_config={
                    "format": {
                        "type": "json_schema",
                        "schema": _LLM_NARRATIVE_JSON_SCHEMA,
                    }
                },
            )
            stop_reason = getattr(response, "stop_reason", None)
            if stop_reason in {"max_tokens", "refusal"}:
                raise ValueError(f"Claude structured output incomplete: stop_reason={stop_reason}")

            text = "".join(
                str(getattr(block, "text", ""))
                for block in getattr(response, "content", [])
                if getattr(block, "type", None) == "text"
            ).strip()
            if not text:
                raise ValueError("Claude response contained no text output block.")

            narrative = LLMNarrative(**json.loads(text))
            latency_ms = int((time.perf_counter() - started) * 1000)
            return narrative, LLMAnalysisTrace(
                enabled=True,
                status="completed",
                endpoint_configured=False,
                provider=self.provider_name,
                provider_configured=True,
                model=self.model,
                prompt_version=self.prompt_version,
                latency_ms=latency_ms,
                used_rule_ids=used_rule_ids,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return None, LLMAnalysisTrace(
                enabled=True,
                status="failed",
                endpoint_configured=False,
                provider=self.provider_name,
                provider_configured=True,
                model=self.model,
                prompt_version=self.prompt_version,
                latency_ms=latency_ms,
                used_rule_ids=used_rule_ids,
                error=str(exc),
            )
