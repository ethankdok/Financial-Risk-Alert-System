"""Migrate validated financial pipeline rows to Firestore.

Dry-run is the default. Writes require ``--execute``. Legacy fact documents are
never left beside v2 fact-key documents: execution stops when legacy keys are
present unless ``--delete-legacy`` is also supplied. Targets are preflighted,
written in bounded batches, and read back before any legacy key is deleted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.services.analysis_repository import document_id, fact_document_id
from scripts.audit_database_contract import audit


COLLECTIONS = (
    "companies",
    "financial_filings",
    "normalized_financial_facts",
    "analysis_runs",
    "calculated_metrics",
    "rule_results",
    "latest_analysis_snapshots",
    "ingestion_runs",
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


def _parse_timestamp(value: str) -> datetime | str:
    if "T" not in value:
        return value
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _convert_temporal(value: Any, key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {item_key: _convert_temporal(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_convert_temporal(item) for item in value]
    if isinstance(value, str) and key and (key.endswith("_at") or key in {"generated_at", "data_updated_at"}):
        return _parse_timestamp(value)
    return value


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = {key: _decode(row[key]) for key in row.keys()}
    return _convert_temporal(payload)


def collect(source: Path, tickers: list[str]) -> dict[str, list[dict[str, Any]]]:
    connection = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result: dict[str, list[dict[str, Any]]] = {}
        latest_analysis_run_ids: set[str] = set()
        latest_ingestion_run_ids: set[str] = set()
        if "analysis_runs" in {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }:
            for ticker in tickers:
                row = connection.execute(
                    """SELECT run_id FROM analysis_runs
                       WHERE ticker = ? ORDER BY started_at DESC, run_id DESC LIMIT 1""",
                    (ticker,),
                ).fetchone()
                if row:
                    latest_analysis_run_ids.add(str(row["run_id"]))
        if "ingestion_runs" in {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }:
            for ticker in tickers:
                row = connection.execute(
                    """SELECT run_id FROM ingestion_runs
                       WHERE ticker = ? ORDER BY started_at DESC, run_id DESC LIMIT 1""",
                    (ticker,),
                ).fetchone()
                if row:
                    latest_ingestion_run_ids.add(str(row["run_id"]))
        for collection in COLLECTIONS:
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (collection,)
            ).fetchone():
                result[collection] = []
                continue
            rows = connection.execute(f'SELECT * FROM "{collection}"').fetchall()
            selected = [row for row in rows if not tickers or str(row["ticker"]) in tickers]
            if collection == "analysis_runs":
                selected = [row for row in selected if str(row["run_id"]) in latest_analysis_run_ids]
            elif collection in {"calculated_metrics", "rule_results"}:
                selected = [row for row in selected if str(row["run_id"]) in latest_analysis_run_ids]
            elif collection == "ingestion_runs":
                selected = [row for row in selected if str(row["run_id"]) in latest_ingestion_run_ids]
            payloads: list[dict[str, Any]] = []
            for row in selected:
                payload = _row_payload(row)
                if collection == "latest_analysis_snapshots" and isinstance(payload.get("snapshot_json"), dict):
                    snapshot = payload.pop("snapshot_json")
                    snapshot["updated_at"] = payload.get("updated_at")
                    payload = snapshot
                if collection == "normalized_financial_facts":
                    payload["fact_key_version"] = "financial-fact-v2"
                payloads.append(payload)
            result[collection] = payloads
        return result
    finally:
        connection.close()


def target_document_id(collection: str, item: dict[str, Any]) -> str:
    if collection == "normalized_financial_facts":
        return fact_document_id(item)
    if collection == "companies":
        return str(item["ticker"])
    if collection == "financial_filings":
        return document_id(item["ticker"], item["period"])
    if collection in {"analysis_runs", "ingestion_runs"}:
        return str(item["run_id"])
    if collection == "latest_analysis_snapshots":
        return str(item["ticker"])
    if collection == "calculated_metrics":
        return document_id(item["run_id"], item["analysis_type"], item["period"], item["metric_code"])
    if collection == "rule_results":
        return document_id(item["run_id"], item["analysis_type"], item["rule_id"])
    raise ValueError(f"Unsupported collection: {collection}")


def legacy_document_ids(collection: str, item: dict[str, Any]) -> list[str]:
    if collection != "normalized_financial_facts":
        return []
    ids = {
        document_id(item["ticker"], item["analysis_type"], item["period"], item["metric_code"]),
        document_id(
            item["ticker"],
            item["analysis_type"],
            item["period"],
            item["metric_code"],
            item.get("statement_scope", "unknown"),
        ),
    }
    ids.discard(target_document_id(collection, item))
    return sorted(ids)


def _json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def fingerprint(value: Any) -> str:
    encoded = json.dumps(_json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_plan(rows: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    documents_by_target: dict[tuple[str, str], dict[str, Any]] = {}
    source_conflicts: list[dict[str, Any]] = []
    for collection in COLLECTIONS:
        for item in rows.get(collection, []):
            document_id_value = target_document_id(collection, item)
            candidate = {
                "collection": collection,
                "document_id": document_id_value,
                "legacy_document_ids": legacy_document_ids(collection, item),
                "fingerprint": fingerprint(item),
                "payload": item,
            }
            key = (collection, document_id_value)
            previous = documents_by_target.get(key)
            if previous is None:
                documents_by_target[key] = candidate
            elif previous["fingerprint"] != candidate["fingerprint"]:
                source_conflicts.append(
                    {
                        "collection": collection,
                        "document_id": document_id_value,
                        "reason": "multiple_source_rows_map_to_one_v2_key",
                        "source_fingerprints": sorted(
                            {previous["fingerprint"], candidate["fingerprint"]}
                        ),
                    }
                )
    documents = [documents_by_target[key] for key in sorted(documents_by_target)]
    counts = {collection: len(rows.get(collection, [])) for collection in COLLECTIONS}
    public_documents = [
        {key: value for key, value in document.items() if key != "payload"}
        for document in documents
    ]
    return {
        "counts": counts,
        "document_count": len(documents),
        "fingerprint": fingerprint(public_documents),
        "source_conflicts": source_conflicts,
        "documents": documents,
    }


def preflight(client: Any, plan: dict[str, Any]) -> dict[str, Any]:
    conflicts: list[dict[str, Any]] = []
    legacy_documents: list[dict[str, str]] = []
    existing_targets = 0
    for document in plan["documents"]:
        collection = document["collection"]
        target = client.collection(collection).document(document["document_id"])
        snapshot = target.get()
        if snapshot.exists:
            existing_targets += 1
            existing = snapshot.to_dict() or {}
            if fingerprint(existing) != document["fingerprint"]:
                conflicts.append(
                    {
                        "collection": collection,
                        "document_id": document["document_id"],
                        "reason": "target_payload_differs",
                    }
                )
        for legacy_id in document["legacy_document_ids"]:
            legacy = client.collection(collection).document(legacy_id).get()
            if legacy.exists:
                legacy_documents.append({"collection": collection, "document_id": legacy_id})
    return {
        "existing_targets": existing_targets,
        "legacy_documents": legacy_documents,
        "conflicts": conflicts,
    }


def execute_plan(client: Any, plan: dict[str, Any], *, delete_legacy: bool) -> dict[str, Any]:
    if plan["source_conflicts"]:
        raise RuntimeError("Source rows collide under the v2 fact key; no writes performed.")
    inspection = preflight(client, plan)
    if inspection["conflicts"]:
        raise RuntimeError("Firestore target conflicts detected; no writes performed.")
    if inspection["legacy_documents"] and not delete_legacy:
        raise RuntimeError(
            "Legacy fact documents exist. Re-run only after review with --delete-legacy; no writes performed."
        )

    writes = 0
    for start in range(0, len(plan["documents"]), 200):
        batch = client.batch()
        for document in plan["documents"][start : start + 200]:
            ref = client.collection(document["collection"]).document(document["document_id"])
            batch.set(ref, document["payload"], merge=False)
            writes += 1
        batch.commit()

    verification_failures: list[dict[str, str]] = []
    for document in plan["documents"]:
        snapshot = client.collection(document["collection"]).document(document["document_id"]).get()
        actual = snapshot.to_dict() if snapshot.exists else None
        if actual is None or fingerprint(actual) != document["fingerprint"]:
            verification_failures.append(
                {"collection": document["collection"], "document_id": document["document_id"]}
            )
    if verification_failures:
        raise RuntimeError(f"Firestore read-back verification failed: {verification_failures}")

    deletes = 0
    if delete_legacy:
        for start in range(0, len(inspection["legacy_documents"]), 200):
            batch = client.batch()
            for legacy in inspection["legacy_documents"][start : start + 200]:
                ref = client.collection(legacy["collection"]).document(legacy["document_id"])
                batch.delete(ref)
                deletes += 1
            batch.commit()

    return {
        **inspection,
        "writes": writes,
        "legacy_deletes": deletes,
        "verification": "PASS",
    }


def _report_payload(
    *,
    status: str,
    project: str,
    tickers: list[str],
    plan: dict[str, Any],
    execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "project": project,
        "tickers": tickers,
        "counts": plan["counts"],
        "document_count": plan["document_count"],
        "fingerprint": plan["fingerprint"],
        "fact_key_version": "financial-fact-v2",
        "run_selection": "latest analysis run and latest ingestion run per ticker",
        "source_conflicts": plan["source_conflicts"],
        "execute": status == "written",
    }
    if execution is not None:
        payload["execution"] = execution
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/backfill-small-v2.sqlite3"))
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "fintrust-alert-ccu"))
    parser.add_argument("--tickers", nargs="+", default=["2330", "2454"])
    parser.add_argument("--execute", action="store_true", help="Actually write Firestore documents")
    parser.add_argument(
        "--delete-legacy",
        action="store_true",
        help="After verified writes, delete superseded v1 fact documents",
    )
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    if args.delete_legacy and not args.execute:
        raise SystemExit("--delete-legacy requires --execute")
    if not args.source.is_file():
        raise SystemExit(f"Source database does not exist: {args.source}")

    audit_result = audit(args.source)
    if audit_result["gate"] != "PASS":
        report = {"status": "blocked", "execute": False, "audit": audit_result}
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(
                json.dumps(_json_value(report), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        print(json.dumps(_json_value(report), ensure_ascii=False, indent=2))
        return 2

    rows = collect(args.source, args.tickers)
    plan = build_plan(rows)
    if not args.execute:
        report = _report_payload(
            status="dry_run", project=args.project, tickers=args.tickers, plan=plan
        )
    else:
        from google.cloud import firestore

        client = firestore.Client(project=args.project)
        execution = execute_plan(client, plan, delete_legacy=args.delete_legacy)
        report = _report_payload(
            status="written",
            project=args.project,
            tickers=args.tickers,
            plan=plan,
            execution=execution,
        )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(_json_value(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(_json_value(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
