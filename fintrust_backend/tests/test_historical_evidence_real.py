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
        # Filing artifacts only (FY2019 onwards MOPS serves inline XBRL); a TPEx summary never becomes a filing version.
        self.assertLessEqual(kinds, {"mops_xbrl_instance", "mops_inline_xbrl", "official_pdf"})
        self.assertIn("official_pdf", kinds)
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
                "SELECT o.match_detail FROM observation_availability o JOIN versioned_financial_facts f ON f.fact_id = o.observation_id "
                "WHERE o.corroborating_kind = 'restatement_comparison'")}
            # Board-approval notices (Phase 2B) never date a restated version.
            board_version_types = {row[0] for row in connection.execute(
                """SELECT v.filing_version_type FROM observation_availability o
                JOIN versioned_financial_facts f ON f.fact_id = o.observation_id
                JOIN financial_filing_versions v ON v.filing_version_id = f.filing_version_id
                WHERE o.corroborating_kind = 'financial_report_disclosure'""")}
        finally:
            connection.close()
        self.assertTrue(details)
        self.assertTrue(all("(post side" in d for d in details), details)
        self.assertNotIn("restated", board_version_types)


@unittest.skipUnless(_has_phase1b_evidence(), "real 1785 evidence archive not present locally")
class RealArchiveMockCloudContract(unittest.TestCase):
    """MOCK cloud tier on the REAL archive: sync a DB copy to in-memory GCS/Firestore and compare reads."""

    def test_real_archive_local_and_cloud_reads_agree(self) -> None:
        from app.services.historical_audit.archive import RawEvidenceArchive
        from app.services.historical_audit.cloud_config import HistoricalCloudConfig
        from app.services.historical_audit.cloud_sync import HistoricalCloudSync
        from app.services.historical_audit.firestore_repository import FirestoreHistoricalResearchRepository
        from app.services.historical_audit.object_storage import GcsObjectStore
        from app.services.historical_audit.research_access import FirestoreResearchBackend, LocalResearchBackend
        from tests.historical_cloud_fakes import FakeFirestoreClient, FakeGcsClient

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            copy = Path(directory) / "copy.sqlite3"
            shutil.copyfile(REAL_DB, copy)
            repository = HistoricalAuditRepository(str(copy))
            config = HistoricalCloudConfig.from_env({
                "HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "isolated-test",
                "HISTORICAL_CLOUD_PROJECT": "fintrust-research-test", "HISTORICAL_CLOUD_BUCKET": "fintrust-historical-test"})
            firestore = FirestoreHistoricalResearchRepository(FakeFirestoreClient())
            sync = HistoricalCloudSync(repository=repository, archive=RawEvidenceArchive(REAL_DB.parent / "raw"),
                                       object_store=GcsObjectStore(FakeGcsClient(), config.bucket, sleep=lambda _: None),
                                       firestore=firestore, config=config)
            report = sync.sync("1785", execute=True)
            self.assertEqual(report.status, "complete", report.errors[:5])
            local, cloud = LocalResearchBackend(repository), FirestoreResearchBackend(firestore)
            for as_of in (None, "2016-05-12", "2016-11-14", "2017-12-31"):
                self.assertEqual(cloud.list_facts("1785", 2011, 2016, as_of=as_of), local.list_facts("1785", 2011, 2016, as_of=as_of))
                self.assertEqual(cloud.list_restatement_comparisons("1785", as_of=as_of),
                                 local.list_restatement_comparisons("1785", as_of=as_of))
                self.assertEqual(cloud.list_summary_observations("1785", as_of=as_of),
                                 local.list_summary_observations("1785", as_of=as_of))
            self.assertEqual(cloud.list_filing_versions("1785", 2011, 2016), local.list_filing_versions("1785", 2011, 2016))
            self.assertEqual(len(local.list_facts("1785", 2011, 2016, as_of="2016-11-14")), 27)
            # Phase 2B: FY2011-2022, including facts dated by board-approval notices (financial_report_disclosure).
            for as_of in (None, "2021-03-05T17:38:19+08:00", "2021-03-05T17:38:20+08:00", "2023-12-31"):
                local_facts = local.list_facts("1785", 2011, 2022, as_of=as_of)
                self.assertEqual(cloud.list_facts("1785", 2011, 2022, as_of=as_of), local_facts, as_of)
            self.assertEqual(cloud.list_filing_versions("1785", 2011, 2022), local.list_filing_versions("1785", 2011, 2022))
            if _has_phase2b_evidence():
                kinds = {r["availability_evidence_kind"] for r in local.list_facts("1785", 2011, 2022, as_of="2023-12-31")}
                self.assertEqual(kinds, {"restatement_disclosure", "financial_report_disclosure"})


CONFERENCE_ROOT = Path(__file__).resolve().parents[1] / "data" / "historical-conference-pdfs"
REAL_2011 = {"178520110325M001.pdf": "b97553ff849f7100931267bab29f7f452a3a9f07a013ddaa9fd1a90af957cea6",
             "178520110325E001.pdf": "c69c9dd3a6df1506b2343ce20e1442ad9aeb97540baaf5e0e18f0318df77ebdb"}


@unittest.skipUnless(_has_phase1b_evidence() and (CONFERENCE_ROOT / "1785" / "2011" / "manifest.json").exists(),
                     "real 1785 evidence / conference archive not present locally")
class RealConferenceAndStrictPackage(unittest.TestCase):
    """REAL tier: the recovered 2011 official conference PDFs and the strict 2016-11-14 package."""

    @classmethod
    def setUpClass(cls) -> None:
        import zipfile

        from app.services.historical_audit.archive import RawEvidenceArchive
        from app.services.historical_audit.research_package import PackageParameters, ResearchPackageBuilder
        from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository

        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        copy = Path(cls._tmp.name) / "copy.sqlite3"
        shutil.copyfile(REAL_DB, copy)
        builder = ResearchPackageBuilder(HistoricalAuditRepository(str(copy)), RawEvidenceArchive(REAL_DB.parent / "raw"),
                                         conference_repository=FileConferencePdfArchiveRepository(CONFERENCE_ROOT),
                                         conference_root=CONFERENCE_ROOT)
        cls.full = Path(cls._tmp.name) / "full.zip"
        cls.strict = Path(cls._tmp.name) / "strict.zip"
        builder.build(PackageParameters("1785", 2011, 2016, include_conference=True), cls.full)
        builder.build(PackageParameters("1785", 2011, 2016, as_of="2016-11-14", version_policy="latest_available",
                                        include_conference=True), cls.strict)
        cls.zipfile = zipfile

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def members(self, path: Path) -> dict[str, bytes]:
        with self.zipfile.ZipFile(path) as archive:
            return {n.split("/", 1)[1]: archive.read(n) for n in archive.namelist()}

    def test_2011_official_conference_pdfs(self) -> None:
        import hashlib
        import json as _json

        manifest = _json.loads((CONFERENCE_ROOT / "1785" / "2011" / "manifest.json").read_text(encoding="utf-8"))
        documents = {d["filename"]: d for d in manifest["documents"]}
        self.assertEqual(set(documents), set(REAL_2011))
        for name, digest in REAL_2011.items():
            self.assertEqual(hashlib.sha256((CONFERENCE_ROOT / "1785" / "2011" / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(documents[name]["page_count"], 47)
            self.assertEqual(documents[name]["conference_dates"], ["100/03/25"])
            self.assertNotEqual(documents[name]["document_type"], "full_earnings_transcript")
        files = self.members(self.full)
        for name, digest in REAL_2011.items():
            self.assertEqual(hashlib.sha256(files[f"raw_evidence/conference_pdfs/1785/2011/{digest}.pdf"]).hexdigest(), digest)

    def test_strict_package_has_no_future_information(self) -> None:
        import csv as _csv
        import io as _io
        from datetime import datetime as _dt

        from app.services.historical_audit.package_verify import verify_package

        files = self.members(self.strict)
        rows = lambda name: list(_csv.DictReader(_io.StringIO(files[name].decode("utf-8"))))
        cutoff = _dt.fromisoformat("2016-11-15T00:00:00+08:00")
        versions = rows("data/filing_versions.csv")
        self.assertEqual({(v["source_kind"], v["filing_version_type"]) for v in versions}, {("official_pdf", "original")})
        self.assertNotIn("2016FY", {v["period"] for v in versions})
        self.assertFalse([n for n in files if n.endswith((".xml", ".xls")) or "listing" in n or n.startswith("conference")])
        self.assertTrue(all(_dt.fromisoformat(e["available_from"]) < cutoff for e in rows("data/publication_timeline.csv")))
        raw = [n for n in files if n.startswith("raw_evidence/")]
        self.assertEqual(len(raw), 11)  # 7 original report PDFs + 4 notices published before the cutoff
        self.assertEqual(len(rows("data/financial_facts.csv")), 27)
        self.assertEqual(len(rows("data/restatement_comparisons.csv")), 158)
        text = b"".join(data for name, data in files.items() if not name.startswith("raw_evidence/")).decode("utf-8", "replace")
        for marker in ("2017-", "106年", "105/12", "2016-12-"):
            self.assertNotIn(marker, text)
        self.assertEqual(verify_package(self.strict)["mode"], "strict_point_in_time")


@unittest.skipUnless(_has_phase1b_evidence(), "real 1785 evidence archive not present locally")
class RealStrictCutoffMatrix(unittest.TestCase):
    """REAL tier: strict packages at the six review cutoffs; expectations come from DB relationships."""

    CUTOFFS = ("2016-05-12", "2016-05-13T00:00:00+08:00", "2016-11-13T21:26:21+08:00", "2016-11-13T21:26:22+08:00",
               "2016-11-14", "2017-12-31")

    @classmethod
    def setUpClass(cls) -> None:
        import csv as _csv
        import io as _io
        import sqlite3
        import zipfile

        from app.services.historical_audit.archive import RawEvidenceArchive
        from app.services.historical_audit.package_verify import verify_package
        from app.services.historical_audit.research_package import PackageParameters, ResearchPackageBuilder

        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        copy = Path(cls._tmp.name) / "copy.sqlite3"
        shutil.copyfile(REAL_DB, copy)
        builder = ResearchPackageBuilder(HistoricalAuditRepository(str(copy)), RawEvidenceArchive(REAL_DB.parent / "raw"))
        cls.packages = {}
        for index, cutoff in enumerate(cls.CUTOFFS):
            path = Path(cls._tmp.name) / f"strict{index}.zip"
            result = builder.build(PackageParameters("1785", 2011, 2016, as_of=cutoff, version_policy="latest_available"), path)
            verified = verify_package(path)
            with zipfile.ZipFile(path) as archive:
                files = {n.split("/", 1)[1]: archive.read(n) for n in archive.namelist()}
            rows = {name: list(_csv.DictReader(_io.StringIO(data.decode("utf-8"))))
                    for name, data in files.items() if name.startswith("data/") and name.endswith(".csv")}
            cls.packages[cutoff] = {"result": result, "verified": verified, "files": files, "rows": rows}
        connection = sqlite3.connect(f"file:{copy.as_posix()}?mode=ro", uri=True)
        try:
            cls.comparison_times = {scope: {t for (t,) in connection.execute(
                "SELECT DISTINCT disclosed_at FROM restatement_comparisons WHERE ticker='1785' AND statement_scope=?", (scope,))}
                for scope in ("individual", "consolidated")}
        finally:
            connection.close()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_every_cutoff_verifies_and_grows_monotonically(self) -> None:
        previous = None
        for cutoff in self.CUTOFFS:
            package = self.packages[cutoff]
            self.assertEqual(package["verified"]["status"], "verified", cutoff)
            counts = package["result"]["counts"]
            if previous:
                self.assertTrue(all(counts[k] >= previous[k] for k in counts), cutoff)
            previous = counts

    def test_pre_revelation_cutoffs_have_no_financial_inputs(self) -> None:
        for cutoff in self.CUTOFFS[:2]:
            rows = self.packages[cutoff]["rows"]
            for name in ("data/financial_facts.csv", "data/filing_versions.csv", "data/historical_summaries.csv",
                         "data/restatement_comparisons.csv", "data/source_inventory.csv"):
                self.assertEqual(rows[name], [], (cutoff, name))
            self.assertFalse([n for n in self.packages[cutoff]["files"] if n.startswith("raw_evidence/")])
        # Date-only TPEx notices of 2016-05-13 become public at the next Taipei midnight, so midnight adds nothing.
        self.assertEqual(self.packages[self.CUTOFFS[0]]["rows"]["data/publication_timeline.csv"],
                         self.packages[self.CUTOFFS[1]]["rows"]["data/publication_timeline.csv"])

    def test_one_second_before_and_at_the_consolidated_notice(self) -> None:
        from datetime import datetime as _dt

        (individual,), (consolidated,) = self.comparison_times["individual"], self.comparison_times["consolidated"]
        self.assertLess(_dt.fromisoformat(individual), _dt.fromisoformat(consolidated))
        before, at = self.packages[self.CUTOFFS[2]]["rows"], self.packages[self.CUTOFFS[3]]["rows"]
        self.assertEqual({r["disclosed_at"] for r in before["data/restatement_comparisons.csv"]}, {individual})
        self.assertEqual({r["disclosed_at"] for r in at["data/restatement_comparisons.csv"]}, {individual, consolidated})
        self.assertEqual(before["data/financial_facts.csv"], [])  # facts are consolidated, dated by the 21:26:22 notice
        self.assertTrue(at["data/financial_facts.csv"])
        self.assertEqual({r["effective_available_at"] for r in at["data/financial_facts.csv"]}, {consolidated})
        for row in before["data/historical_summaries.csv"]:
            self.assertEqual(row["statement_scope"], "individual")

    def test_after_cutoffs_keep_artifacts_withheld_unless_verified_public(self) -> None:
        at_notice = self.packages[self.CUTOFFS[3]]["rows"]["data/financial_facts.csv"]
        self.assertEqual(self.packages["2016-11-14"]["rows"]["data/financial_facts.csv"], at_notice)
        late = self.packages["2017-12-31"]["rows"]
        self.assertIn(("2016FY", "official_pdf"), {(v["period"], v["source_kind"]) for v in late["data/filing_versions.csv"]})
        self.assertNotIn("2016FY", {v["period"] for v in self.packages["2016-11-14"]["rows"]["data/filing_versions.csv"]})
        # The XBRL behind the facts never had verified public availability: identity stays withheld in 2017.
        self.assertEqual({r["artifact_reference_status"] for r in late["data/financial_facts.csv"]}, {"withheld_not_public_at_cutoff"})
        self.assertIn("2016FY", {r["report_period"] for r in late["data/historical_summaries.csv"]})
        self.assertNotIn("2016FY", {r["report_period"] for r in self.packages["2016-11-14"]["rows"]["data/historical_summaries.csv"]})

    def test_no_modern_metadata_in_any_model_facing_file(self) -> None:
        import json as _json

        for cutoff in self.CUTOFFS:
            package = self.packages[cutoff]
            manifest = _json.loads(package["files"]["manifest.json"])
            self.assertIsNone(manifest["generated_at"])
            self.assertNotIn("excluded_by_cutoff", manifest)
            self.assertNotIn("validation/provenance.csv", package["files"])
            text = b"".join(d for n, d in package["files"].items() if not n.startswith("raw_evidence/")
                            and n != "validation/verify_package.py").decode("utf-8", "replace")
            self.assertNotIn("2026-", text)
            self.assertTrue(Path(package["result"]["audit_path"]).exists())

    def test_summary_verification_is_independent_of_producer_flags(self) -> None:
        """F1: every retained summary is re-derived from the included raw notice; mutations fail for a named reason."""
        from app.services.historical_audit.package_verify import PackageVerificationError, verify_package
        from tests.historical_evidence_fixtures import mutate_csv, repack_package

        package = self.packages["2016-11-14"]
        source = Path(package["result"]["output"])
        summaries = package["files"]["data/historical_summaries.csv"]
        retained = package["rows"]["data/historical_summaries.csv"]
        self.assertEqual(len(retained), 11)
        individual = {r["statement_scope"]: r for r in retained}["individual"]["pit_evidence_hash"]
        consolidated = {r["statement_scope"]: r for r in retained}["consolidated"]["pit_evidence_hash"]
        op_income = {"report_period": "2011FY", "observation_role": "current_period", "source_metric_code": "tpex_operating_income"}
        fy2015 = {"report_period": "2015FY", "observation_role": "current_period", "source_metric_code": "tpex_operating_revenue"}
        cases = {
            "side": (op_income, {"pit_evidence_side": "post"}, "pit_evidence_side 'post' but the notice states the value on pre"),
            "value": (op_income, {"value": "1336551", "normalized_value": "1336551000"}, "value 1336551 is not stated"),
            "scope": (op_income, {"statement_scope": "consolidated"}, "statement scope consolidated disagrees with the notice"),
            "period": (op_income, {"report_period": "2010FY", "fiscal_year": "2010", "period": "2010FY"},
                       "value 1336550 is not stated for 2010"),
            "metric": (op_income, {"source_metric_code": "tpex_operating_revenue", "canonical_metric": "revenue"},
                       "value 1336550 is not stated for 2011 revenue"),
            "metric mapping": (op_income, {"canonical_metric": "net_income"}, "has no independent mapping"),
            "unit": (op_income, {"published_unit": "TWD"}, "unit or normalized value disagrees"),
            "framework": (op_income, {"accounting_framework": "TIFRS"}, "accounting framework does not fit"),
            "label": (op_income, {"pit_evidence_label": "營業收入淨額"}, "is not the notice line stating the value"),
            "evidence reference": (op_income, {"pit_evidence_ref": "mops:20161113:212622:3"}, "is not the included notice"),
            "evidence identity": (op_income, {"pit_evidence_ref": "mops:20161113:212622:3", "pit_evidence_hash": consolidated,
                                              "effective_available_at": "2016-11-13T21:26:22+08:00"},
                                  r"statement scope individual disagrees with the notice \(consolidated\)"),
            "restated value in an earlier report": (fy2015, {"value": "61376037", "normalized_value": "61376037000",
                                                             "pit_evidence_side": "post"},
                                                    "a 2015FY report must carry the pre side; the notice states post"),
            "producer flag": (fy2015, {"side_consistency": "inconsistent_side"}, "side_consistency='inconsistent_side'"),
        }
        self.assertNotEqual(individual, consolidated)
        for label, (match, changes, reason) in cases.items():
            with self.subTest(label):
                target = Path(self._tmp.name) / f"mutated-{label.replace(' ', '_')}.zip"
                repack_package(source, target, {"data/historical_summaries.csv": mutate_csv(summaries, match, changes)})
                with self.assertRaisesRegex(PackageVerificationError, reason):
                    verify_package(target)

    def test_comparisons_are_reread_from_the_raw_notices(self) -> None:
        from app.services.historical_audit.package_verify import PackageVerificationError, verify_package
        from tests.historical_evidence_fixtures import mutate_csv, repack_package

        package = self.packages["2016-11-14"]
        data = package["files"]["data/restatement_comparisons.csv"]
        row = {"period": "2011FY", "statement_scope": "individual", "pre_label": "營業淨利"}
        cases = {"pre value": ({"pre_restatement_value": "1336551"}, "pre_restatement_value 1336551 is not what the notice states"),
                 "post value": ({"post_restatement_value": "281539"}, "post_restatement_value 281539 is not what the notice states"),
                 "scope": ({"statement_scope": "consolidated"}, "scope or unit disagrees"),
                 "announcement": ({"announcement_key": "mops:20161113:212531:9"}, "announcement identity")}
        for label, (changes, reason) in cases.items():
            with self.subTest(label):
                target = Path(self._tmp.name) / f"comparison-{label.replace(' ', '_')}.zip"
                repack_package(Path(package["result"]["output"]), target,
                               {"data/restatement_comparisons.csv": mutate_csv(data, row, changes)})
                with self.assertRaisesRegex(PackageVerificationError, reason):
                    verify_package(target)


def _has_phase2a_evidence() -> bool:
    if not _has_phase1b_evidence():
        return False
    import sqlite3

    connection = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
    try:
        return connection.execute("SELECT COUNT(*) FROM financial_filing_versions WHERE fiscal_year = 2019").fetchone()[0] > 0
    finally:
        connection.close()


@unittest.skipUnless(_has_phase2a_evidence(), "real 1785 FY2017-2019 evidence not present locally")
class RealPhase2aFy2017To2019(unittest.TestCase):
    """REAL tier, Phase 2A: FY2017-2019 versions, publication evidence and point-in-time behaviour."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        copy = Path(cls._tmp.name) / "copy.sqlite3"
        shutil.copyfile(REAL_DB, copy)
        cls.repository = HistoricalAuditRepository(str(copy))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def versions(self, year: int) -> list[dict]:
        return [dict(v) for v in self.repository.list_filing_versions("1785", year, year)]

    def test_each_year_has_one_xbrl_with_18_facts_and_no_exponent_text(self) -> None:
        facts = list_historical_facts(self.repository, "1785", 2017, 2019, include_test_fixtures=False)
        for year in (2017, 2018, 2019):
            xbrl = [v for v in self.versions(year) if v["source_kind"].startswith("mops_")]
            self.assertEqual(len(xbrl), 1, year)
            self.assertEqual((xbrl[0]["statement_scope"], xbrl[0]["filing_version_type"], xbrl[0]["availability_status"]),
                             ("consolidated", "unknown_revision", "unverified"))
            self.assertEqual(len([f for f in facts if f["fiscal_year"] == year]), 18)
        self.assertEqual({v["source_kind"] for y in (2017, 2018, 2019) for v in self.versions(y) if v["source_kind"].startswith("mops_")},
                         {"mops_xbrl_instance", "mops_inline_xbrl"})
        self.assertFalse([f for f in facts if "E" in f["value_text"].upper()])
        values = {(f["fiscal_year"], f["metric_code"]): int(f["value_text"]) for f in facts if f["metric_code"] != "eps"}
        for year in (2017, 2018, 2019):  # accounting identities hold on the stored text
            self.assertEqual(values[(year, "revenue")] - values[(year, "cost_of_goods_sold")], values[(year, "gross_profit")])
            self.assertEqual(values[(year, "total_liabilities")] + values[(year, "equity")], values[(year, "total_assets")])

    def test_xbrl_facts_are_never_point_in_time_eligible(self) -> None:
        # No official disclosure dates these values and the XBRL bytes have no verified publication time.
        self.assertEqual(list_historical_facts(self.repository, "1785", 2017, 2019, as_of="2026-10-11"), [])

    def test_fy2019_pdf_publication_boundary(self) -> None:
        def periods(as_of):
            return {(v["period"], v["statement_scope"]) for v in list_filing_versions_as_of(
                self.repository, "1785", as_of=as_of, start_year=2019, end_year=2019)}
        self.assertEqual(periods("2020-02-14T14:58:51+08:00"), set())
        self.assertEqual(periods("2020-02-14T14:58:52+08:00"), {("2019FY", "consolidated")})
        self.assertEqual(periods("2020-02-14T14:59:25+08:00"), {("2019FY", "consolidated"), ("2019FY", "individual")})

    def test_fy2017_fy2018_pdfs_stay_unverified_and_fy2018_correction_is_linked(self) -> None:
        for year in (2017, 2018):
            pdfs = [v for v in self.versions(year) if v["source_kind"] == "official_pdf"]
            self.assertEqual({v["statement_scope"] for v in pdfs}, {"consolidated", "individual"})
            self.assertEqual({v["availability_status"] for v in pdfs}, {"unverified"})  # blank 更(補)正 column
        with self.repository.connect() as connection:
            linked = {row[0] for row in connection.execute(
                """SELECT v.source_kind || ':' || v.statement_scope FROM publication_evidence_links l
                JOIN historical_publication_events e USING (event_id)
                JOIN financial_filing_versions v ON v.filing_version_id = l.target_id
                WHERE e.event_key = 'mops:20190529:141818:1' AND l.link_status = 'unverified_linkage'""")}
        self.assertEqual(linked, {"mops_xbrl_instance:consolidated", "official_pdf:consolidated", "official_pdf:individual"})


def _has_phase2b_evidence() -> bool:
    if not _has_phase1b_evidence():
        return False
    import sqlite3

    connection = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        return "disclosed_financial_values" in tables and connection.execute(
            "SELECT COUNT(*) FROM financial_filing_versions WHERE fiscal_year = 2022").fetchone()[0] > 0
    finally:
        connection.close()


def _typed(value: str):
    return None if value == "" else True if value == "true" else False if value == "false" else value


@unittest.skipUnless(_has_phase2b_evidence(), "real 1785 FY2020-2022 evidence not present locally")
class RealPhase2bFy2020To2022(unittest.TestCase):
    """REAL tier, Phase 2B: FY2020-2022 versions and value-level PIT from annual board-approval notices."""

    NOTICES = {2020: ("mops:20210305:173820:1", "2021-03-05T17:38:20+08:00"),
               2021: ("mops:20220316:175938:2", "2022-03-16T17:59:38+08:00"),
               2022: ("mops:20230302:223839:3", "2023-03-02T22:38:39+08:00")}
    STATED = {"revenue", "gross_profit", "operating_income", "net_income", "eps", "total_assets", "total_liabilities"}

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        copy = Path(cls._tmp.name) / "copy.sqlite3"
        shutil.copyfile(REAL_DB, copy)
        cls.repository = HistoricalAuditRepository(str(copy))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_one_inline_xbrl_per_year_with_exact_identities(self) -> None:
        from decimal import Decimal

        facts = list_historical_facts(self.repository, "1785", 2020, 2022, include_test_fixtures=False)
        for year in (2020, 2021, 2022):
            xbrl = [v for v in self.repository.list_filing_versions("1785", year, year) if v["source_kind"].startswith("mops_")]
            self.assertEqual([(v["source_kind"], v["statement_scope"], v["filing_version_type"], v["availability_status"])
                              for v in xbrl], [("mops_inline_xbrl", "consolidated", "unknown_revision", "unverified")])
            values = {f["metric_code"]: Decimal(f["value_text"]) for f in facts if f["fiscal_year"] == year}
            self.assertEqual(len(values), 18)
            self.assertEqual(values["revenue"] - values["cost_of_goods_sold"], values["gross_profit"])
            self.assertEqual(values["total_liabilities"] + values["equity"], values["total_assets"])
        self.assertFalse([f for f in facts if "E" in f["value_text"].upper()])

    def test_board_notice_dates_exactly_the_stated_metrics(self) -> None:
        from datetime import datetime as _dt, timezone as _tz

        facts = [f for f in list_historical_facts(self.repository, "1785", 2020, 2022) if f["point_in_time_eligible"]]
        self.assertEqual(len(facts), 21)
        for fact in facts:
            key, at = self.NOTICES[fact["fiscal_year"]]
            self.assertIn(fact["metric_code"], self.STATED)
            self.assertEqual((fact["availability_evidence_kind"], fact["availability_evidence_ref"], fact["availability_scope"]),
                             ("financial_report_disclosure", key, "observation"))
            self.assertEqual(fact["effective_available_at"], _dt.fromisoformat(at).astimezone(_tz.utc).isoformat())
            self.assertEqual((fact["available_at"], fact["availability_status"]), (None, "unverified"))  # artifact unchanged
        # The notice states equity attributable to owners of the parent, not total equity: never matched.
        self.assertNotIn("equity", {f["metric_code"] for f in facts})

    def test_exact_cutoff_boundaries(self) -> None:
        def count(as_of):
            return len(list_historical_facts(self.repository, "1785", 2020, 2022, as_of=as_of))
        self.assertEqual(count("2021-03-05T17:38:19+08:00"), 0)
        self.assertEqual(count("2021-03-05T17:38:20+08:00"), 7)
        self.assertEqual(count("2023-03-02T22:38:38+08:00"), 14)
        self.assertEqual(count("2023-03-02T22:38:39+08:00"), 21)
        self.assertEqual(len(list_historical_facts(self.repository, "1785", 2017, 2019, as_of="2026-10-11")), 0)

    def test_pdf_availability_and_corrections(self) -> None:
        def pdfs(year):
            return {v["statement_scope"]: v["availability_status"] for v in self.repository.list_filing_versions("1785", year, year)
                    if v["source_kind"] == "official_pdf"}
        self.assertEqual(pdfs(2020), {"consolidated": "verified", "individual": "verified"})
        self.assertEqual(pdfs(2021), {"consolidated": "verified", "individual": "verified"})
        self.assertEqual(pdfs(2022), {"consolidated": "unverified", "individual": "unverified"})  # blank 更(補)正
        with self.repository.connect() as connection:
            linked = {(row[0], row[1]) for row in connection.execute(
                """SELECT e.event_key, v.period FROM publication_evidence_links l JOIN historical_publication_events e USING (event_id)
                JOIN financial_filing_versions v ON v.filing_version_id = l.target_id
                WHERE e.event_type = 'financial_report_correction' AND v.fiscal_year >= 2017""")}
        self.assertLessEqual({("mops:20210427:145546:1", "2017FY"), ("mops:20230411:171742:3", "2022FY")}, linked)

    def test_strict_verifier_rederives_board_dated_facts(self) -> None:
        import csv as _csv
        import io as _io
        import json as _json
        import zipfile

        from app.services.historical_audit.archive import RawEvidenceArchive
        from app.services.historical_audit.package_verify import PackageVerificationError, verify_package
        from app.services.historical_audit.research_package import PackageParameters, ResearchPackageBuilder
        from tests.historical_evidence_fixtures import mutate_csv, repack_package

        path = Path(self._tmp.name) / "strict2022.zip"
        ResearchPackageBuilder(self.repository, RawEvidenceArchive(REAL_DB.parent / "raw")).build(
            PackageParameters("1785", 2020, 2022, as_of="2023-12-31", version_policy="latest_available"), path)
        self.assertEqual(verify_package(path)["status"], "verified")
        root = "fintrust_historical_research_dataset/"
        with zipfile.ZipFile(path) as archive:
            data = archive.read(root + "data/financial_facts.csv")
            envelope = _json.loads(archive.read(root + "data/financial_facts.json"))
        rows = list(_csv.DictReader(_io.StringIO(data.decode("utf-8"))))
        self.assertEqual(len(rows), 21)
        revenue = {"period": "2020FY", "metric_code": "revenue"}
        other_ref = next(r for r in rows if r["period"] == "2021FY")["availability_evidence_ref"]
        with zipfile.ZipFile(path) as archive:
            included_version = next(_csv.DictReader(_io.StringIO(
                archive.read(root + "data/filing_versions.csv").decode("utf-8"))))["filing_version_id"]
        public = {"artifact_reference_status": "verified_public_artifact", "filing_version_id": included_version}
        cases = {
            "value": ({"value": "26665368000"}, "is not what the notice states"),
            "unit": ({"unit": "TWD/share"}, "disagrees with the notice unit"),
            "metric": ({"metric_code": "cost_of_goods_sold"}, "is not stated by a board-approval notice line"),
            "scope": ({"statement_scope": "individual"}, "statement scope individual disagrees"),
            "period": ({"period": "2019FY", "fiscal_year": "2019"}, "does not report fiscal year 2019"),
            "evidence identity": ({"availability_evidence_ref": other_ref}, "evidence identity/time disagrees"),
            "evidence kind": ({"availability_evidence_kind": "filing_artifact"}, "without a disclosure reference"),
            # A public artifact never exempts a disclosure-dated value from re-derivation (F-2B review).
            "verified artifact, tampered value": ({**public, "value": "26665368000"}, "is not what the notice states"),
            "verified artifact, wrong scope": ({**public, "statement_scope": "individual"}, "statement scope individual disagrees"),
        }
        for label, (changes, reason) in cases.items():
            with self.subTest(label):
                csv_bytes = mutate_csv(data, revenue, changes)
                mutated = list(_csv.DictReader(_io.StringIO(csv_bytes.decode("utf-8"))))
                records = [{k: _typed(v) for k, v in r.items()} for r in mutated]
                payload = {**envelope, "records": records}
                target = repack_package(path, Path(self._tmp.name) / f"board-{label.replace(' ', '_')}.zip",
                                        {"data/financial_facts.csv": csv_bytes,
                                         "data/financial_facts.json": _json.dumps(payload, ensure_ascii=False).encode("utf-8")})
                with self.assertRaisesRegex(PackageVerificationError, reason):
                    verify_package(target)

    def test_coverage_matrix_covers_board_dated_years(self) -> None:
        from app.services.historical_audit.evidence_export import coverage_matrix

        rows = {r["fiscal_year"]: r for r in coverage_matrix(self.repository, "1785", 2011, 2022)}
        for year in (2020, 2021, 2022):
            self.assertEqual(rows[year]["pit_ready_facts"], 7)
            self.assertIn("official financial-report disclosure", rows[year]["pit_ready"])
        self.assertEqual((rows[2019]["pit_ready_facts"], rows[2019]["pit_ready"]), (0, "no"))
