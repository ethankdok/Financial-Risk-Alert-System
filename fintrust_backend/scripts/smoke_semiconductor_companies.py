from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.services.ai_financial_analysis_service import AIFinancialAnalysisService
from app.services.company_registry import get_company
from app.services.historical_analysis_service import HistoricalFinancialAnalysisService

# Phase 3 target set requested by the teacher: keep the initial foundry case,
# add another foundry peer, include IC design, and explicitly cover packaging / testing.
PHASE3_COMPANY_TARGETS: tuple[str, ...] = ("2330", "2303", "2454", "3711")

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_PATH = BACKEND_ROOT / "data" / "demo-output" / "phase3-semiconductor-summary.json"

REQUIRED_METRICS_BY_SUBINDUSTRY: dict[str, tuple[str, ...]] = {
    "晶圓代工": (
        "revenue_growth_yoy",
        "gross_margin",
        "operating_margin",
        "capex_intensity",
        "free_cash_flow",
        "cash_conversion_ratio",
        "debt_ratio",
    ),
    "IC 設計": (
        "revenue_growth_yoy",
        "gross_margin",
        "operating_margin",
        "rd_intensity",
        "inventory_growth_yoy",
        "inventory_turnover_days",
        "receivable_turnover_days",
        "cash_conversion_ratio",
    ),
    "封裝測試": (
        "revenue_growth_yoy",
        "inventory_growth_yoy",
        "operating_cash_flow",
        "cash_conversion_ratio",
        "debt_ratio",
        "current_ratio",
    ),
}


def phase3_target_profiles() -> list[dict[str, str]]:
    """Return the agreed Phase 3 company set for docs, tests, and demos."""
    profiles: list[dict[str, str]] = []
    for ticker in PHASE3_COMPANY_TARGETS:
        company = get_company(ticker)
        if company is None:
            raise RuntimeError(f"Phase 3 company target is missing from registry: {ticker}")
        profiles.append(
            {
                "ticker": company.ticker,
                "company_name": company.name,
                "subindustry": company.subindustry,
            }
        )
    return profiles


def _metric_coverage(report) -> dict[str, bool]:
    metric_map = {metric.code: metric for metric in report.trend_metrics}
    required = REQUIRED_METRICS_BY_SUBINDUSTRY.get(report.subindustry, ())
    return {
        code: bool(metric_map.get(code) and metric_map[code].period_values)
        for code in required
    }


def _rule_scope_counts(report) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rule in report.rule_results:
        counts[rule.rule_scope] = counts.get(rule.rule_scope, 0) + 1
    return dict(sorted(counts.items()))


def _missing_required_metrics(report) -> list[str]:
    coverage = _metric_coverage(report)
    return [code for code, available in coverage.items() if not available]


def _insufficient_rule_ids(report) -> list[str]:
    return [
        rule.rule_id
        for rule in report.rule_results
        if rule.severity.value == "insufficient_data"
    ]


def _period_mapping_status(report) -> list[dict[str, Any]]:
    """Expose per-period parsing status so mapping gaps can be fixed next."""
    return [
        {
            "period": period.period,
            "status": period.status,
            "fields_found_count": len(period.fields_found),
            "fields_missing": period.fields_missing,
            "warnings": period.warnings,
        }
        for period in report.periods
    ]


def _phase3_readiness(summary: dict[str, Any]) -> str:
    if summary.get("status") == "failed":
        return "failed"
    if summary["available_years"] < summary["requested_years"]:
        return "needs_mops_fetch_review"
    if summary["missing_required_metrics"]:
        return "needs_mapping_review"
    if summary["insufficient_rule_ids"]:
        return "needs_rule_coverage_review"
    return "ready_for_frontend_snapshot_demo"


def next_actions_for_company(summary: dict[str, Any]) -> list[str]:
    """Turn live smoke gaps into actionable Phase 3 follow-up items."""
    if summary.get("status") == "failed":
        return [
            "先檢查此公司 MOPS 年度 iXBRL 是否可連線與解析，再決定是否需要 demo_fixture 降級展示。"
        ]

    actions: list[str] = []
    if summary["available_years"] < summary["requested_years"]:
        actions.append(
            "補查無法取得的年度：確認 MOPS 申報是否存在、公司代號是否正確，以及 iXBRL fetch 是否 timeout。"
        )
    if summary["missing_required_metrics"]:
        actions.append(
            "補 robust MOPS mapping aliases：優先處理缺少的 required metrics，避免子產業規則被資料不足影響。"
        )
    if summary["insufficient_rule_ids"]:
        actions.append(
            "檢查資料不足規則：確認是財報欄位缺漏、metric 未計算，還是規則條件需要為該子產業調整。"
        )
    if not actions:
        actions.append(
            "此公司已可作為 Phase 3 子產業擴充 demo 候選；可接到 latest snapshot 或共享 Flask 財報證據卡。"
        )
    return actions


def build_company_summary(report, ai_report: Any | None = None) -> dict[str, Any]:
    """Convert one historical report into a compact teacher-review summary."""
    payload: dict[str, Any] = {
        "ticker": report.ticker,
        "company_name": report.company_name,
        "subindustry": report.subindustry,
        "source_method": report.source_method,
        "requested_years": report.requested_years,
        "available_years": report.available_years,
        "period_range": {
            "start_year": report.start_year,
            "end_year": report.end_year,
        },
        "periods": _period_mapping_status(report),
        "overall_severity": report.overall_severity.value,
        "rule_version": report.rule_version,
        "rule_scope_counts": _rule_scope_counts(report),
        "metric_coverage": _metric_coverage(report),
        "missing_required_metrics": _missing_required_metrics(report),
        "insufficient_rule_ids": _insufficient_rule_ids(report),
        "summary": report.summary,
    }
    if ai_report is not None:
        payload["ai_v2"] = {
            "enabled": True,
            "analysis_engine_version": ai_report.analysis_engine_version,
            "feature_count": ai_report.feature_count,
            "dimension_count": len(ai_report.dimension_assessments),
            "rule_count": len(ai_report.rule_monitoring),
            "llm_status": ai_report.llm_trace.status,
        }
    else:
        payload["ai_v2"] = {
            "enabled": False,
            "reason": "AI v2 currently applies only to supported subindustries; historical rules still run for this company.",
        }
    payload["phase3_readiness"] = _phase3_readiness(payload)
    payload["next_actions"] = next_actions_for_company(payload)
    return payload


async def analyze_company(
    ticker: str,
    *,
    years: int,
    end_year: int | None,
    use_ai_v2: bool,
) -> dict[str, Any]:
    end_roc_year = end_year - 1911 if end_year is not None else None
    historical = await HistoricalFinancialAnalysisService().analyze(
        ticker,
        years=years,
        end_roc_year=end_roc_year,
    )
    ai_report = None
    if use_ai_v2 and AIFinancialAnalysisService.supports(historical.subindustry):
        # Phase 3 live smoke intentionally skips external LLM calls. It validates
        # deterministic features, dimensions and monitorable rules only.
        ai_report = await AIFinancialAnalysisService().analyze_report(
            historical,
            use_llm=False,
        )
    return build_company_summary(historical, ai_report=ai_report)


async def run_smoke(
    *,
    tickers: list[str],
    years: int,
    end_year: int | None,
    use_ai_v2: bool,
    strict: bool,
) -> dict[str, Any]:
    results = []
    failures = []
    for ticker in tickers:
        try:
            summary = await analyze_company(
                ticker,
                years=years,
                end_year=end_year,
                use_ai_v2=use_ai_v2,
            )
            if strict:
                if summary["available_years"] < years:
                    failures.append(f"{ticker}: expected {years} available years, got {summary['available_years']}")
                if summary["missing_required_metrics"]:
                    failures.append(
                        f"{ticker}: missing required metrics {summary['missing_required_metrics']}"
                    )
            results.append(summary)
        except Exception as exc:  # pragma: no cover - live smoke diagnostic path
            failures.append(f"{ticker}: {exc}")
            failed = {
                "ticker": ticker,
                "status": "failed",
                "error": str(exc),
            }
            failed["phase3_readiness"] = _phase3_readiness(failed)
            failed["next_actions"] = next_actions_for_company(failed)
            results.append(failed)

    next_actions = [
        {
            "ticker": item.get("ticker"),
            "company_name": item.get("company_name"),
            "phase3_readiness": item.get("phase3_readiness"),
            "actions": item.get("next_actions", []),
        }
        for item in results
    ]
    payload = {
        "phase": "phase3_semiconductor_subindustry_expansion",
        "teacher_alignment": [
            "統一後端財報服務仍提供給共享 Flask 介面讀取",
            "半導體不只保留台積電，也納入晶圓代工 peer、IC 設計與封裝測試",
            "Gemini remains the agreed LLM provider; this smoke does not call external LLM APIs",
        ],
        "requested_years": years,
        "end_year": end_year,
        "targets": phase3_target_profiles(),
        "results": results,
        "next_actions": next_actions,
        "failures": failures,
        "result": "PASS" if not failures else "WARN" if not strict else "FAIL",
    }
    if strict and failures:
        raise RuntimeError(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def write_payload(payload: dict[str, Any], output_path: str | Path) -> Path:
    path = Path(output_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 3 live smoke across semiconductor subindustries."
    )
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=list(PHASE3_COMPANY_TARGETS),
        help="Ticker list to validate. Defaults to 2330 2303 2454 3711.",
    )
    parser.add_argument("--years", type=int, default=3, choices=(3, 4, 5))
    parser.add_argument("--end-year", type=int, default=2024)
    parser.add_argument(
        "--skip-ai-v2",
        action="store_true",
        help="Skip deterministic AI v2 validation for supported companies.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any company lacks required metrics or full years.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Write the JSON smoke summary to this path for screenshots and mapping review.",
    )
    parser.add_argument(
        "--no-output",
        action="store_true",
        help="Print only; do not write a JSON output artifact.",
    )
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    payload = await run_smoke(
        tickers=[str(ticker).strip() for ticker in args.tickers],
        years=args.years,
        end_year=args.end_year,
        use_ai_v2=not args.skip_ai_v2,
        strict=args.strict,
    )
    if not args.no_output:
        output_path = write_payload(payload, args.output)
        payload["output_file"] = str(output_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
