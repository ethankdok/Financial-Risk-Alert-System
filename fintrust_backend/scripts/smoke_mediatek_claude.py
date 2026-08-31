from __future__ import annotations

import asyncio
import json
import os

from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService


async def main() -> None:
    if os.getenv("FINANCIAL_LLM_PROVIDER", "").strip().lower() != "anthropic":
        raise RuntimeError("請先設定 FINANCIAL_LLM_PROVIDER=anthropic。")
    if not os.getenv("ANTHROPIC_API_KEY", "").strip():
        raise RuntimeError("ANTHROPIC_API_KEY 尚未設定。請只在本機環境變數或 Secret Manager 設定，不要寫進 Git。")

    historical = await HistoricalFinancialAnalysisService().analyze(
        "2454",
        years=3,
        end_roc_year=113,
    )
    ai = await AIFinancialAnalysisService().analyze_report(historical, use_llm=True)

    result = {
        "ticker": ai.ticker,
        "company": ai.company_name,
        "source_period_start": ai.source_period_start,
        "source_period_end": ai.source_period_end,
        "analysis_engine_version": ai.analysis_engine_version,
        "rule_catalog_version": ai.rule_catalog_version,
        "rule_count": len(ai.rule_monitoring),
        "dimension_count": len(ai.dimension_assessments),
        "llm_trace": ai.llm_trace.model_dump(mode="json"),
        "llm_narrative": ai.llm_narrative.model_dump(mode="json") if ai.llm_narrative else None,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if historical.available_years < 3:
        raise RuntimeError("聯發科 Claude live smoke 未取得三個完整年度。")
    if len(ai.rule_monitoring) != 24:
        raise RuntimeError(f"AI layered rule count 異常：{len(ai.rule_monitoring)}")
    if len(ai.dimension_assessments) != 8:
        raise RuntimeError(f"AI dimension count 異常：{len(ai.dimension_assessments)}")
    if ai.llm_trace.status != "completed":
        raise RuntimeError(f"Claude API 未完成：status={ai.llm_trace.status}, error={ai.llm_trace.error}")
    if ai.llm_trace.provider != "anthropic":
        raise RuntimeError(f"LLM provider 異常：{ai.llm_trace.provider}")
    if ai.llm_trace.model != "claude-sonnet-5":
        raise RuntimeError(f"LLM model 異常：{ai.llm_trace.model}")
    if ai.llm_narrative is None:
        raise RuntimeError("Claude API 已回傳完成狀態，但 llm_narrative 為空。")


if __name__ == "__main__":
    asyncio.run(main())
