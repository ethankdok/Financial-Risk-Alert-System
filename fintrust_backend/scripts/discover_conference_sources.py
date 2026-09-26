"""Discovery-only pass over official MOPS conference listings (no PDF download).

Single-threaded with a delay between requests and a per-(ticker, year) cache so
reruns do not hit MOPS again. Company names come from the official listing;
industry codes come from the project semiconductor taxonomy.

Run from fintrust_backend:
  python -m scripts.discover_conference_sources --tickers 2330,2454 --years 2024-2026 \\
      --cache-dir <dir> --output <report.json> [--delay 3]
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from app.services.conference_jsd_corpus_adapter import company_identity
from app.services.mops_conference_pdf_pipeline import HttpMopsTransport, discover_mops_conference_documents


def _years(value: str) -> list[int]:
    if "-" in value:
        start, end = value.split("-", 1)
        return list(range(int(start), int(end) + 1))
    return [int(item) for item in value.split(",")]


def summarize(ticker: str, results: list[dict]) -> dict:
    documents = [doc for result in results for doc in result.get("documents", [])]
    claims = Counter(doc["period_claimed_by_listing"] for doc in documents if doc["period_claimed_by_listing"])
    names = [doc["company_name"] for doc in documents if doc.get("company_name")]
    company, industry = company_identity(ticker, names[0] if names else None)
    anomalies = []
    for doc in documents:
        if len(doc["period_claims_all"]) > 1:
            anomalies.append({"filename": doc["filename"], "issue": "multiple_reported_periods_in_listing",
                              "periods": doc["period_claims_all"]})
    per_language = Counter((doc["language"], doc["period_claimed_by_listing"]) for doc in documents
                           if doc["period_claimed_by_listing"])
    for (language, period), count in per_language.items():
        if count > 1:
            anomalies.append({"issue": "several_files_claim_same_period", "language": language, "period": period,
                              "count": count})
    return {
        "ticker": ticker, "company": company, "industry": industry,
        "source": "MOPS t100sb02_1 法人說明會 (official)",
        "years": {str(result["year"]): {"status": result["status"], "documents": len(result.get("documents", [])),
                                        "listing_url": result["listing_url"], "error": result.get("error")}
                  for result in results},
        "discovered_documents": len(documents),
        "languages": dict(Counter(doc["language"] for doc in documents)),
        "listing_claimed_periods": sorted(claims),
        "documents_without_listing_period": sum(1 for doc in documents if not doc["period_claimed_by_listing"]),
        "files_reused_across_listing_rows": sum(1 for doc in documents if doc["listing_rows"] > 1),
        "anomalies": anomalies,
        "documents": documents,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tickers", required=True)
    parser.add_argument("--years", default="2024-2026")
    parser.add_argument("--market", default="sii")
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=3.0)
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    transport = HttpMopsTransport()
    report = {"source_policy": "official MOPS listing only; no PDF downloaded during discovery", "companies": []}
    for ticker in [item.strip() for item in args.tickers.split(",") if item.strip()]:
        results = []
        for year in _years(args.years):
            cache = args.cache_dir / f"{ticker}-{year}.json"
            if cache.is_file():
                results.append(json.loads(cache.read_text(encoding="utf-8")))
                continue
            result = discover_mops_conference_documents(ticker=ticker, year=year, market=args.market,
                                                        transport=transport)
            cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(result)
            print(f"{ticker} {year}: {result['status']} documents={len(result.get('documents', []))}", flush=True)
            time.sleep(args.delay)
        report["companies"].append(summarize(ticker, results))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
