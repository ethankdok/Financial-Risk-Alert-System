from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from app.ai_analysis_models import DimensionAssessment, LLMAnalysisTrace, LLMNarrative, MonitoredRuleResult


@runtime_checkable
class FinancialLLMProvider(Protocol):
    provider_name: str
    model: str

    @property
    def configured(self) -> bool: ...

    def health(self) -> dict[str, Any]: ...

    async def analyze(
        self,
        *,
        company_name: str,
        ticker: str,
        subindustry: str,
        dimensions: list[DimensionAssessment],
        rules: list[MonitoredRuleResult],
    ) -> tuple[LLMNarrative | None, LLMAnalysisTrace]: ...


class UnavailableFinancialLLMProvider:
    """Explicitly surfaces an invalid provider configuration without breaking deterministic analysis."""

    prompt_version = "financial-analysis-v2"

    def __init__(self, provider_name: str, *, error: str) -> None:
        self.provider_name = provider_name
        self.model = ""
        self.error = error

    @property
    def configured(self) -> bool:
        return False

    def health(self) -> dict[str, Any]:
        return {
            "provider": self.provider_name,
            "configured": False,
            "provider_configured": False,
            "endpoint_configured": False,
            "model": None,
            "prompt_version": self.prompt_version,
            "error": self.error,
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
        return None, LLMAnalysisTrace(
            enabled=True,
            status="failed",
            endpoint_configured=False,
            provider=self.provider_name,
            provider_configured=False,
            model=None,
            prompt_version=self.prompt_version,
            used_rule_ids=[item.rule_id for item in rules if item.triggered],
            error=self.error,
        )


def create_financial_llm_provider() -> FinancialLLMProvider:
    raw_provider = os.getenv("FINANCIAL_LLM_PROVIDER", "").strip().lower()
    provider_name = raw_provider or "openai_compatible"

    if provider_name == "gemini":
        from app.services.gemini_financial_analyst import GeminiFinancialAnalyst

        return GeminiFinancialAnalyst()

    if provider_name == "anthropic":
        from app.services.anthropic_financial_analyst import AnthropicFinancialAnalyst

        return AnthropicFinancialAnalyst()

    if provider_name in {"openai_compatible", "openai-compatible"}:
        from app.services.llm_financial_analyst import LLMFinancialAnalyst

        return LLMFinancialAnalyst()

    return UnavailableFinancialLLMProvider(
        provider_name,
        error=(
            f"Unsupported FINANCIAL_LLM_PROVIDER={provider_name!r}. "
            "Supported values are 'gemini', 'anthropic', and 'openai_compatible'."
        ),
    )
