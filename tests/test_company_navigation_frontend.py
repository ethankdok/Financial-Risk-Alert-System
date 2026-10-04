"""Hardening round 1: frontend company discovery and ticker navigation.

- result.html?ticker=XXXX selects that company and never falls back to the cached
  analysis of another company; without the parameter the legacy flow is kept.
- financial-evidence.html builds its dropdown from the canonical company API,
  honours ?ticker=, and links to the matching result page.
- No page keeps a hard-coded ticker list.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

import tests.test_official_evidence_card_first as card_first
from tests.test_official_evidence_card_first import FakeBackend, standalone_card

ROOT = Path(__file__).resolve().parents[1]
COMPANIES = [
    {"ticker": "2303", "name": "聯電", "subindustry": "晶圓代工", "aliases": ["聯電", "UMC", "2303"]},
    {"ticker": "2330", "name": "台積電", "subindustry": "晶圓代工", "aliases": ["台積電", "TSMC", "2330"]},
    {"ticker": "2408", "name": "南亞科", "subindustry": "記憶體製造", "aliases": ["2408", "南亞科"]},
    {"ticker": "2454", "name": "聯發科", "subindustry": "IC 設計", "aliases": ["聯發科", "MediaTek", "2454"]},
    {"ticker": "3711", "name": "日月光投控", "subindustry": "封裝測試", "aliases": ["日月光", "3711"]},
]
CACHED_2454 = {"analysisResult": json.dumps({"text": "聯發科 2454 法說會"}, ensure_ascii=False)}


def run_node(script: str, payload: dict) -> dict:
    completed = subprocess.run(["node", str(ROOT / "tests" / script)],
                               input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                               capture_output=True, check=True, timeout=60)
    return json.loads(completed.stdout.decode("utf-8"))


@unittest.skipUnless(shutil.which("node"), "node is required to execute script.js")
class ResultTickerDeepLinkTests(unittest.TestCase):
    def pick(self, search: str = "", storage: dict | None = None) -> dict:
        return run_node("result_company_harness.js", {"search": search, "storage": storage or {}, "companies": COMPANIES})

    def test_url_ticker_wins_over_cached_analysis(self) -> None:
        output = self.pick("?ticker=2408", CACHED_2454)
        self.assertEqual(output["picked"]["ticker"], "2408")
        self.assertEqual(output["fetched"], ["/api/financial/companies", "/api/financial/companies/2408/card"])
        self.assertEqual(output["rendered"], ["2408"])
        self.assertNotIn("/api/financial/companies/2454/card", output["fetched"])

    def test_without_query_parameter_the_cached_flow_is_preserved(self) -> None:
        output = self.pick("", CACHED_2454)
        self.assertEqual(output["picked"]["ticker"], "2454")
        self.assertEqual(output["rendered"], ["2454"])
        by_name = self.pick("", {"analysisQuery": "台積電今年展望"})
        self.assertEqual(by_name["picked"]["ticker"], "2330")

    def test_invalid_or_unsupported_ticker_never_uses_the_cache(self) -> None:
        for search, rejection in (("?ticker=abc", "invalid"), ("?ticker=", "invalid"), ("?ticker=24081234567", "invalid"),
                                  ("?ticker=9999", "unsupported")):
            output = self.pick(search, CACHED_2454)
            self.assertEqual(output["picked"]["rejected"], rejection, search)
            self.assertEqual(output["rendered"], [], search)
            self.assertEqual(output["fetched"], ["/api/financial/companies"], search)
            self.assertEqual(len(output["empties"]), 1, search)
            self.assertIn("不會改用先前查詢的資料", output["empties"][0]["detail"])
            self.assertNotIn("2454", output["empties"][0]["message"] + output["empties"][0]["detail"].replace("result.html?ticker=2454", ""))

    def test_legacy_risk_result_is_not_rendered_for_ticker_links(self) -> None:
        js = (ROOT / "script.js").read_text(encoding="utf-8")
        start = js.index("if (page === 'result.html') {")
        branch = js[start:js.index("function renderTickerEntry", start)]
        self.assertIn("if (tickerParam === null) {", branch)
        self.assertLess(branch.index("if (tickerParam === null) {"), branch.index("renderRiskResult();"))
        self.assertIn("renderTickerEntry(tickerParam.trim());", branch)
        data_shift = (ROOT / "official-data-shift.js").read_text(encoding="utf-8")
        prefill = data_shift[data_shift.index("const contextTicker = async () => {"):]
        self.assertLess(prefill.index("get('ticker')"), prefill.index("localStorage.getItem('analysisResult')"))


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page script")
class EvidenceBrowserCompanyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.setUpClass()
        cls.flask = card_first.OfficialEvidenceBrowserTests()
        cls.payload = cls.flask.browse(FakeBackend(standalone_card())).get_json()

    @classmethod
    def tearDownClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.tearDownClass()

    def page(self, search: str = "", companies="default") -> dict:
        payload = {"responses": [self.payload], "search": search}
        if companies == "fail":
            payload["companies"] = "fail"
        elif companies == "default":
            payload["companies"] = {"success": True, "data": {"companies": COMPANIES}}
        return run_node("evidence_browser_harness.js", payload)

    def test_dropdown_lists_the_canonical_companies(self) -> None:
        output = self.page()
        options = re.findall(r'<option value="([^"]+)">', output["html"]["ticker"])
        self.assertEqual(options, [company["ticker"] for company in COMPANIES])
        self.assertIn("2408 南亞科", html.unescape(output["html"]["ticker"]))
        self.assertEqual(output["values"]["ticker"], "2454")
        self.assertEqual(output["companyFetches"], ["/api/financial/companies"])
        self.assertIn("ticker=2454", output["fetches"][0])

    def test_ticker_query_preselects_and_loads_that_company(self) -> None:
        output = self.page("?ticker=2408")
        self.assertEqual(output["values"]["ticker"], "2408")
        self.assertIn("ticker=2408", output["fetches"][0])

    def test_deep_links_point_to_the_current_ticker_result_page(self) -> None:
        output = self.page("?ticker=2408")
        hrefs = set(re.findall(r'class="result-link" href="([^"]+)"', output["html"]["summary"] + output["html"]["officialDocumentPanel"]))
        self.assertEqual(hrefs, {"result.html?ticker=2408"})
        default = self.page()
        self.assertIn('href="result.html?ticker=2454"', default["html"]["summary"])

    def test_company_list_failure_keeps_the_page_usable(self) -> None:
        output = self.page("?ticker=2408", companies="fail")
        self.assertEqual(re.findall(r'<option value="([^"]+)">', output["html"]["ticker"]), ["2408"])
        self.assertIn("ticker=2408", output["fetches"][0])

    def test_invalid_ticker_query_falls_back_to_default(self) -> None:
        output = self.page("?ticker=<script>")
        self.assertEqual(output["values"]["ticker"], "2454")
        self.assertNotIn("<script>", output["html"]["summary"])


class NoDuplicatedCompanyListTests(unittest.TestCase):
    def test_frontend_pages_have_no_hard_coded_ticker_lists(self) -> None:
        for page in ("financial-evidence.html", "member.html", "admin-financial-evidence.html"):
            text = (ROOT / page).read_text(encoding="utf-8")
            self.assertNotRegex(text, r'<option value="(2330|2303|3711)"', page)
            self.assertIn("/api/financial/companies", text, page)
        self.assertNotRegex((ROOT / "member.html").read_text(encoding="utf-8"), r"companyNames=\{\d")

    def test_watchlist_validation_uses_the_canonical_company_list(self) -> None:
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")
        handler = app_source[app_source.index("def member_watchlist_add"):app_source.index('@app.patch("/api/member/watchlist/<ticker>")')]
        self.assertIn("FinTrustClient().companies()", handler)
        self.assertNotIn('{"2454", "2330", "2303", "3711"}', handler)


if __name__ == "__main__":
    unittest.main()
