"""FIXTURE + MOCK tier: research service, API and local/Firestore parity over the synthetic evidence archive.

The archive is built by the existing Phase 1B/1C fixtures (no network). Cloud results here use in-memory MOCK
clients (``historical_cloud_fakes``): they are not Firestore emulator or live-cloud evidence.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.services.financial_research.modes import build_context
from app.services.financial_research.result_store import FirestoreResearchResultStore, SqliteResearchResultStore
from app.services.financial_research.service import ReadOnlyHistoricalAuditRepository, ResearchService
from app.services.historical_audit.models import parse_timestamp
from app.services.historical_audit.research_access import FirestoreResearchBackend, LocalResearchBackend
from tests.historical_cloud_fakes import FakeFirestoreClient
from tests.test_historical_cloud import CloudTestCase

MODES = [("RETROSPECTIVE_FORENSIC", None), ("STRICT_AS_OF", "2016-11-13T21:26:22+08:00"),
         ("STRICT_AS_OF", "2016-11-14T00:00:00+08:00"), ("CURRENT_EVIDENCE_RECONCILIATION", None)]


class FixtureResearchTestCase(CloudTestCase):
    def setUp(self) -> None:
        super().setUp()  # builds the fixture archive (CloudTestCase runs the evidence import)
        self.readonly = ReadOnlyHistoricalAuditRepository(self.repository.database_path)
        self.service = ResearchService(repository=self.readonly, conference_repository=None, pdf_provider=None)

    def digest_db(self) -> str:
        import hashlib
        import sqlite3

        connection = sqlite3.connect(f"file:{Path(self.repository.database_path).as_posix()}?mode=ro", uri=True)
        try:
            rows = []
            for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                rows += sorted(json.dumps([table, *r], default=str) for r in connection.execute(f'SELECT * FROM "{table}"'))
            return hashlib.sha256("\n".join(rows).encode()).hexdigest()
        finally:
            connection.close()


class ResearchServiceFixtureTests(FixtureResearchTestCase):
    def test_read_only_repository_refuses_writes_and_research_never_mutates(self) -> None:
        before = self.digest_db()
        for mode, cutoff in MODES:
            context = build_context(mode, cutoff)
            self.service.build_run("financial_signals", "1785", context, start_year=2011, end_year=2016)
            if mode != "CURRENT_EVIDENCE_RECONCILIATION":
                self.service.bridge("1785", context)
                self.service.timeline("1785", context)
            else:
                self.service.discrepancies("1785", context)
        self.service.case_overview("1785")
        self.assertEqual(self.digest_db(), before)
        with self.assertRaises(Exception):
            with self.readonly.connect() as connection:
                connection.execute("DELETE FROM versioned_financial_facts")

    def test_strict_boundary_and_no_full_fallback(self) -> None:
        before = self.service.snapshot("1785", build_context("STRICT_AS_OF", "2016-11-13T21:26:22+08:00"),
                                       start_year=2011, end_year=2016)
        after = self.service.snapshot("1785", build_context("STRICT_AS_OF", "2016-11-14T00:00:00+08:00"),
                                      start_year=2011, end_year=2016)
        full = self.service.snapshot("1785", build_context("RETROSPECTIVE_FORENSIC"), start_year=2011, end_year=2016)
        self.assertLess(len(before.facts), len(full.facts))
        self.assertTrue(after.facts)
        cutoff = parse_timestamp("2016-11-14T00:00:00+08:00")
        for row in after.facts:
            self.assertLess(parse_timestamp(row["effective_available_at"]), cutoff)
        self.assertTrue(all(f["artifact_reference_status"] in ("included", "withheld_not_public_at_cutoff") for f in after.facts))
        self.assertTrue(any(f["artifact_reference_status"] == "withheld_not_public_at_cutoff" for f in after.facts))

    def test_runs_are_deterministic_and_verifiable(self) -> None:
        context = build_context("RETROSPECTIVE_FORENSIC")
        first = self.service.build_run("restatement_bridge", "1785", context)
        second = self.service.build_run("restatement_bridge", "1785", context)
        self.assertEqual((first["run_id"], first["output_digest"]), (second["run_id"], second["output_digest"]))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = SqliteResearchResultStore(Path(directory) / "r.sqlite3")
            store.record_run(first)
            self.assertEqual(self.service.verify_run(store.get_run(first["run_id"]))["status"], "reproducible")


class CloudParityFixtureTests(FixtureResearchTestCase):
    def test_new_backend_methods_and_research_outputs_match_the_mirror(self) -> None:
        self.assertEqual(self.sync().sync("1785", execute=True).status, "complete")
        local, cloud = LocalResearchBackend(self.readonly), FirestoreResearchBackend(self.firestore)
        for as_of in (None, "2016-11-13T21:26:21+08:00", "2016-11-14"):
            self.assertEqual(cloud.list_disclosed_values("1785", as_of=as_of), local.list_disclosed_values("1785", as_of=as_of))
        self.assertEqual(cloud.list_publication_events("1785"), local.list_publication_events("1785"))
        self.assertTrue(local.list_publication_events("1785"))
        cloud_service = ResearchService(backend=cloud, repository=self.readonly, conference_repository=None, pdf_provider=None)
        for mode, cutoff in MODES:
            context = build_context(mode, cutoff)
            a = self.service.build_run("financial_signals", "1785", context, start_year=2011, end_year=2016)
            b = cloud_service.build_run("financial_signals", "1785", context, start_year=2011, end_year=2016)
            self.assertEqual((a["input_digest"], a["run_id"]), (b["input_digest"], b["run_id"]), mode)
            strip = lambda o: {k: v for k, v in o.items() if k != "input_snapshot"}  # noqa: E731 (backend name differs)
            self.assertEqual(strip(a["output"]), strip(b["output"]), mode)

    def test_result_store_parity_sqlite_vs_mock_firestore(self) -> None:
        run = self.service.build_run("restatement_bridge", "1785", build_context("RETROSPECTIVE_FORENSIC"))
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            sqlite_store = SqliteResearchResultStore(Path(directory) / "r.sqlite3")
            sqlite_store.record_run(run)
            firestore_store = FirestoreResearchResultStore(FakeFirestoreClient())
            firestore_store.record_run(run)
            strip = lambda r: {k: v for k, v in r.items() if k != "created_at"}  # noqa: E731
            self.assertEqual(strip(sqlite_store.get_run(run["run_id"])), strip(firestore_store.get_run(run["run_id"])))


class ResearchApiFixtureTests(FixtureResearchTestCase):
    def setUp(self) -> None:
        super().setUp()
        from app.main import app
        from app.routers.historical_research import get_research_service

        self.app = app
        self.results = Path(self.root) / "results.sqlite3"
        app.dependency_overrides[get_research_service] = lambda: self.service
        self._env = patch.dict(os.environ, {"RESEARCH_RESULTS_DATABASE_PATH": str(self.results),
                                            "APP_ENV": "development", "INGESTION_API_TOKEN": "fixture-token"})
        self._env.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self._env.stop()
        self.app.dependency_overrides.clear()
        super().tearDown()

    def test_endpoints_modes_errors_and_no_path_leakage(self) -> None:
        get = self.client.get
        ok = [get("/api/v1/research/health"), get("/api/v1/research/cases"), get("/api/v1/research/cases/1785"),
              get("/api/v1/research/cases/1785/timeline", params={"analysis_mode": "RETROSPECTIVE_FORENSIC"}),
              get("/api/v1/research/cases/1785/restatement-bridge", params={"analysis_mode": "RETROSPECTIVE_FORENSIC"}),
              get("/api/v1/research/cases/1785/feature-registry", params={"analysis_mode": "RETROSPECTIVE_FORENSIC"}),
              get("/api/v1/research/cases/1785/source-discrepancies", params={"analysis_mode": "CURRENT_EVIDENCE_RECONCILIATION"}),
              get("/api/v1/research/cases/1785/text-readiness", params={"analysis_mode": "RETROSPECTIVE_FORENSIC"})]
        for response in ok:
            self.assertEqual(response.status_code, 200, response.text[:300])
            text = response.text
            for leak in (str(self.root), str(self.root).replace("\\", "/"), "raw_storage_path", ".sqlite3", "listing_raw_path"):
                self.assertNotIn(leak, text, response.url)
        self.assertEqual(self.client.get("/api/v1/research/cases/1785/text-readiness",
                                         params={"analysis_mode": "RETROSPECTIVE_FORENSIC"}).json()["jsd"],
                         {"status": "NOT_APPLICABLE", "value": None})
        cases = [(get("/api/v1/research/cases/2330"), 404), (get("/api/v1/research/cases/abc"), 422),
                 (get("/api/v1/research/cases/1785/timeline"), 422),
                 (get("/api/v1/research/cases/1785/timeline", params={"analysis_mode": "STRICT_AS_OF"}), 422),
                 (get("/api/v1/research/cases/1785/timeline", params={"analysis_mode": "STRICT_AS_OF",
                                                                      "cutoff_at": "2016-05-13"}), 422),
                 (get("/api/v1/research/cases/1785/timeline", params={"analysis_mode": "CURRENT_EVIDENCE_RECONCILIATION"}), 409),
                 (get("/api/v1/research/cases/1785/source-discrepancies", params={"analysis_mode": "STRICT_AS_OF",
                                                                                  "cutoff_at": "2026-10-11T00:00:00+08:00"}), 409),
                 (get("/api/v1/research/runs/not-a-run"), 422), (get("/api/v1/research/runs/rrun1_" + "a" * 32), 404)]
        for response, status in cases:
            self.assertEqual(response.status_code, status, (response.url, response.text[:200]))
        self.assertFalse(self.results.exists())  # GETs never create the result store

    def test_compute_dry_run_persist_requires_token_and_run_roundtrip(self) -> None:
        body = {"ticker": "1785", "analysis_mode": "STRICT_AS_OF", "cutoff_at": "2016-05-13T00:00:00+08:00",
                "version_policy": "latest_available", "start_year": 2011, "end_year": 2016}
        dry = self.client.post("/api/v1/research/financial-signals/compute", json=body)
        self.assertEqual(dry.status_code, 200)
        self.assertEqual(dry.json()["result"]["status"], "insufficient_point_in_time_evidence")
        self.assertFalse(dry.json()["persisted"])
        self.assertFalse(self.results.exists())
        denied = self.client.post("/api/v1/research/financial-signals/compute", json={**body, "persist": True})
        self.assertEqual(denied.status_code, 401)
        self.assertFalse(self.results.exists())
        saved = self.client.post("/api/v1/research/financial-signals/compute", json={**body, "persist": True},
                                 headers={"X-Ingestion-Token": "fixture-token"})
        self.assertEqual((saved.status_code, saved.json()["created"]), (200, True))
        run = self.client.get(f"/api/v1/research/runs/{saved.json()['run_id']}").json()
        self.assertEqual(run["output"], dry.json()["result"])
        self.assertEqual(run["output_digest"], saved.json()["output_digest"])
        verify = self.client.get(f"/api/v1/research/runs/{saved.json()['run_id']}/verify").json()
        self.assertEqual(verify["status"], "reproducible")
        for missing in ({"analysis_mode": None}, {"version_policy": None}, {"start_year": 2009}, {"end_year": 2030},
                        {"ticker": "2330"}):
            response = self.client.post("/api/v1/research/financial-signals/compute", json={**body, **missing})
            self.assertIn(response.status_code, (404, 422), missing)

    def test_openapi_documents_research_routes_and_keeps_production_routes(self) -> None:
        paths = self.client.get("/openapi.json").json()["paths"]
        for path in ("/api/v1/research/cases", "/api/v1/research/cases/{ticker}/timeline",
                     "/api/v1/research/cases/{ticker}/restatement-bridge", "/api/v1/research/financial-signals/compute",
                     "/api/v1/research/cases/{ticker}/source-discrepancies", "/api/v1/research/cases/{ticker}/text-readiness",
                     "/api/v1/research/runs/{run_id}", "/api/v1/financial/companies"):
            self.assertIn(path, paths)
        research = [p for p in paths if p.startswith("/api/v1/research")]
        self.assertFalse([p for p in research if "historical-audit" in p or "admin" in p])
