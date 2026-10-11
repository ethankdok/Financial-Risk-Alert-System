"""Bounded, journaled export of derived research runs to the cloud result store (Phase 5, deploy-ready).

- Source of truth for derived runs: the local append-only SQLite result store. The cloud store is a create-only
  mirror; nothing is ever deleted or overwritten there.
- ``plan`` is read-only (dry run): each run is ``to_create``, ``exists_same`` or ``collision`` (same run id,
  different output digest — reported, never written).
- ``execute`` needs an explicit non-production target built through ``HistoricalCloudConfig`` (emulator or
  isolated-test; production requires a separate approval that this phase never grants), takes an exclusive lock
  file, writes at most ``batch_limit`` runs, retries transient failures with bounded backoff and journals every
  step (JSON lines) so an interrupted export can be inspected and resumed. Re-running is idempotent.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.services.financial_research.result_store import (
    FirestoreResearchResultStore,
    ResultStoreIntegrityError,
    SqliteResearchResultStore,
)

RESULT_COLLECTION_PREFIX = "historical_research_results"


class SyncLockedError(RuntimeError):
    pass


@dataclass
class SyncReport:
    mode: str
    ticker: str
    planned: dict[str, list[str]] = field(default_factory=lambda: {"to_create": [], "exists_same": [], "collision": []})
    written: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    deferred: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.planned["collision"] or self.failed:
            return "attention_required"
        return "complete" if not self.deferred else "partial_batch_limit"

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "ticker": self.ticker, "status": self.status,
                "counts": {k: len(v) for k, v in self.planned.items()} | {"written": len(self.written),
                                                                           "failed": len(self.failed),
                                                                           "deferred": len(self.deferred)},
                "planned": self.planned, "written": self.written, "failed": self.failed, "deferred": self.deferred}


def build_cloud_result_store(config: Any, client: Any | None = None) -> FirestoreResearchResultStore:
    """Target store from a validated ``HistoricalCloudConfig`` (never production without separate approval)."""
    if config.environment == "production":
        raise PermissionError("production research-result writes require a separate, explicit approval")
    if client is None:
        from google.cloud import firestore  # emulator or isolated-test project via ADC

        client = firestore.Client(project=config.project)
    return FirestoreResearchResultStore(client, prefix=RESULT_COLLECTION_PREFIX)


class ResearchResultSync:
    def __init__(self, source: SqliteResearchResultStore, target: FirestoreResearchResultStore, *, journal: Path,
                 lock: Path, batch_limit: int = 25, max_retries: int = 3, backoff_seconds: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if not 1 <= batch_limit <= 500:
            raise ValueError("batch_limit must be between 1 and 500")
        self.source, self.target = source, target
        self.journal, self.lock = Path(journal), Path(lock)
        self.batch_limit, self.max_retries, self.backoff, self.sleep = batch_limit, max_retries, backoff_seconds, sleep

    def _log(self, event: str, **data: Any) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        with self.journal.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(), "event": event, **data},
                                    ensure_ascii=False, sort_keys=True) + "\n")

    def plan(self, ticker: str) -> SyncReport:
        report = SyncReport(mode="dry_run", ticker=ticker)
        for summary in self.source.list_runs(ticker):
            run = self.source.get_run(summary["run_id"])
            existing = self.target.existing_digest(run["run_id"])
            state = "to_create" if existing is None else "exists_same" if existing == run["output_digest"] else "collision"
            report.planned[state].append(run["run_id"])
        return report

    def execute(self, ticker: str) -> SyncReport:
        report = self.plan(ticker)
        report.mode = "execute"
        try:
            descriptor = os.open(self.lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise SyncLockedError(f"another research-result export holds {self.lock}") from exc
        try:
            os.write(descriptor, str(os.getpid()).encode())
            self._log("start", ticker=ticker, planned={k: len(v) for k, v in report.planned.items()})
            batch, report.deferred = report.planned["to_create"][:self.batch_limit], report.planned["to_create"][self.batch_limit:]
            for run_id in batch:
                run = self.source.get_run(run_id)
                for attempt in range(1, self.max_retries + 1):
                    try:
                        self.target.record_run({k: v for k, v in run.items() if k not in ("reviewer_metadata_fields", "immutable", "created_at")})
                        report.written.append(run_id)
                        self._log("written", run_id=run_id, attempt=attempt)
                        break
                    except ResultStoreIntegrityError as exc:
                        report.failed[run_id] = f"integrity: {exc}"
                        self._log("integrity_failure", run_id=run_id, error=str(exc))
                        break
                    except Exception as exc:  # noqa: BLE001 - transient cloud failure, bounded retry
                        self._log("retry", run_id=run_id, attempt=attempt, error=type(exc).__name__)
                        if attempt == self.max_retries:
                            report.failed[run_id] = f"{type(exc).__name__} after {attempt} attempts"
                        else:
                            self.sleep(self.backoff * (4 ** (attempt - 1)))
            self._log("end", status=report.status, written=len(report.written), failed=len(report.failed))
            return report
        finally:
            os.close(descriptor)
            self.lock.unlink(missing_ok=True)
