"""EMULATOR tier: Firestore emulator + local object store. Skipped unless FIRESTORE_EMULATOR_HOST is set.

Start an emulator first, e.g. `gcloud emulators firestore start --host-port=localhost:8080`, then
`FIRESTORE_EMULATOR_HOST=localhost:8080 python -m pytest tests/test_historical_cloud_emulator.py`.
Never points at a real project: the config requires the emulator environment.
"""

from __future__ import annotations

import os
import unittest

from app.services.historical_audit.cloud_config import HistoricalCloudConfig
from app.services.historical_audit.cloud_sync import HistoricalCloudSync
from app.services.historical_audit.firestore_repository import FirestoreHistoricalResearchRepository
from app.services.historical_audit.object_storage import LocalObjectStore
from app.services.historical_audit.research_access import FirestoreResearchBackend, LocalResearchBackend
from tests.test_historical_evidence import EvidenceTestCase


@unittest.skipUnless(os.getenv("FIRESTORE_EMULATOR_HOST"), "Firestore emulator not configured (FIRESTORE_EMULATOR_HOST)")
class FirestoreEmulatorSyncTest(EvidenceTestCase):
    def test_sync_and_read_contract_against_emulator(self) -> None:
        from google.cloud import firestore

        self.run_all()
        config = HistoricalCloudConfig.from_env({
            "HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "emulator",
            "FIRESTORE_EMULATOR_HOST": os.environ["FIRESTORE_EMULATOR_HOST"],
            "HISTORICAL_CLOUD_PROJECT": "fintrust-emulator-test", "HISTORICAL_CLOUD_BUCKET": "emulator-test-bucket",
            "HISTORICAL_CLOUD_COLLECTION_PREFIX": f"historical_research_e{os.getpid()}",
        })
        repository = FirestoreHistoricalResearchRepository(firestore.Client(project=config.project), prefix=config.collection_prefix)
        sync = HistoricalCloudSync(repository=self.repository, archive=self.archive,
                                   object_store=LocalObjectStore(self.root / "objects"), firestore=repository, config=config)
        self.assertEqual(sync.sync("1785", execute=True).status, "complete")
        self.assertEqual(sync.sync("1785", execute=True).status, "complete")
        local, cloud = LocalResearchBackend(self.repository), FirestoreResearchBackend(repository)
        self.assertEqual(cloud.list_facts("1785", 2011, 2016, as_of="2016-11-14"), local.list_facts("1785", 2011, 2016, as_of="2016-11-14"))


if __name__ == "__main__":
    unittest.main()
