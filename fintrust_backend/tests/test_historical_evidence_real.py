"""Gate F point-in-time scenarios on the REAL archived 1785 evidence (Phase 1B).

Runs only where the isolated local archive exists (it is gitignored); it reads a
temporary copy of the database and never writes to the original.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from app.services.historical_audit.evidence_export import list_restatement_comparisons, list_summary_observations
from app.services.historical_audit.reader import list_filing_versions_as_of, list_historical_facts
from app.services.historical_audit.repository import HistoricalAuditRepository


REAL_DB = Path(__file__).resolve().parents[1] / "data" / "historical_audit" / "historical_audit.sqlite3"


def _has_phase1b_evidence() -> bool:
    if not REAL_DB.exists():
        return False
    import sqlite3

    connection = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name = 'restatement_comparisons'").fetchone()[0] == 1
    finally:
        connection.close()


@unittest.skipUnless(_has_phase1b_evidence(), "real 1785 evidence archive not present locally")
class RealPointInTimeScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        copy = Path(cls._tmp.name) / "copy.sqlite3"
        shutil.copyfile(REAL_DB, copy)
        cls.repository = HistoricalAuditRepository(str(copy))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def facts(self, **kwargs):
        return list_historical_facts(self.repository, "1785", 2011, 2016, **kwargs)

    def test_scenario1_before_restatement_no_restated_values(self) -> None:
        cutoff = "2016-11-13T21:25:30+08:00"
        self.assertEqual(self.facts(as_of=cutoff), [])
        self.assertEqual(list_restatement_comparisons(self.repository, "1785", as_of=cutoff), [])
        self.assertEqual(list_summary_observations(self.repository, "1785", as_of=cutoff), [])
        versions = list_filing_versions_as_of(self.repository, "1785", as_of=cutoff)
        self.assertTrue(versions)
        self.assertEqual({v["filing_version_type"] for v in versions}, {"original"})
        self.assertEqual({v["source_kind"] for v in versions}, {"official_pdf"})

    def test_scenario2_during_restatement_disclosure(self) -> None:
        individual = list_restatement_comparisons(self.repository, "1785", as_of="2016-11-13T21:25:31+08:00")
        self.assertTrue(individual)
        self.assertEqual({r["statement_scope"] for r in individual}, {"individual"})
        self.assertEqual(self.facts(as_of="2016-11-13T21:25:31+08:00"), [])  # XBRL facts are consolidated
        at = self.facts(as_of="2016-11-13T21:26:22+08:00")
        self.assertEqual({(f["period"], f["filing_version_type"]) for f in at},
                         {("2013FY", "restated"), ("2014FY", "restated"), ("2015FY", "restated")})
        self.assertTrue(all(f["availability_scope"] == "observation" for f in at))
        self.assertNotIn("inventory", {f["metric_code"] for f in at})  # not disclosed in the notice
        restated_versions = [v for v in self.repository.list_filing_versions("1785") if v["filing_version_type"] == "restated"]
        self.assertTrue(all(v["available_at"] is None for v in restated_versions))

    def test_scenario3_after_restatement(self) -> None:
        after = {(f["period"], f["metric_code"]): f for f in self.facts(as_of="2017-12-31", version_policy="latest_available")}
        self.assertEqual(after[("2014FY", "net_income")]["value_text"], "10466000")
        self.assertEqual(len(after), 27)
        versions = list_filing_versions_as_of(self.repository, "1785", as_of="2017-12-31", start_year=2014, end_year=2014)
        self.assertEqual({v["filing_version_type"] for v in versions}, {"original"})  # original preserved

    def test_scenario4_fy2016_not_visible_before_publication(self) -> None:
        def fy2016(as_of):
            return list_filing_versions_as_of(self.repository, "1785", as_of=as_of, start_year=2016, end_year=2016)

        self.assertEqual(fy2016("2017-03-22T14:20:14+08:00"), [])
        self.assertEqual([v["source_kind"] for v in fy2016("2017-03-22T14:20:15+08:00")], ["official_pdf"])
        self.assertNotIn("2016FY", {f["period"] for f in self.facts(as_of="2030-01-01")})

    def test_scenario5_summary_never_promoted_to_filing(self) -> None:
        kinds = {v["source_kind"] for v in self.repository.list_filing_versions("1785")}
        self.assertEqual(kinds, {"mops_xbrl_instance", "official_pdf"})
        summary = list_summary_observations(self.repository, "1785")
        self.assertEqual({r["completeness"] for r in summary}, {"summary_values_only"})
        self.assertEqual({r["accounting_framework"] for r in summary if r["report_period"] in {"2011FY", "2012FY"}}, {"TW_GAAP"})

    def test_scenario6_conflicting_values_are_all_preserved(self) -> None:
        summary = {(r["report_period"], r["observation_role"]): r["value"] for r in list_summary_observations(self.repository, "1785")
                   if r["fiscal_year"] == 2014 and r["source_metric_code"] == "tpex_net_income_after_tax"}
        self.assertEqual(summary, {("2014FY", "current_period"): "451927", ("2015FY", "prior_year_comparative"): "396380"})
        comparison = next(r for r in list_restatement_comparisons(self.repository, "1785")
                          if r["fiscal_year"] == 2014 and r["canonical_metric"] == "net_income" and r["statement_scope"] == "consolidated")
        self.assertEqual((comparison["pre_restatement_value"], comparison["post_restatement_value"]), ("416617", "10466"))
        self.assertEqual(self.facts(as_of="2016-06-30"), [])  # no newer value served for an earlier date


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(_has_phase1b_evidence(), "real 1785 evidence archive not present locally")
class RealResearchCutoffs(unittest.TestCase):
    """Pre-event detection vs restatement analysis vs retrospective analysis (real evidence)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        copy = Path(cls._tmp.name) / "copy.sqlite3"
        shutil.copyfile(REAL_DB, copy)
        cls.repository = HistoricalAuditRepository(str(copy))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_pre_event_cutoff_before_may_2016_revelation_has_no_verified_data(self) -> None:
        # TPEx 10502004811 (2016-05-13): misstatement admitted. Nothing in the archive is
        # verifiably public before that, so a strict pre-event backtest has no inputs yet.
        for cutoff in ("2016-05-12", "2016-05-13T00:00:00+08:00"):
            self.assertEqual(list_historical_facts(self.repository, "1785", 2011, 2016, as_of=cutoff), [])
            self.assertEqual(list_restatement_comparisons(self.repository, "1785", as_of=cutoff), [])
            self.assertEqual(list_summary_observations(self.repository, "1785", as_of=cutoff), [])
            self.assertEqual(list_filing_versions_as_of(self.repository, "1785", as_of=cutoff), [])

    def test_restatement_cutoff_and_retrospective_cutoff(self) -> None:
        restatement = list_historical_facts(self.repository, "1785", 2011, 2016, as_of="2016-11-14")
        self.assertEqual(len(restatement), 27)
        self.assertTrue(all(f["availability_evidence_kind"] == "restatement_disclosure" for f in restatement))
        retrospective = list_historical_facts(self.repository, "1785", 2011, 2016, as_of="2017-12-31")
        self.assertEqual({f["fact_id"] for f in retrospective}, {f["fact_id"] for f in restatement})
        self.assertEqual(len(list_filing_versions_as_of(self.repository, "1785", as_of="2017-12-31")), 8)

    def test_restated_facts_are_dated_by_post_restatement_values_only(self) -> None:
        import sqlite3

        connection = sqlite3.connect(self.repository.database_path)
        try:
            details = {row[0] for row in connection.execute(
                "SELECT o.match_detail FROM observation_availability o JOIN versioned_financial_facts f ON f.fact_id = o.observation_id")}
        finally:
            connection.close()
        self.assertTrue(details)
        self.assertTrue(all("(post side" in d for d in details), details)
