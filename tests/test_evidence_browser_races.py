"""Hardening round 2: financial-evidence.html keeps the latest user intent, and the
archive_unavailable state reads the same on both pages.

The page's own script runs in tests/evidence_browser_harness.js with deferred
responses, so the tests choose the order in which requests resolve.
"""
from __future__ import annotations

import copy
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
UNAVAILABLE = "MOPS 文件歸檔目前無法讀取"
COMPANIES = {"success": True, "data": {"companies": [
    {"ticker": "2330", "name": "台積電"}, {"ticker": "2408", "name": "南亞科"}, {"ticker": "2454", "name": "聯發科"}]}}
BAD_TOKENS = re.compile(r"\bundefined\b|>null<|\bNone\b|\bNaN\b|Traceback|archive_unavailable|\[object Object\]")


def run(script: str, payload: dict) -> dict:
    completed = subprocess.run(["node", str(ROOT / "tests" / script)],
                               input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                               capture_output=True, check=True, timeout=60)
    return json.loads(completed.stdout.decode("utf-8"))


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page script")
class EvidenceBrowserRaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.setUpClass()
        flask = card_first.OfficialEvidenceBrowserTests()
        cls.base = flask.browse(FakeBackend(standalone_card())).get_json()

    @classmethod
    def tearDownClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.tearDownClass()

    def payload(self, label: str, *, ticker: str = "2454", has_more: bool = False, records: int | None = None) -> dict:
        data = copy.deepcopy(self.base)
        data["summary"]["ticker"] = ticker
        data["records"] = [dict(record, event_id=f"{label}-{index}", title=f"{label} record {index}")
                           for index, record in enumerate(data["records"][:records] if records else data["records"])]
        data["pagination"] = {"page": 1, "limit": 10, "total": 9, "has_more": has_more}
        return data

    def page(self, responses: list, actions: list, **extra) -> dict:
        output = run("evidence_browser_harness.js", {"responses": responses, "actions": actions, "companies": COMPANIES, **extra})
        for element_html in output["html"].values():
            self.assertNotRegex(element_html, BAD_TOKENS)
        return output

    @staticmethod
    def titles(output: dict) -> list[str]:
        return [html.unescape(title) for title in re.findall(r"<h3>([^<]+)</h3>", output["html"]["records"])]

    def assert_settled(self, output: dict) -> None:
        self.assertFalse(output["disabled"]["loadMore"])
        self.assertNotIn("Loading official evidence", output["html"]["records"])

    def test_tab_switch_wins_over_a_slower_earlier_request(self) -> None:
        output = self.page(
            [{"defer": "first", "payload": self.payload("STALE-ALL")}, self.payload("NEW-MATERIAL")],
            [{"tab": "material_event"}, {"resolve": "first"}])
        self.assertIn("type=material_event", output["fetches"][1])
        self.assertEqual(output["aborted"], [output["fetches"][0]])
        self.assertTrue(all(title.startswith("NEW-MATERIAL") for title in self.titles(output)))
        self.assert_settled(output)

    def test_rapid_topic_edits_query_only_the_final_value(self) -> None:
        output = self.page([self.payload("INITIAL"), self.payload("TOPIC-AB")],
                           [{"typeNoWait": ["topic", "a"]}, {"wait": 100}, {"typeNoWait": ["topic", "ab"]}, {"wait": 400}])
        self.assertEqual(len(output["fetches"]), 2)
        self.assertIn("topic=ab", output["fetches"][1])
        self.assertTrue(all(title.startswith("TOPIC-AB") for title in self.titles(output)))

    def test_slower_earlier_topic_response_cannot_overwrite_the_later_one(self) -> None:
        output = self.page([self.payload("INITIAL"), {"defer": "topic-a", "payload": self.payload("TOPIC-A")}, self.payload("TOPIC-B")],
                           [{"input": ["topic", "a"]}, {"input": ["topic", "b"]}, {"resolve": "topic-a"}])
        self.assertIn("topic=a", output["fetches"][1])
        self.assertIn("topic=b", output["fetches"][2])
        self.assertTrue(all(title.startswith("TOPIC-B") for title in self.titles(output)))
        self.assert_settled(output)

    def test_ticker_change_while_2454_is_pending_ends_on_2408(self) -> None:
        output = self.page(
            [{"defer": "t2454", "payload": self.payload("CO-2454", ticker="2454")}, self.payload("CO-2408", ticker="2408")],
            [{"input": ["ticker", "2408"]}, {"resolve": "t2454"}])
        self.assertIn("ticker=2454", output["fetches"][0])
        self.assertIn("ticker=2408", output["fetches"][1])
        self.assertTrue(all(title.startswith("CO-2408") for title in self.titles(output)))
        links = set(re.findall(r'class="result-link" href="([^"]+)"', output["html"]["summary"] + output["html"]["officialDocumentPanel"]))
        self.assertEqual(links, {"result.html?ticker=2408"})
        self.assertEqual(output["values"]["ticker"], "2408")
        self.assert_settled(output)

    def test_load_more_during_a_filter_reset_never_mixes_records(self) -> None:
        output = self.page(
            [self.payload("PAGE1", has_more=True), {"defer": "page2", "payload": self.payload("OLD-PAGE2")}, self.payload("RESET")],
            ["loadMore", {"tab": "material_event"}, {"resolve": "page2"}])
        self.assertIn("page=2", output["fetches"][1])
        self.assertIn("page=1", output["fetches"][2])
        self.assertIn("type=material_event", output["fetches"][2])
        self.assertTrue(all(title.startswith("RESET") for title in self.titles(output)))
        self.assert_settled(output)

    def test_load_more_is_refused_while_a_new_intent_is_debounced(self) -> None:
        output = self.page([self.payload("PAGE1", has_more=True), self.payload("TOPIC-X")],
                           [{"typeNoWait": ["topic", "x"]}, "loadMore", {"wait": 400}])
        self.assertEqual(len(output["fetches"]), 2)
        self.assertNotIn("page=2", output["fetches"][1])
        self.assertTrue(all(title.startswith("TOPIC-X") for title in self.titles(output)))

    def test_double_load_more_requests_the_next_page_once(self) -> None:
        page2 = self.payload("PAGE2", records=1)
        output = self.page([self.payload("PAGE1", has_more=True), {"defer": "page2", "payload": page2}],
                           ["loadMore", "loadMore", {"resolve": "page2"}])
        self.assertEqual(sum("page=2" in url for url in output["fetches"]), 1)
        self.assertFalse(any("page=3" in url for url in output["fetches"]))
        titles = self.titles(output)
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(sum(title.startswith("PAGE2") for title in titles), 1)
        self.assertTrue(output["hidden"]["loadMore"])
        self.assert_settled(output)

    def test_slow_company_list_does_not_change_the_requested_ticker(self) -> None:
        output = self.page([self.payload("CO-2408", ticker="2408"), self.payload("CO-2408-AGAIN", ticker="2408")],
                           [{"input": ["topic", "x"]}, {"resolve": "companies"}],
                           companiesDefer=True, search="?ticker=2408")
        self.assertTrue(output["fetches"])
        self.assertTrue(all("ticker=2408" in url for url in output["fetches"]))
        self.assertEqual(output["values"]["ticker"], "2408")
        self.assertIn('<option value="2408">', output["html"]["ticker"])


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page scripts")
class ArchiveUnavailableWordingTests(unittest.TestCase):
    """The existing archive_unavailable state renders the approved wording end to end."""

    @classmethod
    def setUpClass(cls) -> None:
        card = standalone_card()
        card["conference_document_digest"] = None
        card["conference_summary_state"] = "archive_unavailable"
        card["investor_conferences"][0]["summary_status"] = "archive_unavailable"
        cls.card = card
        card_first.OfficialEvidenceBrowserTests.setUpClass()
        cls.browser_payload = card_first.OfficialEvidenceBrowserTests().browse(FakeBackend(card)).get_json()

    @classmethod
    def tearDownClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.tearDownClass()

    def test_result_page_shows_archive_unavailable_wording(self) -> None:
        output = run("frontend_render_harness.js", {"mode": "evidence", "card": self.card})
        text = output["text"]
        self.assertIn(f"官方文件摘要狀態：{UNAVAILABLE}", text)
        self.assertIn(f"官方文件摘要：{UNAVAILABLE}。", text)
        self.assertNotRegex(text, BAD_TOKENS)
        self.assertNotIn("官方文件摘要 Official Document Summary", text)

    def test_evidence_browser_shows_archive_unavailable_wording(self) -> None:
        self.assertEqual(self.browser_payload["conference_summary_state"], "archive_unavailable")
        output = run("evidence_browser_harness.js", {"responses": [self.browser_payload], "companies": COMPANIES})
        panel = html.unescape(output["html"]["officialDocumentPanel"])
        records = html.unescape(output["html"]["records"])
        self.assertIn(f"官方文件摘要狀態：{UNAVAILABLE}", panel)
        self.assertIn(UNAVAILABLE, records)
        for element_html in output["html"].values():
            self.assertNotRegex(element_html, BAD_TOKENS)


if __name__ == "__main__":
    unittest.main()
