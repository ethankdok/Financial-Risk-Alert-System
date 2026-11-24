#!/usr/bin/env python3
"""Non-mutating UI/API smoke for the isolated FinTrust user-first branch.
Usage: python scripts/fintrust_user_first_ui_smoke.py --base https://fintrust-ui-preview-20261124.vercel.app --ticker 1785
Requires Flask and FastAPI started with working FINTRUST_API_BASE_URL. Only assessment preview posts;
the preview endpoint explicitly rejects persistence and does not scrape live content.
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
                      method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=18) as response:
            return response.status, response.read(2_000_000).decode("utf-8", "replace")
    except HTTPError as exc:
        return exc.code, exc.read(200_000).decode("utf-8", "replace")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:5000")
    parser.add_argument("--ticker", default="1785")
    args = parser.parse_args()
    checks = [
        ("/", 200, "ft-home-query"),
        ("/analysis.html", 200, "ft-form"),
        ("/financial-audit.html", 200, "ft-audit-form"),
        ("/member.html", 200, "watchlistForm"),
        ("/member-demo.html", 200, "ft-member-panel"),
        ("/ft-demo.js", 200, "window.FTDemo"),
        ("/ft-company-search.js", 200, "window.FTCompanies"),
        ("/ft-member-demo.js", 200, "ft-member-demo-v1"),
        ("/ft-i18n.js", 200, "window.FTLocale"),
        ("/ft-mops-data.json", 200, '"industries"'),
        ("/ft-site.css", 200, "ft-header"),
        ("/ft-site.js", 200, "renderAssessment"),
    ]
    failures = []
    for path, expected_code, required_text in checks:
        try:
            status, content = fetch(args.base, path)
            ok = status == expected_code and required_text in content
        except URLError as exc:
            status, ok = str(exc), False
        print(f"{'PASS' if ok else 'FAIL'} static {path}: {status}")
        if not ok:
            failures.append(path)

    try:
        status, body = fetch(args.base, "/api/financial/health")
        data = json.loads(body) if body else {}
        ok = status == 200 and data.get("success") is True
        print(f"{'PASS' if ok else 'FAIL'} Flask-to-FastAPI health: {status}")
        if not ok:
            failures.append("financial API health")
    except (URLError, ValueError) as exc:
        print(f"FAIL financial API health: {exc}")
        failures.append("financial API health")

    try:
        status, body = fetch(args.base, "/api/integrity/companies")
        data = json.loads(body) if body else {}
        items = data.get("data") or {}
        ok = status == 200 and data.get("success") is True and isinstance(
            items.get("companies") if isinstance(items, dict) else None, list
        )
        print(f"{'PASS' if ok else 'FAIL'} companies API: {status}")
        if not ok:
            failures.append("companies API")
    except (URLError, ValueError) as exc:
        print(f"FAIL companies API: {exc}")
        failures.append("companies API")

    try:
        status, body = fetch(args.base, "/api/integrity/assessments/preview",
                             body={"ticker": args.ticker, "review_mode": "CURRENT_REVIEW",
                                   "sections": ["financial_checks", "literature", "jsd", "claims"],
                                   "persist": False})
        data = json.loads(body) if body else {}
        ok = status == 200 and data.get("success") is True and isinstance(data.get("data"), dict)
        print(f"{'PASS' if ok else 'FAIL'} assessment preview API: {status}")
        if not ok:
            print("  detail:", str(data.get("detail") or data.get("error") or "")[:180])
            failures.append("assessment preview")
    except (URLError, ValueError) as exc:
        print(f"FAIL assessment preview: {exc}")
        failures.append("assessment preview")

    try:
        status, _ = fetch(args.base, "/api/member/me")
        ok = status == 401  # Unauthorized access must remain private.
        print(f"{'PASS' if ok else 'FAIL'} member authorization: {status}")
        if not ok:
            failures.append("member authorization")
    except URLError as exc:
        print(f"FAIL member authorization: {exc}")
        failures.append("member authorization")

    if failures:
        print("NOT READY: " + ", ".join(failures))
        return 1
    print("READY: UI/demo assets, proxied financial API, live read-only assessment, and member authorization checked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
