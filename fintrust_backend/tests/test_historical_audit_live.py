"""Opt-in live acquisition test against the official MOPS endpoint.

Skipped unless FINTRUST_LIVE_MOPS=1. Makes exactly one bounded request
(1785 FY2013, consolidated annual) into a temporary isolated database.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.backfill import HistoricalBackfillService
from app.services.historical_audit.repository import HistoricalAuditRepository


@unittest.skipUnless(os.getenv("FINTRUST_LIVE_MOPS") == "1", "live MOPS test is opt-in (FINTRUST_LIVE_MOPS=1)")
class LiveMopsAcquisitionTest(unittest.TestCase):
    def test_1785_fy2013_official_instance(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            service = HistoricalBackfillService(
                repository=HistoricalAuditRepository(str(root / "live.sqlite3")),
                archive=RawEvidenceArchive(root / "raw"),
            )
            result = asyncio.run(service.run("1785", 2013, 2013))
            year = result.years[0]
            if year.status == "source_unavailable":
                self.skipTest(f"Live source unavailable: {year.error}")
            self.assertEqual(year.status, "available", year.error)
            self.assertEqual(year.statement_scope, "consolidated")
            self.assertEqual(year.publication_verification_status, "unverified")
            self.assertEqual(len(year.core_fields_found), 17)
            # The document itself states it is the restated report (audit date 2016-11-11).
            self.assertEqual(year.filing_version_type, "restated")
            self.assertEqual(year.document_dated_at, "2016-11-11")


if __name__ == "__main__":
    unittest.main()
