from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SENSITIVE_FRAGMENTS = ("api_key", "apikey", "secret", "password_hash", "ingestion_token")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def request_json(url: str, timeout: float = 20.0) -> tuple[int, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - URLs are operator supplied.
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body) if body else None
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body) if body else None
        except json.JSONDecodeError:
            payload = body
        return exc.code, payload


def contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if any(fragment in lowered for fragment in SENSITIVE_FRAGMENTS):
                return True
            if contains_sensitive_key(item):
                return True
    elif isinstance(value, list):
        return any(contains_sensitive_key(item) for item in value)
    return False


def check(name: str, url: str, accepted: set[int], *, require_no_sensitive_keys: bool = True) -> CheckResult:
    try:
        status, payload = request_json(url)
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        return CheckResult(name, False, f"request failed: {exc}")
    if status not in accepted:
        return CheckResult(name, False, f"HTTP {status}: {str(payload)[:200]}")
    if require_no_sensitive_keys and contains_sensitive_key(payload):
        return CheckResult(name, False, "response contains a key that looks sensitive")
    return CheckResult(name, True, f"HTTP {status}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Non-destructive Cloud Run smoke tests for FinTrust.")
    parser.add_argument("--web-url", required=True, help="Flask Cloud Run base URL")
    parser.add_argument("--api-url", required=True, help="FastAPI Cloud Run base URL")
    parser.add_argument("--ticker", default="2330")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    web = args.web_url.rstrip("/")
    api = args.api_url.rstrip("/")
    ticker = args.ticker

    checks = [
        check("Flask health", f"{web}/health", {200}),
        check("Flask→FastAPI proxy health", f"{web}/api/financial/health", {200}),
        check("FastAPI health", f"{api}/health", {200}),
        check("FastAPI financial health", f"{api}/api/v1/financial/health", {200}),
        check("Company registry", f"{api}/api/v1/financial/companies", {200}),
        check("Persisted metrics contract", f"{api}/api/v1/financial/companies/{ticker}/metrics?limit=10", {200}),
        check("Analysis runs contract", f"{api}/api/v1/financial/companies/{ticker}/analysis-runs?limit=5", {200}),
        # A fresh project may legitimately have no snapshot yet. This checks the route without triggering ingestion.
        check("Latest snapshot route", f"{api}/api/v1/financial/companies/{ticker}/analysis/latest", {200, 404}),
    ]

    failures = 0
    for result in checks:
        label = "PASS" if result.ok else "FAIL"
        print(f"[{label}] {result.name}: {result.detail}")
        failures += 0 if result.ok else 1
    print(f"\nSummary: {len(checks) - failures}/{len(checks)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
