"""Integrity Workbench Phase 1: F1 / F2 / F4 Decimal screens, alignment and point-in-time admission (SYNTHETIC)."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest import mock

from app.services.integrity import alignment as al
from app.services.integrity import financial_checks as fc
from app.services.integrity.adapters import FactsAdapter
from tests.integrity_fixtures import BASE_DATA, FakeRepository, annual_rows, fact, mops_url

TICKER = "2303"


def index_of(rows):
    return FactsAdapter(FakeRepository(rows)).collect(TICKER)


def data(**overrides):
    merged = {metric: dict(years) for metric, years in BASE_DATA.items()}
    for metric, years in overrides.items():
        merged.setdefault(metric, {}).update(years)
    return merged


class DecimalAlignmentTests(unittest.TestCase):
    def test_float_storage_goes_through_repr_not_binary_expansion(self) -> None:
        self.assertEqual(al.to_decimal(0.1), Decimal("0.1"))
        self.assertEqual(al.to_decimal(530585886000.0), Decimal("530585886000.0"))
        self.assertEqual(al.text(Decimal("5.30585886E+11")), "530585886000")
        self.assertEqual(al.text(Decimal("0.0000010")), "0.000001")
        self.assertIsNone(al.to_decimal(float("nan")))
        self.assertIsNone(al.to_decimal(True))

    def test_unit_scales_and_unknown_units(self) -> None:
        self.assertEqual(al.to_twd(Decimal("2404483690"), "新台幣仟元"), Decimal("2404483690000"))
        self.assertEqual(al.to_twd(Decimal("12"), "新台幣元"), Decimal("12"))
        self.assertIsNone(al.to_twd(Decimal("12"), "USD"))
        self.assertIsNone(al.to_twd(Decimal("12"), None))

    def test_mops_identity_scope_and_filing_policy(self) -> None:
        identity = al.mops_filing_identity(mops_url("2454", 2024))
        self.assertEqual((identity["filing_fiscal_year"], identity["season"], identity["scope"]), (2024, 4, "consolidated"))
        self.assertEqual(al.derive_scope("unknown", mops_url("2454", 2024)),
                         ("consolidated", "mops_report_id_C_reviewed_sample_assumption"))
        self.assertEqual(al.derive_scope("unknown", mops_url("2454", 2024, report_id="A"))[0], "unknown")
        self.assertEqual(al.derive_scope("individual", mops_url("2454", 2024)), ("individual", "stored_statement_scope"))
        self.assertEqual(al.derive_scope(None, "https://example.test/x")[0], "unknown")
        self.assertEqual(al.filing_policy("2024FY", mops_url("2454", 2024)), "as_filed_own_year")
        self.assertEqual(al.filing_policy("2023FY", mops_url("2454", 2024)), "comparative_from_FY2024_filing")
        self.assertIsNone(al.filing_policy("2026Q2", mops_url("2454", 2026, season=2)))

    def test_periods(self) -> None:
        self.assertEqual(al.parse_period("2024FY")["end"], "2024-12-31")
        self.assertEqual(al.parse_period("2026Q2")["period_type"], "quarter")
        self.assertEqual(al.parse_period("FY24")["period_type"], "unknown")


class PointInTimeTests(unittest.TestCase):
    CUTOFF = datetime(2025, 3, 1, tzinfo=timezone(timedelta(hours=8)))

    def test_unknown_naive_future_and_later_versions_never_enter_strict(self) -> None:
        cases = {
            "effective_available_at_unknown": {"effective_available_at": None, "effective_available_at_precision": "unknown"},
            "effective_available_at_timezone_unknown": {"effective_available_at": "2025-01-01T10:00:00",
                                                        "effective_available_at_precision": "exact_instant"},
            "available_at_or_after_cutoff": {"effective_available_at": "2025-03-01T00:00:00+08:00",
                                             "effective_available_at_precision": "exact_instant"},
            "later_filing_version_without_publication_time": {"filing_policy": "comparative_from_FY2025_filing"},
            "effective_available_at_unparseable": {"effective_available_at": "soon",
                                                   "effective_available_at_precision": "exact_instant"},
        }
        for reason, record in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(al.strict_admissible(record, self.CUTOFF), (False, reason))

    def test_cutoff_is_exclusive_and_date_precision_is_end_of_day_taipei(self) -> None:
        before = {"effective_available_at": "2025-02-28T23:59:59+08:00", "effective_available_at_precision": "exact_instant"}
        self.assertEqual(al.strict_admissible(before, self.CUTOFF), (True, "available_before_cutoff"))
        same_day = {"effective_available_at": "2025-03-01", "effective_available_at_precision": "date"}
        self.assertFalse(al.strict_admissible(same_day, self.CUTOFF)[0])
        prior_day = {"effective_available_at": "2025-02-28", "effective_available_at_precision": "date"}
        self.assertFalse(al.strict_admissible(prior_day, self.CUTOFF)[0])  # end of 02-28 Taipei == cutoff (exclusive)
        self.assertTrue(al.strict_admissible({"effective_available_at": "2025-02-27",
                                              "effective_available_at_precision": "date"}, self.CUTOFF)[0])

    def test_naive_cutoff_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            al.strict_admissible({}, datetime(2025, 3, 1))

    def test_pipeline_facts_are_never_pit_eligible(self) -> None:
        facts = index_of(annual_rows(TICKER, BASE_DATA))
        self.assertTrue(facts["index"])
        for record in facts["index"].values():
            self.assertFalse(record["pit_eligible"])
            self.assertEqual(record["pit_reason"], "effective_available_at_unknown")
            self.assertIn("published_at", record["missing_fields"])


class RevenueReceivablesTests(unittest.TestCase):
    def test_exact_decimal_gap_and_divergence_status(self) -> None:
        finding = fc.check_revenue_receivables(index_of(annual_rows(TICKER, BASE_DATA))["index"])
        self.assertEqual(finding["status"], "descriptive_divergence")
        self.assertEqual(finding["period"], "2025FY")
        self.assertEqual(finding["review_queue"], "requires_verification")
        c = finding["computed"]
        self.assertEqual((c["sales_growth"], c["ar_growth"], c["gap"], c["gap_percentage_points"]),
                         ("0.1", "0.5", "0.4", "40"))
        self.assertEqual(c["delta_receivables_twd"], "100")
        self.assertEqual(c["receivables_to_revenue_relative_change"], "0.363636")
        self.assertEqual(c["sensitivity"], {"0.1": True, "0.2": True, "0.3": True})
        self.assertFalse(finding["heuristic"]["calibrated"])
        self.assertIn("beneish_1999_full8_v1:DSRI", finding["not_independent_of"])
        self.assertEqual([p["status"] for p in finding["series"]], ["within_screening_heuristic", "descriptive_divergence"])

    def test_real_magnitude_values_are_exact(self) -> None:
        rows = annual_rows(TICKER, {"revenue": {2024: 530585886000.0, 2025: 595965682000.0},
                                    "accounts_receivable": {2024: 43944786000.0, 2025: 62056117000.0}})
        c = fc.check_revenue_receivables(index_of(rows)["index"])["computed"]
        self.assertEqual(c["sales_growth"], "0.123222")
        self.assertEqual(c["ar_growth"], "0.412138")
        self.assertEqual(c["gap_percentage_points"], "28.89")
        self.assertEqual(c["delta_revenue_twd"], "65379796000")

    def test_heuristic_threshold_is_configurable_and_reported(self) -> None:
        with mock.patch.dict(os.environ, {fc.F1_ENV: "0.5"}):
            finding = fc.check_revenue_receivables(index_of(annual_rows(TICKER, BASE_DATA))["index"])
        self.assertEqual(finding["status"], "within_screening_heuristic")
        self.assertIsNone(finding["review_queue"])
        self.assertEqual((finding["heuristic"]["threshold"], finding["heuristic"]["threshold_source"]), ("0.5", "environment"))
        with mock.patch.dict(os.environ, {fc.F1_ENV: "not-a-number"}):
            self.assertEqual(fc.f1_heuristic()["threshold_source"], "default")

    def test_thousand_and_one_scales_are_normalised_before_comparison(self) -> None:
        rows = annual_rows(TICKER, {"revenue": {2024: 1000.0}, "accounts_receivable": {2024: 200.0}})
        rows += annual_rows(TICKER, {"revenue": {2025: 1.1}, "accounts_receivable": {2025: 0.3}}, unit="新台幣仟元")
        finding = fc.check_revenue_receivables(index_of(rows)["index"])
        self.assertEqual(finding["computed"]["gap"], "0.4")

    def test_currency_scope_and_filing_revision_mismatches_are_not_comparable(self) -> None:
        cases = {
            "unit_not_a_known_twd_scale": [fact(TICKER, "revenue", "2025FY", 1100.0, unit="USD")],
            "scope_unknown": [fact(TICKER, "revenue", "2025FY", 1100.0, url=mops_url(TICKER, 2025, report_id="A"))],
            "scope_mismatch": [fact(TICKER, "revenue", "2025FY", 1100.0, scope="individual"),
                               fact(TICKER, "accounts_receivable", "2025FY", 300.0, scope="consolidated")],
            "filing_policy_mismatch": [fact(TICKER, "revenue", "2024FY", 1000.0, url=mops_url(TICKER, 2025))],
        }
        for expected, replacements in cases.items():
            with self.subTest(expected=expected):
                keys = {(r["metric_code"], r["period"]) for r in replacements}
                rows = [r for r in annual_rows(TICKER, BASE_DATA) if (r["metric_code"], r["period"]) not in keys]
                finding = fc.check_revenue_receivables(index_of(rows + replacements)["index"])
                self.assertEqual(finding["series"][-1]["status"], "not_comparable")
                self.assertTrue(any(r.startswith(expected) for r in finding["series"][-1]["reasons"]),
                                finding["series"][-1]["reasons"])

    def test_zero_and_negative_denominators_are_not_computable(self) -> None:
        cases = {"prior_revenue_not_positive": {"revenue": {2024: 0.0}},
                 "prior_receivables_not_positive": {"accounts_receivable": {2024: 0.0}},
                 "negative_current_value": {"revenue": {2025: -5.0}}}
        for reason, override in cases.items():
            with self.subTest(reason=reason):
                finding = fc.check_revenue_receivables(index_of(annual_rows(TICKER, data(**override)))["index"])
                self.assertEqual(finding["series"][-1]["status"], "not_computable")
                self.assertIn(reason, finding["series"][-1]["reasons"])

    def test_reported_zero_is_a_value_but_missing_is_not(self) -> None:
        zero = fc.check_revenue_receivables(index_of(annual_rows(TICKER, data(accounts_receivable={2025: 0.0})))["index"])
        self.assertEqual(zero["computed"]["ar_growth"], "-1")
        rows = [r for r in annual_rows(TICKER, BASE_DATA) if (r["metric_code"], r["period"]) != ("accounts_receivable", "2025FY")]
        missing = fc.check_revenue_receivables(index_of(rows)["index"])
        self.assertEqual(missing["series"][-1]["status"], "not_computable")
        self.assertIn("missing:accounts_receivable:2025FY", missing["series"][-1]["reasons"])
        # Review CR-02: the latest year stays top-level; the older computable pair is history only.
        self.assertEqual((missing["period"], missing["status"], missing["freshness_status"], missing["review_queue"]),
                         ("2025FY", "not_computable", "latest_period_not_computable", "insufficient_evidence"))
        self.assertEqual(missing["last_computable"]["period"], "2024FY")

    def test_quarterly_and_demo_values_are_excluded_with_reasons(self) -> None:
        rows = annual_rows(TICKER, BASE_DATA) + [fact(TICKER, "revenue", "2026Q2", 5.0, unit="新台幣仟元", analysis_type="latest")]
        rows = [r for r in rows if (r["metric_code"], r["period"]) != ("revenue", "2025FY")]
        rows.append(fact(TICKER, "revenue", "2025FY", 1100.0, is_demo=True))
        facts = index_of(rows)
        reasons = sorted(e["reason"] for e in facts["excluded"])
        self.assertEqual(reasons, ["demo_fixture_value", "period_type_quarter_not_used"])
        self.assertNotIn(("revenue", 2025), facts["index"])

    def test_conflicting_duplicates_fail_closed(self) -> None:
        rows = annual_rows(TICKER, BASE_DATA) + [fact(TICKER, "revenue", "2025FY", 1200.0, retrieved_at="2026-10-01T00:00:00+00:00")]
        facts = index_of(rows)
        self.assertNotIn(("revenue", 2025), facts["index"])
        self.assertEqual(facts["quality"][0]["issue"], "conflicting_duplicate_values")

    def test_fewer_than_two_years(self) -> None:
        finding = fc.check_revenue_receivables(index_of(annual_rows(TICKER, {"revenue": {2025: 1.0}}))["index"])
        self.assertEqual(finding["status"], "not_computable")
        self.assertEqual(finding["review_queue"], "insufficient_evidence")


class NetIncomeCashFlowTests(unittest.TestCase):
    def test_gap_series_streak_and_monitor_rule(self) -> None:
        finding = fc.check_net_income_cfo(index_of(annual_rows(TICKER, BASE_DATA))["index"])
        self.assertEqual(finding["status"], "descriptive_gap")
        c = finding["computed"]
        self.assertEqual((c["net_income_minus_cfo_twd"], c["cfo_to_net_income"], c["direction"]),
                         ("60", "0.6", "cfo_below_net_income"))
        self.assertEqual(c["consecutive_latest_years_cfo_below_net_income"], 2)
        self.assertEqual(finding["review_queue"], "monitor")
        self.assertEqual([s["period"] for s in finding["series"]], ["2023FY", "2024FY", "2025FY"])

    def test_cfo_above_income_has_no_queue_item(self) -> None:
        finding = fc.check_net_income_cfo(index_of(annual_rows(TICKER, data(operating_cash_flow={2025: 200.0})))["index"])
        self.assertIsNone(finding["review_queue"])
        self.assertEqual(finding["computed"]["consecutive_latest_years_cfo_below_net_income"], 0)

    def test_negative_income_ratio_undefined(self) -> None:
        finding = fc.check_net_income_cfo(index_of(annual_rows(TICKER, data(net_income={2025: -10.0})))["index"])
        self.assertIsNone(finding["computed"]["cfo_to_net_income"])
        self.assertIn("net_income_not_positive_ratio_undefined", finding["reasons"])

    def test_filing_version_mismatch_and_missing(self) -> None:
        index = index_of(annual_rows(TICKER, {"net_income": {2025: 150.0}, "operating_cash_flow": {2025: 90.0}}))["index"]
        index[("operating_cash_flow", 2025)]["filing_version"] = "mops_t164sb01:2025:S4:C:restated_copy"
        finding = fc.check_net_income_cfo(index)
        self.assertEqual(finding["status"], "not_comparable")
        self.assertIn("filing_version_mismatch", finding["reasons"])
        self.assertEqual(fc.check_net_income_cfo({})["status"], "unavailable")


class RevenueNfmTests(unittest.TestCase):
    INDEX = None

    def setUp(self) -> None:
        self.index = index_of(annual_rows(TICKER, BASE_DATA))["index"]

    def nfm(self, year, value, **extra):
        return {"measure": "employees", "fiscal_year": year, "value": value, "unit": "persons", "scope": "consolidated",
                "verified_source": True, "scale_related": True, **extra}

    def test_no_data_is_unavailable_not_a_score(self) -> None:
        finding = fc.check_revenue_nfm(self.index, [])
        self.assertEqual((finding["status"], finding["implementation_tier"]), ("unavailable", "readiness_only"))
        self.assertEqual(finding["reasons"], ["no_verified_nonfinancial_measure_series"])
        self.assertEqual(finding["computed"], {})

    def test_unverified_or_unrelated_measures_are_refused(self) -> None:
        self.assertEqual(fc.check_revenue_nfm(self.index, [self.nfm(2025, 10, verified_source=False)])["reasons"],
                         ["nfm_source_not_verified"])
        self.assertEqual(fc.check_revenue_nfm(self.index, [self.nfm(2025, 10, scale_related=False)])["reasons"],
                         ["nfm_not_scale_related"])

    def test_verified_two_year_series_gives_exact_difference_without_threshold(self) -> None:
        finding = fc.check_revenue_nfm(self.index, [self.nfm(2024, 100), self.nfm(2025, 105)])
        self.assertEqual(finding["status"], "descriptive_gap")
        self.assertEqual(finding["computed"], {"revenue_growth": "0.1", "nfm_growth": "0.05", "growth_difference": "0.05"})
        self.assertIsNone(finding["heuristic"]["threshold"])
        self.assertIsNone(finding["review_queue"])

    def test_nfm_unit_mismatch_and_single_year(self) -> None:
        self.assertEqual(fc.check_revenue_nfm(self.index, [self.nfm(2024, 100), self.nfm(2025, 105, unit="FTE")])["status"],
                         "not_comparable")
        self.assertEqual(fc.check_revenue_nfm(self.index, [self.nfm(2025, 105)])["status"], "not_computable")
        self.assertEqual(fc.check_revenue_nfm(self.index, [self.nfm(2024, 0), self.nfm(2025, 5)])["status"], "not_computable")


if __name__ == "__main__":
    unittest.main()
