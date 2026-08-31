from __future__ import annotations

import json
import os
import time
from typing import Any

import httpx

from app.ai_analysis_models import DimensionAssessment, LLMAnalysisTrace, LLMNarrative, MonitoredRuleResult


class LLMFinancialAnalyst:
    """Optional OpenAI-compatible chat-completions LLM layer over deterministic evidence."""

    provider_name = "openai_compatible"
    prompt_version = "financial-analysis-v1"

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = (endpoint or os.getenv("FINANCIAL_LLM_ENDPOINT", "")).strip()
        self.api_key = (api_key or os.getenv("FINANCIAL_LLM_API_KEY", "")).strip()
        self.model = (model or os.getenv("FINANCIAL_LLM_MODEL", "")).strip()
        self.client = client

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.api_key and self.model)

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": self.configured,
            "provider_configured": self.configured,
            "endpoint_configured": bool(self.endpoint),
            "model": self.model or None,
            "prompt_version": self.prompt_version,
        }

    @staticmethod
    def _evidence_payload(
        dimensions: list[DimensionAssessment],
        rules: list[MonitoredRuleResult],
    ) -> dict[str, Any]:
        return {
            "dimensions": [item.model_dump(mode="json") for item in dimensions],
            "triggered_rules": [
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
                endpoint_configured=bool(self.endpoint),
                provider=self.provider_name,
                provider_configured=False,
                model=self.model or None,
                prompt_version=self.prompt_version,
                used_rule_ids=used_rule_ids,
            )

        evidence = self._evidence_payload(dimensions, rules)
        system_prompt = (
            "你是金融資訊可信度系統中的財報分析 AI。只能使用提供的官方財報衍生證據與規則結果，"
            "不得自行補數字、不得預測股價、不得提供投資建議。分析時必須區分直接指標與間接指標，"
            "若訊號互相衝突要明確標示為 mixed；資料不足時必須保留限制。"
            "請輸出 JSON，欄位固定為 executive_summary、dimension_insights、watch_items、limitations。"
        )
        user_prompt = json.dumps(
            {
                "company": {"name": company_name, "ticker": ticker, "subindustry": subindustry},
                "evidence": evidence,
            },
            ensure_ascii=False,
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        started = time.perf_counter()
        owns_client = self.client is None
        client = self.client or httpx.AsyncClient(timeout=30.0)
        try:
            response = await client.post(self.endpoint, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
            text = str(content).strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:].lstrip()
            parsed = json.loads(text)
            narrative = LLMNarrative(**parsed)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return narrative, LLMAnalysisTrace(
                enabled=True,
                status="completed",
                endpoint_configured=True,
                provider=self.provider_name,
                provider_configured=True,
                model=self.model,
                prompt_version=self.prompt_version,
                latency_ms=latency_ms,
                used_rule_ids=used_rule_ids,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return None, LLMAnalysisTrace(
                enabled=True,
                status="failed",
                endpoint_configured=True,
                provider=self.provider_name,
                provider_configured=True,
                model=self.model,
                prompt_version=self.prompt_version,
                latency_ms=latency_ms,
                used_rule_ids=used_rule_ids,
                error=str(exc),
            )
        finally:
            if owns_client:
                await client.aclose()
