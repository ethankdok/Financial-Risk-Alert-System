from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai_analysis_models import AnalysisDimension, DimensionAssessment, DimensionSignal, MonitoredRuleResult, RuleEvaluationStatus
from app.financial_analysis_models import RuleSeverity
from app.services.gemini_financial_analyst import GeminiFinancialAnalyst
from app.services.text_embedding_provider import create_text_embedding_provider


def _synthetic_dimensions() -> list[DimensionAssessment]:
    return [
        DimensionAssessment(
            dimension=AnalysisDimension.GROWTH,
            label="成長性",
            signal=DimensionSignal.NORMAL,
            coverage_ratio=1.0,
            evaluated_rules=1,
            total_rules=1,
            summary="Synthetic smoke fixture: revenue trend rule was evaluated without high-attention signal.",
        )
    ]


def _synthetic_rules() -> list[MonitoredRuleResult]:
    return [
        MonitoredRuleResult(
            rule_id="synthetic_growth_rule",
            name="Synthetic revenue trend guardrail",
            rule_scope="ic_design",
            rule_version="smoke-v1",
            dimension=AnalysisDimension.GROWTH,
            dimension_label="成長性",
            assessment_type="direct",
            severity=RuleSeverity.NORMAL,
            evaluation_status=RuleEvaluationStatus.EVALUATED,
            triggered=False,
            logic_expression="synthetic_revenue_growth_yoy >= 0",
            rationale="Bounded smoke test only; not real company data.",
            threshold_basis="Synthetic deterministic fixture.",
            evidence_basis="Synthetic deterministic fixture.",
            direct_metrics=["revenue_growth_yoy"],
            actual_values={"revenue_growth_yoy": 3.2},
        )
    ]


async def main_async(include_embedding: bool) -> dict[str, object]:
    if not os.getenv("GEMINI_API_KEY", "").strip():
        return {"gemini_smoke": "GEMINI_REAL_SMOKE_NOT_RUN_NO_KEY"}

    analyst = GeminiFinancialAnalyst()
    narrative, trace = await analyst.analyze(
        company_name="Synthetic IC Design Co.",
        ticker="SYNTH",
        subindustry="IC 設計",
        dimensions=_synthetic_dimensions(),
        rules=_synthetic_rules(),
        official_text_evidence=[
            {
                "evidence_id": "synthetic-official-text-1",
                "source_type": "synthetic_fixture",
                "source_name": "bounded_local_smoke",
                "source_url": "https://example.test/synthetic",
                "topics": ["outlook"],
                "relevance_score": 0.8,
                "text": "Synthetic official text evidence says management expects demand visibility to remain stable.",
                "limitations": ["Synthetic smoke fixture; not real official evidence."],
            }
        ],
    )
    result: dict[str, object] = {
        "gemini_smoke": trace.status,
        "provider": trace.provider,
        "requested_model": trace.requested_model,
        "effective_model": trace.effective_model,
        "latency_ms": trace.latency_ms,
        "error_type": trace.error_type,
        "error_code": trace.error_code,
        "retryable": trace.retryable,
        "safe_error_message": trace.safe_error_message,
        "parsed": narrative is not None,
    }
    if include_embedding:
        provider = create_text_embedding_provider()
        embedding = provider.embed_sentences(["synthetic revenue outlook", "synthetic demand visibility"])
        result["embedding_smoke"] = embedding.metadata.__dict__
    else:
        result["embedding_smoke"] = "NOT_CONFIGURED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one bounded Gemini financial analyst smoke without printing secrets.")
    parser.add_argument("--embedding", action="store_true", help="Also run configured text embedding provider smoke.")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(main_async(args.embedding)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
