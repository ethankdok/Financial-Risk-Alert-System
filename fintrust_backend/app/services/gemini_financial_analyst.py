from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from app.ai_analysis_models import DimensionAssessment, LLMAnalysisTrace, LLMNarrative, MonitoredRuleResult


_DEFAULT_MODEL = "gemini-3.6-flash"
_DEFAULT_FALLBACK_MODEL = "gemini-3.5-flash-lite"
_DEFAULT_TIMEOUT_SECONDS = 45.0
_MINIMUM_API_KEY_LENGTH = 20
_TEMPERATURE = 0.1
_RETRYABLE_API_CODES = {408, 429, 500, 502, 503, 504}
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
    "若收到 official_text_evidence 或 narrative_shift，只能作為補充官方文字脈絡，不得用來改寫 deterministic rule results。"
    "rule_coverage_status 是規則涵蓋的權威標記；若為 common_only 或 partial，必須明確說明子產業專屬模型不完整，"
    "不得描述成完整的 subindustry model；若為 unsupported，不得假稱已有子產業規則。"
    "每項具體判斷必須引用輸入中的期間、rule_id 或 actual_values；若輸入沒有具體值，必須明說證據不足。"
)


class GeminiFinancialAnalyst:
    """Gemini Developer API provider over deterministic financial evidence."""

    provider_name = "gemini"
    prompt_version = "financial-analysis-gemini-v2"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        fallback_model: str | None = None,
        timeout_seconds: float | None = None,
        client: Any | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")).strip()
        raw_model = model if model is not None else os.getenv("FINANCIAL_LLM_MODEL", "")
        self.model = (raw_model or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
        raw_fallback = (
            fallback_model
            if fallback_model is not None
            else os.getenv("FINANCIAL_LLM_FALLBACK_MODEL", _DEFAULT_FALLBACK_MODEL)
        )
        self.fallback_model = (raw_fallback or "").strip()
        raw_timeout = timeout_seconds if timeout_seconds is not None else os.getenv("FINANCIAL_LLM_TIMEOUT_SECONDS", "")
        self.timeout_seconds = float(raw_timeout or _DEFAULT_TIMEOUT_SECONDS)
        self._client = client
        self._root_client: Any | None = None

    @property
    def configured(self) -> bool:
        return bool(
            self.model
            and len(self._api_key) >= _MINIMUM_API_KEY_LENGTH
            and not any(character.isspace() for character in self._api_key)
        )

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": self.configured,
            "provider_configured": self.configured,
            "endpoint_configured": False,
            "model": self.model,
            "fallback_model": self.fallback_model or None,
            "prompt_version": self.prompt_version,
            "structured_output": True,
            "timeout_seconds": self.timeout_seconds,
            "temperature": _TEMPERATURE,
            "configuration_error": None if self.configured else "GEMINI_API_KEY is missing or malformed.",
        }

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai

            self._root_client = genai.Client(api_key=self._api_key)
            self._client = self._root_client.aio
        return self._client

    @staticmethod
    def _evidence_payload(
        dimensions: list[DimensionAssessment],
        rules: list[MonitoredRuleResult],
        source_context: dict[str, Any] | None = None,
        official_text_evidence: list[dict[str, Any]] | None = None,
        narrative_shift: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "dimensions": [item.model_dump(mode="json") for item in dimensions],
            "source_context": source_context or {},
            "rule_results": [
                item.model_dump(mode="json")
                for item in rules
                if item.triggered or item.evaluation_status.value != "evaluated"
            ],
            "official_text_evidence": official_text_evidence or [],
            "narrative_shift": narrative_shift,
            "guardrails": [
                "Official text evidence may explain mixed signals but cannot change deterministic rules.",
                "Do not invent missing financial numbers or causal explanations.",
                "Do not provide investment advice or stock-price forecasts.",
            ],
        }

    @staticmethod
    def _is_retryable_api_error(exc: Exception) -> bool:
        if isinstance(exc, TimeoutError):
            return True
        code = GeminiFinancialAnalyst._error_code(exc)
        try:
            return int(code) in _RETRYABLE_API_CODES
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _error_code(exc: Exception) -> str | int | None:
        current: BaseException | None = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            for attr in ("code", "status_code", "status"):
                value = getattr(current, attr, None)
                if value is not None:
                    return value
            current = current.__cause__ or current.__context__
        return None

    @classmethod
    def _safe_trace_error(cls, exc: Exception) -> dict[str, Any]:
        code = cls._error_code(exc)
        message = str(exc)
        if "GEMINI_API_KEY" in message:
            message = message.replace("GEMINI_API_KEY", "API key")
        return {
            "error": message[:800],
            "error_type": type(exc).__name__,
            "error_code": code,
            "retryable": cls._is_retryable_api_error(exc),
            "safe_error_message": message[:280],
        }

    async def _generate(self, *, model: str, user_prompt: str) -> Any:
        return await self._get_client().models.generate_content(
            model=model,
            contents=user_prompt,
            config={
                "max_output_tokens": 2500,
                "temperature": _TEMPERATURE,
                "system_instruction": _SYSTEM_PROMPT,
                "response_mime_type": "application/json",
                "response_json_schema": _LLM_NARRATIVE_JSON_SCHEMA,
            },
        )

    @staticmethod
    def _parse_narrative(response: Any) -> LLMNarrative:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, dict):
            return LLMNarrative(**parsed)

        text = str(getattr(response, "text", "") or "").strip()
        if not text:
            raise ValueError("Gemini response contained no text output.")
        return LLMNarrative(**json.loads(text))

    async def analyze(
        self,
        *,
        company_name: str,
        ticker: str,
        subindustry: str,
        dimensions: list[DimensionAssessment],
        rules: list[MonitoredRuleResult],
        source_context: dict[str, Any] | None = None,
        official_text_evidence: list[dict[str, Any]] | None = None,
        narrative_shift: dict[str, Any] | None = None,
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
                requested_model=self.model,
                effective_model=None,
                prompt_version=self.prompt_version,
                used_rule_ids=used_rule_ids,
                llm_evidence_ids=[str(item.get("evidence_id")) for item in official_text_evidence or [] if item.get("evidence_id")],
            )

        evidence = self._evidence_payload(dimensions, rules, source_context, official_text_evidence, narrative_shift)
        user_prompt = json.dumps(
            {
                "company": {"name": company_name, "ticker": ticker, "subindustry": subindustry},
                "evidence": evidence,
            },
            ensure_ascii=False,
        )
        started = time.perf_counter()
        effective_model = self.model

        try:
            try:
                response = await asyncio.wait_for(
                    self._generate(model=self.model, user_prompt=user_prompt),
                    timeout=self.timeout_seconds,
                )
            except Exception as primary_exc:
                should_fallback = (
                    self.fallback_model
                    and self.fallback_model != self.model
                    and self._is_retryable_api_error(primary_exc)
                )
                if not should_fallback:
                    raise

                effective_model = self.fallback_model
                try:
                    response = await asyncio.wait_for(
                        self._generate(model=effective_model, user_prompt=user_prompt),
                        timeout=self.timeout_seconds,
                    )
                except Exception as fallback_exc:
                    raise RuntimeError(
                        f"Primary Gemini model {self.model} failed with a retryable error "
                        f"({primary_exc}); fallback model {effective_model} also failed ({fallback_exc})."
                    ) from fallback_exc

            narrative = self._parse_narrative(response)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return narrative, LLMAnalysisTrace(
                enabled=True,
                status="completed",
                endpoint_configured=False,
                provider=self.provider_name,
                provider_configured=True,
                model=effective_model,
                requested_model=self.model,
                effective_model=effective_model,
                prompt_version=self.prompt_version,
                latency_ms=latency_ms,
                used_rule_ids=used_rule_ids,
                llm_evidence_ids=[str(item.get("evidence_id")) for item in official_text_evidence or [] if item.get("evidence_id")],
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            error_fields = self._safe_trace_error(exc)
            return None, LLMAnalysisTrace(
                enabled=True,
                status="failed",
                endpoint_configured=False,
                provider=self.provider_name,
                provider_configured=True,
                model=effective_model,
                requested_model=self.model,
                effective_model=effective_model,
                prompt_version=self.prompt_version,
                latency_ms=latency_ms,
                used_rule_ids=used_rule_ids,
                llm_evidence_ids=[str(item.get("evidence_id")) for item in official_text_evidence or [] if item.get("evidence_id")],
                **error_fields,
            )
