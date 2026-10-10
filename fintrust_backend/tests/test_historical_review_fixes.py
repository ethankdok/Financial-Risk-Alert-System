"""Regression tests for the pre-Phase 1C independent review (H1–H4, M2, export consistency).

SYNTHETIC fixtures only; the real-archive cutoff checks live in test_historical_evidence_real.py.
"""

from __future__ import annotations

import csv
import io
import json
import unittest

from app.services.historical_audit.archive import RawEvidenceArchive
from app.services.historical_audit.evidence_export import (
    list_restatement_comparisons,
    list_summary_observations,
)
from app.services.historical_audit.evidence_import import EvidencePlanError, HistoricalEvidenceService, load_plan
from app.services.historical_audit.export import build_export_records, export_historical_facts
from app.services.historical_audit.quality import quality_report
from app.services.historical_audit.reader import list_filing_versions_as_of, list_historical_facts
from tests.test_historical_evidence import PLAN, EvidenceTestCase


# Public revelation of the misstatement (TPEx 10502004811 / MOPS 2016-05-13 press conference).
PRE_EVENT_CUTOFF = "2016-05-12"
RESTATEMENT_CUTOFF = "2016-11-14"
RETROSPECTIVE_CUTOFF = "2017-12-31"


class CorroborationSemanticsTests(EvidenceTestCase):  # H1
    def setUp(self) -> None:
        super().setUp()
        self.run_all()

    def eligible(self) -> dict[str, dict]:
        return {f["metric_code"]: f for f in list_historical_facts(self.repository, "1785", 2013, 2013)
                if f["point_in_time_eligible"]}

    def test_restated_fact_is_dated_only_by_restated_values(self) -> None:
        self.assertIn("net_income", self.eligible())
        with self.repository.connect() as connection:
            # Make the restated XBRL value (30,000k) appear only in the *pre* column.
            connection.execute(
                "UPDATE restatement_comparisons SET pre_value_text = '30000', post_value_text = '31000' "
                "WHERE fiscal_year = 2013 AND canonical_metric = 'net_income'")
        report = HistoricalEvidenceService(repository=self.repository, archive=self.archive).import_evidence(
            load_plan("1785", self.plan_path))
        self.assertEqual(report.counts.get("corroborations_removed"), 1)
        self.assertNotIn("net_income", self.eligible())

    def test_match_detail_names_the_side_actually_used(self) -> None:
        with self.repository.connect() as connection:
            details = {row[0] for row in connection.execute(
                "SELECT match_detail FROM observation_availability WHERE observation_kind = 'versioned_fact'")}
        self.assertTrue(details)
        self.assertTrue(all("(post side" in detail for detail in details), details)

    def test_rebuild_is_idempotent(self) -> None:
        report = HistoricalEvidenceService(repository=self.repository, archive=self.archive).import_evidence(
            load_plan("1785", self.plan_path))
        self.assertEqual((report.counts.get("corroborations_added"), report.counts.get("corroborations_removed")), (0, 0))


class ComparisonVerificationTests(EvidenceTestCase):  # H2
    def test_comparisons_require_a_verified_claim(self) -> None:
        plan = json.loads(json.dumps(PLAN))
        detail = next(s for s in plan["sources"] if s.get("comparison_scope"))
        detail["events"][0]["quote"] = "這段文字不在公告中"
        self.plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        _, report = self.run_all()
        self.assertTrue(any("no verified claim" in error for error in report.errors), report.errors)
        self.assertEqual(self.table("restatement_comparisons"), [])
        self.assertEqual(list_historical_facts(self.repository, "1785", 2013, 2013, as_of="2030-01-01"), [])


class AvailabilityEvidenceIdentityTests(EvidenceTestCase):  # H3 + export consistency
    def setUp(self) -> None:
        super().setUp()
        self.run_all()

    def test_eligible_fact_names_the_disclosure_not_the_filing(self) -> None:
        fact = next(f for f in list_historical_facts(self.repository, "1785", 2013, 2013) if f["metric_code"] == "total_assets")
        self.assertEqual(fact["availability_scope"], "observation")
        self.assertEqual(fact["availability_evidence_kind"], "restatement_disclosure")
        self.assertEqual(fact["availability_evidence_ref"], "mops:20161113:212622:3")
        self.assertTrue(fact["availability_evidence_url"].startswith("https://mopsov.twse.com.tw/"))
        self.assertNotEqual(fact["availability_evidence_hash"], fact["content_hash"])
        self.assertIsNone(fact["available_at"])  # the XBRL artifact itself stays undated
        inventory = next(f for f in list_historical_facts(self.repository, "1785", 2013, 2013) if f["metric_code"] == "inventory")
        self.assertIsNone(inventory["availability_evidence_kind"])

    def test_reader_cli_csv_json_and_quality_agree(self) -> None:
        reader = {f["fact_id"] for f in list_historical_facts(self.repository, "1785", 2013, 2014, include_test_fixtures=False)
                  if f["point_in_time_eligible"]}
        csv_path, json_path = self.root / "f.csv", self.root / "f.json"
        export_historical_facts(self.repository, "1785", 2013, 2014, output_path=csv_path)
        export_historical_facts(self.repository, "1785", 2013, 2014, output_path=json_path, output_format="json")
        csv_rows = list(csv.DictReader(io.StringIO(csv_path.read_text(encoding="utf-8"))))
        json_rows = json.loads(json_path.read_text(encoding="utf-8"))["records"]
        self.assertEqual(sum(r["point_in_time_eligible"] == "true" for r in csv_rows), len(reader))
        self.assertEqual(sum(r["point_in_time_eligible"] for r in json_rows), len(reader))
        report = quality_report(self.repository, self.archive, "1785", 2013, 2014)
        self.assertEqual(report["point_in_time_eligible_facts"], len(reader))
        self.assertEqual(report["artifact_level_verified_versions"], 1)  # only the uncorrected original PDF
        as_of_rows = build_export_records(self.repository, "1785", 2013, 2014, as_of="2016-12-31")
        self.assertEqual(len(as_of_rows), len(reader))


class ResearchCutoffTests(EvidenceTestCase):  # H4
    def setUp(self) -> None:
        super().setUp()
        self.run_all()

    def test_pre_event_cutoff_has_no_verified_evidence(self) -> None:
        self.assertEqual(list_historical_facts(self.repository, "1785", 2011, 2016, as_of=PRE_EVENT_CUTOFF), [])
        self.assertEqual(list_restatement_comparisons(self.repository, "1785", as_of=PRE_EVENT_CUTOFF), [])
        self.assertEqual(list_summary_observations(self.repository, "1785", as_of=PRE_EVENT_CUTOFF), [])
        self.assertEqual(list_filing_versions_as_of(self.repository, "1785", as_of=PRE_EVENT_CUTOFF), [])

    def test_restatement_and_retrospective_cutoffs(self) -> None:
        restatement = list_historical_facts(self.repository, "1785", 2011, 2016, as_of=RESTATEMENT_CUTOFF)
        self.assertTrue(restatement)
        self.assertEqual({f["filing_version_type"] for f in restatement}, {"restated"})
        retrospective = list_historical_facts(self.repository, "1785", 2011, 2016, as_of=RETROSPECTIVE_CUTOFF)
        self.assertEqual({f["fact_id"] for f in retrospective}, {f["fact_id"] for f in restatement})


class PathSafetyTests(EvidenceTestCase):  # M2
    def test_archive_store_rejects_escaping_paths(self) -> None:
        archive = RawEvidenceArchive(self.root / "safe")
        for period in ("../outside", "evidence/../../x", "C:/x", "a\\b"):
            with self.assertRaises(ValueError, msg=period):
                archive.store(ticker="1785", period=period, content=b"x", detected_format=None, retrieval={})
        with self.assertRaises(ValueError):
            archive.store(ticker="..", period="2013FY", content=b"x", detected_format=None, retrieval={})

    def test_plan_rejects_unsafe_source_keys(self) -> None:
        for key in ("../escape", "a/b", "", "a..b"):
            bad = dict(PLAN, sources=[dict(PLAN["sources"][0], source_key=key)])
            self.plan_path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(EvidencePlanError, msg=key):
                load_plan("1785", self.plan_path)


if __name__ == "__main__":
    unittest.main()
