"""UNIT tier for the Phase 3 research layer (no archive needed): modes, Decimal rules, bridge rows, feature
states, literature gates, reconciliation outcomes, label isolation, PDF statement parsing and the append-only store."""

from __future__ import annotations

import ast
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from app.services.financial_research import decimal_math as dm
from app.services.financial_research.case_labels import labels_for_retrospective_evaluation
from app.services.financial_research.feature_registry import FEATURE_INDEX, FEATURES
from app.services.financial_research.financial_features import compute_feature, compute_features, index_facts
from app.services.financial_research.input_snapshot import InputSnapshot, safe_official_url
from app.services.financial_research.literature_models import model_readiness
from app.services.financial_research.modes import (
    AnalysisMode,
    AnalysisRequestError,
    ModeNotSupportedError,
    build_context,
)
from app.services.financial_research.pdf_evidence import parse_balance_sheet_page
from app.services.financial_research.restatement_bridge import bridge_rows, build_bridge, denominator_status
from app.services.financial_research.result_store import (
    FirestoreResearchResultStore,
    ResultStoreIntegrityError,
    SqliteResearchResultStore,
    build_run,
)
from app.services.financial_research.source_reconciliation import compare_board_notices, reconcile
from tests.historical_cloud_fakes import FakeFirestoreClient, ServiceUnavailable

PACKAGE = Path(__file__).resolve().parents[1] / "app" / "services" / "financial_research"
RETRO = build_context("RETROSPECTIVE_FORENSIC")
RECON = build_context("CURRENT_EVIDENCE_RECONCILIATION")


def fact(year, metric, value, *, scope="consolidated", unit="TWD", version="v", framework="TIFRS", vtype="unknown_revision",
         available=None):
    return {"fact_id": f"f-{year}-{metric}-{scope}", "ticker": "1785", "period": f"{year}FY", "fiscal_year": year,
            "metric_code": metric, "value": value, "unit": unit, "statement_type": "x", "statement_scope": scope,
            "accounting_framework": framework, "filing_version_id": f"{version}{year}", "filing_version_type": vtype,
            "quality_status": "ok", "effective_available_at": available, "availability_scope": None,
            "availability_evidence_kind": None, "availability_evidence_ref": None, "availability_evidence_hash": None,
            "availability_evidence_url": None, "point_in_time_eligible": available is not None,
            "observation_evidence_status": "no_verified_observation", "artifact_evidence_status": "E0",
            "artifact_reference_status": "included", "artifact_sha256": "a" * 64, "artifact_url": None}


def snapshot(facts, context=RETRO, start=2014, end=2015, comparisons=(), disclosed=()):
    return InputSnapshot(ticker="1785", context=context, start_year=start, end_year=end, version_policy="latest_available",
                         backend_name="unit", facts=list(facts), comparisons=list(comparisons), disclosed_values=list(disclosed))


def comparison(year, metric, label, pre, post, diff, *, sign=1, scope="consolidated", framework="TIFRS",
               statement="income_statement"):
    return {"period": f"{year}FY", "fiscal_year": year, "statement_scope": scope, "accounting_framework": framework,
            "statement_type": statement, "pre_label": label, "post_label": label, "canonical_metric": metric,
            "sign_factor": sign, "pre_restatement_value": pre, "post_restatement_value": post, "difference": diff,
            "published_unit": "TWD_thousand", "disclosed_at": "2016-11-13T21:26:22+08:00",
            "availability_status": "verified", "announcement_key": "mops:20161113:212622:3", "content_hash": "c" * 64,
            "source_url": None}


class ModeTests(unittest.TestCase):
    def test_mode_is_mandatory_and_strict_requires_an_aware_exclusive_cutoff(self) -> None:
        for bad in (None, "", "FULL", "strict_as_of"):
            with self.assertRaises(AnalysisRequestError):
                build_context(bad)
        with self.assertRaisesRegex(AnalysisRequestError, "requires cutoff_at"):
            build_context("STRICT_AS_OF")
        for bad in ("2016-05-13", "2016-05-13T00:00:00", "yesterday"):
            with self.assertRaises(AnalysisRequestError):
                build_context("STRICT_AS_OF", bad)
        with self.assertRaisesRegex(AnalysisRequestError, "only to STRICT_AS_OF"):
            build_context("RETROSPECTIVE_FORENSIC", "2016-05-13T00:00:00+08:00")
        context = build_context("STRICT_AS_OF", "2016-11-13T21:26:22+08:00")
        boundary = datetime(2016, 11, 13, 13, 26, 22, tzinfo=timezone.utc)
        self.assertFalse(context.admits(boundary))  # equality is excluded
        self.assertTrue(context.admits(datetime(2016, 11, 13, 13, 26, 21, tzinfo=timezone.utc)))
        self.assertFalse(context.admits(None))
        self.assertEqual(context.reader_as_of, boundary - timedelta(microseconds=1))
        with self.assertRaises(ModeNotSupportedError):
            build_context("STRICT_AS_OF", "2016-05-13T00:00:00+08:00", allowed=(AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION,))


class DecimalTests(unittest.TestCase):
    def test_official_number_forms_and_float_refusal(self) -> None:
        self.assertEqual(dm.parse_decimal("(1,234)"), Decimal("-1234"))
        self.assertEqual(dm.parse_decimal("-32256578"), Decimal("-32256578"))
        self.assertEqual(dm.parse_decimal("0"), Decimal(0))  # a real zero, not missing
        for missing in (None, "", "-", "—"):
            self.assertIsNone(dm.parse_decimal(missing))
        with self.assertRaises(dm.DecimalParseError):
            dm.parse_decimal(1.5)
        with self.assertRaises(dm.DecimalParseError):
            dm.parse_decimal("1e9")
        self.assertEqual(dm.text(dm.to_twd(Decimal("33223945"), "TWD_thousand")), "33223945000")
        self.assertEqual(dm.ratio_text(Decimal(1), Decimal(3)), "0.333333")
        with self.assertRaises(dm.DecimalParseError):
            dm.to_twd(Decimal(1), "USD")

    def test_denominator_policy(self) -> None:
        revenue = Decimal(34241550000)
        self.assertEqual(denominator_status(Decimal(0), Decimal(5), revenue), "zero_denominator")
        self.assertEqual(denominator_status(Decimal(810590000), Decimal(-1417891000), revenue), "sign_reversal")
        self.assertEqual(denominator_status(Decimal(1000), Decimal(2000), revenue), "near_zero_denominator")
        self.assertEqual(denominator_status(Decimal(408817000), Decimal(67393000), revenue), "stable")
        self.assertEqual(denominator_status(None, Decimal(1), revenue), "missing_side")


class BridgeTests(unittest.TestCase):
    ROWS = [comparison(2013, "revenue", "營業收入", "34241550", "34241550", "0"),
            comparison(2013, "cost_of_goods_sold", "營業成本", "-32256578", "-33223945", "-967367", sign=-1),
            comparison(2013, "gross_profit", "營業毛利淨額", "1984972", "1017605", "-967367"),
            comparison(2013, "net_income", "本期淨利", "408817", "67393", "-341424")]

    def test_sign_unit_delta_and_margins(self) -> None:
        rows = {r["canonical_metric"]: r for r in bridge_rows(self.ROWS, "1785")}
        cogs = rows["cost_of_goods_sold"]
        self.assertEqual((cogs["pre_twd"], cogs["post_twd"], cogs["delta_twd"]), ("32256578000", "33223945000", "967367000"))
        self.assertEqual(cogs["notice_reported_post"], "-33223945")  # the notice text is preserved as published
        self.assertEqual(cogs["difference_check"], "consistent")
        result = build_bridge(snapshot([], comparisons=self.ROWS, start=2011, end=2015))
        bridge = result["year_bridges"][0]
        self.assertEqual(bridge["accounting_identity_gross_profit"], {"pre": "holds", "post": "holds"})
        self.assertEqual(bridge["margins"]["gross_margin"]["pre"]["value"], "0.057970")
        self.assertEqual(bridge["margins"]["operating_margin"]["status"], "not_computable")  # no operating line
        self.assertEqual(bridge["inventory"]["status"], "not_computable")
        self.assertEqual(result["integrity"]["baseline_check"], "mismatch")  # 4 rows, not the 158 baseline
        self.assertTrue(result["hindsight"])
        self.assertIn("2016-11-13", result["warning"])

    def test_tampered_sign_or_difference_or_regime_is_inconsistent(self) -> None:
        flipped = [dict(r) for r in self.ROWS]
        flipped[1]["sign_factor"] = 1  # COGS sign tampered: identity no longer holds
        self.assertGreater(build_bridge(snapshot([], comparisons=flipped))["integrity"]["identity_failures"], 0)
        self.assertEqual(build_bridge(snapshot([], comparisons=flipped))["status"], "INCONSISTENT")
        wrong_diff = [dict(r) for r in self.ROWS]
        wrong_diff[3]["difference"] = "-341425"
        self.assertEqual(build_bridge(snapshot([], comparisons=wrong_diff))["integrity"]["difference_inconsistent"], 1)
        regime = [dict(r) for r in self.ROWS]
        for r in regime:
            r["accounting_framework"] = "TW_GAAP"  # 2013 must be TIFRS
        self.assertEqual(build_bridge(snapshot([], comparisons=regime))["integrity"]["regime_inconsistent"], 4)

    def test_strict_without_disclosed_comparisons_is_insufficient(self) -> None:
        strict = build_context("STRICT_AS_OF", "2016-05-13T00:00:00+08:00")
        result = build_bridge(snapshot([], context=strict))
        self.assertEqual(result["status"], "insufficient_point_in_time_evidence")
        self.assertEqual(result["hypothesis_links"], [])


class FeatureTests(unittest.TestCase):
    BASE = [fact(2014, "revenue", "100"), fact(2014, "gross_profit", "20"), fact(2014, "cost_of_goods_sold", "80"),
            fact(2014, "inventory", "30"), fact(2014, "total_assets", "200"), fact(2015, "revenue", "120"),
            fact(2015, "cost_of_goods_sold", "90"), fact(2015, "gross_profit", "30"), fact(2015, "inventory", "50"),
            fact(2015, "total_assets", "240")]

    def feature(self, facts, feature_id, year=2015, context=RETRO):
        return compute_feature(FEATURE_INDEX[feature_id], year, "consolidated", index_facts(facts), context)

    def test_exact_values_and_prior_period(self) -> None:
        self.assertEqual(self.feature(self.BASE, "gross_margin")["value"], "0.250000")
        turnover = self.feature(self.BASE, "inventory_turnover")
        self.assertEqual((turnover["value"], turnover["numerator"], turnover["denominator"]), ("2.250000", "90", "40"))
        self.assertEqual(self.feature(self.BASE, "inventory_growth_assets")["value"], "0.090909")
        first = self.feature(self.BASE, "inventory_turnover", year=2014)
        self.assertEqual(first["status"], "not_computable")
        self.assertIn("missing_prior_period", {r["code"] for r in first["missing_reasons"]})

    def test_zero_missing_and_not_applicable_are_distinct(self) -> None:
        zero = [f if f["metric_code"] != "revenue" or f["fiscal_year"] != 2015 else fact(2015, "revenue", "0") for f in self.BASE]
        self.assertEqual(self.feature(zero, "gross_margin")["missing_reasons"][0]["code"], "zero_denominator")
        real_zero = [f if f["metric_code"] != "gross_profit" or f["fiscal_year"] != 2015 else fact(2015, "gross_profit", "0")
                     for f in self.BASE]
        self.assertEqual(self.feature(real_zero, "gross_margin")["value"], "0.000000")  # 0 numerator is a real value
        missing = [f for f in self.BASE if f["metric_code"] != "gross_profit"]
        self.assertEqual(self.feature(missing, "gross_margin")["missing_reasons"][0]["code"], "missing_input")
        self.assertEqual(self.feature(self.BASE, "source_value_gap")["status"], "not_applicable")
        self.assertEqual(self.feature(self.BASE, "gross_margin", context=RECON)["status"], "not_applicable")

    def test_scope_unit_version_and_regime_are_never_mixed(self) -> None:
        scoped = [f if f["metric_code"] != "revenue" else fact(f["fiscal_year"], "revenue", f["value"], scope="individual")
                  for f in self.BASE]
        self.assertEqual(self.feature(scoped, "gross_margin")["missing_reasons"][0]["code"], "missing_input")
        unit = [f if f["metric_code"] != "revenue" else fact(f["fiscal_year"], "revenue", f["value"], unit="TWD_thousand")
                for f in self.BASE]
        self.assertEqual(self.feature(unit, "gross_margin")["missing_reasons"][0]["code"], "unit_mismatch")
        version = [f if f["metric_code"] != "revenue" else fact(f["fiscal_year"], "revenue", f["value"], version="w")
                   for f in self.BASE]
        self.assertIn("version_mismatch", {r["code"] for r in self.feature(version, "gross_margin")["missing_reasons"]})
        regime = [f if f["fiscal_year"] != 2014 else fact(2014, f["metric_code"], f["value"], framework="TW_GAAP")
                  for f in self.BASE]
        self.assertIn("accounting_regime_break", {r["code"] for r in self.feature(regime, "inventory_turnover")["missing_reasons"]})
        with self.assertRaises(ValueError):
            index_facts(self.BASE + [fact(2015, "revenue", "121", version="x")])

    def test_strict_missing_reason_never_consults_full_data(self) -> None:
        strict = build_context("STRICT_AS_OF", "2016-05-13T00:00:00+08:00")
        result = compute_features(snapshot([], context=strict, start=2013, end=2015))
        self.assertEqual(result["status"], "insufficient_point_in_time_evidence")
        self.assertEqual(result["counts"]["computed"], 0)
        reasons = {r["code"] for f in result["features"] for r in f["missing_reasons"]}
        self.assertIn("no_verified_observation_before_cutoff", reasons)
        self.assertNotIn("missing_input", reasons)
        self.assertIn("not a low-risk result", result["strict_note"])

    def test_restated_inputs_are_flagged(self) -> None:
        restated = [fact(f["fiscal_year"], f["metric_code"], f["value"], vtype="restated") for f in self.BASE]
        self.assertTrue(self.feature(restated, "gross_margin")["warnings"])

    def test_registry_definitions_are_complete(self) -> None:
        for feature in FEATURES:
            data = feature.as_dict()
            for key in ("literature_reference", "formula_version", "required_metrics", "period_alignment",
                        "accounting_framework_policy", "scope_policy", "version_policy", "source_availability_policy",
                        "unit", "zero_policy", "missing_reason_catalog", "original_vs_proxy", "allowed_modes"):
                self.assertIn(key, data)
            self.assertEqual(data["approval_status"], "DRAFT_PENDING_METHOD_OWNER_REVIEW")
        self.assertEqual(FEATURE_INDEX["earnings_cashflow_gap_proxy"].original_vs_proxy, "proxy")


class LiteratureGateTests(unittest.TestCase):
    def test_full_models_not_computable_and_no_score_emitted(self) -> None:
        result = model_readiness(snapshot(FeatureTests.BASE))
        beneish, dechow = result["models"][0], result["models"][1]
        self.assertEqual(beneish["full_model_status"], "not_computable")
        self.assertEqual(dechow["full_model_status"], "not_computable")
        for name in ("AQI", "DEPI", "SGAI", "LVGI", "TATA"):
            self.assertEqual(beneish["variables"][name]["status"], "not_computable")
        self.assertIn("property_plant_equipment_net", beneish["variables"]["AQI"]["inputs_not_in_canonical_dataset"])
        self.assertTrue(all(m["full_model_status"] == "not_computable" for m in result["models"][2:]))
        text = repr(result).lower()
        self.assertNotIn("m_score_value", text)
        self.assertNotIn("'score'", text)
        sgi = [c for c in result["descriptive_components"] if c["component"] == "SGI" and c["fiscal_year"] == 2015][0]
        self.assertEqual(sgi["value"], "1.200000")
        self.assertIn("NOT an M-Score", sgi["note"])


class ReconciliationTests(unittest.TestCase):
    def notice(self, metric, value, *, scope="consolidated", unit="TWD", period="2025FY", label="期末總資產"):
        return {"disclosure_kind": "annual", "period": period, "fiscal_year": int(period[:4]), "statement_scope": scope,
                "accounting_framework": "TIFRS", "source_label": label, "canonical_metric": metric,
                "value": str(int(value) // 1000), "published_unit": "TWD_thousand", "normalized_value": value,
                "normalized_unit": unit, "disclosed_at": "2026-03-06T18:41:23+08:00", "availability_status": "verified",
                "dated_facts": 0, "announcement_key": "mops:20260306:184123:3", "content_hash": "d" * 64, "source_url": None}

    def test_outcomes_and_exact_identity(self) -> None:
        facts = [fact(2025, "total_assets", "34434450000"), fact(2025, "revenue", "39411439000")]
        rows = compare_board_notices(snapshot(facts, context=RECON, start=2025, end=2025, disclosed=[
            self.notice("total_assets", "34436171000"), self.notice("revenue", "39411439000", label="營業收入"),
            self.notice(None, "14961333000", label="期末歸屬於母公司業主之權益"),
            self.notice("revenue", "39411439000", scope="individual", label="營業收入"),
            self.notice("total_assets", "34436171000", unit="TWD/share")]))
        outcomes = [r["outcome"] for r in rows]
        self.assertEqual(outcomes, ["mismatch_unresolved", "match", "not_comparable", "not_comparable", "not_comparable"])
        self.assertEqual(rows[0]["difference"], "1721000")
        self.assertEqual(rows[2]["reasons"], ["no_verified_canonical_metric_mapping"])
        self.assertEqual(rows[3]["reasons"], ["no_filed_fact_same_period_scope_metric"])
        self.assertEqual(rows[4]["reasons"], ["unit_mismatch"])

    def test_mismatch_never_routes_to_risk_and_mode_is_enforced(self) -> None:
        class Backend:
            def list_summary_observations(self, ticker):
                return []

        snap = snapshot([fact(2025, "total_assets", "34434450000")], context=RECON, start=2025, end=2025,
                        disclosed=[self.notice("total_assets", "34436171000")])
        result = reconcile(snap, Backend())
        self.assertFalse(result["routes_to_risk_score"])
        finding = result["discrepancies"][0]
        self.assertEqual((finding["status"], finding["cause"], finding["fraud_label"], finding["routes_to_risk_score"]),
                         ("mismatch_unresolved", "unverified", None, False))
        self.assertEqual(finding["audited_pdf"]["status"], "pdf_evidence_unavailable_in_this_deployment")
        with self.assertRaises(ModeNotSupportedError):
            reconcile(snapshot([], context=RETRO), Backend())


class IsolationTests(unittest.TestCase):
    def test_labels_are_retrospective_only_and_not_imported_by_feature_paths(self) -> None:
        self.assertTrue(labels_for_retrospective_evaluation("1785", RETRO))
        for mode in (build_context("STRICT_AS_OF", "2026-10-11T00:00:00+08:00"), RECON):
            with self.assertRaises(ModeNotSupportedError):
                labels_for_retrospective_evaluation("1785", mode)
        for module in ("financial_features", "input_snapshot", "feature_registry", "literature_models",
                       "restatement_bridge", "source_reconciliation", "service", "text_evidence_bridge"):
            tree = ast.parse((PACKAGE / f"{module}.py").read_text(encoding="utf-8"))
            imported = {getattr(n, "module", None) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            self.assertNotIn("app.services.financial_research.case_labels", imported, module)

    def test_research_layer_never_imports_risk_scoring_or_llm_modules(self) -> None:
        forbidden = ("financial_rule_engine", "historical_rule_engine", "monitorable_rule_engine", "gemini", "anthropic",
                     "claim_llm", "llm_", "company_registry", "jsd_method", "data_shift")
        for path in PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
            names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
            self.assertFalse([n for n in names for f in forbidden if f in n], path.name)

    def test_only_official_hosts_are_exposed(self) -> None:
        self.assertIsNotNone(safe_official_url("https://mopsov.twse.com.tw/mops/web/ajax_t05st01"))
        for url in ("javascript:alert(1)", "https://evil.example/x", "file:///c:/x", "https://lawplayer.com/x", None):
            self.assertIsNone(safe_official_url(url))


class PdfParseTests(unittest.TestCase):
    PAGE = ("光 洋 應 用 材 料 科 技 股 份 有 限 公 司 及 子 公 司\n合 併 資 產 負 債 表\n單 位 ： 新 台 幣 千 元\n"
            "1XXX  資產總計    $ 34,434,450     100    $ 31,292,876     100\n"
            "2XXX    負債總計     19,421,914     56     17,005,813     54\n"
            "31XX  本公司業主權益總計     14,961,333     44     14,266,307     46\n"
            "3XXX  權益總計     15,012,536     44     14,287,063     46\n- 8 -")

    def test_account_code_totals(self) -> None:
        parsed = parse_balance_sheet_page(self.PAGE)
        self.assertEqual(parsed["unit"], "TWD_thousand")
        self.assertEqual(parsed["printed_page_label"], "8")
        self.assertEqual({k: v["value_thousand_twd"] for k, v in parsed["totals"].items()},
                         {"total_assets": "34434450", "total_liabilities": "19421914", "equity": "15012536",
                          "equity_attributable_to_owners_of_parent": "14961333"})
        self.assertIsNone(parse_balance_sheet_page("合 併 綜 合 損 益 表\n4000 營業收入 1"))


class ResultStoreTests(unittest.TestCase):
    def run_record(self, value="0.25", parameters=None):
        snap = snapshot(FeatureTests.BASE).describe()
        output = {"status": "READY", "features": [{"feature_id": "gross_margin", "fiscal_year": 2015,
                                                   "statement_scope": "consolidated", "status": "computed", "value": value,
                                                   "unit": "ratio", "missing_reasons": [],
                                                   "inputs": [{"fact_id": "f", "availability_evidence_hash": None,
                                                               "artifact_sha256": "a" * 64}]}]}
        return build_run(result_kind="financial_signals", method_version="m1", method_ids=["m1"],
                         approval_status="DRAFT_PENDING_METHOD_OWNER_REVIEW", snapshot=snap,
                         parameters=parameters or {"statement_scope": "consolidated"}, output=output)

    def test_append_only_idempotent_and_deterministic(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            store = SqliteResearchResultStore(Path(directory) / "results.sqlite3")
            run = self.run_record()
            self.assertEqual(store.record_run(run), (run["run_id"], True))
            self.assertEqual(store.record_run(run), (run["run_id"], False))
            with self.assertRaises(ResultStoreIntegrityError):
                store.record_run(self.run_record(value="0.26"))  # same identity, different output
            other = self.run_record(parameters={"statement_scope": "individual"})
            self.assertNotEqual(other["run_id"], run["run_id"])  # a correction is a new run
            self.assertEqual(store.record_run(other)[1], True)
            labels = labels_for_retrospective_evaluation("1785", RETRO)
            self.assertEqual(store.record_labels("1785", labels), len(labels))
            self.assertEqual(store.record_labels("1785", labels), 0)
            with sqlite3.connect(store.path) as connection:
                for statement in ("UPDATE research_runs SET status = 'x'", "DELETE FROM research_runs",
                                  "DELETE FROM research_features", "UPDATE case_research_labels SET label = 'x'"):
                    with self.assertRaisesRegex(sqlite3.DatabaseError, "append-only"):
                        connection.execute(statement)
            stored = store.get_run(run["run_id"])
            self.assertEqual(stored["output_digest"], run["output_digest"])
            self.assertEqual(store.projection_counts(run["run_id"])["research_features"], 1)

    def test_refuses_the_approved_database_and_matches_firestore_view(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            approved = Path(directory) / "historical_audit.sqlite3"
            with self.assertRaises(ResultStoreIntegrityError):
                SqliteResearchResultStore(approved, protected=(str(approved),))
            sqlite_store = SqliteResearchResultStore(Path(directory) / "results.sqlite3")
            firestore_store = FirestoreResearchResultStore(FakeFirestoreClient())
            run = self.run_record()
            sqlite_store.record_run(run)
            self.assertEqual(firestore_store.record_run(run), (run["run_id"], True))
            self.assertEqual(firestore_store.record_run(run), (run["run_id"], False))
            strip = lambda r: {k: v for k, v in r.items() if k not in ("created_at",)}  # noqa: E731
            self.assertEqual(strip(firestore_store.get_run(run["run_id"])), strip(sqlite_store.get_run(run["run_id"])))
            with self.assertRaises(ValueError):
                FirestoreResearchResultStore(FakeFirestoreClient(), prefix="companies")

    def test_firestore_failure_injection_leaves_no_committed_run(self) -> None:
        client = FakeFirestoreClient()
        store = FirestoreResearchResultStore(client)
        run = self.run_record()
        client.fail_write = lambda collection, document, operation: collection.endswith("_runs")
        with self.assertRaises(ServiceUnavailable):
            store.record_run(run)
        self.assertIsNone(store.get_run(run["run_id"]))  # the run document is the commit marker
        client.fail_write = None
        self.assertEqual(store.record_run(run), (run["run_id"], True))  # retry re-verifies existing chunks


if __name__ == "__main__":
    unittest.main()
