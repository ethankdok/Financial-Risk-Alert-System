"""CLOUD-01 … CLOUD-06 with MOCK GCS/Firestore clients (tests/historical_cloud_fakes.py).

These are mock tests: they prove the sync, identity and recovery logic, not a
live Google Cloud deployment.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.services.historical_audit.cloud_config import (
    CloudSafetyError,
    CloudSyncDisabledError,
    HistoricalCloudConfig,
    build_clients,
)
from app.services.historical_audit.cloud_sync import HistoricalCloudSync
from app.services.historical_audit.firestore_repository import (
    FirestoreConflictError,
    FirestoreHistoricalResearchRepository,
)
from app.services.historical_audit.object_storage import (
    GcsObjectStore,
    LocalObjectStore,
    ObjectIntegrityError,
    object_name,
)
from app.services.historical_audit.research_access import FirestoreResearchBackend, LocalResearchBackend
from tests.historical_cloud_fakes import FakeFirestoreClient, FakeGcsClient
from tests.test_historical_evidence import EvidenceTestCase


ISOLATED_ENV = {
    "HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "isolated-test",
    "HISTORICAL_CLOUD_PROJECT": "fintrust-research-test", "HISTORICAL_CLOUD_BUCKET": "fintrust-historical-test",
    "GOOGLE_CLOUD_PROJECT": "fintrust-prod", "CONFERENCE_PDF_ARCHIVE_GCS_BUCKET": "fintrust-prod-archive",
}


async def _no_sleep(_: float) -> None:
    return None


class CloudTestCase(EvidenceTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.run_all()
        self.config = HistoricalCloudConfig.from_env(ISOLATED_ENV)
        self.gcs = FakeGcsClient()
        self.firestore_client = FakeFirestoreClient()
        self.firestore = FirestoreHistoricalResearchRepository(self.firestore_client)
        self.store = GcsObjectStore(self.gcs, self.config.bucket, sleep=lambda _: None)

    def sync(self) -> HistoricalCloudSync:
        return HistoricalCloudSync(repository=self.repository, archive=self.archive, object_store=self.store,
                                   firestore=self.firestore, config=self.config)

    def objects(self) -> dict:
        return self.gcs.buckets.get(self.config.bucket, {})


class Cloud01ObjectIdentityTests(CloudTestCase):
    def test_content_addressed_create_only_and_verified_reads(self) -> None:
        digest = "ab" * 32
        name = object_name("financial_filings", "1785", digest, "xml")
        self.assertEqual(name, f"historical-financial-filings/1785/sha256/ab/{digest}.xml")
        with self.assertRaises(ValueError):
            object_name("financial_filings", "../x", digest, "xml")
        data = b"<xbrl/>"
        real = object_name("financial_filings", "1785", __import__("hashlib").sha256(data).hexdigest(), "xml")
        self.assertEqual(self.store.put_if_absent(real, data, content_type="application/xml", metadata={}).status, "created")
        self.assertEqual(self.store.put_if_absent(real, data, content_type="application/xml", metadata={}).status, "exists_same")
        self.assertEqual(self.store.put_if_absent(real, b"other", content_type="application/xml", metadata={}).status, "conflict")
        self.assertEqual(self.objects()[real]["data"], data)  # never overwritten
        self.gcs.corrupt_download = lambda n: True
        with self.assertRaises(ObjectIntegrityError):
            self.store.get_verified(real, __import__("hashlib").sha256(data).hexdigest())
        local = LocalObjectStore(self.root / "mirror")
        self.assertEqual(local.put_if_absent(real, data, content_type="", metadata={}).status, "created")
        self.assertEqual(local.put_if_absent(real, b"other", content_type="", metadata={}).status, "conflict")
        with self.assertRaises(ValueError):
            local.put_if_absent("../escape", data, content_type="", metadata={})


class Cloud02To04SyncTests(CloudTestCase):
    def test_cloud02_complete_sync_is_idempotent(self) -> None:
        plan = self.sync().sync("1785")
        self.assertEqual(plan.status, "planned")
        self.assertEqual(self.objects(), {})  # dry-run writes nothing
        first = self.sync().sync("1785", execute=True)
        self.assertEqual(first.status, "complete", first.errors)
        object_count, uploads = len(self.objects()), sum(1 for c in self.gcs.calls if c[0] == "upload")
        second = self.sync().sync("1785", execute=True)
        self.assertEqual(second.status, "complete", second.errors)
        self.assertNotEqual(second.run_id, first.run_id)
        self.assertEqual(len(self.objects()), object_count)
        self.assertEqual(sum(1 for c in self.gcs.calls if c[0] == "upload"), uploads)  # no new uploads
        self.assertTrue(all(key.endswith(":exists_same") for key in second.records), second.records)
        # PDF filing versions and their source documents share one content-addressed object.
        versions = self.repository.list_filing_versions("1785")
        self.assertLess(object_count, len(versions) + len(self.table("historical_source_documents")))

    def test_cloud03_filing_versions_never_overwrite_each_other(self) -> None:
        self.assertEqual(self.sync().sync("1785", execute=True).status, "complete")
        local = {v["filing_version_id"]: v for v in self.repository.list_filing_versions("1785")}
        stored = {d["filing_version_id"]: d for d in self.firestore.list("filing_versions", ticker="1785")}
        self.assertEqual(set(stored), set(local))
        by_period = {}
        for doc in stored.values():
            by_period.setdefault((doc["period"], doc["statement_scope"]), set()).add(doc["filing_version_type"])
        self.assertIn({"original", "restated"}, list(by_period.values()))
        victim = next(iter(local.values()))
        with self.assertRaises(FirestoreConflictError):
            self.firestore.write("filing_versions", {**victim, "content_hash": "0" * 64, "object_bucket": self.config.bucket,
                                                     "object_name": stored[victim["filing_version_id"]]["object_name"]})
        unknown = next(v for v in stored.values() if v["availability_status"] == "unverified")
        filled = {**unknown, "available_at": "2016-12-01T00:00:00+00:00", "availability_status": "verified",
                  "availability_basis": "test fill"}
        filled.pop("_record_sha256")
        self.assertEqual(self.firestore.write("filing_versions", filled), "filled")  # monotonic fill only

    def test_cloud04_interrupted_upload_resumes_and_completes(self) -> None:
        target = sorted(self.repository.list_filing_versions("1785"), key=lambda v: v["filing_version_id"])[0]
        self.gcs.fail_upload = lambda name: target["content_hash"] in name
        failed = self.sync().sync("1785", execute=True)
        self.assertEqual(failed.status, "incomplete")
        self.assertTrue(any("upload" in error for error in failed.errors))
        self.assertIsNone(self.firestore.get("filing_versions", target["filing_version_id"]))  # no dangling metadata
        states = self.sync().status("1785")[0]["items_by_state"]
        self.assertIn("upload_error", states)
        self.gcs.fail_upload = None
        retried = self.sync().sync("1785", execute=True)
        self.assertTrue(retried.resumed)
        self.assertEqual(retried.run_id, failed.run_id)
        self.assertEqual(retried.status, "complete", retried.errors)
        self.assertIsNotNone(self.firestore.get("filing_versions", target["filing_version_id"]))

    def test_cloud04_firestore_failure_and_corrupt_object_keep_run_incomplete(self) -> None:
        self.firestore_client.fail_write = lambda collection, doc, op: collection.endswith("_facts")
        broken = self.sync().sync("1785", execute=True)
        self.assertEqual(broken.status, "incomplete")
        self.assertTrue(any(error.startswith("metadata facts/") for error in broken.errors))
        self.firestore_client.fail_write = None
        self.assertEqual(self.sync().sync("1785", execute=True).status, "complete")

        other = HistoricalCloudSync(repository=self.repository, archive=self.archive,
                                    object_store=GcsObjectStore(FakeGcsClient(), self.config.bucket, sleep=lambda _: None),
                                    firestore=FirestoreHistoricalResearchRepository(FakeFirestoreClient()),
                                    config=HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_BUCKET": "fintrust-historical-test2"}))
        other.store.client.corrupt_download = lambda name: True
        result = other.sync("1785", execute=True)
        self.assertEqual(result.status, "incomplete")
        self.assertTrue(any(error.startswith("verify ") for error in result.errors))

    def test_missing_local_source_blocks_completion(self) -> None:
        version = self.repository.list_filing_versions("1785")[0]
        (self.archive.root / version["raw_storage_path"]).unlink()
        report = self.sync().sync("1785", execute=True)
        self.assertEqual(report.status, "incomplete")
        self.assertTrue(any(error.startswith("validate ") for error in report.errors))
        self.assertIsNone(self.firestore.get("filing_versions", version["filing_version_id"]))


class Cloud05ReadContractTests(CloudTestCase):
    def test_local_and_cloud_backends_agree(self) -> None:
        self.assertEqual(self.sync().sync("1785", execute=True).status, "complete")
        local, cloud = LocalResearchBackend(self.repository), FirestoreResearchBackend(self.firestore)
        for kwargs in ({}, {"as_of": "2016-11-13T21:26:21+08:00"}, {"as_of": "2016-11-14"},
                       {"as_of": "2017-12-31", "version_policy": "latest_available"}, {"version_policy": "original_only"}):
            self.assertEqual(cloud.list_facts("1785", 2011, 2016, **kwargs), local.list_facts("1785", 2011, 2016, **kwargs), kwargs)
        self.assertEqual(cloud.list_filing_versions("1785", 2011, 2016), local.list_filing_versions("1785", 2011, 2016))
        for as_of in (None, "2016-05-12", "2016-11-14"):
            self.assertEqual(cloud.list_restatement_comparisons("1785", as_of=as_of),
                             local.list_restatement_comparisons("1785", as_of=as_of))
            self.assertEqual(cloud.list_summary_observations("1785", as_of=as_of),
                             local.list_summary_observations("1785", as_of=as_of))
        self.assertTrue(local.list_facts("1785", 2011, 2016, as_of="2016-11-14"))


class Cloud06SafetyTests(unittest.TestCase):
    def test_disabled_by_default_and_production_blocked(self) -> None:
        with self.assertRaises(CloudSyncDisabledError):
            HistoricalCloudConfig.from_env({})
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_ENVIRONMENT": "production"})
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_ENVIRONMENT": "production",
                                            "HISTORICAL_CLOUD_PRODUCTION_APPROVAL": "CHG-1"})  # flag not passed
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_PROJECT": "fintrust-prod"})
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_BUCKET": "fintrust-prod-archive"})
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_PROJECT": "fintrust-research"})
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_ENVIRONMENT": "emulator"})
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_COLLECTION_PREFIX": "normalized_financial"})
        with self.assertRaises(ValueError):
            FirestoreHistoricalResearchRepository(FakeFirestoreClient(), prefix="companies")
        emulator = HistoricalCloudConfig.from_env({**ISOLATED_ENV, "HISTORICAL_CLOUD_ENVIRONMENT": "emulator",
                                                   "FIRESTORE_EMULATOR_HOST": "localhost:8080"})
        self.assertEqual(emulator.environment, "emulator")

    def test_missing_credentials_fail_closed(self) -> None:
        from google.auth.exceptions import DefaultCredentialsError

        config = HistoricalCloudConfig.from_env(ISOLATED_ENV)
        with patch("google.cloud.storage.Client", side_effect=DefaultCredentialsError("none")):
            with self.assertRaises(CloudSafetyError):
                build_clients(config)

    def test_cli_cloud_sync_refuses_without_opt_in(self) -> None:
        from scripts import historical_audit_case as cli

        with patch.dict(os.environ, {"HISTORICAL_CLOUD_SYNC_ENABLED": ""}):
            with self.assertRaises(CloudSyncDisabledError):
                cli.main(["cloud-sync", "plan", "--ticker", "1785", "--database", "unused.sqlite3"])


if __name__ == "__main__":
    unittest.main()
