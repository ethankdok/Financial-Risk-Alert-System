"""Recoverable GCS + Firestore synchronization of the local historical archive.

GCS and Firestore share no transaction, so progress is recorded per item in the
local isolated database (``historical_cloud_sync_runs`` / ``_items``):

    1 validate local evidence (SHA-256 re-hash)       → validated
    2 upload missing objects (create-only)            → uploaded
    3 verify objects (download + re-hash)             → object_verified
    4 write Firestore metadata incl. object refs      → metadata_written
    5 read back records and objects                   → consistent
    6 mark the run complete (only if every item is consistent)

Any failure leaves the run ``incomplete`` with per-item errors; ``sync`` resumes
the latest incomplete run for the same target. Objects and records are
create-only, so a retry never duplicates or overwrites anything.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any
from uuid import uuid4

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.cloud_config import HistoricalCloudConfig
from app.services.historical_audit.firestore_repository import (
    ID_FIELDS,
    FirestoreConflictError,
    FirestoreHistoricalResearchRepository,
)
from app.services.historical_audit.models import iso, stable_hash, utc_now
from app.services.historical_audit.object_storage import ObjectStore, object_name
from app.services.historical_audit.repository import HistoricalAuditRepository


SYNC_SCHEMA = """
CREATE TABLE IF NOT EXISTS historical_cloud_sync_runs (
    run_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    target TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS historical_cloud_sync_items (
    run_id TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    item_id TEXT NOT NULL,
    object_name TEXT,
    sha256 TEXT,
    state TEXT NOT NULL,
    error TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, item_kind, item_id)
);
"""
STATES = ("pending", "validated", "uploaded", "object_verified", "metadata_written", "consistent")
# local table → (record kind, ticker column present)
RECORD_TABLES = {
    "filing_versions": "financial_filing_versions",
    "facts": "versioned_financial_facts",
    "source_documents": "historical_source_documents",
    "publication_events": "historical_publication_events",
    "comparisons": "restatement_comparisons",
    "summary_observations": "official_summary_observations",
    "disclosed_values": "disclosed_financial_values",
}
_CONTENT_TYPES = {"xml": "application/xml", "html": "text/html", "pdf": "application/pdf",
                  "xls": "application/vnd.ms-excel", "zip": "application/zip", "bin": "application/octet-stream"}


@dataclass
class SyncReport:
    run_id: str
    mode: str
    status: str = "running"
    resumed: bool = False
    objects: dict[str, int] = field(default_factory=dict)
    records: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def bump(self, bucket: dict[str, int], key: str) -> None:
        bucket[key] = bucket.get(key, 0) + 1


def _namespace(kind: str, category: str | None) -> str:
    # Report PDFs are both filing versions and source documents: one namespace, one object.
    if kind == "filing_version" or category == "official_filing_pdf":
        return "financial_filings"
    if category == "official_historical_summary":
        return "official_summaries"
    return "regulatory_disclosures"


class HistoricalCloudSync:
    def __init__(self, *, repository: HistoricalAuditRepository, archive: RawEvidenceArchive,
                 object_store: ObjectStore | None, firestore: FirestoreHistoricalResearchRepository | None,
                 config: HistoricalCloudConfig) -> None:
        self.repository = repository
        self.archive = archive
        self.store = object_store
        self.firestore = firestore
        self.config = config
        with self.repository.connect() as connection:
            connection.executescript(SYNC_SCHEMA)

    @property
    def target(self) -> str:
        return f"{self.config.environment}:{self.config.project}:{self.config.bucket}:{self.config.collection_prefix}"

    # ------------------------------------------------------------ inputs
    def _artifacts(self, ticker: str) -> list[dict[str, Any]]:
        with self.repository.connect() as connection:
            versions = [dict(r) for r in connection.execute(
                "SELECT filing_version_id AS item_id, content_hash, raw_storage_path, NULL AS category "
                "FROM financial_filing_versions WHERE ticker = ? ORDER BY filing_version_id", (ticker,))]
            documents = [dict(r) for r in connection.execute(
                "SELECT source_document_id AS item_id, content_hash, raw_storage_path, source_category AS category "
                "FROM historical_source_documents WHERE ticker = ? ORDER BY source_document_id", (ticker,))]
        items = [{**v, "item_kind": "filing_version"} for v in versions]
        items += [{**d, "item_kind": "source_document"} for d in documents]
        for item in items:
            extension = PurePosixPath(item["raw_storage_path"]).suffix.lstrip(".") or "bin"
            item["object_name"] = object_name(_namespace(item["item_kind"], item["category"]), ticker,
                                              item["content_hash"], extension, prefix=self.config.object_prefix)
            item["extension"] = extension
        return items

    def _records(self, ticker: str, object_refs: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
        records: dict[str, list[dict[str, Any]]] = {}
        with self.repository.connect() as connection:
            for kind, table in RECORD_TABLES.items():
                rows = [dict(r) for r in connection.execute(
                    f"SELECT * FROM {table} WHERE ticker = ? ORDER BY {ID_FIELDS[kind]}", (ticker,))]
                for row in rows:
                    if kind in {"filing_versions", "source_documents"}:
                        row["object_bucket"] = self.config.bucket
                        row["object_name"] = object_refs.get(row[ID_FIELDS[kind]])
                records[kind] = rows
            ids = {r["observation_id"] for r in records["summary_observations"]} | {r["fact_id"] for r in records["facts"]}
            records["observation_availability"] = sorted(
                (dict(r) for r in connection.execute("SELECT * FROM observation_availability ORDER BY availability_id")
                 if r["observation_id"] in ids), key=lambda r: r["availability_id"])
            event_ids = {r["event_id"] for r in records["publication_events"]}
            records["evidence_links"] = [dict(r) for r in connection.execute(
                "SELECT * FROM publication_evidence_links ORDER BY link_id") if r["event_id"] in event_ids]
            case = connection.execute(
                "SELECT ticker, case_id, company_name, market, payload_json FROM historical_audit_cases WHERE ticker = ?",
                (ticker,)).fetchone()
            records["cases"] = [dict(case)] if case else []
        for kind in ("observation_availability", "evidence_links"):
            for row in records[kind]:
                row["ticker"] = ticker  # enables per-case queries; not part of the local row identity
        return records

    # --------------------------------------------------------- run state
    def _latest_incomplete(self, ticker: str) -> str | None:
        with self.repository.connect() as connection:
            row = connection.execute(
                "SELECT run_id FROM historical_cloud_sync_runs WHERE ticker = ? AND target = ? AND mode = 'execute' "
                "AND status != 'complete' ORDER BY started_at DESC LIMIT 1", (ticker, self.target)).fetchone()
        return row["run_id"] if row else None

    def _item_states(self, run_id: str) -> dict[tuple[str, str], str]:
        with self.repository.connect() as connection:
            return {(r["item_kind"], r["item_id"]): r["state"] for r in connection.execute(
                "SELECT item_kind, item_id, state FROM historical_cloud_sync_items WHERE run_id = ?", (run_id,))}

    def _set_item(self, run_id: str, item: dict[str, Any], state: str, error: str | None = None) -> None:
        with self.repository.connect() as connection:
            connection.execute(
                """INSERT INTO historical_cloud_sync_items VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, item_kind, item_id) DO UPDATE SET state = excluded.state,
                error = excluded.error, updated_at = excluded.updated_at""",
                (run_id, item["item_kind"], item["item_id"], item.get("object_name"), item.get("content_hash"),
                 state, error, iso(utc_now())))

    def _save_run(self, ticker: str, report: SyncReport, started_at: str | None = None) -> None:
        summary = json.dumps({"objects": report.objects, "records": report.records, "errors": report.errors[:50]},
                             ensure_ascii=False, sort_keys=True)
        with self.repository.connect() as connection:
            connection.execute(
                """INSERT INTO historical_cloud_sync_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, completed_at = excluded.completed_at,
                summary_json = excluded.summary_json""",
                (report.run_id, ticker, self.target, report.mode, report.status, started_at or iso(utc_now()),
                 iso(utc_now()) if report.status in {"complete", "incomplete", "planned"} else None, summary))

    def status(self, ticker: str) -> list[dict[str, Any]]:
        with self.repository.connect() as connection:
            runs = [dict(r) for r in connection.execute(
                "SELECT * FROM historical_cloud_sync_runs WHERE ticker = ? ORDER BY started_at DESC", (ticker,))]
            for run in runs:
                run["items_by_state"] = {r["state"]: r["n"] for r in connection.execute(
                    "SELECT state, COUNT(*) AS n FROM historical_cloud_sync_items WHERE run_id = ? GROUP BY state",
                    (run["run_id"],))}
        return runs

    # ---------------------------------------------------------------- sync
    def sync(self, ticker: str, *, execute: bool = False) -> SyncReport:
        artifacts = self._artifacts(ticker)
        if not execute:
            report = SyncReport(run_id=f"plan-{uuid4().hex}", mode="dry_run")
            for item in artifacts:
                remote = self.store.stat(item["object_name"]) if self.store is not None else None
                report.bump(report.objects, "planned_upload" if remote is None else "already_present")
            for kind, rows in self._records(ticker, {}).items():
                report.records[f"planned_{kind}"] = len(rows)
            report.status = "planned"
            return report
        if self.store is None or self.firestore is None:
            raise RuntimeError("execute requires an object store and a Firestore repository")
        resumed_id = self._latest_incomplete(ticker)
        report = SyncReport(run_id=resumed_id or uuid4().hex, mode="execute", resumed=bool(resumed_id))
        self._save_run(ticker, report)
        done = self._item_states(report.run_id)
        object_refs: dict[str, str] = {}
        blocked = False

        for item in artifacts:  # steps 1-3
            key = (item["item_kind"], item["item_id"])
            if done.get(key) in {"object_verified", "metadata_written", "consistent"}:
                object_refs[item["item_id"]] = item["object_name"]
                report.bump(report.objects, "skipped_already_verified")
                continue
            try:
                data = self.archive.read(item["raw_storage_path"])
            except Exception as exc:
                self._set_item(report.run_id, item, "failed_validation", f"{type(exc).__name__}: {exc}")
                report.errors.append(f"validate {item['item_id']}: {type(exc).__name__}")
                blocked = True
                continue
            self._set_item(report.run_id, item, "validated")
            result = self.store.put_if_absent(
                item["object_name"], data, content_type=_CONTENT_TYPES.get(item["extension"], "application/octet-stream"),
                metadata={"ticker": ticker, "item_kind": item["item_kind"], "item_id": item["item_id"],
                          "pipeline": "historical_audit_cloud_sync"})
            report.bump(report.objects, result.status)
            if result.status not in {"created", "exists_same"}:
                self._set_item(report.run_id, item, f"upload_{result.status}", result.error)
                report.errors.append(f"upload {item['object_name']}: {result.status} {result.error or ''}".strip())
                blocked = True
                continue
            self._set_item(report.run_id, item, "uploaded")
            try:
                self.store.get_verified(item["object_name"], item["content_hash"])
            except Exception as exc:
                self._set_item(report.run_id, item, "object_verification_failed", type(exc).__name__)
                report.errors.append(f"verify {item['object_name']}: {type(exc).__name__}")
                blocked = True
                continue
            self._set_item(report.run_id, item, "object_verified")
            object_refs[item["item_id"]] = item["object_name"]

        records = self._dependent_records(self._records(ticker, object_refs), object_refs)  # step 4
        # One document per stored object; the records that reference it carry object_name themselves
        # (a report PDF is both a filing version and a source document but one object).
        objects = {
            item["object_name"]: {"object_id": stable_hash("obj", item["object_name"])[:32], "ticker": ticker,
                                  "bucket": self.config.bucket, "object_name": item["object_name"],
                                  "sha256": item["content_hash"]}
            for item in artifacts if item["item_id"] in object_refs
        }
        records["objects"] = [objects[name] for name in sorted(objects)]
        for kind in ("cases", "objects", "source_documents", "filing_versions", "facts", "publication_events",
                     "evidence_links", "comparisons", "summary_observations", "disclosed_values", "observation_availability"):
            for row in records.get(kind, []):
                try:
                    report.bump(report.records, f"{kind}:{self.firestore.write(kind, row)}")
                except FirestoreConflictError as exc:
                    report.errors.append(f"conflict {exc}")
                    blocked = True
                except Exception as exc:
                    report.errors.append(f"metadata {kind}/{row.get(ID_FIELDS[kind])}: {type(exc).__name__}")
                    blocked = True
        for item in artifacts:
            if self._item_states(report.run_id).get((item["item_kind"], item["item_id"])) == "object_verified":
                self._set_item(report.run_id, item, "metadata_written")

        inconsistent = self._verify_consistency(ticker, records, artifacts, report)  # step 5
        for item in artifacts:
            if self._item_states(report.run_id).get((item["item_kind"], item["item_id"])) == "metadata_written" \
                    and item["item_id"] not in inconsistent:
                self._set_item(report.run_id, item, "consistent")
        states = self._item_states(report.run_id)
        complete = (not blocked and not inconsistent and len(states) == len(artifacts)
                    and all(state == "consistent" for state in states.values()))
        report.status = "complete" if complete else "incomplete"  # step 6
        self._save_run(ticker, report)
        try:
            self.firestore.write("sync_runs", {"run_id": report.run_id, "ticker": ticker, "status": report.status,
                                               "target": self.target, "completed_at": iso(utc_now()),
                                               "objects": report.objects, "error_count": len(report.errors)})
        except Exception as exc:
            report.errors.append(f"sync_runs status write: {type(exc).__name__}")
        return report

    @staticmethod
    def _dependent_records(records: dict[str, list[dict[str, Any]]], object_refs: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
        """Only write metadata whose evidence objects are verified in storage (no dangling references)."""
        records["filing_versions"] = [r for r in records["filing_versions"] if r["filing_version_id"] in object_refs]
        records["source_documents"] = [r for r in records["source_documents"] if r["source_document_id"] in object_refs]
        versions = {r["filing_version_id"] for r in records["filing_versions"]}
        documents = {r["source_document_id"] for r in records["source_documents"]}
        records["facts"] = [r for r in records["facts"] if r["filing_version_id"] in versions]
        for kind in ("publication_events", "comparisons", "summary_observations", "disclosed_values"):
            records[kind] = [r for r in records.get(kind, []) if r["source_document_id"] in documents]
        events = {r["event_id"] for r in records["publication_events"]}
        records["comparisons"] = [r for r in records["comparisons"] if r["event_id"] in events]
        records["disclosed_values"] = [r for r in records["disclosed_values"] if r["event_id"] in events]
        records["evidence_links"] = [r for r in records["evidence_links"]
                                     if r["event_id"] in events and r["target_id"] in versions]
        observations = {r["fact_id"] for r in records["facts"]} | {r["observation_id"] for r in records["summary_observations"]}
        corroborating = {r["comparison_id"] for r in records["comparisons"]} | {
            r["disclosed_value_id"] for r in records["disclosed_values"]}
        records["observation_availability"] = [r for r in records["observation_availability"]
                                                if r["observation_id"] in observations and r["corroborating_id"] in corroborating]
        return records

    def _verify_consistency(self, ticker: str, records: dict[str, list[dict[str, Any]]],
                            artifacts: list[dict[str, Any]], report: SyncReport) -> set[str]:
        inconsistent: set[str] = set()
        for item in artifacts:
            kind = "filing_versions" if item["item_kind"] == "filing_version" else "source_documents"
            stored = self.firestore.get(kind, item["item_id"])
            remote = self.store.stat(item["object_name"])
            if (stored is None or stored.get("object_name") != item["object_name"]
                    or stored.get("content_hash") != item["content_hash"] or remote is None
                    or remote.get("sha256") not in (None, item["content_hash"])):
                inconsistent.add(item["item_id"])
        for kind, rows in records.items():
            if kind in {"objects", "cases"}:
                continue
            stored_ids = {str(row.get(ID_FIELDS[kind])) for row in self.firestore.list(kind, ticker=ticker)}
            missing = {str(row[ID_FIELDS[kind]]) for row in rows} - stored_ids
            if missing:
                report.errors.append(f"consistency {kind}: {len(missing)} records missing in Firestore")
                inconsistent.update(missing)
        return inconsistent
