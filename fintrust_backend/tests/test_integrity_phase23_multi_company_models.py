"""Synthetic-only tests of multi-company frozen panel research adapter."""
from __future__ import annotations

import unittest

from app.services.financial_research.literature_inputs import Panel
from app.services.integrity.multi_company_models import evaluate_research_panels


def row(ticker: str, year: int, **overrides):
    item = {
        "ticker": ticker, "fiscal_year": year, "version_policy": "original_only",
        "frozen_panel": Panel(year, "TIFRS", {}, {}, {year: "no_reviewed_frozen_filing"}),
        "release_sha256": "a" * 64,
        "source_gate_verified": True,
        "source_identity_verified": True,
    }
    item.update(overrides)
    return item


class MultiCompanyResearchTests(unittest.TestCase):
    def test_multiple_companies_do_not_borrow_1785_scores(self):
        out = evaluate_research_panels([row("2330", 2025), row("2454", 2025)])
        self.assertEqual(out["evaluated_panel_count"], 2)
        self.assertFalse(out["production_scores_admitted"])
        self.assertEqual({r["ticker"] for r in out["rows"]}, {"2330", "2454"})
        for r in out["rows"]:
            self.assertEqual(len(r["models"]), 2)
            self.assertTrue(all(m["score"] is None for m in r["models"]))
            self.assertTrue(all(m["status"] == "not_computable" for m in r["models"]))

    def test_refuses_nonfrozen_panel(self):
        entry = row("2330", 2025)
        entry["frozen_panel"] = object()
        out = evaluate_research_panels([entry])
        self.assertIn("missing_or_mismatched_frozen_literature_panel", out["rows"][0]["reasons"])

    def test_refuses_version_conflict_and_duplicate(self):
        entries = [row("2330", 2025), row("2330", 2025)]
        result = evaluate_research_panels(entries)
        self.assertEqual(result["rejected_panel_count"], 1)
        self.assertEqual(result["rows"][1]["reasons"], ["duplicate_company_year_version"])

    def test_unverified_inputs_never_reach_model_engines(self):
        item = row("2330", 2025, source_gate_verified=False)
        out = evaluate_research_panels([item])
        self.assertEqual(out["rows"][0]["models"], [])
        self.assertEqual(out["rows"][0]["status"], "not_computable")

    def test_historical_scores_not_allowed_in_current_review(self):
        with self.assertRaises(ValueError):
            evaluate_research_panels([row("2330", 2025)], mode="CURRENT_REVIEW")


if __name__ == "__main__":
    unittest.main()
