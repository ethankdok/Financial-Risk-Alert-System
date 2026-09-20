"""Migrate validated financial pipeline rows to Firestore.

Dry-run is the default. ``--execute`` is required for writes. The source is
rejected when the contract audit is blocked; this prevents known period/source
errors from being copied into the production database.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from app.services.analysis_repository import document_id


COLLECTIONS = (
    "companies", "financial_filings", "normalized_financial_facts",
    "analysis_runs", "calculated_metrics", "rule_results",
    "latest_analysis_snapshots", "ingestion_runs",
)


def _decode(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = {key: _decode(row[key]) for key in row.keys()}
    for key in ("listed_at", "source_report_date"):
        # Firestore accepts date strings, and keeping the source representation
        # avoids timezone assumptions during migration.
        payload[key] = payload.get(key)
    return payload


def collect(source: Path, tickers: list[str]) -> dict[str, list[dict[str, Any]]]:
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    try:
        result: dict[str, list[dict[str, Any]]] = {}
        for collection in COLLECTIONS:
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (collection,)
            ).fetchone():
                result[collection] = []
                continue
            rows = connection.execute(f"SELECT * FROM {collection}").fetchall()
            selected = [row for row in rows if not tickers or row["ticker"] in tickers]
            payloads = []
            for row in selected:
                payload = _row_payload(row)
                if collection == "latest_analysis_snapshots" and isinstance(payload.get("snapshot_json"), dict):
                    snapshot = payload.pop("snapshot_json")
                    snapshot["updated_at"] = payload.get("updated_at")
                    payload = snapshot
                payloads.append(payload)
            result[collection] = payloads
        return result
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/backfill-small-v2.sqlite3"))
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "fintrust-alert-ccu"))
    parser.add_argument("--tickers", nargs="+", default=["2330", "2454"])
    parser.add_argument("--execute", action="store_true", help="Actually write Firestore documents")
    args = parser.parse_args()

    if not args.source.is_file():
        raise SystemExit(f"Source database does not exist: {args.source}")
    # Import lazily so the read-only dry-run works without google-cloud-firestore.
    from audit_database_contract import audit
    audit_result = audit(args.source)
    if audit_result["gate"] != "PASS":
        print(json.dumps({"status": "blocked", "audit": audit_result}, ensure_ascii=False, indent=2))
        return 2

    rows = collect(args.source, args.tickers)
    summary = {collection: len(items) for collection, items in rows.items()}
    if not args.execute:
        print(json.dumps({"status": "dry_run", "project": args.project, "tickers": args.tickers, "counts": summary}, ensure_ascii=False, indent=2))
        return 0

    from google.cloud import firestore
    client = firestore.Client(project=args.project)
    writes = 0
    for collection, items in rows.items():
        for item in items:
            if collection == "normalized_financial_facts":
                key = document_id(
                    item["ticker"], item["analysis_type"], item["period"],
                    item["metric_code"], item.get("statement_scope", "unknown"),
                )
            elif collection == "companies":
                key = item["ticker"]
            elif collection == "financial_filings":
                key = document_id(item["ticker"], item["period"])
            elif collection in {"analysis_runs", "ingestion_runs", "latest_analysis_snapshots"}:
                key = item.get("run_id") or item["ticker"]
            elif collection == "calculated_metrics":
                key = document_id(item["run_id"], item["analysis_type"], item["period"], item["metric_code"])
            elif collection == "rule_results":
                key = document_id(item["run_id"], item["analysis_type"], item["rule_id"])
            else:  # pragma: no cover
                raise ValueError(collection)
            client.collection(collection).document(key).set(item, merge=True)
            writes += 1

    print(json.dumps({"status": "written", "project": args.project, "tickers": args.tickers, "counts": summary, "writes": writes}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
