"""P4: financial-evidence.html shows source identity, the compact MOPS digest and
the standalone latest MOPS document, and labels narrative_shift as text
intelligence. Payloads come from the real P2 Flask browser route (fake FastAPI
backend); the page's own inline script renders them."""
from __future__ import annotations

import copy
import html
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

# Imported as a module so pytest does not collect its TestCase classes a second time.
import tests.test_official_evidence_card_first as card_first
from tests.test_official_evidence_card_first import (
    CARD_PATH,
    IR_DOCUMENT_URL,
    MOPS_FILE,
    MOPS_LISTING,
    MOPS_SHA,
    FakeBackend,
    legacy_card_v110,
    matched_card,
    standalone_card,
)

ROOT = Path(__file__).resolve().parents[1]
NARRATIVE_LABEL = "文字敘事變化（Text Intelligence，非官方法說會 JSD 校準）"
NARRATIVE_NOTE = "此區為文字敘事變化分析，與系統中的官方法說會跨期 JSD 校準為不同分析。"
STATE_LABELS = {
    "attached": "已連結同期間 MOPS 法說會文件",
    "standalone_latest": "顯示最新可用的 MOPS 法說會文件",
    "no_matching_archive": "尚無此期間的 MOPS 歸檔法說會文件",
    "archive_unavailable": "MOPS 文件歸檔目前無法讀取",
    "digest_failed": "官方文件摘要產生失敗",
    "digest_timeout": "官方文件摘要處理逾時",
    "not_configured": "此次資料未啟用官方文件摘要",
}


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page script")
class FinancialEvidencePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.setUpClass()
        cls.flask = card_first.OfficialEvidenceBrowserTests()

    @classmethod
    def tearDownClass(cls) -> None:
        card_first.OfficialEvidenceBrowserTests.tearDownClass()

    def browser_payload(self, card: dict | None, *, fail_card: bool = False) -> dict:
        backend = FakeBackend(card, fail={CARD_PATH} if fail_card else None)
        return self.flask.browse(backend).get_json()

    def page(self, *responses: dict, actions: list | None = None) -> dict:
        completed = subprocess.run(
            ["node", str(ROOT / "tests" / "evidence_browser_harness.js")],
            input=json.dumps({"responses": list(responses), "actions": actions or []}, ensure_ascii=False).encode("utf-8"),
            capture_output=True, check=True, timeout=60,
        )
        output = json.loads(completed.stdout.decode("utf-8"))
        for element_html in output["html"].values():
            self.assertNotRegex(element_html, r"\bundefined\b|>null<|\bNone\b|\bNaN\b|\[object Object\]|href=\"\"")
        return output

    @staticmethod
    def cards(records_html: str) -> list[str]:
        return [html.unescape(part) for part in re.split(r'(?=<article class="record-card">)', records_html)[1:]]

    def conference_card(self, output: dict) -> str:
        return next(card for card in self.cards(output["html"]["records"]) if "<span>法說會</span>" in card)

    def test_2454_company_ir_record_and_standalone_mops_document_are_separate(self) -> None:
        output = self.page(self.browser_payload(standalone_card()))
        panel = html.unescape(output["html"]["officialDocumentPanel"])
        self.assertFalse(output["hidden"]["officialDocumentPanel"])
        self.assertIn("最新可用的 MOPS 法說會文件", panel)
        self.assertIn(f"官方文件摘要狀態：{STATE_LABELS['standalone_latest']}", panel)
        self.assertIn("不一定與下方公司 IR 法說會資料屬於同一期間或來源", panel)
        self.assertIn(f"文件：{MOPS_FILE}", panel)
        self.assertIn("期間：2025Q3", panel)
        self.assertIn("公開資訊觀測站（MOPS）法說會文件", panel)
        self.assertNotIn("mediatek.com", panel)
        record = self.conference_card(output)
        self.assertIn("公司官方投資人關係（IR）", record)
        self.assertIn("期間：2026Q2", record)
        self.assertIn(STATE_LABELS["no_matching_archive"], record)
        self.assertNotIn(MOPS_FILE, record)
        self.assertNotIn(MOPS_SHA, record)
        self.assertNotIn("官方文件摘要（精簡）", record)

    def test_matched_period_keeps_record_and_nested_digest_source_blocks_apart(self) -> None:
        output = self.page(self.browser_payload(matched_card()))
        self.assertTrue(output["hidden"]["officialDocumentPanel"] is False)
        self.assertIn(STATE_LABELS["attached"], html.unescape(output["html"]["officialDocumentPanel"]))
        record = self.conference_card(output)
        split = record.index('<div class="digest-compact">')
        record_part, digest_part = record[:split], record[split:]
        self.assertIn("法說會資料來源", record_part)
        self.assertIn("公司官方投資人關係（IR）", record_part)
        self.assertIn(IR_DOCUMENT_URL, record_part)
        self.assertNotIn(MOPS_FILE, record_part)
        self.assertNotIn(MOPS_SHA, record_part)
        self.assertIn("MOPS 歸檔法說會文件", digest_part)
        self.assertIn(f"文件：{MOPS_FILE}", digest_part)
        self.assertIn(MOPS_LISTING, digest_part)
        self.assertNotIn("mediatek.com", digest_part)
        self.assertIn("財務表現（1 項）", digest_part)
        self.assertIn("重要量化資訊（1 項）", digest_part)
        # SHA only in the collapsed provenance, never in the visible source line.
        provenance = digest_part.index("查看原始證據 / Provenance")
        self.assertNotIn(MOPS_SHA, digest_part[:provenance])
        self.assertIn(MOPS_SHA, digest_part[provenance:])

    def test_source_identity_fields_render_with_chinese_labels(self) -> None:
        output = self.page(self.browser_payload(standalone_card()))
        event = next(card for card in self.cards(output["html"]["records"]) if "<span>重大訊息</span>" in card)
        self.assertIn("公告來源", event)
        self.assertIn("來源：臺灣證券交易所 OpenAPI", event)
        self.assertIn("日期：2026-09-01", event)
        self.assertIn("狀態：可用", event)
        self.assertNotIn("期間：", event)
        self.assertNotIn("source: twse_openapi", event)
        self.assertNotIn("status: available", event)
        self.assertNotIn("來源：twse_openapi", event)
        self.assertNotIn("狀態：available", event)

    def test_every_summary_state_has_chinese_wording(self) -> None:
        for state, label in STATE_LABELS.items():
            card = standalone_card()
            card["conference_summary_state"] = state
            card["conference_document_digest"] = None
            output = self.page(self.browser_payload(card))
            panel = html.unescape(output["html"]["officialDocumentPanel"])
            self.assertIn(f"官方文件摘要狀態：{label}", panel, state)
            self.assertNotIn(state, panel)

    def test_narrative_shift_is_labelled_as_text_intelligence(self) -> None:
        output = self.page(self.browser_payload(standalone_card()))
        text_panel = html.unescape(output["html"]["textPanel"])
        self.assertIn(NARRATIVE_LABEL, text_panel)
        self.assertIn(NARRATIVE_NOTE, text_panel)
        self.assertNotIn("Narrative Shift</h3>", text_panel)
        for forbidden in ("官方 JSD", "校準後 JSD", "法說會漂移結果"):
            self.assertNotIn(forbidden, text_panel)
        page_source = (ROOT / "financial-evidence.html").read_text(encoding="utf-8")
        self.assertIn(f"<h3>{NARRATIVE_LABEL}</h3>", page_source)

    def test_schema_110_and_fallback_payloads_render_safely(self) -> None:
        legacy = self.page(self.browser_payload(legacy_card_v110()))
        self.assertIn("來源：company_official_ir", html.unescape(legacy["html"]["records"]))
        self.assertTrue(legacy["hidden"]["officialDocumentPanel"] is False)  # card digest still exists
        fallback = self.page(self.browser_payload(standalone_card(), fail_card=True))
        self.assertTrue(fallback["hidden"]["officialDocumentPanel"])
        self.assertEqual(len(self.cards(fallback["html"]["records"])), 2)

    def test_unusual_source_values_render_safely(self) -> None:
        card = standalone_card()
        card["investor_conferences"][0]["source_identity"].update(source_type="unknown", availability="needs_review",
                                                                 period=None, provenance={"url": None})
        card["material_events"][0]["source_identity"]["source_type"] = "demo_fixture"
        output = self.page(self.browser_payload(card))
        records = html.unescape(output["html"]["records"])
        for label in ("來源未分類", "待人工確認", "示範資料（非官方即時資料）"):
            self.assertIn(label, records)
        for raw_value in ("needs_review", "demo_fixture"):
            self.assertNotIn(raw_value, records)

    def test_partial_coverage_reads_as_partial_not_failure(self) -> None:
        output = self.page(self.browser_payload(standalone_card()))
        panel = html.unescape(output["html"]["officialDocumentPanel"])
        self.assertIn("涵蓋部分", panel)
        self.assertIn("涵蓋 2/15 個內容頁", panel)
        self.assertNotIn("失敗", panel)

    def test_filters_and_pagination_still_work(self) -> None:
        first = self.browser_payload(standalone_card())
        first["pagination"] = {"page": 1, "limit": 10, "total": 3, "has_more": True}
        second = copy.deepcopy(first)
        second["records"] = [dict(first["records"][0], event_id="next-page", title="Next page record")]
        second["pagination"] = {"page": 2, "limit": 10, "total": 3, "has_more": False}
        output = self.page(first, second, first, first, actions=["loadMore", {"tab": "material_event"}, {"input": ["topic", "revenue"]}])
        self.assertIn("page=1", output["fetches"][0])
        self.assertIn("page=2", output["fetches"][1])
        self.assertIn("type=material_event", output["fetches"][2])
        self.assertIn("topic=revenue", output["fetches"][3])
        self.assertTrue(output["hidden"]["loadMore"] is False)

    def test_load_more_appends_records(self) -> None:
        first = self.browser_payload(standalone_card())
        first["pagination"] = {"page": 1, "limit": 10, "total": 3, "has_more": True}
        second = copy.deepcopy(first)
        second["records"] = [dict(first["records"][1], event_id="next-page", title="Next page record")]
        second["pagination"] = {"page": 2, "limit": 10, "total": 3, "has_more": False}
        output = self.page(first, second, actions=["loadMore"])
        self.assertIn("Next page record", output["html"]["records"])
        self.assertEqual(len(self.cards(output["html"]["records"])), 3)
        self.assertTrue(output["hidden"]["loadMore"])


if __name__ == "__main__":
    unittest.main()
