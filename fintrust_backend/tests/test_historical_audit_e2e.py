"""Smoke (CLI) and E2E tests for historical audit-case ingestion.

Fixture E2E PASS proves pipeline behaviour on SYNTHETIC documents. It does not
prove that real original/restated 1785 filings were retrieved; see the opt-in
live test in test_historical_audit_live.py.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.backfill import HistoricalBackfillService
from app.services.historical_audit.export import EXPORT_FIELDS, build_export_records
from app.services.historical_audit.reader import list_historical_facts
from app.services.historical_audit.repository import HistoricalAuditRepository
from app.services.historical_audit.sources import OfficialSourceFetcher
from scripts import historical_audit_case as cli
from tests.historical_audit_fixtures import MOPS_NOT_FOUND_PAGE, synthetic_instance, write_manifest


async def _no_sleep(_: float) -> None:
    return None


def run_cli(*argv: str) -> dict:
    buffer = io.BytesIO()
    wrapper = io.TextIOWrapper(buffer, encoding="utf-8")
    with patch.object(sys, "stdout", wrapper):
        cli.main(list(argv))
        wrapper.flush()
    return json.loads(buffer.getvalue().decode("utf-8"))


class HistoricalAuditSmokeTest(unittest.TestCase):
    def test_cli_smoke_flow(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            db, archive = str(root / "smoke.sqlite3"), str(root / "raw")
            common = ["--database", db, "--archive", archive]
            (root / "a.xml").write_bytes(synthetic_instance(fiscal_year=2014))
            manifest = write_manifest(root, [{
                "period": "2014FY", "source_kind": "test_fixture", "local_path": "a.xml",
                "statement_scope": "consolidated", "available_at": "2015-03-31T10:00:00+08:00",
                "availability_basis": "synthetic fixture timeline", "verification_evidence": ["synthetic"],
            }])

            init = run_cli("init-db", *common, "--ticker", "1785")
            self.assertEqual(init["schema_version"], "1")
            self.assertEqual(init["tables"]["historical_audit_cases"], 1)

            plan = run_cli("backfill", *common, "--ticker", "1785", "--dry-run")
            self.assertEqual([item["fiscal_year"] for item in plan["plan"]], list(range(2011, 2017)))

            args = ["backfill", *common, "--ticker", "1785", "--start-year", "2014", "--end-year", "2014",
                    "--source-strategy", "manifest", "--manifest", str(manifest)]
            first = run_cli(*args)
            second = run_cli(*args)
            self.assertEqual(first["evidence_matrix"][0]["acquisition_status"], "available")
            self.assertEqual(first["evidence_matrix"][0]["facts_inserted"], 17)
            self.assertEqual(second["evidence_matrix"][0]["facts_inserted"], 0)
            self.assertEqual(second["evidence_matrix"][0]["persistence_status"], "unchanged")

            quality = run_cli("quality", *common, "--ticker", "1785", "--start-year", "2014", "--end-year", "2014")
            self.assertTrue(quality["integrity_passed"])
            self.assertEqual(quality["checks"]["duplicate_fact_identities"], 0)

            query = run_cli("query", *common, "--ticker", "1785", "--start-year", "2014", "--end-year", "2014",
                            "--metric", "inventory", "--include-test-fixtures")
            self.assertEqual(query["count"], 1)
            before = run_cli("query", *common, "--ticker", "1785", "--start-year", "2014", "--end-year", "2014",
                             "--as-of", "2015-03-30", "--include-test-fixtures")
            self.assertEqual(before["count"], 0)

            out_csv, out_json = root / "x.csv", root / "x.json"
            self.assertEqual(run_cli("export", *common, "--ticker", "1785", "--start-year", "2014", "--end-year", "2014",
                                     "--format", "csv", "--output", str(out_csv), "--include-test-fixtures")["records"], 17)
            run_cli("export", *common, "--ticker", "1785", "--start-year", "2014", "--end-year", "2014",
                    "--format", "json", "--output", str(out_json), "--as-of", "2015-04-01", "--include-test-fixtures")
            header = next(csv.reader(io.StringIO(out_csv.read_text(encoding="utf-8"))))
            self.assertEqual(tuple(header), EXPORT_FIELDS)
            self.assertEqual(json.loads(out_json.read_text(encoding="utf-8"))["record_count"], 17)


class HistoricalAuditE2ETest(unittest.TestCase):
    def test_source_to_point_in_time_export(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            root = Path(directory)
            originals = {year: synthetic_instance(fiscal_year=year) for year in (2013, 2014, 2015, 2016)}
            restated_2014 = synthetic_instance(
                fiscal_year=2014, audit_date="2016-11-11", emphasis_text="如重編後財務報表附註所述",
                overrides={"inventory": 210_000_000, "current_assets": 610_000_000, "total_assets": 1_910_000_000,
                           "equity": 710_000_000},
            )
            served = dict(originals)
            requests: list[httpx.Request] = []

            def mops(request: httpx.Request) -> httpx.Response:
                requests.append(request)
                body = served.get(int(request.url.params["year"]), MOPS_NOT_FOUND_PAGE)
                return httpx.Response(200, content=body)

            repository = HistoricalAuditRepository(str(root / "e2e.sqlite3"))
            archive = RawEvidenceArchive(root / "raw")
            fetcher = OfficialSourceFetcher(transport=httpx.MockTransport(mops), sleep=_no_sleep, min_interval_seconds=0)
            service = HistoricalBackfillService(repository=repository, archive=archive, fetcher=fetcher)

            # 1. Acquisition of the exact range from the (stubbed) official endpoint.
            first = asyncio.run(service.run("1785", 2011, 2016))
            self.assertEqual([y.status for y in first.years],
                             ["filing_not_found", "filing_not_found", "available", "available", "available", "available"])
            self.assertTrue(all(y.publication_verification_status == "unverified" for y in first.years if y.status == "available"))
            self.assertEqual(list_historical_facts(repository, "1785", 2011, 2016, as_of="2030-01-01"), [])

            # 2. The source later serves a restated 2014 report: a new immutable version.
            served[2014] = restated_2014
            second = asyncio.run(service.run("1785", 2011, 2016))
            year_2014 = next(y for y in second.years if y.fiscal_year == 2014)
            self.assertTrue(year_2014.new_version)
            self.assertEqual(year_2014.filing_version_type, "restated")
            self.assertFalse(any(y.new_version for y in second.years if y.fiscal_year != 2014))

            # 3. Research evidence (manifest) verifies availability for both 2014 versions.
            (root / "orig.xml").write_bytes(originals[2014])
            (root / "rest.xml").write_bytes(restated_2014)
            manifest = write_manifest(root, [
                {"period": "2014FY", "source_kind": "mops_xbrl_instance", "local_path": "orig.xml",
                 "filing_version_type": "original", "available_at": "2015-03-31T18:00:00+08:00",
                 "availability_basis": "synthetic fixture timeline", "verification_evidence": ["synthetic evidence"]},
                {"period": "2014FY", "source_kind": "mops_xbrl_instance", "local_path": "rest.xml",
                 "available_at": "2016-11-14T18:00:00+08:00",
                 "availability_basis": "synthetic fixture timeline", "verification_evidence": ["synthetic evidence"]},
            ])
            third = asyncio.run(service.run("1785", 2014, 2014, source_strategy="manifest", manifest_path=manifest))
            self.assertFalse(any(y.new_version for y in third.years))
            with repository.connect() as connection:
                annotations = connection.execute("SELECT field FROM filing_version_annotations ORDER BY field").fetchall()
            self.assertEqual([row["field"] for row in annotations], ["available_at", "available_at", "filing_version_type"])

            # 4. Point-in-time retrieval and export.
            pit = list_historical_facts(repository, "1785", 2014, 2014, metrics=["inventory"],
                                        as_of="2016-06-30", version_policy="latest_available")
            self.assertEqual([(r["filing_version_type"], r["value"]) for r in pit], [("original", 300_000_000.0)])
            records = build_export_records(repository, "1785", 2011, 2016, as_of="2016-12-31", version_policy="latest_available")
            inventory = [r for r in records if r["metric_code"] == "inventory"]
            self.assertEqual([(r["period"], r["filing_version_type"], r["value"]) for r in inventory],
                             [("2014FY", "restated", "210000000")])
            self.assertTrue(all(r["point_in_time_eligible"] for r in records))

            # 5. Archive reprocessing is offline and idempotent.
            before = repository.table_counts()
            requests.clear()
            asyncio.run(service.run("1785", 2011, 2016, source_strategy="archive"))
            self.assertEqual(requests, [])
            after = repository.table_counts()
            for table in ("financial_filing_versions", "versioned_financial_facts", "filing_version_annotations"):
                self.assertEqual(before[table], after[table])
            connection = sqlite3.connect(repository.database_path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM financial_filing_versions").fetchone()[0], 5)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
