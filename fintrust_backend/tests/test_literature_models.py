"""Beneish (1999) / Dechow et al. (2011) literature models: paper mathematics, graceful incompleteness, PIT, F05/F06.

Tiers: UNIT/FIXTURE tests always run (synthetic, baseline-independent); the REAL tier rebuilds the literature-input
store from the approved local raw archive into a temporary file and is skipped when the archive is absent.

Expected values cite their source: the Dechow et al. (2011) Enron worked example is the paper's own computation
(CAR p. 61); the Beneish example below is hand-derived from the Table 2 definitions with the arithmetic written out
in the comments and re-derived here with ``fractions.Fraction`` (independent of the engine's Decimal helpers).
"""

from __future__ import annotations

import copy
import random
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from app.services.financial_research import beneish_1999, dechow_2011
from app.services.financial_research import literature_common as lc
from app.services.financial_research.input_snapshot import InputSnapshot
from app.services.financial_research.literature_comparison import (
    compare,
    compute_models,
    freeze_literature_inputs,
    select_filings,
)
from app.services.financial_research.literature_extraction import (
    parse_code_rows,
    parse_label_rows,
    parse_total_rows,
    roc_year,
)
from app.services.financial_research.literature_inputs import FilingLines, assemble
from app.services.financial_research.literature_method_registry import (
    BENEISH_MODEL_ID,
    DECHOW_MODEL_ID,
    model_spec,
    registry_payload,
    verification_problems,
)
from app.services.financial_research.literature_store import (
    LiteratureInputStore,
    LiteratureInputsUnavailable,
    LiteratureStoreIntegrityError,
)
from app.services.financial_research.modes import AnalysisRequestError, ModeNotSupportedError, build_context
from app.services.financial_research.source_reconciliation import compare_board_notices
from app.services.financial_research.version_selection import build_index

RETRO = build_context("RETROSPECTIVE_FORENSIC")
STRICT = build_context("STRICT_AS_OF", "2016-05-13T00:00:00+08:00")
RECON = build_context("CURRENT_EVIDENCE_RECONCILIATION")
ROOT = Path(__file__).resolve().parents[1]
DATABASE = ROOT / "data" / "historical_audit" / "historical_audit.sqlite3"
RAW = ROOT / "data" / "historical_audit" / "raw"
HAS_REAL = DATABASE.is_file() and RAW.is_dir()

# ------------------------------------------------------------------------------------------- synthetic fixture
# Beneish hand example (TWD; t = FY2015, t-1 = FY2014). Hand arithmetic from Table 2:
#   DSRI = (150/1200)/(100/1000) = 1.25        GMI  = (400/1000)/(420/1200) = 8/7
#   AQI  = (1-860/1200)/(1-700/1000) = 17/18   SGI  = 1200/1000 = 1.2
#   DEPI = (50/350)/(40/400) = 10/7            SGAI = (132/1200)/(100/1000) = 1.1
#   LVGI = (600/1200)/(400/1000) = 1.25
#   TATA = [(100-10) - (100-10-5) - (40+10)]/1200 = -45/1200 = -0.0375
#   M = -4.840 + .920*1.25 + .528*8/7 + .404*17/18 + .892*1.2 + .115*10/7 - .172*1.1 + 4.679*(-0.0375) - .327*1.25
#     = -2.2437426587... -> "-2.243743"
T_1 = {"OperatingRevenue": 1000, "OperatingCosts": 600, "AccountsReceivableNet": 100, "CurrentAssets": 400,
       "PropertyPlantAndEquipment": 300, "Assets": 1000, "DepreciationExpense": 50, "AmortizationExpense": 5,
       "SellingExpenses": 30, "AdministrativeExpense": 70, "LongtermBorrowings": 200, "CurrentLiabilities": 200,
       "CashAndCashEquivalents": 50, "LongtermLiabilitiesCurrentPortion": 20, "CurrentTaxLiabilities": 10,
       "Inventories": 120, "Liabilities": 450, "ShorttermBorrowings": 40, "CapitalStock": 300, "OrdinaryShare": 300,
       "ProfitLossFromContinuingOperations": 40, "NoncurrentAvailableForSaleFinancialAssets": 30,
       "CashFlowsFromUsedInOperatingActivities": 90, "ProceedsFromLongTermDebt": 0}
T_0 = {"OperatingRevenue": 1200, "OperatingCosts": 780, "AccountsReceivableNet": 150, "CurrentAssets": 500,
       "PropertyPlantAndEquipment": 360, "Assets": 1200, "DepreciationExpense": 40, "AmortizationExpense": 10,
       "SellingExpenses": 40, "AdministrativeExpense": 92, "LongtermBorrowings": 300, "CurrentLiabilities": 300,
       "CashAndCashEquivalents": 60, "LongtermLiabilitiesCurrentPortion": 30, "CurrentTaxLiabilities": 15,
       "Inventories": 150, "Liabilities": 650, "ShorttermBorrowings": 60, "CapitalStock": 300, "OrdinaryShare": 300,
       "ProfitLossFromContinuingOperations": 66, "NoncurrentAvailableForSaleFinancialAssets": 30,
       "CashFlowsFromUsedInOperatingActivities": 100, "ProceedsFromLongTermDebt": 250}
T_2 = {"AccountsReceivableNet": 80, "Assets": 900, "CurrentAssets": 380}  # CurrentAssets = statement anchor
DURATION = {"OperatingRevenue", "OperatingCosts", "DepreciationExpense", "AmortizationExpense", "SellingExpenses",
            "AdministrativeExpense", "ProfitLossFromContinuingOperations", "CashFlowsFromUsedInOperatingActivities",
            "ProceedsFromLongTermDebt"}


def obs(filing: str, year: int, line: str, value, *, framework="TIFRS", vtype="restated", sha="a"):
    duration = line in DURATION
    period = ({"period_type": "duration", "period_start": f"{year}-01-01", "period_end": f"{year}-12-31"} if duration
              else {"period_type": "instant", "period_start": None, "period_end": f"{year}-12-31"})
    oid = f"lobs1_{filing}_{line}_{year}_{value}"
    return {"observation_id": oid, "ticker": "1785", "filing_version_id": filing, "filing_version_type": vtype,
            "filing_fiscal_year": int(filing[-4:]), "source_kind": "mops_xbrl_instance", "accounting_framework": framework,
            "statement_scope": "consolidated", "statement": "primary_statement", "line_key": line,
            "source_concept": f"ifrs:{line}", "value": str(value), "published_value": str(value), "published_unit": "TWD",
            "locator": "context=x", "raw_sha256": sha * 64, "source_url": None, "extraction_method": "xbrl_instance",
            "extractor_version": "test", "artifact_available_at": None, "artifact_availability_status": "unverified",
            "pit_admitted": False, "pit_basis": "test", "checks": {}, **period}


def fixture_observations(*, drop=(), overrides=None):
    rows = []
    for line, value in {**T_0, **(overrides or {})}.items():
        if line not in drop:
            rows.append(obs("F2015", 2015, line, value))
    for line, value in T_1.items():
        if line not in drop:
            rows.append(obs("F2015", 2014, line, value))
            rows.append(obs("F2014", 2014, line, value))
    for line, value in T_2.items():
        if line not in drop:
            rows.append(obs("F2014", 2013, line, value))
    return rows


def filing(fid, year, vtype="restated"):
    return {"filing_version_id": fid, "ticker": "1785", "fiscal_year": year, "statement_scope": "consolidated",
            "filing_version_type": vtype, "source_kind": "mops_xbrl_instance", "content_hash": "a" * 64,
            "available_at": None, "availability_status": "unverified", "source_url": None}


class FakeStore:
    def __init__(self, observations):
        self.observations = observations

    def list_observations(self, ticker, **_):
        return list(self.observations)


def literature_snapshot(observations=None, *, context=RETRO, policy="latest_available", start=2015, end=2015,
                        versions=None):
    snapshot = InputSnapshot(ticker="1785", context=context, start_year=start, end_year=end, version_policy=policy,
                             backend_name="unit")
    versions = versions if versions is not None else [filing("F2015", 2015), filing("F2014", 2014)]
    return freeze_literature_inputs(snapshot, versions, FakeStore(fixture_observations() if observations is None
                                                                  else observations))


def result_for(snapshot, model_id, year=2015):
    return next(r for r in compute_models(snapshot, [model_id])["results"][model_id] if r["fiscal_year"] == year)


# ------------------------------------------------------------------------------------------- method lock
class MethodLockTests(unittest.TestCase):
    def test_registry_records_verified_source_locations_and_both_models_are_enabled(self) -> None:
        payload = registry_payload()
        models = {m["model_id"]: m for m in payload["models"]}
        self.assertTrue(models[BENEISH_MODEL_ID]["score_enabled"])
        self.assertTrue(models[DECHOW_MODEL_ID]["score_enabled"])
        self.assertEqual([t["variable"] for t in models[BENEISH_MODEL_ID]["terms"]],
                         ["DSRI", "GMI", "AQI", "SGI", "DEPI", "SGAI", "LVGI", "TATA"])
        self.assertEqual([t["coefficient"] for t in models[BENEISH_MODEL_ID]["terms"]],
                         ["0.920", "0.528", "0.404", "0.892", "0.115", "-0.172", "-0.327", "4.679"])
        self.assertEqual(models[BENEISH_MODEL_ID]["intercept"]["value"], "-4.840")
        self.assertEqual([t["coefficient"] for t in models[DECHOW_MODEL_ID]["terms"]],
                         ["0.790", "2.518", "1.191", "1.979", "0.171", "-0.932", "1.029"])
        self.assertEqual(models[DECHOW_MODEL_ID]["intercept"]["value"], "-7.893")
        self.assertEqual(models[DECHOW_MODEL_ID]["scaling"]["unconditional_probability"], "0.0037")
        for model in models.values():
            self.assertEqual(model["approval_status"], "DRAFT_PENDING_METHOD_OWNER_REVIEW")
            for term in model["terms"]:
                self.assertTrue(term["location"] and term["verification"].startswith("source_verified"))
        # the 1999 AQI has no securities term (later variants add it)
        self.assertNotIn("securities", models[BENEISH_MODEL_ID]["terms"][2]["definition"].lower())
        self.assertFalse(payload["paper_sources"]["dechow_2011"]["verified_text"]["redistributed"])

    def test_unverified_or_wrong_coefficients_fail_closed(self) -> None:
        values = {name: Decimal(1) for name in beneish_1999.COMPONENTS}
        secondary = model_spec(BENEISH_MODEL_ID)
        secondary["terms"][0]["verification"] = "secondary_only"
        self.assertEqual(beneish_1999.score(values, secondary)["status"], "model_formula_unverified")
        self.assertIsNone(beneish_1999.score(values, secondary)["score"])
        guessed = model_spec(DECHOW_MODEL_ID)
        guessed["scaling"]["source"]["verification"] = "unverified"
        dechow_values = {name: Decimal(0) for name in dechow_2011.VARIABLES}
        self.assertEqual(dechow_2011.score(dechow_values, guessed)["status"], "model_formula_unverified")
        not_numeric = model_spec(DECHOW_MODEL_ID)
        not_numeric["intercept"]["value"] = "about -7.9"
        self.assertIn("intercept:value_not_exact_decimal", verification_problems(not_numeric))
        # reusing the Beneish coefficient table for the Dechow variant is refused
        reused = model_spec(DECHOW_MODEL_ID)
        reused["terms"] = copy.deepcopy(model_spec(BENEISH_MODEL_ID)["terms"])
        self.assertEqual(dechow_2011.score(dechow_values, reused)["status"], "model_formula_unverified")
        # a coefficient set missing one variable is never scored
        short = model_spec(BENEISH_MODEL_ID)
        short["terms"] = short["terms"][:5]
        self.assertEqual(beneish_1999.score(values, short)["status"], "model_formula_unverified")


# ------------------------------------------------------------------------------------------- paper mathematics
class PaperMathematicsTests(unittest.TestCase):
    def test_dechow_reproduces_the_published_enron_example(self) -> None:
        example = model_spec(DECHOW_MODEL_ID)["reference_example"]
        result = dechow_2011.score({k: Decimal(v) for k, v in example["inputs"].items()})
        self.assertEqual(Decimal(result["predicted_value_exact"]).quantize(Decimal("0.001")), Decimal("-4.575"))
        self.assertEqual(Decimal(result["probability_exact"]).quantize(Decimal("0.00001")), Decimal("0.01020"))
        self.assertEqual(Decimal(result["score_exact"]).quantize(Decimal("0.01")), Decimal("2.76"))

    def test_logistic_and_probit_are_stable_at_extremes(self) -> None:
        for value in ("-1000", "-50", "0", "50", "1000"):
            probability = lc.logistic(Decimal(value))
            self.assertTrue(Decimal(0) <= probability <= Decimal(1))
        self.assertEqual(lc.logistic(Decimal(0)), Decimal("0.5"))
        self.assertEqual(lc.normal_cdf(Decimal("-50")), ("<1e-300", True))
        self.assertEqual(lc.normal_cdf(Decimal("0")), ("0.5", False))
        # the paper's own cut-off pairing: probability .0376 corresponds to a score of about -1.78 (p. 17)
        self.assertEqual(round(float(lc.normal_cdf(Decimal("-1.78"))[0]), 3), 0.038)

    def test_beneish_hand_example_through_the_full_engine(self) -> None:
        result = result_for(literature_snapshot(), BENEISH_MODEL_ID)
        self.assertEqual(result["status"], "computed", result.get("missing_inputs"))
        components = {c["variable"]: Decimal(c["value_exact"]) for c in result["components"]}
        expected = {"DSRI": Fraction(5, 4), "GMI": Fraction(8, 7), "AQI": Fraction(17, 18), "SGI": Fraction(6, 5),
                    "DEPI": Fraction(10, 7), "SGAI": Fraction(11, 10), "LVGI": Fraction(5, 4), "TATA": Fraction(-3, 80)}
        for name, fraction in expected.items():
            self.assertAlmostEqual(components[name], Decimal(fraction.numerator) / Decimal(fraction.denominator),
                                   places=25, msg=name)
        coefficients = {"DSRI": "0.920", "GMI": "0.528", "AQI": "0.404", "SGI": "0.892", "DEPI": "0.115",
                        "SGAI": "-0.172", "LVGI": "-0.327", "TATA": "4.679"}
        m_fraction = Fraction("-4.840") + sum(Fraction(coefficients[k]) * v for k, v in expected.items())
        self.assertEqual(result["score"], "-2.243743")
        self.assertEqual(Decimal(result["score_exact"]).quantize(Decimal("1e-20")),
                         (Decimal(m_fraction.numerator) / Decimal(m_fraction.denominator)).quantize(Decimal("1e-20")))

    def test_dechow_fixture_components_are_independently_derived(self) -> None:
        result = result_for(literature_snapshot(), DECHOW_MODEL_ID)
        self.assertEqual(result["status"], "computed", result.get("missing_inputs"))
        c = {x["variable"]: Decimal(x["value_exact"]) for x in result["components"]}
        avg_t, avg_t1 = Fraction(1200 + 1000, 2), Fraction(1000 + 900, 2)
        # WC = (CA - CHE) - (CL - DLC); NCO = (TA - CA - IVAO) - (TL - CL - LTD); FIN = (STI + IVAO) - (LTD + DLC + PS)
        def wc(d):
            return (d["CurrentAssets"] - d["CashAndCashEquivalents"]) - (
                d["CurrentLiabilities"] - d["ShorttermBorrowings"] - d["LongtermLiabilitiesCurrentPortion"])

        def nco(d):
            return (d["Assets"] - d["CurrentAssets"] - d["NoncurrentAvailableForSaleFinancialAssets"]) - (
                d["Liabilities"] - d["CurrentLiabilities"] - d["LongtermBorrowings"])

        def fin(d):  # preferred stock = CapitalStock - OrdinaryShare = 0 in the fixture
            return d["NoncurrentAvailableForSaleFinancialAssets"] - (
                d["LongtermBorrowings"] + d["ShorttermBorrowings"] + d["LongtermLiabilitiesCurrentPortion"] + 0)
        expected = {
            "rsst_acc": Fraction((wc(T_0) - wc(T_1)) + (nco(T_0) - nco(T_1)) + (fin(T_0) - fin(T_1))) / avg_t,
            "ch_rec": Fraction(150 - 100) / avg_t, "ch_inv": Fraction(150 - 120) / avg_t,
            "soft_assets": Fraction(1200 - 360 - 60, 1200),
            "ch_cs": (Fraction(1200 - (150 - 100)) - Fraction(1000 - (100 - 80))) / Fraction(1000 - (100 - 80)),
            "ch_roa": Fraction(66) / avg_t - Fraction(40) / avg_t1, "issue": Fraction(1)}
        for name, fraction in expected.items():
            self.assertAlmostEqual(c[name], Decimal(fraction.numerator) / Decimal(fraction.denominator), places=25,
                                   msg=name)
        self.assertEqual([e["line_key"] for e in result["components"][-1]["evidence"]], ["ProceedsFromLongTermDebt"])
        self.assertIsNotNone(result["score"])
        self.assertTrue(result["scaling_provenance"]["scaling"]["source"]["location"].startswith("CAR p. 61"))


# ------------------------------------------------------------------------------------------- incompleteness
class GracefulIncompletenessTests(unittest.TestCase):
    def test_missing_component_gives_a_component_panel_never_a_partial_score(self) -> None:
        result = result_for(literature_snapshot(fixture_observations(drop={"DepreciationExpense"})), BENEISH_MODEL_ID)
        self.assertEqual(result["status"], "not_computable")
        self.assertIsNone(result["score"])
        statuses = {c["variable"]: c["status"] for c in result["components"]}
        self.assertEqual(statuses["DEPI"], "not_computable")
        self.assertEqual(statuses["TATA"], "not_computable")
        self.assertEqual(statuses["DSRI"], "computed")
        self.assertIn("partial sum is not an M-Score", result["component_panel_note"])
        self.assertTrue(any(m["metric"] == "depreciation" for m in result["missing_inputs"]))

    def test_missing_t_minus_2_and_unknown_issuance_are_explicit(self) -> None:
        no_t2 = [o for o in fixture_observations() if not (o["filing_version_id"] == "F2014" and o["period_end"] == "2013-12-31")]
        result = result_for(literature_snapshot(no_t2), DECHOW_MODEL_ID)
        self.assertEqual(result["status"], "not_computable")
        self.assertIn("missing_t_minus_2", {m["status"] for m in result["missing_inputs"]})
        self.assertEqual({m["component"] for m in result["missing_inputs"] if m["status"] == "missing_t_minus_2"},
                         {"ch_cs", "ch_roa"})
        no_issue = fixture_observations(overrides={"ProceedsFromLongTermDebt": 0})
        issue = next(c for c in result_for(literature_snapshot(no_issue), DECHOW_MODEL_ID)["components"]
                     if c["variable"] == "issue")
        self.assertEqual(issue["status"], "not_computable")  # a zero / absent issuance line is UNKNOWN, never 0
        self.assertEqual(issue["reasons"][0]["code"], "issuance_absence_not_evidenced")
        self.assertIsNone(issue["value"])

    def test_zero_and_negative_denominators_are_explicit(self) -> None:
        zero = result_for(literature_snapshot(fixture_observations(overrides={"OperatingRevenue": 0})), BENEISH_MODEL_ID)
        reasons = {r["code"] for c in zero["components"] for r in c["reasons"]}
        self.assertIn("invalid_denominator_zero", reasons)
        self.assertIsNone(zero["score"])
        negative = result_for(literature_snapshot(fixture_observations(overrides={"Assets": -5})), DECHOW_MODEL_ID)
        self.assertIn("invalid_denominator_negative", {r["code"] for c in negative["components"] for r in c["reasons"]})
        self.assertIsNone(negative["score"])

    def test_reported_zero_is_a_value_and_missing_line_is_not(self) -> None:
        lines = FilingLines([obs("F2015", 2015, "CurrentAssets", 10), obs("F2015", 2015, "CurrentTaxLiabilities", 0),
                             obs("F2015", 2015, "CurrentLiabilities", 5)])
        self.assertEqual(assemble(lines, "TIFRS", "income_tax_payable", "I:2015-12-31").value, Decimal(0))
        missing = assemble(lines, "TIFRS", "inventory", "I:2015-12-31")
        self.assertEqual((missing.status, missing.value), ("missing_input", None))
        no_anchor = FilingLines([obs("F2015", 2015, "ShorttermBorrowings", 3)])
        self.assertEqual(assemble(no_anchor, "TIFRS", "short_term_debt", "I:2015-12-31").status, "anchor_missing")

    def test_accounting_regime_break_is_never_bridged(self) -> None:
        versions = [filing("F2015", 2015), filing("F2014", 2014)]
        rows = [o if o["filing_version_id"] != "F2014" else {**o, "accounting_framework": "TW_GAAP"}
                for o in fixture_observations()]
        snapshot = literature_snapshot(rows, versions=versions)
        for record in snapshot.literature_filings:
            if record["fiscal_year"] == 2014 and record["filing"]:
                record["filing"]["accounting_framework"] = "TW_GAAP"
        result = result_for(snapshot, DECHOW_MODEL_ID)
        self.assertEqual(result["status"], "not_computable")
        self.assertTrue(any("accounting_regime_break" in r for m in result["missing_inputs"] for r in m["reasons"]))


# ------------------------------------------------------------------------------------------- modes, versions, F05
class ModeVersionTests(unittest.TestCase):
    def test_strict_admits_no_literature_observation_and_reconciliation_is_refused(self) -> None:
        strict = literature_snapshot(context=STRICT)
        self.assertEqual(strict.literature_observations, [])
        computed = compute_models(strict, [BENEISH_MODEL_ID, DECHOW_MODEL_ID])
        self.assertEqual(computed["status"], "insufficient_point_in_time_evidence")
        for rows in computed["results"].values():
            self.assertTrue(all(r["score"] is None and r["status"] == "insufficient_point_in_time_evidence" for r in rows))
        with self.assertRaises(ModeNotSupportedError):
            literature_snapshot(context=RECON)
        with self.assertRaises(AnalysisRequestError):
            literature_snapshot(policy="earliest_available")

    def test_no_hidden_fallback_to_an_older_version(self) -> None:
        versions = [filing("F2015", 2015, "original"), filing("R2015", 2015, "restated")]
        selection = select_filings(versions, {"F2015"}, range(2015, 2016), "latest_available", "1785")[0]
        self.assertIsNone(selection["filing"])  # the restated version is unreadable; the original is not used instead
        self.assertTrue(selection["problem"].startswith("source_unavailable"))
        original = select_filings(versions, {"F2015"}, range(2015, 2016), "original_only", "1785")[0]
        self.assertEqual(original["filing"]["filing_version_id"], "F2015")
        ambiguous = select_filings([filing("A2015", 2015), filing("B2015", 2015)], {"A2015", "B2015"},
                                   range(2015, 2016), "latest_available", "1785")[0]
        self.assertTrue(ambiguous["problem"].startswith("ambiguous_version"))

    def test_conflicting_duplicate_line_values_are_ambiguous(self) -> None:
        rows = fixture_observations() + [obs("F2015", 2015, "AccountsReceivableNet", 999)]
        result = result_for(literature_snapshot(rows), BENEISH_MODEL_ID)
        self.assertIsNone(result["score"])
        self.assertIn("ambiguous_version", {m["status"] for m in result["missing_inputs"]})

    def test_permuting_inputs_never_changes_digest_or_result(self) -> None:
        rows = fixture_observations()
        baseline = literature_snapshot(rows)
        reference = compute_models(baseline, [BENEISH_MODEL_ID, DECHOW_MODEL_ID])
        for seed in range(3):
            shuffled = rows[:]
            random.Random(seed).shuffle(shuffled)
            snapshot = literature_snapshot(shuffled, versions=list(reversed([filing("F2015", 2015), filing("F2014", 2014)])))
            self.assertEqual(snapshot.input_digest, baseline.input_digest)
            self.assertEqual(compute_models(snapshot, [BENEISH_MODEL_ID, DECHOW_MODEL_ID])["results"], reference["results"])

    def test_any_changed_extra_metric_changes_the_input_digest(self) -> None:
        base = literature_snapshot()
        changed = literature_snapshot(fixture_observations(overrides={"AmortizationExpense": 11}))
        self.assertNotEqual(base.input_digest, changed.input_digest)
        self.assertNotEqual(base.dependency_digests()["literature_observations"],
                            changed.dependency_digests()["literature_observations"])

    def test_comparison_pairs_only_same_observation_and_reports_no_performance_metrics(self) -> None:
        computed = compute_models(literature_snapshot(), [BENEISH_MODEL_ID, DECHOW_MODEL_ID])
        result = compare(computed)
        self.assertEqual(result["coverage"]["comparable_pairs"], 1)
        self.assertIsNone(result["performance_metrics"])
        incomplete = compare(compute_models(literature_snapshot(fixture_observations(drop={"DepreciationExpense"})),
                                            [BENEISH_MODEL_ID, DECHOW_MODEL_ID]))
        self.assertEqual(incomplete["coverage"]["comparable_pairs"], 0)
        self.assertEqual(incomplete["concordance"]["denominator"], 0)
        self.assertIn("beneish:not_computable", incomplete["pairs"][0]["reasons"])


class FactSelectionF05Tests(unittest.TestCase):
    def fact(self, version, value, vtype="original", sha="a"):
        return {"fact_id": f"f-{version}", "period": "2025FY", "fiscal_year": 2025, "statement_scope": "consolidated",
                "metric_code": "total_assets", "value": value, "unit": "TWD", "accounting_framework": "TIFRS",
                "filing_version_id": version, "filing_version_type": vtype, "taxonomy_concept": "ifrs:Assets",
                "artifact_sha256": sha * 64, "artifact_evidence_status": "E0", "artifact_url": None}

    def test_versions_conflicting_hashes_and_equal_amounts_are_ambiguous_in_any_order(self) -> None:
        cases = {"different_values": [self.fact("v1", "1"), self.fact("v2", "2", "restated")],
                 "equal_values_different_identity": [self.fact("v1", "1"), self.fact("v2", "1", "restated")],
                 "same_version_conflicting_hash": [self.fact("v1", "1", sha="a"), self.fact("v1", "1", sha="b")]}
        for name, facts in cases.items():
            for ordering in (facts, list(reversed(facts))):
                index = build_index(ordering)
                self.assertEqual(index.lookup(("2025FY", "consolidated", "total_assets")),
                                 (None, "ambiguous_filed_fact_versions"), name)
        identical = build_index([self.fact("v1", "1"), {**self.fact("v1", "1"), "fact_id": "dup"}])
        self.assertIsNotNone(identical.lookup(("2025FY", "consolidated", "total_assets"))[0])

    def test_reconciliation_reports_ambiguity_instead_of_last_writer_wins(self) -> None:
        notice = {"disclosure_kind": "annual_financial_report_board_approval", "period": "2025FY", "fiscal_year": 2025,
                  "statement_scope": "consolidated", "accounting_framework": "TIFRS", "source_label": "資產總計",
                  "canonical_metric": "total_assets", "value": "1", "published_unit": "TWD", "normalized_value": "1",
                  "normalized_unit": "TWD", "disclosed_at": "2026-03-01T00:00:00+08:00", "availability_status": "verified",
                  "announcement_key": "k", "content_hash": "c" * 64, "source_url": None}
        facts = [self.fact("v1", "1"), self.fact("v2", "2", "restated")]
        outcomes = []
        for ordering in (facts, list(reversed(facts))):
            snapshot = InputSnapshot(ticker="1785", context=RECON, start_year=2025, end_year=2025,
                                     version_policy="latest_available", backend_name="unit", facts=ordering,
                                     disclosed_values=[notice])
            outcomes.append(compare_board_notices(snapshot)[0])
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(outcomes[0]["outcome"], "not_comparable")
        self.assertEqual(outcomes[0]["reasons"], ["ambiguous_filed_fact_versions"])


# ------------------------------------------------------------------------------------------- extraction & store
FY2012_BALANCE_LINES = (
    "1100 現金及約當現金 二/四.1 $646,719 3.00 $696,017 3.49 2100 短期借款 四.11 $1,039,288 4.81 $1,529,301 7.67\n"
    """1140 應收帳款淨額 二/四.3/五 1,708,039 7.91 1,902,656 9.54 2120 應付票據 七 228,759 1.06 71,843 0.36
2110 應付短期票券淨額 四.12 499,868 2.31 -           -
15X9 減：累計折舊 (2,823,738)(13.08) (2,240,337)(11.23)3110    普通股股本 4,090,603 18.94 3,739,481 18.75
資 產 總 計 $19,943,634 100.00 $16,766,322 100.00 負債及股東權益 總計 $19,943,634 100.00 $16,766,322 100.00
5000 營業成本 四.4及26/五 (72,415,098) (97.89) (69,039,732) (96.44)""")
FY2012_CASHFLOW_LINES = """  各項折舊(含出租資產) 629,767 534,497 買回海外可轉換公司債 (108,843) (441,093)
  應付公司債(減少)增加 (500,000) 3,438,782 長期借款增加 1,915,539 1,041,923
  營業活動之淨現金流入(出) 396,221 (1,169,422)"""


class ExtractionParserTests(unittest.TestCase):
    def test_two_column_account_code_rows(self) -> None:
        rows = parse_code_rows(FY2012_BALANCE_LINES, ("1100", "1140", "2100", "2110", "3110", "5000"))
        self.assertEqual((rows["1100"]["current"], rows["1100"]["comparative"]), ("$646,719", "$696,017"))
        self.assertEqual((rows["2100"]["current"], rows["2100"]["comparative"]), ("$1,039,288", "$1,529,301"))
        self.assertEqual((rows["2110"]["current"], rows["2110"]["comparative"]), ("499,868", "-"))
        self.assertEqual((rows["3110"]["current"], rows["3110"]["comparative"]), ("4,090,603", "3,739,481"))
        self.assertEqual(rows["5000"]["current"], "(72,415,098)")  # note refs like 四.4及26 are never read as amounts
        totals = parse_total_rows(FY2012_BALANCE_LINES)
        self.assertEqual((totals["資產總計"]["current"], totals["資產總計"]["comparative"]), ("$19,943,634", "$16,766,322"))

    def test_cash_flow_labels_and_roc_years(self) -> None:
        rows = parse_label_rows(FY2012_CASHFLOW_LINES, ("各項折舊(含出租資產)", "長期借款增加", "應付公司債(減少)增加",
                                                        "營業活動之淨現金流入(出)", "營業活動之淨現金流入"))
        self.assertEqual(rows["各項折舊(含出租資產)"]["current"], "629,767")
        self.assertEqual(rows["應付公司債(減少)增加"]["current"], "(500,000)")
        self.assertEqual(rows["長期借款增加"]["comparative"], "1,041,923")
        self.assertIn("營業活動之淨現金流入(出)", rows)
        self.assertNotIn("營業活動之淨現金流入", rows)  # the longer exact label wins; no partial-label match
        self.assertEqual(roc_year("合併資產負債表 民國一０一年 十二月三十一日"), 101)
        self.assertEqual(roc_year("民國一００年"), 100)


class LiteratureStoreTests(unittest.TestCase):
    def test_append_only_idempotent_and_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lit.sqlite3"
            store = LiteratureInputStore(path)
            rows = fixture_observations()[:5]
            self.assertEqual(store.record_observations(rows), 5)
            self.assertEqual(store.record_observations(rows), 0)
            with self.assertRaises(LiteratureStoreIntegrityError):
                store.record_observations([{**rows[0], "value": "123456"}])
            connection = sqlite3.connect(path)
            for statement in ("UPDATE literature_line_observations SET value = '0'",
                              "DELETE FROM literature_line_observations"):
                with self.assertRaises(sqlite3.DatabaseError):
                    connection.execute(statement)
            connection.close()
            self.assertEqual(len(LiteratureInputStore(path, read_only=True).list_observations("1785")), 5)
            with self.assertRaises(LiteratureStoreIntegrityError):
                LiteratureInputStore(path, protected=(str(path),))
            with self.assertRaises(LiteratureInputsUnavailable):
                LiteratureInputStore(Path(tmp) / "absent.sqlite3", read_only=True)


class LiteratureRunPersistenceMockTests(unittest.TestCase):
    """MOCK cloud tier: a literature run is mirrored create-only with its score projection (same read view)."""

    def test_firestore_mirror_parity_for_literature_runs(self) -> None:
        from app.services.financial_research.result_store import (
            FirestoreResearchResultStore,
            SqliteResearchResultStore,
            build_run,
        )
        from tests.historical_cloud_fakes import FakeFirestoreClient

        snapshot = literature_snapshot()
        output = compute_models(snapshot, [BENEISH_MODEL_ID, DECHOW_MODEL_ID])
        run = build_run(result_kind="literature_models", method_version="m", method_ids=["m"],
                        approval_status="DRAFT_PENDING_METHOD_OWNER_REVIEW", snapshot=snapshot.describe(),
                        parameters={"model_ids": [BENEISH_MODEL_ID, DECHOW_MODEL_ID]}, output=output)
        client = FakeFirestoreClient()
        cloud = FirestoreResearchResultStore(client, prefix="historical_research_results")
        self.assertEqual(cloud.record_run(run), (run["run_id"], True))
        self.assertEqual(cloud.record_run(run), (run["run_id"], False))
        with tempfile.TemporaryDirectory() as tmp:
            local = SqliteResearchResultStore(Path(tmp) / "r.sqlite3")
            local.record_run(run)
            strip = lambda view: {k: v for k, v in view.items() if k != "created_at"}  # noqa: E731
            self.assertEqual(strip(local.get_run(run["run_id"])), strip(cloud.get_run(run["run_id"])))
            self.assertEqual(local.projection_counts(run["run_id"])["research_literature_scores"], 2)


# ------------------------------------------------------------------------------------------- REAL tier
@unittest.skipUnless(HAS_REAL, "approved local 1785 archive not present")
class RealLiteratureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from scripts.ingest_literature_inputs import run

        from app.services.financial_research.service import ResearchConfig, ResearchService

        cls.tmp = tempfile.TemporaryDirectory()
        cls.store_path = str(Path(cls.tmp.name) / "literature_inputs.sqlite3")
        cls.report = run("1785", database=str(DATABASE), raw_root=str(RAW), store_path=cls.store_path, dry_run=False)
        cls.service = ResearchService(ResearchConfig(database=str(DATABASE), raw_root=str(RAW),
                                                     conference_root=str(ROOT / "data" / "historical-conference-pdfs"),
                                                     literature_database=cls.store_path))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def test_extraction_is_bounded_deterministic_and_reports_unreadable_versions(self) -> None:
        self.assertEqual(self.report["network_requests"], 0)
        self.assertEqual(self.report["observations"], 4393)
        self.assertEqual(self.report["observation_digest"],
                         "1dc6ef8c4125781f8c594a6f801c8fd61013da66ad9891674dec675392748d93")
        self.assertEqual(self.report["status_counts"]["statement_pages_not_machine_readable"], 12)
        for detail in self.report["artifacts_detail"]:
            if detail["source_kind"] == "official_pdf" and detail["status"] == "extracted":
                self.assertIn(detail["fiscal_year"], (2011, 2012))
                self.assertTrue(all(v == "verified" for v in detail["arithmetic_checks"].values()))

    def test_retrospective_latest_series(self) -> None:
        computed = self.service.literature_compute("1785", RETRO, model_ids=[BENEISH_MODEL_ID, DECHOW_MODEL_ID],
                                                   start_year=2011, end_year=2025, version_policy="latest_available")
        beneish = {r["fiscal_year"]: r for r in computed["results"][BENEISH_MODEL_ID]}
        dechow = {r["fiscal_year"]: r for r in computed["results"][DECHOW_MODEL_ID]}
        self.assertEqual([y for y, r in beneish.items() if r["status"] == "computed"], list(range(2013, 2026)))
        self.assertEqual({beneish[y]["status"] for y in (2011, 2012)}, {"source_unavailable"})
        self.assertEqual(beneish[2015]["score"], "-2.240182")
        self.assertEqual(dechow[2015]["score"], "0.890320")
        self.assertEqual(dechow[2018]["status"], "not_computable")  # no positive issuance line in FY2018
        self.assertIn("issuance_absence_not_evidenced", {m["status"] for m in dechow[2018]["missing_inputs"]})
        self.assertTrue(all(r["hindsight"] for r in beneish.values()))
        self.assertTrue(any("restated" == r["observation"]["filing_version_type"] for r in beneish.values()
                            if r["fiscal_year"] == 2014))

    def test_original_filing_series_and_t_minus_2(self) -> None:
        computed = self.service.literature_compute("1785", RETRO, model_ids=[BENEISH_MODEL_ID, DECHOW_MODEL_ID],
                                                   start_year=2011, end_year=2015, version_policy="original_only")
        beneish = {r["fiscal_year"]: r for r in computed["results"][BENEISH_MODEL_ID]}
        dechow = {r["fiscal_year"]: r for r in computed["results"][DECHOW_MODEL_ID]}
        self.assertEqual((beneish[2011]["score"], beneish[2012]["score"]), ("-1.730106", "-2.286269"))
        self.assertEqual(beneish[2011]["observation"]["accounting_framework"], "TW_GAAP")
        self.assertEqual(dechow[2012]["score"], "0.892005")
        self.assertEqual({m["status"] for m in dechow[2011]["missing_inputs"]}, {"missing_t_minus_2"})
        for year in (2013, 2014, 2015):  # original TIFRS reports: statement pages are images only
            self.assertEqual(beneish[year]["status"], "source_unavailable")

    def test_strict_pre_event_and_one_second_boundary(self) -> None:
        for cutoff in ("2016-05-13T00:00:00+08:00", "2016-11-13T21:26:22+08:00", "2016-11-13T21:26:23+08:00"):
            computed = self.service.literature_compute(
                "1785", build_context("STRICT_AS_OF", cutoff), model_ids=[BENEISH_MODEL_ID, DECHOW_MODEL_ID],
                start_year=2011, end_year=2015, version_policy="latest_available")
            self.assertEqual(computed["status"], "insufficient_point_in_time_evidence", cutoff)
            self.assertEqual(computed["input_snapshot"]["literature_observation_count"], 0)
            self.assertTrue(all(r["score"] is None for rows in computed["results"].values() for r in rows))
        facts = self.service.backend.list_facts("1785", 2011, 2025)
        self.assertEqual(len(facts), 234)
        self.assertEqual(sum(1 for f in facts if f["point_in_time_eligible"]), 67)
        self.assertEqual(len(self.service.backend.list_restatement_comparisons("1785")), 158)

    def test_runs_are_reproducible_and_method_changes_are_distinguished(self) -> None:
        run = self.service.build_run("literature_comparison", "1785", RETRO, start_year=2011, end_year=2025,
                                     version_policy="latest_available")
        again = self.service.build_run("literature_comparison", "1785", RETRO, start_year=2011, end_year=2025,
                                       version_policy="latest_available")
        self.assertEqual((run["run_id"], run["output_digest"]), (again["run_id"], again["output_digest"]))
        stored = {**run, "snapshot": run["snapshot"]}
        self.assertEqual(self.service.verify_run(stored)["status"], "reproducible")
        legacy = {**run, "method_version": "dechow_2011_model1_v0+legacy"}
        verdict = self.service.verify_run(legacy)
        self.assertEqual((verdict["status"], verdict["legacy_method_not_reproducible"], verdict["source_inputs_unchanged"]),
                         ("method_version_changed", True, True))
        mutated = {**run, "input_digest": "0" * 64}
        self.assertEqual(self.service.verify_run(mutated)["status"], "inputs_changed_since_run")
        with tempfile.TemporaryDirectory() as tmp:
            from app.services.financial_research.result_store import SqliteResearchResultStore

            store = SqliteResearchResultStore(Path(tmp) / "results.sqlite3", protected=(str(DATABASE),))
            self.assertEqual(store.record_run(run), (run["run_id"], True))
            self.assertEqual(store.record_run(run), (run["run_id"], False))
            self.assertEqual(store.projection_counts(run["run_id"])["research_literature_scores"], 30)
            self.assertEqual(self.service.verify_run(store.get_run(run["run_id"]))["status"], "reproducible")

    def test_reconciliation_never_uses_literature_scores(self) -> None:
        with self.assertRaises(ModeNotSupportedError):
            self.service.literature_compare("1785", RECON, start_year=2025, end_year=2025, version_policy="latest_available")
        discrepancies = self.service.discrepancies("1785", RECON)
        self.assertNotIn("beneish", str(discrepancies).lower())
        self.assertNotIn("dechow", str(discrepancies).lower())


if __name__ == "__main__":
    unittest.main()
