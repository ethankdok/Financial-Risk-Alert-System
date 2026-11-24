#!/usr/bin/env python3
"""Read-only FinTrust preview and production smoke.

Core probes use public GET APIs. Optional integration APIs may be 404 on the
currently deployed Cloud Run service: this is reported as PENDING, not as proof
of success. --strict-full-stack also requires optional integration endpoints.
Usage:
  python scripts/fintrust_user_first_ui_smoke.py \
      --base https://fintrust-ui-preview-20261124.vercel.app --ticker 2330
"""
from __future__ import annotations

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def fetch(base: str, path: str, *, body: dict | None = None) -> tuple[int, str]:
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(base.rstrip("/") + path, data=payload, headers=headers,
                      method="POST" if payload is not None else "GET")
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, response.read(6_000_000).decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read(300_000).decode("utf-8", "replace")


def parse_json(body: str) -> dict | list:
    try:
        return json.loads(body)
    except ValueError:
        return {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5000")
    parser.add_argument("--ticker", default="2330")
    parser.add_argument("--strict-full-stack", action="store_true")
    args = parser.parse_args()
    failures: list[str] = []
    pending: list[str] = []

    static = [
        ("/", "ft-home-query"),
        ("/analysis.html", "ft-form"),
        ("/financial-audit.html", "ft-sheet-report"),
        ("/member-demo.html", "ft-member-panel"),
        ("/ft-site.css", ".ft-app"),
        ("/ft-site.js", "window.FTLiveFinancial"),
        ("/ft-company-search.js", "FTCompanies"),
        ("/ft-news-evidence.js", "FTNewsEvidence"),
        ("/ft-narrative.js", "FTNarrative"),
        ("/ft-live-financial.js", "FTLiveFinancial"),
        ("/ft-mops-report.js", "beneish"),
        ("/ft-mops-data.json", '"industries"'),
        ("/ft-i18n.js", "FTLocale"),
        ("/ft-demo.js", "FTDemo"),
    ]
    for path, marker in static:
        try:
            code, body = fetch(args.base, path)
            success = code == 200 and marker in body
            print(f"{'PASS' if success else 'FAIL'} static {path}: HTTP {code}")
            if not success:
                failures.append(path)
        except URLError as exc:
            print(f"FAIL static {path}: {exc}")
            failures.append(path)

    probes = [
        ("/api/financial/health", lambda d: d.get("success") is True and
         (d.get("data") or {}).get("status") == "ok"),
        ("/api/financial/companies", lambda d: d.get("success") is True and
         isinstance((d.get("data") or {}).get("companies"), list)),
        (f"/api/financial/companies/{args.ticker}/card",
         lambda d: d.get("success") is True and
         (d.get("data") or {}).get("ticker") == args.ticker),
        (f"/api/financial/companies/{args.ticker}/metrics",
         lambda d: d.get("success") is True and
         isinstance((d.get("data") or {}).get("metrics"), list)),
    ]
    for path, verify in probes:
        try:
            code, body = fetch(args.base, path)
            obj = parse_json(body)
            valid = code == 200 and isinstance(obj, dict) and verify(obj)
            print(f"{'PASS' if valid else 'FAIL'} live {path}: HTTP {code}")
            if not valid:
                failures.append(path)
        except URLError as exc:
            print(f"FAIL live {path}: {exc}")
            failures.append(path)

    for market, sample in (("listed", "2330"), ("otc", "1240")):
        path = f"/data/companies/{market}"
        try:
            code, body = fetch(args.base, path)
            raw = parse_json(body)
            companies = raw if isinstance(raw, list) else (raw.get("data") or [])
            valid = code == 200 and len(companies) > 100 and any(
                str(item.get("ticker") or item.get("公司代號") or
                    item.get("SecuritiesCompanyCode") or "") == sample
                for item in companies if isinstance(item, dict)
            )
            print(f"{'PASS' if valid else 'FAIL'} directory {market}: "
                  f"HTTP {code}, {len(companies)} records")
            if not valid:
                failures.append(path)
        except (URLError, TypeError) as exc:
            print(f"FAIL directory {path}: {exc}")
            failures.append(path)

    optional = [
        ("/api/integrity/companies", None),
        ("/api/integrity/assessments/preview",
         {"ticker": args.ticker, "review_mode": "CURRENT_REVIEW",
          "sections": ["financial_checks", "literature", "jsd", "claims"],
          "persist": False}),
    ]
    for path, body in optional:
        try:
            code, reply = fetch(args.base, path, body=body)
            if code == 404:
                pending.append(path)
                print(f"PENDING optional {path}: not deployed")
            elif code == 200 and isinstance(parse_json(reply), dict) and parse_json(reply).get("success") is True:
                print(f"PASS optional {path}: HTTP 200")
            else:
                failures.append(path)
                print(f"FAIL optional {path}: HTTP {code}")
        except URLError as exc:
            pending.append(path)
            print(f"PENDING optional {path}: {exc}")

    if args.strict_full_stack:
        failures.extend(pending)
    print(f"\nSummary: {len(failures)} failure(s), {len(pending)} optional pending.")
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
