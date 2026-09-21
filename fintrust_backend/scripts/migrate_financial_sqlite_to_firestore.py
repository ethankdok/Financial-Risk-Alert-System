"""Migrate validated financial pipeline rows to Firestore.

Dry-run is the default. Writes require ``--execute``. Legacy fact documents are
always retained; compatible readers prefer v2 facts and use legacy facts only as
a fallback. Targets are classified before writes and every mutation is read back.
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

from app.services.analysis_repository import (
    document_id,
    fact_document_id,
    legacy_fact_document_ids,
)
from app.pipeline_models import COMPLETED_RUN_STATUS
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

JSON_FIELD_NAMES = {
    "companies": {"aliases_json": "aliases"},
    "financial_filings": {
        "concept_matches_json": "concept_matches",
        "warnings_json": "warnings",
    },
    "calculated_metrics": {
        "comparison_periods_json": "comparison_periods",
        "source_fields_json": "source_fields",
    },
    "rule_results": {
        "actual_values_json": "actual_values",
        "evidence_metrics_json": "evidence_metrics",
        "evidence_periods_json": "evidence_periods",
    },
    "ingestion_runs": {"persistence_json": "persistence"},
}

FRESHNESS_FIELDS = {
    "companies": "synced_at",
    "financial_filings": "retrieved_at",
    "normalized_financial_facts": "retrieved_at",
    "latest_analysis_snapshots": "updated_at",
}

IDENTITY_FIELDS = {
    "companies": ("ticker",),
    "financial_filings": ("ticker", "period", "source_url"),
    "normalized_financial_facts": (
        "ticker", "metric_code", "period", "statement_scope", "statement_type",
        "unit", "source_kind", "source_url",
    ),
    "latest_analysis_snapshots": ("ticker",),
}


class NoValidRunError(RuntimeError):
    def __init__(self, collection: str, ticker: str) -> None:
        self.collection = collection
        self.ticker = ticker
        super().__init__(f"no-valid-run: {collection} has no completed run for {ticker}")


class AtomicWriteConflict(RuntimeError):
    def __init__(self, path: str, reason: str, *, attempted_paths: list[str]) -> None:
        self.path = path
        self.reason = reason
        self.attempted_paths = attempted_paths
        super().__init__(f"atomic-write-conflict: {path}: {reason}")


class PostWriteVerificationError(RuntimeError):
    def __init__(self, execution: dict[str, Any]) -> None:
        self.execution = execution
        super().__init__(
            f"Firestore read-back verification failed: {execution['verification_failures']}"
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


def _normalize_payload(collection: str, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for old_name, new_name in JSON_FIELD_NAMES.get(collection, {}).items():
        if old_name in normalized:
            normalized[new_name] = normalized.pop(old_name)
    return normalized


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
                       WHERE ticker = ? AND status = ?
                       ORDER BY started_at DESC, run_id DESC LIMIT 1""",
                    (ticker, COMPLETED_RUN_STATUS),
                ).fetchone()
                if row is None:
                    raise NoValidRunError("analysis_runs", ticker)
                latest_analysis_run_ids.add(str(row["run_id"]))
        if "ingestion_runs" in {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }:
            for ticker in tickers:
                row = connection.execute(
                    """SELECT run_id FROM ingestion_runs
                       WHERE ticker = ? AND status = ?
                       ORDER BY started_at DESC, run_id DESC LIMIT 1""",
                    (ticker, COMPLETED_RUN_STATUS),
                ).fetchone()
                if row is None:
                    raise NoValidRunError("ingestion_runs", ticker)
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
                payload = _normalize_payload(collection, _row_payload(row))
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
    return legacy_fact_document_ids(item)


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
        "selected_runs": {
            collection: [
                {
                    key: row.get(key)
                    for key in ("ticker", "run_id", "status", "started_at")
                }
                for row in rows.get(collection, [])
            ]
            for collection in ("analysis_runs", "ingestion_runs")
        },
    }


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and "T" in value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify_target(collection: str, source: dict[str, Any], target: dict[str, Any] | None) -> str:
    if target is None:
        return "NEW"
    if fingerprint(target) == fingerprint(source):
        return "SAME"
    freshness_field = FRESHNESS_FIELDS.get(collection)
    identity_fields = IDENTITY_FIELDS.get(collection)
    if not freshness_field or not identity_fields:
        return "DIVERGENT"
    if any(source.get(field) != target.get(field) for field in identity_fields):
        return "DIVERGENT"
    source_time = _timestamp(source.get(freshness_field))
    target_time = _timestamp(target.get(freshness_field))
    if source_time is None or target_time is None or source_time == target_time:
        return "DIVERGENT"
    return "SOURCE_NEWER" if source_time > target_time else "TARGET_NEWER"


def preflight(client: Any, plan: dict[str, Any]) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    legacy_documents: list[dict[str, str]] = []
    target_update_times: dict[str, Any] = {}
    references: dict[str, Any] = {}
    for document in plan["documents"]:
        collection = document["collection"]
        document_id_value = document["document_id"]
        references[f"{collection}/{document_id_value}"] = (
            client.collection(collection).document(document_id_value)
        )
        for legacy_id in document["legacy_document_ids"]:
            references[f"{collection}/{legacy_id}"] = client.collection(collection).document(legacy_id)
    snapshots: dict[str, Any] | None = None
    if hasattr(client, "get_all"):
        snapshots = {snapshot.reference.path: snapshot for snapshot in client.get_all(references.values())}

    def read_snapshot(collection: str, document_id_value: str) -> Any:
        path = f"{collection}/{document_id_value}"
        if snapshots is not None:
            return snapshots[path]
        return references[path].get()

    for document in plan["documents"]:
        collection = document["collection"]
        snapshot = read_snapshot(collection, document["document_id"])
        existing = snapshot.to_dict() if snapshot.exists else None
        path = f"{collection}/{document['document_id']}"
        target_update_times[path] = getattr(snapshot, "update_time", None)
        classification = classify_target(collection, document["payload"], existing)
        overlaps: list[str] = []
        for legacy_id in document["legacy_document_ids"]:
            legacy = read_snapshot(collection, legacy_id)
            if legacy.exists:
                legacy_path = f"{collection}/{legacy_id}"
                overlaps.append(legacy_path)
                legacy_documents.append(
                    {"collection": collection, "document_id": legacy_id, "path": legacy_path}
                )
        entries.append(
            {
                "collection": collection,
                "document_id": document["document_id"],
                "path": path,
                "ticker": str(document["payload"].get("ticker") or ""),
                "classification": classification,
                "source_fingerprint": document["fingerprint"],
                "target_exists": bool(snapshot.exists),
                "target_fingerprint": fingerprint(existing) if existing is not None else None,
                "legacy_overlap_paths": overlaps,
            }
        )
    counts: dict[str, int] = {}
    for entry in entries:
        classification = entry["classification"]
        counts[classification] = counts.get(classification, 0) + 1
    counts["LEGACY_OVERLAP"] = len(legacy_documents)
    return {
        "entries": entries,
        "classification_counts": counts,
        "legacy_documents": legacy_documents,
        "legacy_overlap_count": len(legacy_documents),
        "_target_update_times": target_update_times,
    }


def build_manifest(plan: dict[str, Any], inspection: dict[str, Any]) -> dict[str, Any]:
    migration_id = f"financial-datastore-{plan['fingerprint'][:16]}"
    entries: list[dict[str, Any]] = []
    for entry in inspection["entries"]:
        classification = entry["classification"]
        action = {
            "NEW": "CREATE",
            "SAME": "NO_OP",
            "SOURCE_NEWER": "OVERWRITE_CANDIDATE",
            "TARGET_NEWER": "BLOCK",
            "DIVERGENT": "BLOCK",
        }[classification]
        rollback = {
            "NEW": "DELETE_CREATED_DOCUMENT",
            "SOURCE_NEWER": "RESTORE_PRE_IMAGE",
        }.get(classification, "NONE")
        entries.append(
            {
                **entry,
                "migration_id": migration_id,
                "action": action,
                "pre_image_backup_required": classification == "SOURCE_NEWER",
                "rollback_action": rollback,
                "legacy_documents_preserved": True,
            }
        )
    public = {
        "migration_id": migration_id,
        "source_plan_fingerprint": plan["fingerprint"],
        "entries": entries,
        "legacy_documents": inspection["legacy_documents"],
        "expected_create_count": sum(entry["classification"] == "NEW" for entry in entries),
        "overwrite_candidate_count": sum(
            entry["classification"] == "SOURCE_NEWER" for entry in entries
        ),
    }
    return {**public, "manifest_fingerprint": fingerprint(public)}


def execute_plan(
    client: Any,
    plan: dict[str, Any],
    *,
    allow_source_newer_overwrite: bool = False,
) -> dict[str, Any]:
    if plan["source_conflicts"]:
        raise RuntimeError("Source rows collide under the v2 fact key; no writes performed.")
    inspection = preflight(client, plan)
    blocked = [
        entry for entry in inspection["entries"]
        if entry["classification"] in {"TARGET_NEWER", "DIVERGENT"}
    ]
    if blocked:
        raise RuntimeError("Firestore target has newer or divergent documents; no writes performed.")
    overwrite_candidates = [
        entry for entry in inspection["entries"]
        if entry["classification"] == "SOURCE_NEWER"
    ]
    if overwrite_candidates and not allow_source_newer_overwrite:
        raise RuntimeError("Source-newer overwrite candidates require explicit opt-in; no writes performed.")

    allowed_paths = {
        entry["path"] for entry in inspection["entries"]
        if entry["classification"] == "NEW"
        or (entry["classification"] == "SOURCE_NEWER" and allow_source_newer_overwrite)
    }
    mutations = [
        document for document in plan["documents"]
        if f"{document['collection']}/{document['document_id']}" in allowed_paths
    ]
    attempted_paths = [
        f"{document['collection']}/{document['document_id']}" for document in mutations
    ]
    entries_by_path = {entry["path"]: entry for entry in inspection["entries"]}

    if not mutations:
        return {
            **{key: value for key, value in inspection.items() if not key.startswith("_")},
            "attempted_writes": 0,
            "writes": 0,
            "created_paths": [],
            "overwritten_paths": [],
            "failed_writes": 0,
            "skipped_writes": 0,
            "legacy_deletes": 0,
            "legacy_documents_preserved": True,
            "verification": "PASS",
            "executed_at": datetime.now(timezone.utc),
        }

    # One company-scoped transaction keeps all reads ahead of all writes and
    # makes a concurrent target change abort the entire execution unit.
    transaction = client.transaction()
    transaction_reads: dict[str, Any] = {}
    references: dict[str, Any] = {}
    for document in mutations:
        path = f"{document['collection']}/{document['document_id']}"
        reference = client.collection(document["collection"]).document(document["document_id"])
        references[path] = reference
        transaction_reads[path] = reference.get(transaction=transaction)

    for path in attempted_paths:
        entry = entries_by_path[path]
        snapshot = transaction_reads[path]
        if entry["classification"] == "NEW":
            if snapshot.exists:
                raise AtomicWriteConflict(
                    path, "NEW target was created after preflight", attempted_paths=attempted_paths
                )
            continue

        expected_update_time = inspection["_target_update_times"].get(path)
        current_update_time = getattr(snapshot, "update_time", None)
        if not snapshot.exists or current_update_time != expected_update_time:
            raise AtomicWriteConflict(
                path,
                "SOURCE_NEWER target version changed after preflight",
                attempted_paths=attempted_paths,
            )

    for document in mutations:
        path = f"{document['collection']}/{document['document_id']}"
        transaction.set(references[path], document["payload"], merge=False)
    try:
        transaction.commit()
    except Exception as exc:
        path = attempted_paths[0] if attempted_paths else "<empty-plan>"
        raise AtomicWriteConflict(
            path,
            f"transaction commit rejected; no migration writes committed ({type(exc).__name__})",
            attempted_paths=attempted_paths,
        ) from exc

    writes = len(mutations)
    created_paths = [
        path for path in attempted_paths if entries_by_path[path]["classification"] == "NEW"
    ]
    overwritten_paths = [
        path
        for path in attempted_paths
        if entries_by_path[path]["classification"] == "SOURCE_NEWER"
    ]

    verification_failures: list[dict[str, str]] = []
    for document in mutations:
        snapshot = client.collection(document["collection"]).document(document["document_id"]).get()
        actual = snapshot.to_dict() if snapshot.exists else None
        if actual is None or fingerprint(actual) != document["fingerprint"]:
            verification_failures.append(
                {"collection": document["collection"], "document_id": document["document_id"]}
            )
    if verification_failures:
        raise PostWriteVerificationError(
            {
                **{key: value for key, value in inspection.items() if not key.startswith("_")},
                "attempted_writes": len(attempted_paths),
                "writes": writes,
                "created_paths": created_paths,
                "overwritten_paths": overwritten_paths,
                "failed_writes": len(verification_failures),
                "skipped_writes": 0,
                "legacy_deletes": 0,
                "legacy_documents_preserved": True,
                "verification": "FAIL",
                "verification_failures": verification_failures,
                "executed_at": datetime.now(timezone.utc),
            }
        )

    return {
        **{key: value for key, value in inspection.items() if not key.startswith("_")},
        "attempted_writes": len(attempted_paths),
        "writes": writes,
        "created_paths": created_paths,
        "overwritten_paths": overwritten_paths,
        "failed_writes": 0,
        "skipped_writes": 0,
        "legacy_deletes": 0,
        "legacy_documents_preserved": True,
        "verification": "PASS",
        "executed_at": datetime.now(timezone.utc),
    }


def _report_payload(
    *,
    status: str,
    project: str,
    tickers: list[str],
    plan: dict[str, Any],
    execution: dict[str, Any] | None = None,
    inspection: dict[str, Any] | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "status": status,
        "project": project,
        "tickers": tickers,
        "counts": plan["counts"],
        "document_count": plan["document_count"],
        "fingerprint": plan["fingerprint"],
        "fact_key_version": "financial-fact-v2",
        "run_selection": (
            "latest completed analysis run and latest completed ingestion run per ticker; "
            "started_at DESC, run_id DESC"
        ),
        "source_conflicts": plan["source_conflicts"],
        "execute": status == "written",
        "selected_runs": plan["selected_runs"],
    }
    if execution is not None:
        payload["execution"] = {
            key: value for key, value in execution.items() if key != "entries"
        }
    if inspection is not None:
        payload["preflight"] = {
            "classification_counts": inspection["classification_counts"],
            "legacy_overlap_count": inspection["legacy_overlap_count"],
        }
    if manifest is not None:
        payload["manifest"] = {
            "migration_id": manifest["migration_id"],
            "manifest_fingerprint": manifest["manifest_fingerprint"],
            "entry_count": len(manifest["entries"]),
            "expected_create_count": manifest["expected_create_count"],
            "overwrite_candidate_count": manifest["overwrite_candidate_count"],
        }
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/backfill-small-v2.sqlite3"))
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", "fintrust-alert-ccu"))
    parser.add_argument("--tickers", nargs="+", default=["2330", "2454"])
    parser.add_argument("--execute", action="store_true", help="Actually write Firestore documents")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Read Firestore targets and build a dry-run classification manifest",
    )
    parser.add_argument(
        "--allow-source-newer-overwrite",
        action="store_true",
        help="Allow SOURCE_NEWER targets to be overwritten; requires --execute",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    if args.allow_source_newer_overwrite and not args.execute:
        raise SystemExit("--allow-source-newer-overwrite requires --execute")
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

    try:
        rows = collect(args.source, args.tickers)
    except NoValidRunError as exc:
        report = {
            "status": "blocked",
            "execute": False,
            "reason": "no-valid-run",
            "collection": exc.collection,
            "ticker": exc.ticker,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    plan = build_plan(rows)
    inspection = None
    manifest = None
    if args.preflight or args.execute:
        from google.cloud import firestore

        client = firestore.Client(project=args.project)
        inspection = preflight(client, plan)
        manifest = build_manifest(plan, inspection)
    if not args.execute:
        report = _report_payload(
            status="dry_run", project=args.project, tickers=args.tickers, plan=plan,
            inspection=inspection, manifest=manifest,
        )
    else:
        try:
            execution = execute_plan(
                client,
                plan,
                allow_source_newer_overwrite=args.allow_source_newer_overwrite,
            )
            report = _report_payload(
                status="written",
                project=args.project,
                tickers=args.tickers,
                plan=plan,
                execution=execution,
                inspection=inspection,
                manifest=manifest,
            )
        except AtomicWriteConflict as exc:
            report = _report_payload(
                status="blocked",
                project=args.project,
                tickers=args.tickers,
                plan=plan,
                execution={
                    "attempted_writes": len(exc.attempted_paths),
                    "writes": 0,
                    "created_paths": [],
                    "overwritten_paths": [],
                    "failed_writes": len(exc.attempted_paths),
                    "skipped_writes": 0,
                    "legacy_deletes": 0,
                    "verification": "NOT_RUN",
                    "conflict_path": exc.path,
                    "conflict_reason": exc.reason,
                    "executed_at": datetime.now(timezone.utc),
                },
                inspection=inspection,
                manifest=manifest,
            )
        except PostWriteVerificationError as exc:
            report = _report_payload(
                status="partial",
                project=args.project,
                tickers=args.tickers,
                plan=plan,
                execution=exc.execution,
                inspection=inspection,
                manifest=manifest,
            )

    if args.manifest:
        if manifest is None:
            raise SystemExit("--manifest requires --preflight or --execute")
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(_json_value(manifest), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(_json_value(report), ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(_json_value(report), ensure_ascii=False, indent=2))
    return 0 if report["status"] in {"dry_run", "written"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
