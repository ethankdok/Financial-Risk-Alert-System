"""Phase 1.1 incident closure: approved data stores are protected *before* any write.

Every negative test attempts to open an approved location and asserts the attempt is refused before the
constructor runs: the approved file's SHA-256 and mtime are unchanged and no new file appears in the data directory.
Nothing in this module writes to approved data.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests import protected_stores as guard

BACKEND = Path(__file__).resolve().parents[1]
PIPELINE = guard.PROTECTED_DIR / "financial_pipeline.sqlite3"


def snapshot() -> dict:
    files = sorted(p.name for p in guard.PROTECTED_DIR.iterdir()) if guard.PROTECTED_DIR.is_dir() else []
    state = {"listing": files}
    if PIPELINE.is_file():
        state.update(sha=guard.sha256(PIPELINE), mtime=PIPELINE.stat().st_mtime_ns)
    return state


class ConstructorGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before = snapshot()

    def tearDown(self) -> None:
        self.assertEqual(snapshot(), self.before)  # nothing written, nothing created

    def test_installed_on_all_three_write_capable_repositories(self) -> None:
        self.assertEqual(sorted(guard.install()), ["SqliteAnalysisRepository", "SqliteCompanyMasterRepository",
                                                   "SqliteIngestionRunRepository"])
        for cls in guard.guarded_classes():
            self.assertTrue(getattr(cls.__init__, "_protected_store_guard", False))

    def test_direct_construction_on_approved_or_new_paths_is_refused(self) -> None:
        targets = [PIPELINE, guard.PROTECTED_DIR / "zz_guard_probe_never_created.sqlite3",
                   guard.PROTECTED_DIR / "nested" / "zz_probe.sqlite3", "./data/financial_pipeline.sqlite3",
                   guard.PROTECTED_DIR / ".." / "data" / "financial_pipeline.sqlite3"]
        for cls in guard.guarded_classes():
            for target in targets:
                with self.subTest(cls=cls.__name__, target=str(target)):
                    cwd = os.getcwd()
                    os.chdir(BACKEND)
                    try:
                        with self.assertRaises(guard.ProtectedStoreWriteBlocked):
                            cls(str(target))
                    finally:
                        os.chdir(cwd)
        self.assertFalse((guard.PROTECTED_DIR / "nested").exists())

    def test_default_builders_and_dependency_are_refused_when_pointed_at_live_data(self) -> None:
        from app.dependencies import get_analysis_repository, get_company_master_repository, get_ingestion_run_repository
        from app.services.analysis_repository import build_analysis_repository
        from app.services.company_master_repository import build_company_master_repository
        from app.services.ingestion_run_repository import build_ingestion_run_repository

        live = str(PIPELINE)
        with mock.patch.dict(os.environ, {"FINANCIAL_DATABASE_PATH": live, "DATASTORE_BACKEND": "sqlite"}):
            for builder in (build_analysis_repository, build_company_master_repository, build_ingestion_run_repository):
                with self.subTest(builder=builder.__name__), self.assertRaises(guard.ProtectedStoreWriteBlocked):
                    builder()
            for provider in (get_analysis_repository, get_company_master_repository, get_ingestion_run_repository):
                provider.cache_clear()
                try:
                    with self.subTest(provider=provider.__name__), self.assertRaises(guard.ProtectedStoreWriteBlocked):
                        provider()
                finally:
                    provider.cache_clear()

    def test_api_request_through_the_imported_router_cannot_touch_live_data(self) -> None:
        from fastapi.testclient import TestClient

        from app.dependencies import get_analysis_repository
        from app.main import app

        with mock.patch.dict(os.environ, {"FINANCIAL_DATABASE_PATH": str(PIPELINE), "DATASTORE_BACKEND": "sqlite"}):
            get_analysis_repository.cache_clear()
            try:
                with TestClient(app) as client, self.assertRaises(guard.ProtectedStoreWriteBlocked):
                    client.post("/api/v1/integrity/assessments/preview", json={"ticker": "2454"})
            finally:
                get_analysis_repository.cache_clear()

    def test_temporary_databases_still_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for cls in guard.guarded_classes():
                path = Path(tmp) / f"{cls.__name__}.sqlite3"
                cls(str(path))
                self.assertTrue(path.is_file())

    def test_session_defaults_point_to_a_temporary_directory(self) -> None:
        for variable in guard.DEFAULT_PATH_VARIABLES:
            self.assertFalse(guard.is_protected(os.environ[variable]), variable)


class BaselineCheckTests(unittest.TestCase):
    def test_absolute_baseline_detects_mismatch_and_accepts_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store.sqlite3"
            store.write_bytes(b"approved bytes")
            approved = {store.resolve(): guard.sha256(store)}
            self.assertEqual(guard.baseline_mismatches(approved), [])
            store.write_bytes(b"changed bytes")
            self.assertEqual(len(guard.baseline_mismatches(approved)), 1)
            self.assertEqual(guard.baseline_mismatches({Path(tmp, "absent.sqlite3"): "0" * 64}), [])

    def test_tracked_manifest_records_the_option_b_decision(self) -> None:
        manifest = json.loads(guard.BASELINE_FILE.read_text(encoding="utf-8"))
        entry = manifest["stores"]["data/financial_pipeline.sqlite3"]
        self.assertEqual(entry["sha256"], "8734fb68bca0e6e4a741226764d03de1684a56b2fa0fad90150fb193c50f2b9f")
        self.assertEqual(entry["supersedes_sha256"], "5526d2adc20fee9253b39cafaa9bb967fb45521af20d114a003442ae840ea181")
        self.assertEqual(entry["status"], "accepted_modified_baseline_option_B")
        self.assertFalse(entry["byte_identity_with_pre_incident"])
        self.assertIn("71 normalized_financial_facts rows", entry["unprovable"])
        self.assertEqual(len(entry["row_fingerprints_sha256"]), 12)

    def test_present_approved_stores_match_the_approved_baseline(self) -> None:
        self.assertEqual(guard.baseline_mismatches(), [])


class NewProcessTests(unittest.TestCase):
    def test_a_new_process_with_the_guard_cannot_initialise_the_default_store(self) -> None:
        before = snapshot()
        env = {k: v for k, v in os.environ.items() if k not in guard.DEFAULT_PATH_VARIABLES}
        code = ("import sys; sys.path.insert(0, '.'); from tests import protected_stores as g; g.install(); "
                "from app.services.analysis_repository import build_analysis_repository\n"
                "try:\n    build_analysis_repository()\nexcept g.ProtectedStoreWriteBlocked:\n    print('BLOCKED')\n")
        result = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, env=env, capture_output=True, text=True,
                                timeout=120)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "BLOCKED"), result.stderr[-800:])
        self.assertEqual(snapshot(), before)


if __name__ == "__main__":
    unittest.main()
