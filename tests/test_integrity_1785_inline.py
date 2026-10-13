"""Retrospective 1785 rendering contract inside the current-workbench page.

The historical endpoint is read-only and MUST NOT feed CURRENT_REVIEW or B2B scores.
These guards are intentionally dependency-free so they also run without FastAPI.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "financial-integrity.html"
JS = ROOT / "financial-integrity.js"


class Historical1785InWorkbenchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = HTML.read_text(encoding="utf-8")
        self.js = JS.read_text(encoding="utf-8")

    def test_company_dropdown_and_explicit_history_mode(self):
        self.assertIn('id="tickerSelect"', self.html)
        self.assertIn('id="reviewModeBadge"', self.html)
        self.assertIn('id="reviewModeHint"', self.html)
        self.assertIn('var HISTORICAL_TICKER = "1785"', self.js)
        self.assertIn("addHistoricalOption(select);", self.js)
        self.assertIn("RETROSPECTIVE_CASE", self.js)
        self.assertIn("歷史財報研究（事後）", self.js)

    def test_retrospective_api_is_read_only_and_separate(self):
        self.assertIn('request("GET", "/api/integrity/research-cases/1785/summary?version_policy="', self.js)
        self.assertIn('if (ticker === HISTORICAL_TICKER) { runHistorical(); return; }', self.js)
        self.assertIn('request("POST", "/api/integrity/assessments/preview"', self.js)
        self.assertIn('"CURRENT_REVIEW"', self.js)
        self.assertIn("data.strict_pre_event.conclusion", self.js)
        self.assertIn("不產生合作方評級", self.js)
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("persist: true", self.js)

    def test_existing_view_ids_and_script_are_preserved(self):
        for value in ("overview", "models", "cross", "b2b"):
            with self.subTest(view=value):
                self.assertIn(f'id="view-{value}"', self.html)
                self.assertIn(f'id="tab-{value}"', self.html)
                self.assertIn(f'id="{value}Body"', self.html)
        self.assertIn('src="financial-integrity.js"', self.html)
        self.assertIn('src="financial-integrity-case.js"', (ROOT / "financial-integrity-case.html").read_text(encoding="utf-8"))

    def test_historical_case_can_be_selected_even_if_current_companies_fail(self):
        # In the error path, the retrospective option remains available without
        # pretending that the CURRENT_REVIEW company roster was fetched.
        self.assertIn('現行健檢公司清單暫時無法載入', self.js)
        self.assertIn('if (wanted === HISTORICAL_TICKER)', self.js)
        self.assertIn('runHistorical();', self.js)


if __name__ == "__main__":
    unittest.main()
