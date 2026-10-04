"""Hardening round 3: Text Intelligence comparison periods state their basis, the
evidence pages read in Chinese while keeping technical terms, and no favicon request 404s.

The page scripts run in the existing Node harnesses; nothing here reaches a backend.
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
NARRATIVE_LABEL = "文字敘事變化（Text Intelligence，非官方法說會 JSD 校準）"
NARRATIVE_NOTE = "此區為文字敘事變化分析，與系統中的官方法說會跨期 JSD 校準為不同分析。"
MIXED_NOTICE = "兩份比較文件的期間依據不同"
BAD_TOKENS = re.compile(r"\bundefined\b|>null<|\bNone\b|\bNaN\b|\[object Object\]|Traceback")
METRICS = {"relevant_text_word_jsd": 0.123456, "topic_distribution_jsd": 0.0421,
           "semantic_tfidf_cosine_similarity": 0.8765, "semantic_embedding_cosine_similarity": 0.5}


def run(script: str, payload: dict) -> dict:
    completed = subprocess.run(["node", str(ROOT / "tests" / script)],
                               input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                               capture_output=True, check=True, timeout=60)
    return json.loads(completed.stdout.decode("utf-8"))


def narrative(**fields) -> dict:
    return {"ticker": "2454", "metrics": dict(METRICS), "data_quality": {"passed": True},
            "topic_changes": [], "emerging_terms": [], "disappearing_terms": [], "supporting_sentences": [], **fields}


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page script")
class TextIntelligencePeriodLabelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.setUpClass()
        cls.base = card_first.OfficialEvidenceBrowserTests().browse(FakeBackend(standalone_card())).get_json()

    @classmethod
    def tearDownClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.tearDownClass()

    def panel(self, shift: dict | None) -> str:
        payload = copy.deepcopy(self.base)
        payload["narrative_shift"] = shift
        output = run("evidence_browser_harness.js", {"responses": [payload]})
        for element_html in output["html"].values():
            self.assertNotRegex(element_html, BAD_TOKENS)
        return html.unescape(output["html"]["textPanel"])

    def metric(self, panel: str, value: str) -> str:
        match = re.search(r'<div class="metric"><span>([^<]*)</span><strong>' + re.escape(value) + "</strong>", panel)
        self.assertIsNotNone(match, value)
        return match.group(1)

    # A: a dated document and a fiscal quarter are labelled as different things.
    def test_date_and_quarter_are_labelled_with_their_own_basis(self) -> None:
        panel = self.panel(narrative(period_1="2026-08-31", period_2="2026Q2",
                                     period_1_basis="announcement_date", period_2_basis="fiscal_quarter",
                                     period_1_source_type="material_event", period_2_source_type="investor_conference"))
        self.assertEqual(self.metric(panel, "2026-08-31"), "比較基準・公告日期（重大訊息）")
        self.assertEqual(self.metric(panel, "2026Q2"), "比較對象・會計期間（法說會）")
        self.assertIn(MIXED_NOTICE, panel)
        self.assertIn("未將日期換算為會計季度", panel)
        self.assertNotRegex(panel, r"2026Q3")  # the date is never turned into a quarter

    def test_conference_date_basis_is_named(self) -> None:
        panel = self.panel(narrative(period_1="2026-04-30", period_2="2026-08-31",
                                     period_1_basis="conference_date", period_2_basis="announcement_date",
                                     period_1_source_type="investor_conference", period_2_source_type="material_event"))
        self.assertEqual(self.metric(panel, "2026-04-30"), "比較基準・法說會日期（法說會）")
        self.assertEqual(self.metric(panel, "2026-08-31"), "比較對象・公告日期（重大訊息）")
        self.assertIn(MIXED_NOTICE, panel)

    # B: two quarters read consistently, with no mixed-basis notice.
    def test_two_quarters_share_one_label(self) -> None:
        panel = self.panel(narrative(period_1="2026Q1", period_2="2026Q2",
                                     period_1_basis="fiscal_quarter", period_2_basis="fiscal_quarter",
                                     period_1_source_type="investor_conference", period_2_source_type="investor_conference"))
        self.assertEqual(self.metric(panel, "2026Q1"), "比較基準・會計期間（法說會）")
        self.assertEqual(self.metric(panel, "2026Q2"), "比較對象・會計期間（法說會）")
        self.assertNotIn(MIXED_NOTICE, panel)

    # C: persisted runs without basis metadata fall back to the value's format only.
    def test_missing_basis_falls_back_to_the_value_format(self) -> None:
        panel = self.panel(narrative(period_1="2026-08-31", period_2="2026Q2"))
        self.assertEqual(self.metric(panel, "2026-08-31"), "比較基準・日期")
        self.assertEqual(self.metric(panel, "2026Q2"), "比較對象・會計期間")
        self.assertIn(MIXED_NOTICE, panel)
        self.assertNotRegex(panel, r"2026Q3")

    def test_legacy_baseline_keys_and_unknown_formats(self) -> None:
        panel = self.panel(narrative(baseline_period="2026Q1", current_period="2026Q2"))
        self.assertEqual(self.metric(panel, "2026Q1"), "比較基準・會計期間")
        self.assertNotIn(MIXED_NOTICE, panel)
        panel = self.panel(narrative(period_1="FY2026 H1", period_2=None))
        self.assertEqual(self.metric(panel, "FY2026 H1"), "比較基準・期間")
        self.assertEqual(self.metric(panel, "無資料"), "比較對象・期間")
        self.assertNotIn(MIXED_NOTICE, panel)

    def test_basis_applies_only_to_its_own_field(self) -> None:
        # baseline_period wins for display; period_1's basis does not describe it.
        panel = self.panel(narrative(baseline_period="2026Q1", period_1="2026-08-31", period_1_basis="announcement_date",
                                     period_1_source_type="material_event", period_2="2026Q2", period_2_basis="fiscal_quarter"))
        self.assertEqual(self.metric(panel, "2026Q1"), "比較基準・會計期間")

    # D: Text Intelligence stays distinct from the calibrated official Data Shift.
    def test_wording_stays_distinct_from_calibrated_jsd(self) -> None:
        panel = self.panel(narrative(period_1="2026-08-31", period_2="2026Q2"))
        self.assertIn(NARRATIVE_LABEL, panel)
        self.assertIn(NARRATIVE_NOTE, panel)
        self.assertIn("文字分析（Text Intelligence）", panel)
        for forbidden in ("官方 JSD", "校準後 JSD", "法說會漂移結果", "Narrative Shift</h3>"):
            self.assertNotIn(forbidden, panel)

    # E: metric values pass through unchanged.
    def test_metric_values_are_rendered_verbatim(self) -> None:
        panel = self.panel(narrative(period_1="2026-08-31", period_2="2026Q2"))
        self.assertEqual(self.metric(panel, "0.123456"), "Relevant-text JSD")
        self.assertEqual(self.metric(panel, "0.0421"), "Topic JSD")
        self.assertEqual(self.metric(panel, "0.8765"), "TF-IDF Cosine")
        self.assertEqual(self.metric(panel, "0.5"), "Semantic Cosine")

    # F: missing values never print raw null-ish tokens (checked in panel()).
    def test_absent_narrative_and_metrics_render_cleanly(self) -> None:
        self.assertIn("目前沒有足夠的可比較期間", self.panel(None))
        panel = self.panel({"metrics": {}, "period_1": None, "period_2": None})
        self.assertEqual(self.metric(panel, "無資料"), "比較基準・期間")
        self.assertNotIn(MIXED_NOTICE, panel)


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page scripts")
class ReleaseUiLanguageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.setUpClass()
        cls.payload = card_first.OfficialEvidenceBrowserTests().browse(FakeBackend(standalone_card())).get_json()
        cls.page_source = (ROOT / "financial-evidence.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.tearDownClass()

    def test_static_labels_are_chinese(self) -> None:
        for label in ('>全部</button>', '>法說會</button>', '>重大訊息</button>', "<h2>官方紀錄</h2>",
                      ">載入更多</button>", "主題 / 指標", ">由新到舊<", ">由舊到新<"):
            self.assertIn(label, self.page_source)
        for english in (">All<", ">Investor Conferences<", ">Material Events<", "Official Records", ">Load More<",
                        ">Newest<", ">Oldest<", "Topic / Metric", "Persisted Official Evidence", "Loading official evidence",
                        "Provenance details</summary>", "Representative evidence sentences", "official source URL",
                        "Baseline period", "Current period", "Run ID</span>", "insufficient data", "'unavailable'"):
            self.assertNotIn(english, self.page_source)

    def test_rendered_records_and_summary_are_chinese(self) -> None:
        output = run("evidence_browser_harness.js", {"responses": [self.payload]})
        rendered = html.unescape(output["html"]["records"] + output["html"]["summary"])
        for label in ("<span>法說會</span>", "<span>重大訊息</span>", "同步時間：", "相關句數：", "資料來源細節 / Provenance",
                      "已保存的可用紀錄"):
            self.assertIn(label, rendered)
        for english in ("synchronized:", "relevant sentences:", "persisted available records", "Investor Conference",
                        "Material Event", "unavailable"):
            self.assertNotIn(english, rendered)
        self.assertNotRegex(rendered, BAD_TOKENS)

    def test_technical_terms_are_kept(self) -> None:
        for term in ("JSD", "Cosine", "SHA-256", "MOPS", "IR", "Text Intelligence"):
            self.assertIn(term, self.page_source)

    def test_sources_keep_ir_and_mops_apart(self) -> None:
        output = run("evidence_browser_harness.js", {"responses": [self.payload]})
        panel = html.unescape(output["html"]["officialDocumentPanel"])
        records = html.unescape(output["html"]["records"])
        self.assertIn("公開資訊觀測站（MOPS）法說會文件", panel)
        self.assertNotIn("公開資訊觀測站（MOPS）法說會文件", records)
        self.assertIn("公司官方投資人關係（IR）", records)

    def test_result_page_source_list_uses_chinese_status(self) -> None:
        card = standalone_card()
        card["sources"] = [{"source_name": "TWSE OpenAPI", "source_url": "https://openapi.twse.com.tw/v1/x", "status": "available"},
                           {"source_name": "MOPS", "source_url": "https://mops.twse.com.tw/x", "status": "metadata_only"},
                           {"source_name": "Other", "source_url": "https://example.test/x", "status": "custom_state"}]
        output = run("frontend_render_harness.js", {"mode": "evidence", "card": card})
        text = output["text"]
        self.assertIn("官方資料來源 Official Sources", text)
        self.assertIn("可用", text)
        self.assertIn("僅有基本資料", text)
        self.assertIn("custom_state", text)  # unknown values stay readable instead of disappearing
        self.assertNotRegex(text, r"\bmetadata_only\b")
        self.assertNotRegex(text, BAD_TOKENS)

    def test_both_pages_declare_an_inline_favicon(self) -> None:
        for page in ("financial-evidence.html", "result.html"):
            source = (ROOT / page).read_text(encoding="utf-8")
            self.assertIn('<link rel="icon" href="data:,">', source, page)
            self.assertNotRegex(source, r'href="[^"]*favicon', page)


if __name__ == "__main__":
    unittest.main()
