"""MOCK and EMULATOR tiers for Phase 5 research-result cloud compatibility.

MOCK results use the in-memory clients of ``historical_cloud_fakes`` (not Firestore). The EMULATOR class runs only
with ``FIRESTORE_EMULATOR_HOST`` set and a ``demo-``/test project; it never targets a real project.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from app.services.financial_research.result_store import FirestoreResearchResultStore, SqliteResearchResultStore, build_run
from app.services.financial_research.result_sync import ResearchResultSync, SyncLockedError, build_cloud_result_store
from app.services.historical_audit.cloud_config import CloudSafetyError, CloudSyncDisabledError, HistoricalCloudConfig
from tests.historical_cloud_fakes import FakeFirestoreClient
import tests.test_financial_research_units as research_units  # module import: avoids re-collecting its tests


def make_runs(count: int) -> list[dict]:
    template = research_units.ResultStoreTests().run_record()
    runs = []
    for index in range(count):
        runs.append(build_run(result_kind="financial_signals", method_version=f"m{index}", method_ids=[f"m{index}"],
                              approval_status="DRAFT_PENDING_METHOD_OWNER_REVIEW", snapshot=template["snapshot"],
                              parameters={"statement_scope": "consolidated"}, output=template["output"]))
    return runs


class ResultSyncMockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self._tmp.name)
        self.source = SqliteResearchResultStore(self.root / "results.sqlite3")
        self.runs = make_runs(5)
        for run in self.runs:
            self.source.record_run(run)
        self.client = FakeFirestoreClient()
        self.target = FirestoreResearchResultStore(self.client)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def sync(self, **kwargs) -> ResearchResultSync:
        return ResearchResultSync(self.source, self.target, journal=self.root / "journal.jsonl", lock=self.root / "sync.lock",
                                  sleep=lambda _: None, **kwargs)

    def test_dry_run_writes_nothing_then_bounded_idempotent_execute(self) -> None:
        plan = self.sync().plan("1785")
        self.assertEqual(plan.as_dict()["counts"]["to_create"], 5)
        self.assertEqual(self.client.data, {})  # dry run: no document written
        first = self.sync(batch_limit=2).execute("1785")
        self.assertEqual((len(first.written), len(first.deferred), first.status), (2, 3, "partial_batch_limit"))
        second = self.sync(batch_limit=10).execute("1785")
        self.assertEqual((len(second.written), second.planned["exists_same"].__len__(), second.status), (3, 2, "complete"))
        third = self.sync().execute("1785")
        self.assertEqual((third.written, third.as_dict()["counts"]["exists_same"]), ([], 5))
        for run in self.runs:  # cloud mirror reads back identically
            strip = lambda r: {k: v for k, v in r.items() if k != "created_at"}  # noqa: E731
            self.assertEqual(strip(self.target.get_run(run["run_id"])), strip(self.source.get_run(run["run_id"])))
        self.assertIn('"event": "end"', (self.root / "journal.jsonl").read_text(encoding="utf-8"))

    def test_collision_is_reported_and_never_overwritten(self) -> None:
        tampered = dict(self.runs[0], output={"status": "TAMPERED"})
        tampered["output_digest"] = "0" * 64
        self.target.record_run(tampered)
        report = self.sync().execute("1785")
        self.assertEqual(report.planned["collision"], [self.runs[0]["run_id"]])
        self.assertEqual(report.status, "attention_required")
        self.assertEqual(self.target.existing_digest(self.runs[0]["run_id"]), "0" * 64)

    def test_transient_failures_retry_with_a_bound_and_lock_is_exclusive(self) -> None:
        calls = {"n": 0}

        def flaky(collection, document, operation):
            calls["n"] += 1
            return calls["n"] <= 2  # the first two writes fail
        self.client.fail_write = flaky
        report = self.sync(batch_limit=1, max_retries=3).execute("1785")
        self.assertEqual(len(report.written), 1)
        self.client.fail_write = lambda *a: True
        failed = self.sync(batch_limit=1, max_retries=2).execute("1785")
        self.assertEqual(list(failed.failed.values()), ["ServiceUnavailable after 2 attempts"])
        self.client.fail_write = None
        (self.root / "sync.lock").write_text("other", encoding="utf-8")
        with self.assertRaises(SyncLockedError):
            self.sync().execute("1785")

    def test_cloud_target_is_fail_closed(self) -> None:
        with self.assertRaises(CloudSyncDisabledError):
            HistoricalCloudConfig.from_env({})
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({"HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "production",
                                            "HISTORICAL_CLOUD_PROJECT": "fintrust-alert-ccu", "HISTORICAL_CLOUD_BUCKET": "bucket-x"})
        isolated = HistoricalCloudConfig.from_env({
            "HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "isolated-test",
            "HISTORICAL_CLOUD_PROJECT": "fintrust-research-test", "HISTORICAL_CLOUD_BUCKET": "fintrust-research-test-bucket",
            "GOOGLE_CLOUD_PROJECT": "fintrust-alert-ccu"})
        self.assertIsInstance(build_cloud_result_store(isolated, client=FakeFirestoreClient()), FirestoreResearchResultStore)

        class Production:
            environment = "production"
        with self.assertRaises(PermissionError):
            build_cloud_result_store(Production(), client=FakeFirestoreClient())


@unittest.skipUnless(os.getenv("FIRESTORE_EMULATOR_HOST"), "Firestore emulator not configured (FIRESTORE_EMULATOR_HOST)")
class ResultSyncEmulatorTests(unittest.TestCase):
    def test_sqlite_and_emulator_result_stores_agree(self) -> None:
        from google.cloud import firestore

        def config(namespace):
            return HistoricalCloudConfig.from_env({
                "HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "emulator",
                "FIRESTORE_EMULATOR_HOST": os.environ["FIRESTORE_EMULATOR_HOST"], "HISTORICAL_CLOUD_PROJECT": "demo-fintrust",
                "HISTORICAL_CLOUD_BUCKET": "demo-fintrust-bucket",
                "HISTORICAL_CLOUD_COLLECTION_PREFIX": f"historical_research_{namespace}{os.getpid()}"})
        client = firestore.Client(project="demo-fintrust")
        target = build_cloud_result_store(config("ea"), client=client)  # namespace derived from the config
        other = build_cloud_result_store(config("eb"), client=client)
        self.assertEqual(target.prefix, f"historical_research_ea{os.getpid()}_results")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            source = SqliteResearchResultStore(Path(directory) / "r.sqlite3")
            for run in make_runs(3):
                source.record_run(run)
            sync = ResearchResultSync(source, target, journal=Path(directory) / "j.jsonl", lock=Path(directory) / "l.lock")
            self.assertEqual(sync.execute("1785").status, "complete")
            self.assertEqual(sync.execute("1785").as_dict()["counts"]["exists_same"], 3)
            for summary in source.list_runs("1785"):
                strip = lambda r: {k: v for k, v in r.items() if k != "created_at"}  # noqa: E731
                self.assertEqual(strip(target.get_run(summary["run_id"])), strip(source.get_run(summary["run_id"])))
                self.assertIsNone(other.get_run(summary["run_id"]))  # isolated namespaces never share results


if __name__ == "__main__":
    unittest.main()


from tests.test_historical_evidence import EvidenceTestCase  # noqa: E402  (base class, defines no tests)


@unittest.skipUnless(os.getenv("FIRESTORE_EMULATOR_HOST"), "Firestore emulator not configured (FIRESTORE_EMULATOR_HOST)")
class ResearchMirrorEmulatorTests(EvidenceTestCase):
    def test_research_outputs_agree_between_sqlite_and_emulator_mirror(self) -> None:
        from google.cloud import firestore

        from app.services.financial_research.modes import build_context
        from app.services.financial_research.service import ReadOnlyHistoricalAuditRepository, ResearchService
        from app.services.historical_audit.cloud_sync import HistoricalCloudSync
        from app.services.historical_audit.firestore_repository import FirestoreHistoricalResearchRepository
        from app.services.historical_audit.object_storage import LocalObjectStore
        from app.services.historical_audit.research_access import FirestoreResearchBackend

        self.run_all()
        config = HistoricalCloudConfig.from_env({
            "HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "emulator",
            "FIRESTORE_EMULATOR_HOST": os.environ["FIRESTORE_EMULATOR_HOST"], "HISTORICAL_CLOUD_PROJECT": "demo-fintrust",
            "HISTORICAL_CLOUD_BUCKET": "demo-fintrust-bucket",
            "HISTORICAL_CLOUD_COLLECTION_PREFIX": f"historical_research_r{os.getpid()}"})
        mirror = FirestoreHistoricalResearchRepository(firestore.Client(project=config.project), prefix=config.collection_prefix)
        sync = HistoricalCloudSync(repository=self.repository, archive=self.archive,
                                   object_store=LocalObjectStore(self.root / "objects"), firestore=mirror, config=config)
        self.assertEqual(sync.sync("1785", execute=True).status, "complete")
        readonly = ReadOnlyHistoricalAuditRepository(self.repository.database_path)
        local = ResearchService(repository=readonly, conference_repository=None, pdf_provider=None)
        cloud = ResearchService(backend=FirestoreResearchBackend(mirror), repository=readonly,
                                conference_repository=None, pdf_provider=None)
        for mode, cutoff in (("RETROSPECTIVE_FORENSIC", None), ("STRICT_AS_OF", "2016-11-14T00:00:00+08:00"),
                             ("CURRENT_EVIDENCE_RECONCILIATION", None)):
            context = build_context(mode, cutoff)
            a = local.build_run("financial_signals", "1785", context, start_year=2011, end_year=2016)
            b = cloud.build_run("financial_signals", "1785", context, start_year=2011, end_year=2016)
            self.assertEqual((a["run_id"], a["input_digest"]), (b["run_id"], b["input_digest"]), mode)
            strip = lambda o: {k: v for k, v in o.items() if k != "input_snapshot"}  # noqa: E731 (backend name differs)
            self.assertEqual(strip(a["output"]), strip(b["output"]), mode)
        self.assertEqual(cloud.backend.list_publication_events("1785"), local.backend.list_publication_events("1785"))
