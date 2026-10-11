"""Append-only persistence of derived research runs (never the official historical tables).

A run is identified by ``run_id = rrun1_<sha256(result_kind, method_version, input_digest, parameters)>``:
re-running identical inputs with the same method is idempotent (the stored output digest must match, otherwise the
write fails as a determinism/integrity error); a correction is a new run (new method version or inputs, optionally
``supersedes_run_id``) and never overwrites. ``created_at`` and ``git_commit`` are reviewer metadata outside every
digest.

Backends: ``SqliteResearchResultStore`` (separate file; SQL triggers forbid UPDATE/DELETE) and
``FirestoreResearchResultStore`` (create-only documents under ``historical_research_results_*``; same read view).
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.financial_research.input_snapshot import canonical_json, digest

STORE_SCHEMA_VERSION = "1"
DEFAULT_RESULTS_DATABASE = "./data/historical_audit/research_results.sqlite3"
RESULT_KINDS = ("financial_signals", "restatement_bridge", "source_reconciliation")
_TABLES = ("research_dataset_snapshots", "research_methods", "research_runs", "research_features",
           "research_restatement_bridges", "source_discrepancies", "case_research_labels")

SCHEMA = """
CREATE TABLE IF NOT EXISTS research_store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_dataset_snapshots (
    snapshot_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, analysis_mode TEXT NOT NULL, cutoff_at TEXT,
    input_digest TEXT NOT NULL, description_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_methods (
    method_version TEXT PRIMARY KEY, method_ids_json TEXT NOT NULL, approval_status TEXT NOT NULL,
    approved_by TEXT, specification_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS research_runs (
    run_id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES research_dataset_snapshots (snapshot_id),
    ticker TEXT NOT NULL, result_kind TEXT NOT NULL, analysis_mode TEXT NOT NULL, cutoff_at TEXT,
    method_version TEXT NOT NULL REFERENCES research_methods (method_version), input_digest TEXT NOT NULL,
    parameters_json TEXT NOT NULL, status TEXT NOT NULL, output_json TEXT NOT NULL, output_digest TEXT NOT NULL,
    supersedes_run_id TEXT, git_commit TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_research_runs_ticker ON research_runs (ticker, result_kind, created_at);
CREATE TABLE IF NOT EXISTS research_features (
    run_id TEXT NOT NULL REFERENCES research_runs (run_id), feature_id TEXT NOT NULL, fiscal_year INTEGER NOT NULL,
    statement_scope TEXT NOT NULL, status TEXT NOT NULL, value_decimal TEXT, unit TEXT NOT NULL,
    missing_reasons_json TEXT NOT NULL, input_fact_ids_json TEXT NOT NULL, input_evidence_sha256_json TEXT NOT NULL,
    PRIMARY KEY (run_id, feature_id, fiscal_year, statement_scope));
CREATE TABLE IF NOT EXISTS research_restatement_bridges (
    run_id TEXT NOT NULL REFERENCES research_runs (run_id), comparison_key TEXT NOT NULL, period TEXT NOT NULL,
    statement_scope TEXT NOT NULL, accounting_framework TEXT NOT NULL, source_label TEXT, canonical_metric TEXT,
    sign_factor INTEGER NOT NULL, pre_twd TEXT, post_twd TEXT, delta_twd TEXT, delta_pct TEXT,
    denominator_status TEXT NOT NULL, notice_ref TEXT NOT NULL, notice_sha256 TEXT NOT NULL,
    PRIMARY KEY (run_id, comparison_key));
CREATE TABLE IF NOT EXISTS source_discrepancies (
    run_id TEXT NOT NULL REFERENCES research_runs (run_id), issue_id TEXT NOT NULL, metric TEXT NOT NULL,
    period TEXT NOT NULL, statement_scope TEXT NOT NULL, value_a TEXT, value_b TEXT, difference TEXT,
    status TEXT NOT NULL, sources_json TEXT NOT NULL, review_note TEXT NOT NULL,
    PRIMARY KEY (run_id, issue_id, metric));
CREATE TABLE IF NOT EXISTS case_research_labels (
    label_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, label TEXT NOT NULL, outcome_known_at TEXT NOT NULL,
    legal_source TEXT NOT NULL, confidence TEXT NOT NULL, purpose TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class ResultStoreIntegrityError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_identity(result_kind: str, method_version: str, input_digest: str, parameters: dict[str, Any]) -> str:
    if result_kind not in RESULT_KINDS:
        raise ValueError(f"unknown result kind {result_kind}")
    return "rrun1_" + digest([result_kind, method_version, input_digest, parameters])[:32]


def build_run(*, result_kind: str, method_version: str, method_ids: list[str], approval_status: str,
              snapshot: dict[str, Any], parameters: dict[str, Any], output: dict[str, Any],
              supersedes_run_id: str | None = None, git_commit: str | None = None) -> dict[str, Any]:
    run_id = run_identity(result_kind, method_version, snapshot["input_digest"], parameters)
    return {"run_id": run_id, "snapshot_id": "snap_" + snapshot["input_digest"][:32], "ticker": snapshot["ticker"],
            "result_kind": result_kind, "analysis_mode": snapshot["analysis_mode"], "cutoff_at": snapshot.get("cutoff_at"),
            "method_version": method_version, "method_ids": method_ids, "approval_status": approval_status,
            "input_digest": snapshot["input_digest"], "parameters": parameters, "status": output.get("status"),
            "snapshot": snapshot, "output": output, "output_digest": digest(output),
            "supersedes_run_id": supersedes_run_id, "git_commit": git_commit}


def _projections(run: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    output, kind = run["output"], run["result_kind"]
    features, bridges, discrepancies = [], [], []
    if kind == "financial_signals":
        for f in output.get("features", []):
            features.append({"feature_id": f["feature_id"], "fiscal_year": f["fiscal_year"],
                             "statement_scope": f["statement_scope"], "status": f["status"], "value_decimal": f["value"],
                             "unit": f["unit"], "missing_reasons": f["missing_reasons"],
                             "input_fact_ids": [i["fact_id"] for i in f["inputs"]],
                             "input_evidence_sha256": sorted({i["availability_evidence_hash"] or i["artifact_sha256"] or ""
                                                              for i in f["inputs"]} - {""})})
    if kind == "restatement_bridge":
        for r in output.get("rows", []):
            bridges.append({k: r[k] for k in ("comparison_key", "period", "statement_scope", "accounting_framework",
                                              "source_label", "canonical_metric", "sign_factor", "pre_twd", "post_twd",
                                              "delta_twd", "delta_pct", "denominator_status")}
                           | {"notice_ref": r["announcement_key"], "notice_sha256": r["notice_sha256"]})
    if kind == "source_reconciliation":
        for finding in output.get("discrepancies", []):
            for item in finding["items"]:
                discrepancies.append({"issue_id": finding["issue_id"], "metric": item["metric"], "period": finding["period"],
                                      "statement_scope": finding["statement_scope"], "value_a": item["board_notice_value"],
                                      "value_b": item["filed_value_thousand_twd"], "difference": item["difference_thousand_twd"],
                                      "status": finding["status"],
                                      "sources": {"board_notice": finding["board_notice"], "filed_report": finding["filed_report"],
                                                  "audited_pdf": {k: finding["audited_pdf"].get(k) for k in
                                                                  ("pdf_sha256", "pdf_page_index", "printed_page_label", "status")}},
                                      "review_note": finding["explanation_limits"]})
    return {"features": features, "bridges": bridges, "discrepancies": discrepancies}


class SqliteResearchResultStore:
    backend_name = "sqlite"

    def __init__(self, path: str | os.PathLike[str] = DEFAULT_RESULTS_DATABASE, *, protected: tuple[str, ...] = ()) -> None:
        target = Path(path).resolve()
        for candidate in protected:
            if candidate and Path(candidate).resolve() == target:
                raise ResultStoreIntegrityError("the result store must not be the approved historical database")
        self.path = target
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            for table in _TABLES:
                for action in ("UPDATE", "DELETE"):
                    connection.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} BEFORE {action} ON {table} "
                        f"BEGIN SELECT RAISE(ABORT, 'append-only research result store'); END")
            connection.execute("INSERT OR IGNORE INTO research_store_meta VALUES ('schema_version', ?)", (STORE_SCHEMA_VERSION,))

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def record_run(self, run: dict[str, Any]) -> tuple[str, bool]:
        created_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")  # single-writer lock for the whole run
            try:
                existing = connection.execute("SELECT output_digest FROM research_runs WHERE run_id = ?",
                                              (run["run_id"],)).fetchone()
                if existing is not None:
                    connection.execute("ROLLBACK")
                    if existing["output_digest"] != run["output_digest"]:
                        raise ResultStoreIntegrityError(
                            f"{run['run_id']}: identical inputs produced a different output (non-deterministic method)")
                    return run["run_id"], False
                snapshot = run["snapshot"]
                connection.execute("INSERT OR IGNORE INTO research_dataset_snapshots VALUES (?,?,?,?,?,?,?)",
                                   (run["snapshot_id"], run["ticker"], run["analysis_mode"], run["cutoff_at"],
                                    run["input_digest"], canonical_json(snapshot), created_at))
                connection.execute("INSERT OR IGNORE INTO research_methods VALUES (?,?,?,?,?,?)",
                                   (run["method_version"], canonical_json(run["method_ids"]), run["approval_status"], None,
                                    canonical_json({"method_ids": run["method_ids"]}), created_at))
                connection.execute(
                    "INSERT INTO research_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (run["run_id"], run["snapshot_id"], run["ticker"], run["result_kind"], run["analysis_mode"],
                     run["cutoff_at"], run["method_version"], run["input_digest"], canonical_json(run["parameters"]),
                     run["status"] or "", canonical_json(run["output"]), run["output_digest"], run["supersedes_run_id"],
                     run["git_commit"], created_at))
                projections = _projections(run)
                for f in projections["features"]:
                    connection.execute("INSERT INTO research_features VALUES (?,?,?,?,?,?,?,?,?,?)",
                                       (run["run_id"], f["feature_id"], f["fiscal_year"], f["statement_scope"], f["status"],
                                        f["value_decimal"], f["unit"], canonical_json(f["missing_reasons"]),
                                        canonical_json(f["input_fact_ids"]), canonical_json(f["input_evidence_sha256"])))
                for b in projections["bridges"]:
                    connection.execute("INSERT INTO research_restatement_bridges VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                       (run["run_id"], b["comparison_key"], b["period"], b["statement_scope"],
                                        b["accounting_framework"], b["source_label"], b["canonical_metric"], b["sign_factor"],
                                        b["pre_twd"], b["post_twd"], b["delta_twd"], b["delta_pct"], b["denominator_status"],
                                        b["notice_ref"], b["notice_sha256"]))
                for d in projections["discrepancies"]:
                    connection.execute("INSERT INTO source_discrepancies VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                       (run["run_id"], d["issue_id"], d["metric"], d["period"], d["statement_scope"],
                                        d["value_a"], d["value_b"], d["difference"], d["status"],
                                        canonical_json(d["sources"]), d["review_note"]))
                connection.execute("COMMIT")
            except Exception:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")
                raise
        return run["run_id"], True

    def record_labels(self, ticker: str, labels: list[dict[str, Any]]) -> int:
        created = 0
        with self._connect() as connection:
            for label in labels:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO case_research_labels VALUES (?,?,?,?,?,?,?,?)",
                    (label["label_id"], ticker, label["label"], label["outcome_known_at"], label["legal_source"],
                     label["confidence"], label["purpose"], _now()))
                created += cursor.rowcount
        return created

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM research_runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                return None
            snapshot = connection.execute("SELECT description_json FROM research_dataset_snapshots WHERE snapshot_id = ?",
                                          (row["snapshot_id"],)).fetchone()
            method = connection.execute("SELECT * FROM research_methods WHERE method_version = ?",
                                        (row["method_version"],)).fetchone()
        return public_run({
            "run_id": row["run_id"], "snapshot_id": row["snapshot_id"], "ticker": row["ticker"],
            "result_kind": row["result_kind"], "analysis_mode": row["analysis_mode"], "cutoff_at": row["cutoff_at"],
            "method_version": row["method_version"], "method_ids": json.loads(method["method_ids_json"]),
            "approval_status": method["approval_status"], "input_digest": row["input_digest"],
            "parameters": json.loads(row["parameters_json"]), "status": row["status"],
            "snapshot": json.loads(snapshot["description_json"]), "output": json.loads(row["output_json"]),
            "output_digest": row["output_digest"], "supersedes_run_id": row["supersedes_run_id"],
            "git_commit": row["git_commit"], "created_at": row["created_at"]})

    def list_runs(self, ticker: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT run_id, result_kind, analysis_mode, cutoff_at, method_version, input_digest, status, created_at "
                "FROM research_runs WHERE ticker = ? ORDER BY created_at, run_id", (ticker,)).fetchall()
        return [dict(row) for row in rows]

    def projection_counts(self, run_id: str) -> dict[str, int]:
        with self._connect() as connection:
            return {table: connection.execute(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (run_id,)).fetchone()[0]
                    for table in ("research_features", "research_restatement_bridges", "source_discrepancies")}


def public_run(run: dict[str, Any]) -> dict[str, Any]:
    """Stable read view shared by every backend (parity-tested)."""
    keys = ("run_id", "snapshot_id", "ticker", "result_kind", "analysis_mode", "cutoff_at", "method_version",
            "method_ids", "approval_status", "input_digest", "parameters", "status", "snapshot", "output",
            "output_digest", "supersedes_run_id", "git_commit", "created_at")
    view = {key: run.get(key) for key in keys}
    view["reviewer_metadata_fields"] = ["created_at", "git_commit"]
    view["immutable"] = True
    return view


class FirestoreResearchResultStore:
    """Create-only Firestore mirror of research runs (emulator / isolated-test only via ``cloud_config``)."""

    backend_name = "firestore"
    CHUNK = 400_000  # characters per output chunk (Firestore document limit is 1 MiB)

    def __init__(self, client: Any, *, prefix: str = "historical_research_results") -> None:
        if not prefix.startswith("historical_research_results"):
            raise ValueError("result collections must start with 'historical_research_results'")
        self.client, self.prefix = client, prefix

    def _collection(self, kind: str):
        return self.client.collection(f"{self.prefix}_{kind}")

    def record_run(self, run: dict[str, Any]) -> tuple[str, bool]:
        runs = self._collection("runs")
        existing = runs.document(run["run_id"]).get()
        if getattr(existing, "exists", False):
            if (existing.to_dict() or {}).get("output_digest") != run["output_digest"]:
                raise ResultStoreIntegrityError(f"{run['run_id']}: identical inputs produced a different output")
            return run["run_id"], False
        text = canonical_json(run["output"])
        chunks = [text[i:i + self.CHUNK] for i in range(0, len(text), self.CHUNK)] or [""]
        for index, chunk in enumerate(chunks):  # chunks first; the run document is the commit marker
            self._create(self._collection("run_chunks").document(f"{run['run_id']}_{index:04d}"),
                         {"run_id": run["run_id"], "index": index, "text": chunk})
        projections = _projections(run)
        for name, rows in projections.items():
            for position, row in enumerate(rows):
                self._create(self._collection(name).document(f"{run['run_id']}_{position:05d}"),
                             {"run_id": run["run_id"], "ticker": run["ticker"], **row})
        document = {k: v for k, v in run.items() if k != "output"}
        document.update(chunk_count=len(chunks), created_at=_now())
        try:
            runs.document(run["run_id"]).create(document)
        except Exception as exc:  # concurrent writer won the race
            if type(exc).__name__ not in {"AlreadyExists", "Conflict"} and getattr(exc, "code", None) != 409:
                raise
            return self.record_run(run)
        return run["run_id"], True

    @staticmethod
    def _create(reference: Any, data: dict[str, Any]) -> None:
        try:
            reference.create(data)
        except Exception as exc:  # a retried run re-creates identical chunks; verify instead of overwriting
            if type(exc).__name__ not in {"AlreadyExists", "Conflict"} and getattr(exc, "code", None) != 409:
                raise
            if (reference.get().to_dict() or {}) != data:
                raise ResultStoreIntegrityError(f"conflicting existing document {reference.id}") from exc

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        snapshot = self._collection("runs").document(run_id).get()
        if not getattr(snapshot, "exists", False):
            return None
        document = snapshot.to_dict() or {}
        text = "".join((self._collection("run_chunks").document(f"{run_id}_{i:04d}").get().to_dict() or {})["text"]
                       for i in range(document["chunk_count"]))
        output = json.loads(text)
        if digest(output) != document["output_digest"]:
            raise ResultStoreIntegrityError(f"{run_id}: stored output does not match its digest")
        return public_run({**document, "output": output})
