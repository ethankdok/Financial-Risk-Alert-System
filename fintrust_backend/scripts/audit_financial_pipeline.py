from __future__ import annotations

import argparse
import json
import sys

import httpx


SUBINDUSTRY_REQUIRED = {
    "晶圓代工": {
        "revenue",
        "gross_margin",
        "operating_margin",
        "operating_cash_flow",
        "free_cash_flow",
        "capex_intensity",
        "cash_conversion_ratio",
        "debt_ratio",
    },
    "IC 設計": {
        "revenue",
        "gross_margin",
        "operating_margin",
        "rd_intensity",
        "inventory_growth_yoy",
        "cash_conversion_ratio",
    },
    "封裝測試": {
        "revenue",
        "inventory_growth_yoy",
        "operating_cash_flow",
        "capex_intensity",
        "debt_ratio",
        "current_ratio",
    },
}


def get_json(client: httpx.Client, path: str):
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def post_json(client: httpx.Client, path: str, payload: dict):
    response = client.post(path, json=payload)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit FinTrust API, persistence and rule coverage.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ticker", default="2330")
    args = parser.parse_args()

    base = args.base_url.rstrip("/") + "/api/v1/financial"
    failures: list[str] = []
    warnings: list[str] = []

    with httpx.Client(timeout=30.0) as client:
        health = get_json(client, f"{base}/health")
        companies = get_json(client, f"{base}/companies")
        rules = get_json(client, f"{base}/rules")
        snapshot = get_json(client, f"{base}/companies/{args.ticker}/analysis/latest")
        metrics_payload = get_json(
            client,
            f"{base}/companies/{args.ticker}/metrics?limit=1000&latest_only=true",
        )
        runs = get_json(client, f"{base}/companies/{args.ticker}/analysis-runs?limit=20")
        verification = post_json(
            client,
            f"{base}/claims/verify",
            {"text": "台積電 2024 年全年營收較去年增加", "ticker": args.ticker},
        )

    if health.get("status") != "ok":
        failures.append("health endpoint did not return status=ok")
    if health.get("readiness_scope") != "configuration_only":
        failures.append("health endpoint does not disclose its readiness scope")
    if not any(item.get("ticker") == args.ticker for item in companies.get("companies", [])):
        failures.append("ticker is absent from company registry")
    if not rules.get("rules"):
        failures.append("latest TWSE rule catalog is empty")

    run_id = snapshot.get("analysis_run_id")
    if not run_id:
        failures.append("latest snapshot has no analysis_run_id")
    if metrics_payload.get("run_id") != run_id:
        failures.append("latest_only metrics did not use the latest snapshot run_id")

    latest_run_rows = [
        item
        for item in metrics_payload.get("metrics", [])
        if item.get("run_id") == run_id and item.get("analysis_type") == "historical"
    ]
    metric_codes = {item.get("metric_code") for item in latest_run_rows}
    required = SUBINDUSTRY_REQUIRED.get(snapshot.get("subindustry"), set())
    missing_metrics = sorted(required - metric_codes)
    if missing_metrics:
        warnings.append("missing required subindustry metrics: " + ", ".join(missing_metrics))

    insufficient_rules = [
        item
        for item in snapshot.get("rule_cards", [])
        if item.get("severity") == "insufficient_data"
    ]
    if insufficient_rules:
        warnings.append(
            "insufficient rules: "
            + ", ".join(item.get("rule_id", "unknown") for item in insufficient_rules)
        )

    if not any(item.get("run_id") == run_id and item.get("status") == "completed" for item in runs):
        failures.append("latest snapshot run is absent from completed analysis runs")

    unavailable_sources = [
        source
        for source in snapshot.get("sources", [])
        if source.get("status") != "available"
    ]
    if unavailable_sources:
        warnings.append(
            "non-available sources: "
            + ", ".join(
                f"{item.get('source_name')}({item.get('period')}:{item.get('status')})"
                for item in unavailable_sources
            )
        )

    verification_verdict = verification.get("verdict")
    if verification_verdict == "insufficient_evidence":
        failures.append("claim verification is not reading persisted pipeline facts")

    report = {
        "ticker": args.ticker,
        "analysis_run_id": run_id,
        "subindustry": snapshot.get("subindustry"),
        "overall_severity": snapshot.get("overall_severity"),
        "historical_metric_codes": sorted(code for code in metric_codes if code),
        "missing_required_metrics": missing_metrics,
        "insufficient_rule_ids": [item.get("rule_id") for item in insufficient_rules],
        "source_count": len(snapshot.get("sources", [])),
        "claim_verification_verdict": verification_verdict,
        "failures": failures,
        "warnings": warnings,
        "result": "FAIL" if failures else "WARN" if warnings else "PASS",
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
