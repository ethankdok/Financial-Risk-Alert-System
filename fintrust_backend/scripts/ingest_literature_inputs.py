"""Build / extend the append-only literature-input store from the preserved raw archive (no network).

Reads ``financial_filing_versions`` of the approved historical database read-only (``mode=ro``), re-verifies each
archived artifact's SHA-256, extracts line observations (``literature_extraction``) and appends them to the separate
sidecar store. Idempotent: re-running with identical inputs creates nothing new. Bounded: only the requested ticker's
consolidated annual filings; no download is attempted (FY2011-2012 MOPS XBRL acquisition was already recorded as
``filing_not_found`` in the approved archive, and MOPS serves only the current XBRL version).

    python -m scripts.ingest_literature_inputs --ticker 1785 [--dry-run] [--report out.json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from app.services.financial_research.input_snapshot import digest
from app.services.financial_research.literature_extraction import EXTRACTOR_VERSION, extract_filing
from app.services.financial_research.literature_store import DEFAULT_LITERATURE_DATABASE, LiteratureInputStore
from app.services.financial_research.service import DEFAULT_DATABASE, DEFAULT_RAW_ROOT, ReadOnlyHistoricalAuditRepository


def run(ticker: str, *, database: str, raw_root: str, store_path: str, dry_run: bool) -> dict:
    repository = ReadOnlyHistoricalAuditRepository(database)
    versions = [v for v in repository.list_filing_versions(ticker) if v["statement_scope"] == "consolidated"]
    observations, diagnostics = [], []
    for version in sorted(versions, key=lambda v: (v["fiscal_year"], v["filing_version_id"])):
        rows, diagnostic = extract_filing(raw_root, version)
        observations.extend(rows)
        diagnostics.append(diagnostic)
    report = {"ticker": ticker, "extractor_version": EXTRACTOR_VERSION, "artifacts": len(diagnostics),
              "observations": len(observations), "dry_run": dry_run,
              "status_counts": {}, "network_requests": 0, "approved_database_opened": "read_only"}
    for diagnostic in diagnostics:
        report["status_counts"][diagnostic["status"]] = report["status_counts"].get(diagnostic["status"], 0) + 1
    report["artifacts_detail"] = [{k: d.get(k) for k in ("fiscal_year", "filing_version_id", "filing_version_type",
                                                          "source_kind", "status", "observations", "raw_sha256",
                                                          "statement_pages", "identity_checks", "arithmetic_checks")}
                                  for d in diagnostics]
    report["observation_digest"] = digest(sorted(o["observation_id"] for o in observations))
    if dry_run:
        report["new_observations"] = None
        return report
    store = LiteratureInputStore(store_path, protected=(database,))
    created = store.record_observations(observations)
    store.record_diagnostics(ticker, diagnostics, EXTRACTOR_VERSION)
    run_id = "lrun1_" + digest({"ticker": ticker, "extractor": EXTRACTOR_VERSION,
                                "observations": report["observation_digest"]})[:32]
    store.record_run({"extraction_run_id": run_id, "extractor_version": EXTRACTOR_VERSION, "ticker": ticker,
                      "artifacts": report["artifacts_detail"], "observation_count": len(observations),
                      "new_observation_count": created, "git_commit": os.getenv("FINTRUST_BUILD_COMMIT") or None})
    report.update(new_observations=created, extraction_run_id=run_id, store_counts=store.counts())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ticker", default="1785")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--raw-root", default=DEFAULT_RAW_ROOT)
    parser.add_argument("--store", default=DEFAULT_LITERATURE_DATABASE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    report = run(args.ticker, database=args.database, raw_root=args.raw_root, store_path=args.store,
                 dry_run=args.dry_run)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(json.dumps({k: v for k, v in report.items() if k != "artifacts_detail"}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
