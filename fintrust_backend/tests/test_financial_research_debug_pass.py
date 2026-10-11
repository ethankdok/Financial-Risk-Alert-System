"""Consolidated debug pass (independent review findings P1-F01, P1-F02, P2-F03, P2-F04 and hardening).

UNIT / MOCK tiers always run; the REAL tier reproduces the reviewer cases on the approved local archive and is
skipped when it is absent. Mock Firestore results are not emulator or live-cloud evidence.
"""

from __future__ import annotations

import copy
from decimal import Decimal
import tempfile
import unittest
from pathlib import Path

import tests.test_financial_research_units as units  # module import: avoids re-collecting its tests
from app.services.financial_research.modes import build_context
from app.services.financial_research.pdf_evidence import EXTRACTOR_VERSION, ArchivePdfEvidenceProvider, identity_checks
from app.services.financial_research.result_store import (
    FirestoreResearchResultStore,
    SqliteResearchResultStore,
    build_run,
)
from app.services.financial_research.result_sync import build_cloud_result_store, result_prefix
from app.services.financial_research.source_reconciliation import (
    BOARD_NOTICE_KIND,
    compare_board_notices,
    compare_restatement_post_side,
    consistency,
    freeze_dependencies,
    pdf_check,
    reconcile,
)
from app.services.historical_audit.cloud_config import CloudSafetyError, HistoricalCloudConfig
from tests.historical_cloud_fakes import FakeFirestoreClient
from tests.test_financial_research_real import HAS_REAL, MutatingBackend, service as real_service

RECON = build_context("CURRENT_EVIDENCE_RECONCILIATION")


def summary(value: str) -> dict:
    return {"period": "2025FY", "fiscal_year": 2025, "report_period": "2025FY", "observation_role": "current_period",
            "statement_scope": "consolidated", "statement_scope_basis": "equals consolidated XBRL revenue",
            "accounting_framework": "TIFRS", "source_label": "營業收入", "source_metric_code": "rev",
            "canonical_metric": "revenue", "mapping_status": "mapped", "normalized_value": value, "normalized_unit": "TWD",
            "content_hash": "e" * 64, "source_url": "https://www.tpex.org.tw/storage/statistic/financial/O_2025Q4.xls",
            "retrieved_at": "2026-10-10T00:00:00+00:00"}


class SummaryBackend:
    def __init__(self, rows):
        self.rows = rows

    def list_summary_observations(self, ticker):
        return copy.deepcopy(self.rows)


class FakePdfProvider:
    def __init__(self, evidence):
        self.evidence = evidence

    def statement_evidence(self, ticker, fiscal_year, *, xbrl_version_type):
        return copy.deepcopy(self.evidence)


def pdf_evidence(*, total_assets="34434450", unit="TWD_thousand", roc_year=114, sha="f" * 64):
    evidence = {"fiscal_year": 2025, "status": "extracted", "extractor": "pypdf test", "extractor_version": EXTRACTOR_VERSION,
                "pdf_page_index": 8, "printed_page_label": "8", "unit": unit, "statement_title": "合併資產負債表",
                "statement_scope": "consolidated", "reporting_roc_year": roc_year, "comparative_roc_year": roc_year - 1,
                "totals": {"total_assets": {"account_code": "1XXX", "label": "資產總計", "value_thousand_twd": total_assets,
                                            "line": f"1XXX 資產總計 {total_assets}"}},
                "filing_version_id": "hfv1_pdf", "filing_version_type": "unknown_revision", "selection_basis": "test",
                "pdf_sha256": sha, "content_sha256_verified": True, "source_url": None,
                "artifact_available_at": "2026-03-26T05:50:14+00:00", "artifact_availability_status": "verified"}
    evidence["checks"] = identity_checks(evidence, 2025)
    return evidence


def recon_snapshot(*, summaries=(), pdf=None, notice_value="34436171000"):
    notice = units.ReconciliationTests().notice("total_assets", notice_value)
    snap = units.snapshot([units.fact(2025, "total_assets", "34434450000")], context=RECON, start=2025, end=2025,
                          disclosed=[notice])
    return freeze_dependencies(snap, SummaryBackend(list(summaries)), FakePdfProvider(pdf) if pdf else None)


def run_of(snap, kind="source_reconciliation"):
    return build_run(result_kind=kind, method_version="m", method_ids=["m"], approval_status="DRAFT",
                     snapshot=snap.describe(), parameters={}, output=reconcile(snap))


class P1F01FrozenDependencyTests(unittest.TestCase):
    def test_reviewer_case_summary_change_alters_digest_and_run_id(self) -> None:
        first, second = recon_snapshot(summaries=[summary("100")]), recon_snapshot(summaries=[summary("200")])
        self.assertNotEqual(first.input_digest, second.input_digest)
        a, b = run_of(first), run_of(second)
        self.assertNotEqual(a["run_id"], b["run_id"])
        again = run_of(recon_snapshot(summaries=[summary("100")]))
        self.assertEqual((again["run_id"], again["output_digest"]), (a["run_id"], a["output_digest"]))
        self.assertNotIn("retrieved_at", first.summary_observations[0])  # no retrieval metadata in frozen inputs
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:  # previously: integrity conflict
            sqlite_store = SqliteResearchResultStore(Path(directory) / "r.sqlite3")
            firestore_store = FirestoreResearchResultStore(FakeFirestoreClient())
            for run in (a, b, again):
                sqlite_store.record_run(run)
                firestore_store.record_run(run)
            strip = lambda r: {k: v for k, v in r.items() if k != "created_at"}  # noqa: E731
            for run in (a, b):
                self.assertEqual(strip(sqlite_store.get_run(run["run_id"])), strip(firestore_store.get_run(run["run_id"])))

    def test_pdf_evidence_changes_alter_digest_and_unavailable_is_explicit(self) -> None:
        base = recon_snapshot(pdf=pdf_evidence())
        for changed in (pdf_evidence(total_assets="34434451"), pdf_evidence(sha="0" * 64), pdf_evidence(unit="unverified")):
            self.assertNotEqual(recon_snapshot(pdf=changed).input_digest, base.input_digest)
        self.assertEqual(recon_snapshot(pdf=pdf_evidence()).input_digest, base.input_digest)
        missing = recon_snapshot(pdf=None)
        self.assertEqual(missing.pdf_evidence[0]["status"], "unavailable")
        self.assertEqual(missing.pdf_evidence[0]["reason"], "pdf_evidence_not_available_in_this_deployment")
        self.assertNotEqual(missing.input_digest, base.input_digest)
        audited = reconcile(missing)["discrepancies"][0]["audited_pdf"]
        self.assertEqual(audited["status"], "unavailable")
        self.assertTrue(all(c["status"] == "not_comparable" for c in audited["checks"]))
        self.assertEqual(base.dependency_versions["pdf_extractor"], EXTRACTOR_VERSION)
        self.assertIn("pdf_evidence", base.describe()["dependency_digests"])

    def test_pdf_evidence_is_frozen_only_for_mismatch_years(self) -> None:
        matching = recon_snapshot(pdf=pdf_evidence(), notice_value="34434450000")
        self.assertEqual(matching.pdf_evidence, [])


class P1F02FailClosedCompatibilityTests(unittest.TestCase):
    def comparison(self, **overrides):
        row = units.comparison(2013, "cost_of_goods_sold", "營業成本", "-32256578", "-33223945", "-967367", sign=-1)
        row.update(overrides)
        return row

    def restated_fact(self, **overrides):
        fact = units.fact(2013, "cost_of_goods_sold", "33223945000", vtype="restated")
        fact.update(overrides)
        return fact

    def outcome(self, fact, comparison):
        rows = compare_restatement_post_side(units.snapshot([fact], context=RECON, start=2013, end=2013,
                                                            comparisons=[comparison]))
        return rows[0]["outcome"], rows[0]["reasons"]

    def test_reviewer_case_wrong_framework_is_not_a_match(self) -> None:
        self.assertEqual(self.outcome(self.restated_fact(), self.comparison()), ("match", []))
        outcome, reasons = self.outcome(self.restated_fact(accounting_framework="WRONG_FRAMEWORK"), self.comparison())
        self.assertEqual(outcome, "not_comparable")
        self.assertIn("framework_mismatch", reasons)

    def test_every_uncertainty_is_not_comparable(self) -> None:
        cases = {
            "filed_fact_framework_unknown": (self.restated_fact(accounting_framework="unknown"), self.comparison()),
            "framework_inconsistent_with_fiscal_year_regime": (
                self.restated_fact(accounting_framework="TW_GAAP"), self.comparison(accounting_framework="TW_GAAP")),
            "filing_version_not_restated": (self.restated_fact(filing_version_type="unknown_revision"), self.comparison()),
            "sign_factor_invalid": (self.restated_fact(), self.comparison(sign_factor=2)),
            "post_side_value_missing": (self.restated_fact(), self.comparison(post_restatement_value=None)),
            "post_side_label_missing": (self.restated_fact(), self.comparison(post_label=None)),
            "notice_unit_not_convertible": (self.restated_fact(), self.comparison(published_unit="USD_thousand")),
            "unit_mismatch": (self.restated_fact(unit="TWD_thousand"), self.comparison()),
            "notice_availability_unverified": (self.restated_fact(), self.comparison(availability_status="unverified")),
        }
        for reason, (fact, comparison) in cases.items():
            outcome, reasons = self.outcome(fact, comparison)
            self.assertEqual(outcome, "not_comparable", reason)
            self.assertIn(reason, reasons)
        rows = compare_restatement_post_side(units.snapshot([], context=RECON, comparisons=[self.comparison()]))
        self.assertEqual((rows[0]["outcome"], rows[0]["reasons"]), ("not_comparable", ["no_filed_fact_same_period_scope_metric"]))

    def test_board_notice_version_kind_and_availability_fail_closed(self) -> None:
        notice = units.ReconciliationTests().notice("total_assets", "34434450000")
        base = units.fact(2025, "total_assets", "34434450000")
        variants = {
            "match": (base, notice),
            "filed_version_restated_vs_original_approval_notice": (units.fact(2025, "total_assets", "34434450000",
                                                                             vtype="restated"), notice),
            "notice_availability_unverified": (base, {**notice, "availability_status": "unverified"}),
            "notice_kind_not_annual_board_approval": (base, {**notice, "disclosure_kind": "interim"}),
            "framework_mismatch": (units.fact(2025, "total_assets", "34434450000", framework="IFRS_OTHER"), notice),
        }
        for expected, (fact, value) in variants.items():
            row = compare_board_notices(units.snapshot([fact], context=RECON, start=2025, end=2025, disclosed=[value]))[0]
            if expected == "match":
                self.assertEqual((row["outcome"], value["disclosure_kind"]), ("match", BOARD_NOTICE_KIND))
            else:
                self.assertEqual(row["outcome"], "not_comparable", expected)
                self.assertIn(expected, row["reasons"])


class P2F03PdfIdentityTests(unittest.TestCase):
    def finding_row(self, board="100000", filed="100000"):
        return {"metric": "total_assets", "source_a": {"value_normalized": board}, "source_b": {"value_twd": filed}}

    def test_reviewer_case_unverified_unit_never_claims_equality(self) -> None:
        evidence = pdf_evidence(total_assets="100", unit="unverified")
        result = pdf_check([self.finding_row()], evidence)
        check = result["checks"][0]
        self.assertEqual(check["status"], "not_comparable")
        self.assertIsNone(check["equals_filed_xbrl"])
        self.assertIsNone(check["equals_board_notice"])
        self.assertIn("unit:unit_unverified", check["reasons"])

    def test_fiscal_year_and_scope_must_be_verified(self) -> None:
        wrong_year = pdf_check([self.finding_row()], pdf_evidence(total_assets="100", roc_year=113))
        self.assertIn("fiscal_year:fiscal_year_mismatch", wrong_year["checks"][0]["reasons"])
        verified = pdf_check([self.finding_row()], pdf_evidence(total_assets="100"))
        self.assertEqual((verified["checks"][0]["status"], verified["checks"][0]["equals_filed_xbrl"]), ("compared", True))

    def test_provider_selects_by_exact_version_identity_not_sort_order(self) -> None:
        def version(identifier, kind):
            return {"filing_version_id": identifier, "filing_version_type": kind, "source_kind": "official_pdf",
                    "statement_scope": "consolidated", "fiscal_year": 2013, "period": "2013FY",
                    "raw_storage_path": f"{identifier}.pdf", "content_hash": "0" * 64, "source_url": None,
                    "available_at": None, "availability_status": "unverified"}

        class Repository:
            def __init__(self, versions):
                self.versions = versions

            def list_filing_versions(self, ticker, start, end):
                return self.versions

        class Archive:
            def __init__(self):
                self.read_paths = []

            def read(self, path):
                self.read_paths.append(path)
                raise RuntimeError("unreadable in test")

        archive = Archive()
        provider = ArchivePdfEvidenceProvider(Repository([version("hfv1_a_original", "original"),
                                                          version("hfv1_b_restated", "restated")]), archive)
        evidence = provider.statement_evidence("1785", 2013, xbrl_version_type="restated")
        self.assertEqual(archive.read_paths, ["hfv1_b_restated.pdf"])  # not the lexicographically first version
        self.assertEqual((evidence["status"], evidence["filing_version_id"]), ("unavailable", "hfv1_b_restated"))
        ambiguous = ArchivePdfEvidenceProvider(Repository([version("hfv1_x", "restated"), version("hfv1_y", "restated")]),
                                               Archive()).statement_evidence("1785", 2013, xbrl_version_type="restated")
        self.assertEqual(ambiguous["reason"], "ambiguous_pdf_versions")
        none = ArchivePdfEvidenceProvider(Repository([version("hfv1_x", "original")]), Archive()).statement_evidence(
            "1785", 2013, xbrl_version_type="restated")
        self.assertEqual(none["reason"], "no_pdf_version_matching_xbrl_version_type")
        empty = ArchivePdfEvidenceProvider(Repository([]), Archive()).statement_evidence("1785", 2013, xbrl_version_type="x")
        self.assertEqual(empty["reason"], "no_consolidated_annual_pdf_version")


class P2F04NamespaceTests(unittest.TestCase):
    def config(self, prefix, environment="isolated-test"):
        env = {"HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": environment,
               "HISTORICAL_CLOUD_PROJECT": "fintrust-research-test", "HISTORICAL_CLOUD_BUCKET": "fintrust-research-test-bucket",
               "GOOGLE_CLOUD_PROJECT": "fintrust-alert-ccu", "HISTORICAL_CLOUD_COLLECTION_PREFIX": prefix}
        if environment == "emulator":
            env["FIRESTORE_EMULATOR_HOST"] = "127.0.0.1:8085"
        return HistoricalCloudConfig.from_env(env)

    def test_reviewer_case_prefix_is_derived_from_config(self) -> None:
        store = build_cloud_result_store(self.config("historical_research_staging_abc"), client=FakeFirestoreClient())
        self.assertEqual(store.prefix, "historical_research_staging_abc_results")
        self.assertEqual(result_prefix(self.config("historical_research")), "historical_research_results")

    def test_two_isolated_namespaces_never_share_results(self) -> None:
        client = FakeFirestoreClient()
        first = build_cloud_result_store(self.config("historical_research_ns_a"), client=client)
        second = build_cloud_result_store(self.config("historical_research_ns_b"), client=client)
        self.assertNotEqual(first.prefix, second.prefix)
        run = run_of(recon_snapshot())
        first.record_run(run)
        self.assertIsNotNone(first.get_run(run["run_id"]))
        self.assertIsNone(second.get_run(run["run_id"]))
        self.assertTrue(all(name.startswith("historical_research_ns_a_results_") for name in client.data))

    def test_production_and_invalid_namespaces_are_refused(self) -> None:
        with self.assertRaises(CloudSafetyError):
            HistoricalCloudConfig.from_env({"HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "production",
                                            "HISTORICAL_CLOUD_PROJECT": "fintrust-alert-ccu", "HISTORICAL_CLOUD_BUCKET": "b-x"})

        class Production:
            environment, collection_prefix = "production", "historical_research"

        with self.assertRaises(PermissionError):
            build_cloud_result_store(Production(), client=FakeFirestoreClient())
        for bad in ("companies_results", "historical_research_results_e1", "historical_research_x_results_extra"):
            with self.assertRaises(ValueError):
                FirestoreResearchResultStore(FakeFirestoreClient(), prefix=bad)


class ConsistencyStateTests(unittest.TestCase):
    def test_all_not_comparable_is_inconclusive_never_consistent(self) -> None:
        self.assertEqual(consistency({"x": {"match": 0, "mismatch_unresolved": 0, "not_comparable": 5}}),
                         "INCONCLUSIVE_NOT_COMPARABLE")
        self.assertEqual(consistency({}), "INCONCLUSIVE_NOT_COMPARABLE")
        self.assertEqual(consistency({"x": {"match": 1, "mismatch_unresolved": 0, "not_comparable": 5}}), "CONSISTENT")
        self.assertEqual(consistency({"x": {"match": 9, "mismatch_unresolved": 1, "not_comparable": 0}}), "INCONSISTENT")
        result = reconcile(freeze_dependencies(units.snapshot([], context=RECON, start=2025, end=2025,
                                                              disclosed=[units.ReconciliationTests().notice(None, "1000")]),
                                               SummaryBackend([]), None))
        self.assertEqual(result["consistency"], "INCONCLUSIVE_NOT_COMPARABLE")


@unittest.skipUnless(HAS_REAL, "approved local 1785 archive not present")
class RealDebugPassTests(unittest.TestCase):
    def test_summary_and_pdf_changes_alter_real_run_ids_for_both_kinds(self) -> None:
        base = real_service()

        def bump(rows):
            rows = copy.deepcopy(rows)
            used = next(r for r in rows if r["observation_role"] == "current_period" and r.get("canonical_metric"))
            used["normalized_value"] = str(Decimal(used["normalized_value"]) + 100)  # a row the reconciliation uses
            return rows

        class SummaryMutation(MutatingBackend):
            def list_summary_observations(self, ticker, **kwargs):
                return bump(self.inner.list_summary_observations(ticker, **kwargs))

        from app.services.financial_research.service import ResearchService

        mutated = ResearchService(backend=SummaryMutation(base.backend), repository=base.repository,
                                  conference_repository=None, pdf_provider=base.pdf_provider)
        for kind in ("source_reconciliation", "financial_signals"):
            original, again = base.build_run(kind, "1785", RECON), real_service().build_run(kind, "1785", RECON)
            changed = mutated.build_run(kind, "1785", RECON)
            self.assertEqual((original["run_id"], original["output_digest"]), (again["run_id"], again["output_digest"]), kind)
            self.assertNotEqual(original["input_digest"], changed["input_digest"], kind)
            self.assertNotEqual(original["run_id"], changed["run_id"], kind)
        no_pdf = ResearchService(backend=base.backend, repository=base.repository, conference_repository=None, pdf_provider=None)
        unavailable = no_pdf.build_run("source_reconciliation", "1785", RECON)
        self.assertNotEqual(unavailable["run_id"], base.build_run("source_reconciliation", "1785", RECON)["run_id"])
        self.assertEqual(unavailable["output"]["discrepancies"][0]["audited_pdf"]["status"], "unavailable")

    def test_real_baselines_preserved_after_fail_closed_changes(self) -> None:
        result = real_service().discrepancies("1785", RECON)
        self.assertEqual(result["counts"]["board_notice_vs_filed_xbrl"], {"match": 40, "mismatch_unresolved": 2, "not_comparable": 18})
        self.assertEqual(result["counts"]["restatement_notice_post_vs_restated_xbrl"],
                         {"match": 27, "mismatch_unresolved": 0, "not_comparable": 67})
        self.assertEqual(result["consistency"], "INCONSISTENT")
        [finding] = result["discrepancies"]
        self.assertEqual([(i["metric"], i["difference_thousand_twd"]) for i in finding["items"]],
                         [("total_assets", "1721"), ("total_liabilities", "1721")])
        pdf = finding["audited_pdf"]
        self.assertEqual(pdf["identity_checks"], {"unit": "verified", "fiscal_year": "verified", "statement_scope": "verified"})
        self.assertEqual((pdf["filing_version_id"], pdf["pdf_page_index"], pdf["reporting_roc_year"]),
                         ("hfv1_8fa5f75c0aa6fd07ab5691f0b13356f3", 8, 114))
        self.assertTrue(all(c["equals_filed_xbrl"] and c["equals_board_notice"] is False for c in pdf["checks"]))
        self.assertEqual((finding["fraud_label"], finding["routes_to_risk_score"], finding["cause"]), (None, False, "unverified"))


if __name__ == "__main__":
    unittest.main()
