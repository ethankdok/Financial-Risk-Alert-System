"""Synthetic-only Phase 2+3 regression tests: no database, network or secrets."""
from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import replace
from decimal import Decimal
import unittest

from app.services.financial_nonfinancial_alignment import (
    GrowthEvidence, compare_financial_nonfinancial_growth,
)

PUBLISHED = datetime(2026, 3, 1, tzinfo=timezone.utc)
URL = "https://mops.twse.com.tw/server-java/t164sb01"
SHA = "a" * 64


def rows(ticker="2454"):
    def item(metric, year, value, unit, period_basis, policy):
        return GrowthEvidence(
            ticker=ticker, fiscal_year=year, metric=metric, value=value,
            unit=unit, statement_scope="consolidated", measurement_policy=policy,
            period_basis=period_basis, source_url=URL, source_sha256=SHA,
            filing_version_id=f"v{year}", published_at=PUBLISHED,
            source_trust="verified_official_document",
        )
    return [
        item("revenue", 2024, "1000", "TWD", "annual_flow", "IFRS_revenue"),
        item("revenue", 2025, "1100", "TWD", "annual_flow", "IFRS_revenue"),
        item("employees", 2024, "200", "persons", "year_end_stock", "all_fte"),
        item("employees", 2025, "210", "persons", "year_end_stock", "all_fte"),
    ]


def assess(data, **kwargs):
    return compare_financial_nonfinancial_growth(
        data, ticker="2454", fiscal_year=2025, **kwargs
    )


class FinancialNonfinancialGrowthTests(unittest.TestCase):
    def test_descriptive_growth_and_gap_are_exact_decimals(self):
        result = assess(rows())
        self.assertEqual(result.status, "computed_descriptive")
        self.assertEqual(result.financial_growth, Decimal("0.1"))
        self.assertEqual(result.nonfinancial_growth, Decimal("0.05"))
        self.assertEqual(result.growth_gap_percentage_points, Decimal("5.00"))
        self.assertIsNone(result.as_dict()["fraud_probability"])
        self.assertFalse(result.as_dict()["independent_corroboration"])
        self.assertEqual(len(result.evidence), 4)

    def test_missing_nfm_year_fails_closed(self):
        self.assertIn("missing:employees:2025", assess(rows()[:-1]).reasons)

    def test_zero_or_negative_baselines_fail_closed(self):
        for value in (0, -1):
            with self.subTest(value=value):
                x = rows()
                x[2] = replace(x[2], value=value)
                self.assertIn("nonpositive_growth_input", assess(x).reasons)

    def test_infinite_and_invalid_numeric_values_fail_closed(self):
        for value in ("NaN", "Infinity", "nope"):
            with self.subTest(value=value):
                x = rows()
                x[0] = replace(x[0], value=value)
                self.assertEqual(assess(x).status, "not_computable")

    def test_mismatched_scopes_fail_closed(self):
        x = rows()
        x[2] = replace(x[2], statement_scope="individual")
        self.assertIn("incompatible_measurement_basis:employees", assess(x).reasons)

    def test_mismatched_units_fail_closed(self):
        x = rows()
        x[3] = replace(x[3], unit="thousands_persons")
        self.assertIn("incompatible_measurement_basis:employees", assess(x).reasons)

    def test_mismatched_measurement_policies_fail_closed(self):
        x = rows()
        x[3] = replace(x[3], measurement_policy="permanent_only")
        self.assertIn("incompatible_measurement_basis:employees", assess(x).reasons)

    def test_mismatched_period_bases_fail_closed(self):
        x = rows()
        x[3] = replace(x[3], period_basis="annual_average")
        self.assertIn("incompatible_measurement_basis:employees", assess(x).reasons)

    def test_demo_data_cannot_be_used(self):
        x = rows()
        x[1] = replace(x[1], source_trust="demo")
        self.assertEqual(assess(x).status, "not_computable")

    def test_unofficial_host_or_suffix_attack_cannot_be_used(self):
        for url in (
            "https://mops.twse.com.tw.evil.test/f",
            "http://mops.twse.com.tw/f", "https://evil.test/f",
        ):
            with self.subTest(url=url):
                x = rows()
                x[1] = replace(x[1], source_url=url)
                self.assertIn(
                    "unverified_or_nonofficial_source:revenue:2025",
                    assess(x).reasons,
                )

    def test_missing_hash_or_version_fails_closed(self):
        x = rows()
        x[1] = replace(x[1], source_sha256="bad")
        self.assertIn("incomplete_source_provenance:revenue:2025", assess(x).reasons)
        x[1] = replace(x[1], source_sha256=SHA, filing_version_id="")
        self.assertIn("incomplete_source_provenance:revenue:2025", assess(x).reasons)

    def test_same_source_duplicate_is_safe(self):
        x = rows()
        x.append(x[1])
        self.assertEqual(assess(x).status, "computed_descriptive")

    def test_different_version_even_same_value_fails_closed(self):
        x = rows()
        x.append(replace(x[1], source_sha256="b" * 64, filing_version_id="restated"))
        self.assertIn("ambiguous_filing_versions:revenue:2025", assess(x).reasons)

    def test_pit_unknown_publication_time_is_rejected(self):
        x = rows()
        x[1] = replace(x[1], published_at=None)
        self.assertIn(
            "publication_time_unknown:revenue:2025",
            assess(x, cutoff_at=datetime(2026, 4, 1, tzinfo=timezone.utc)).reasons,
        )

    def test_pit_publication_at_cutoff_is_excluded(self):
        self.assertIn(
            "source_unavailable_at_cutoff:revenue:2024",
            assess(rows(), cutoff_at=PUBLISHED).reasons,
        )

    def test_pit_all_before_cutoff_are_eligible(self):
        self.assertEqual(
            assess(
                rows(), cutoff_at=datetime(2026, 4, 1, tzinfo=timezone.utc)
            ).status,
            "computed_descriptive",
        )

    def test_invalid_cutoff_is_rejected(self):
        with self.assertRaises(ValueError):
            assess(rows(), cutoff_at=datetime(2026, 4, 1))

    def test_prevents_nonconsecutive_inference(self):
        x = rows()
        x[2] = replace(x[2], fiscal_year=2023)
        self.assertIn("missing:employees:2024", assess(x).reasons)

    def test_value_cannot_be_construed_as_independent_third_party(self):
        self.assertEqual(
            assess(rows()).as_dict()["interpretation"],
            "Growth consistency check only; no calibrated threshold or fraud inference.",
        )


if __name__ == "__main__":
    unittest.main()
