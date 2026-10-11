"""REAL-DATA tier: the research layer over the approved local 1785 archive (Phase 2C baseline 506b64c).

Skipped when the local archive is absent (e.g. a fresh worktree). Counts are verified baseline assertions on the
user's artifacts, not targets. Adversarial cases wrap the real backend and alter one property at a time.
"""

from __future__ import annotations

import tempfile
import unittest
from collections import Counter
from pathlib import Path
from typing import Any

from app.services.financial_research.modes import build_context
from app.services.financial_research.result_store import SqliteResearchResultStore
from app.services.financial_research.service import ResearchConfig, ResearchService
from app.services.historical_audit.models import parse_timestamp
from scripts.research_baseline import database_digest

ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "historical_audit" / "historical_audit.sqlite3"
HAS_REAL = DATABASE.is_file() and (ROOT / "data" / "historical-conference-pdfs" / "1785").is_dir()
FY2025_PDF_SHA = "fc7151400c1cd776852e9f309f7840eb794881f6e1ab27970cf2c2996b613b01"
FY2025_NOTICE_SHA = "0d598c11d95d71714b0955c60ddb4694026cfc76eee776a0954be487813fb0d0"


def service() -> ResearchService:
    return ResearchService(ResearchConfig(database=str(DATABASE), raw_root=str(ROOT / "data" / "historical_audit" / "raw"),
                                          conference_root=str(ROOT / "data" / "historical-conference-pdfs")))


class MutatingBackend:
    """Wraps the real backend and alters exactly one property of the rows it returns."""

    def __init__(self, inner: Any, *, facts=None, comparisons=None) -> None:
        self.inner, self.facts_fn, self.comparisons_fn = inner, facts, comparisons
        self.backend_name = "mutated"

    def list_facts(self, *args, **kwargs):
        rows = self.inner.list_facts(*args, **kwargs)
        return self.facts_fn(rows) if self.facts_fn else rows

    def list_restatement_comparisons(self, *args, **kwargs):
        rows = self.inner.list_restatement_comparisons(*args, **kwargs)
        return self.comparisons_fn(rows) if self.comparisons_fn else rows

    def __getattr__(self, name):
        return getattr(self.inner, name)


@unittest.skipUnless(HAS_REAL, "approved local 1785 archive not present")
class RealResearchBaselineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.service = service()
        cls.retro = build_context("RETROSPECTIVE_FORENSIC")

    def test_baseline_counts(self) -> None:
        overview = self.service.case_overview("1785")
        self.assertEqual(overview["coverage"]["canonical_facts"], 234)
        self.assertEqual(overview["coverage"]["point_in_time_eligible_facts"], 67)
        self.assertEqual(overview["coverage"]["restatement_comparisons"], 158)
        self.assertEqual(overview["coverage"]["publication_events"], 919)
        self.assertEqual(overview["coverage"]["filing_versions"], 44)
        self.assertEqual(overview["coverage"]["fiscal_years_with_facts"], list(range(2013, 2026)))
        self.assertFalse(overview["production_universe"])
        self.assertEqual(overview["research_coverage"], {"start_year": 2011, "end_year": 2025})
        self.assertEqual(overview["priority_event_period"], {"start_year": 2011, "end_year": 2016})

    def test_restatement_bridge_2011_2015(self) -> None:
        bridge = self.service.bridge("1785", self.retro)
        self.assertEqual(bridge["status"], "READY")
        self.assertEqual(bridge["integrity"], {"rows_total": 158, "expected_baseline_rows": 158, "baseline_check": "match",
                                               "difference_inconsistent": 0, "regime_inconsistent": 0, "identity_failures": 0})
        frameworks = {(r["fiscal_year"], r["accounting_framework"]) for r in bridge["rows"]}
        self.assertEqual(frameworks, {(2011, "TW_GAAP"), (2012, "TW_GAAP"), (2013, "TIFRS"), (2014, "TIFRS"), (2015, "TIFRS")})
        self.assertEqual(bridge["heatmap"]["accounting_regime_break_before_years"], [2013])
        self.assertEqual(Counter(r["statement_scope"] for r in bridge["rows"]), {"consolidated": 79, "individual": 79})
        year = next(b for b in bridge["year_bridges"] if b["period"] == "2013FY" and b["statement_scope"] == "consolidated")
        cogs = year["metrics"]["cost_of_goods_sold"]
        self.assertEqual((cogs["pre_twd"], cogs["post_twd"], cogs["delta_twd"]), ("32256578000", "33223945000", "967367000"))
        self.assertEqual(year["announcement_key"], "mops:20161113:212622:3")
        self.assertEqual(year["decomposition"]["gross_profit_bridge_check"], "holds")
        self.assertEqual(year["margins"]["gross_margin"]["change"], "-0.028252")
        ni_2011 = next(b for b in bridge["year_bridges"] if b["period"] == "2011FY" and b["statement_scope"] == "consolidated")
        self.assertEqual(ni_2011["metrics"]["net_income"]["denominator_status"], "sign_reversal")
        self.assertIsNone(ni_2011["metrics"]["net_income"]["delta_pct"])
        self.assertTrue(all(link["linkage_status"] != "proven" for link in bridge["hypothesis_links"]))
        self.assertEqual(len(self.service.bridge("1785", self.retro, scope="individual")["rows"]), 79)

    def test_strict_pre_revelation_is_insufficient(self) -> None:
        for cutoff in ("2016-05-13T00:00:00+08:00", "2016-05-13T18:49:19+08:00", "2016-05-17T00:00:00+08:00",
                       "2016-11-13T21:25:31+08:00"):
            context = build_context("STRICT_AS_OF", cutoff)
            _, result = self.service.features("1785", context, start_year=2011, end_year=2016, version_policy="latest_available")
            self.assertEqual(result["status"], "insufficient_point_in_time_evidence", cutoff)
            self.assertEqual(result["counts"]["computed"], 0)
            self.assertIsNone(next((f for f in result["features"] if f["value"] is not None), None))
        self.assertEqual(self.service.bridge("1785", build_context("STRICT_AS_OF", "2016-05-13T00:00:00+08:00"))["status"],
                         "insufficient_point_in_time_evidence")

    def test_november_2016_one_second_boundary(self) -> None:
        counts = {}
        for cutoff in ("2016-11-13T21:26:21+08:00", "2016-11-13T21:26:22+08:00", "2016-11-13T21:26:23+08:00"):
            snapshot = self.service.snapshot("1785", build_context("STRICT_AS_OF", cutoff), start_year=2011, end_year=2016)
            counts[cutoff[-14:-6]] = len(snapshot.facts)
            for fact in snapshot.facts:
                self.assertLess(parse_timestamp(fact["effective_available_at"]), parse_timestamp(cutoff))
        self.assertEqual(counts, {"21:26:21": 0, "21:26:22": 0, "21:26:23": 27})
        after = self.service.snapshot("1785", build_context("STRICT_AS_OF", "2016-11-13T21:26:23+08:00"),
                                      start_year=2011, end_year=2016)
        self.assertEqual(Counter(f["fiscal_year"] for f in after.facts), {2013: 9, 2014: 9, 2015: 9})
        self.assertTrue(all(f["artifact_reference_status"] == "withheld_not_public_at_cutoff" for f in after.facts))
        self.assertTrue(all(f["observation_evidence_status"] == "E2_verified_notice_observation" for f in after.facts))

    def test_strict_2026_has_67_and_fy2025_only_five_board_values(self) -> None:
        snapshot = self.service.snapshot("1785", build_context("STRICT_AS_OF", "2026-10-11T00:00:00+08:00"))
        years = Counter(f["fiscal_year"] for f in snapshot.facts)
        self.assertEqual(len(snapshot.facts), 67)
        self.assertEqual(sum(years[y] for y in (2013, 2014, 2015)), 27)
        self.assertEqual(sum(years[y] for y in (2020, 2021, 2022)), 21)
        self.assertEqual([years[y] for y in (2023, 2024, 2025)], [7, 7, 5])
        fy2025 = {f["metric_code"] for f in snapshot.facts if f["fiscal_year"] == 2025}
        self.assertEqual(fy2025, {"revenue", "gross_profit", "operating_income", "net_income", "eps"})
        for cutoff, expected in (("2026-03-06T18:41:23+08:00", 0), ("2026-03-06T18:41:24+08:00", 5)):
            snap = self.service.snapshot("1785", build_context("STRICT_AS_OF", cutoff), start_year=2025, end_year=2025)
            self.assertEqual(len(snap.facts), expected, cutoff)

    def test_fy2025_discrepancy_with_both_sources_and_pdf_page_8(self) -> None:
        result = self.service.discrepancies("1785", build_context("CURRENT_EVIDENCE_RECONCILIATION"))
        self.assertEqual(result["counts"]["board_notice_vs_filed_xbrl"], {"match": 40, "mismatch_unresolved": 2, "not_comparable": 18})
        self.assertEqual(result["counts"]["restatement_notice_post_vs_restated_xbrl"]["match"], 27)
        self.assertEqual(result["counts"]["tpex_summary_vs_filed_xbrl"]["match"], 0)
        self.assertFalse(result["routes_to_risk_score"])
        [finding] = result["discrepancies"]
        self.assertEqual((finding["period"], finding["statement_scope"], finding["cause"], finding["fraud_label"]),
                         ("2025FY", "consolidated", "unverified", None))
        items = {i["metric"]: i for i in finding["items"]}
        self.assertEqual(items["total_assets"]["board_notice_value"], "34436171")
        self.assertEqual(items["total_assets"]["filed_value_thousand_twd"], "34434450")
        self.assertEqual(items["total_liabilities"]["board_notice_value"], "19423635")
        self.assertEqual(items["total_liabilities"]["filed_value_thousand_twd"], "19421914")
        self.assertEqual({i["difference_thousand_twd"] for i in items.values()}, {"1721"})
        self.assertEqual(finding["board_notice"]["notice_sha256"], FY2025_NOTICE_SHA)
        self.assertEqual(finding["board_notice"]["announcement_key"], "mops:20260306:184123:3")
        pdf = finding["audited_pdf"]
        self.assertEqual((pdf["pdf_sha256"], pdf["pdf_page_index"], pdf["printed_page_label"], pdf["unit"]),
                         (FY2025_PDF_SHA, 8, "8", "TWD_thousand"))
        self.assertTrue(all(c["equals_filed_xbrl"] and not c["equals_board_notice"] for c in pdf["checks"]))
        self.assertEqual(pdf["other_lines"]["equity"]["value_thousand_twd"], "15012536")

    def test_text_readiness_zero_ready_and_no_jsd_number(self) -> None:
        for context in (self.retro, build_context("STRICT_AS_OF", "2026-10-11T00:00:00+08:00")):
            result = self.service.text("1785", context)
            self.assertEqual((result["archive"]["file_records"], result["archive"]["unique_sha256"],
                              result["archive"]["pages"], result["archive"]["text_pages"],
                              result["archive"]["listing_meeting_rows"], result["jsd_ready_records"]), (44, 38, 1190, 1139, 26, 0))
            self.assertEqual(result["jsd"]["status"], "NOT_APPLICABLE")
            self.assertIsNone(result["jsd"]["value"])
            self.assertEqual(result["readiness_issue_counts"]["period_unconfirmed"], 44)
            self.assertEqual(result["readiness_issue_counts"]["publication_unverified"], 44)
        self.assertEqual(self.service.text("1785", build_context("STRICT_AS_OF", "2026-10-11T00:00:00+08:00"))
                         ["strict_eligible_documents"], 0)

    def test_literature_models_not_computable_on_real_inputs(self) -> None:
        _, result = self.service.features("1785", self.retro, start_year=2013, end_year=2025, version_policy="latest_available")
        models = {m["model_id"]: m for m in result["literature_models"]["models"]}
        self.assertEqual(models["beneish_1999_m_score_8_variable"]["full_model_status"], "not_computable")
        self.assertEqual(models["dechow_2011_f_score_model_1"]["full_model_status"], "not_computable")
        computed = {f["feature_id"] for f in result["features"] if f["status"] == "computed"}
        self.assertTrue({"gross_margin", "cogs_sales_ratio", "inventory_turnover", "earnings_cashflow_gap_proxy"} <= computed)
        first_turnover = next(f for f in result["features"] if f["feature_id"] == "inventory_turnover" and f["fiscal_year"] == 2013)
        self.assertEqual(first_turnover["status"], "not_computable")


@unittest.skipUnless(HAS_REAL, "approved local 1785 archive not present")
class RealAdversarialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = service()

    def wrapped(self, **kwargs) -> ResearchService:
        return ResearchService(backend=MutatingBackend(self.base.backend, **kwargs), repository=self.base.repository,
                               conference_repository=None, pdf_provider=None)

    def strict(self, cutoff="2026-10-11T00:00:00+08:00"):
        return build_context("STRICT_AS_OF", cutoff)

    def test_a_leaked_post_cutoff_row_fails_closed(self) -> None:
        def leak(rows):
            if rows:
                rows[0] = {**rows[0], "effective_available_at": "2026-10-11T00:00:00+08:00"}
            return rows
        with self.assertRaisesRegex(AssertionError, "not available before the cutoff"):
            self.wrapped(facts=leak).snapshot("1785", self.strict())

    def test_value_hash_and_version_changes_alter_the_input_digest(self) -> None:
        original = self.base.snapshot("1785", self.strict()).input_digest
        for field, value in (("value_text", "1"), ("availability_evidence_hash", "0" * 64),
                             ("filing_version_type", "original"), ("statement_scope", "individual"), ("unit", "USD"),
                             ("effective_available_at", "2016-11-13T21:26:21+08:00")):
            mutated = self.wrapped(facts=lambda rows, f=field, v=value: [{**rows[0], f: v}] + rows[1:])
            self.assertNotEqual(mutated.snapshot("1785", self.strict()).input_digest, original, field)
        # The filing artifact was not public at the cutoff: its hash is withheld from strict inputs ...
        artifact = self.wrapped(facts=lambda rows: [{**rows[0], "content_hash": "0" * 64}] + rows[1:])
        self.assertEqual(artifact.snapshot("1785", self.strict()).input_digest, original)
        # ... but is part of the retrospective inputs.
        retro = build_context("RETROSPECTIVE_FORENSIC")
        self.assertNotEqual(artifact.snapshot("1785", retro).input_digest, self.base.snapshot("1785", retro).input_digest)

    def test_scope_and_version_mutations_make_features_not_computable(self) -> None:
        def scope(rows):
            return [{**r, "statement_scope": "individual"} if r["fiscal_year"] == 2024 and r["metric_code"] == "revenue" else r
                    for r in rows]

        def version(rows):
            return [{**r, "filing_version_id": "hfv1_tampered"} if r["fiscal_year"] == 2024 and r["metric_code"] == "revenue" else r
                    for r in rows]

        for mutate, reason in ((scope, "no_verified_observation_before_cutoff"), (version, "version_mismatch")):
            _, result = self.wrapped(facts=mutate).features("1785", self.strict(), start_year=2024, end_year=2024,
                                                              version_policy="latest_available")
            margin = next(f for f in result["features"] if f["feature_id"] == "gross_margin")
            self.assertEqual(margin["status"], "not_computable")
            self.assertIn(reason, {r["code"] for r in margin["missing_reasons"]})

    def test_sign_mutation_is_inconsistent(self) -> None:
        def sign(rows):
            return [{**r, "sign_factor": 1} if r["canonical_metric"] == "cost_of_goods_sold" else r for r in rows]
        bridge = self.wrapped(comparisons=sign).bridge("1785", build_context("RETROSPECTIVE_FORENSIC"))
        self.assertEqual(bridge["status"], "INCONSISTENT")
        self.assertGreater(bridge["integrity"]["identity_failures"], 0)

    def test_persisted_run_detects_changed_inputs(self) -> None:
        context = self.strict()
        run = self.base.build_run("financial_signals", "1785", context, start_year=2023, end_year=2025)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = SqliteResearchResultStore(Path(directory) / "r.sqlite3")
            store.record_run(run)
            stored = store.get_run(run["run_id"])
            self.assertEqual(self.base.verify_run(stored)["status"], "reproducible")
            tampered = self.wrapped(facts=lambda rows: [{**rows[0], "value_text": "1"}] + rows[1:])
            self.assertEqual(tampered.verify_run(stored)["status"], "inputs_changed_since_run")


@unittest.skipUnless(HAS_REAL, "approved local 1785 archive not present")
class RealNonMutationAndIsolationTests(unittest.TestCase):
    def test_full_research_pass_leaves_the_approved_database_identical(self) -> None:
        before = database_digest(DATABASE)
        research = service()
        for mode, cutoff in (("RETROSPECTIVE_FORENSIC", None), ("STRICT_AS_OF", "2016-05-13T00:00:00+08:00"),
                             ("STRICT_AS_OF", "2026-10-11T00:00:00+08:00"), ("CURRENT_EVIDENCE_RECONCILIATION", None)):
            context = build_context(mode, cutoff)
            research.build_run("financial_signals", "1785", context)
            if mode == "CURRENT_EVIDENCE_RECONCILIATION":
                research.build_run("source_reconciliation", "1785", context)
            else:
                research.build_run("restatement_bridge", "1785", context)
                research.timeline("1785", context)
                research.text("1785", context)
        research.case_overview("1785")
        self.assertEqual(database_digest(DATABASE), before)

    def test_1785_stays_outside_the_production_universe(self) -> None:
        from app.services.company_registry import get_company, list_companies
        from app.services.ingestion_pipeline import validate_refresh_tickers

        self.assertNotIn("1785", [c.ticker for c in list_companies()])
        self.assertIsNone(get_company("1785"))
        with self.assertRaises(ValueError):
            validate_refresh_tickers(["1785"])

    def test_runs_are_deterministic(self) -> None:
        research = service()
        context = build_context("CURRENT_EVIDENCE_RECONCILIATION")
        first = research.build_run("source_reconciliation", "1785", context)
        second = service().build_run("source_reconciliation", "1785", context)
        self.assertEqual((first["run_id"], first["input_digest"], first["output_digest"]),
                         (second["run_id"], second["input_digest"], second["output_digest"]))


if __name__ == "__main__":
    unittest.main()
