"""Result page: truthful material-event states and a human-readable financial narrative.

Renders the real script.js through tests/frontend_render_harness.js; nothing here
reaches a backend. Narrative strings are the ones the FastAPI presentation layer
serves for the 2454 snapshot.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "frontend_render_harness.js"
LISTING_URL = "https://mopsov.twse.com.tw/mops/web/ajax_t05st01?encodeURIComponent=1&step=1&firstin=1&off=1&TYPEK=all&co_id=2454&year=115"

FORBIDDEN_PRIMARY = [
    "COM_GROWTH_002", "COM_PROFIT_002", "SEM_PROFIT_001", "IC_RD_001",
    "revenue_growth_yoy", "net_income_growth_yoy", "gross_margin_change_pp",
    "operating_margin_change_pp", "rd_expense_growth_yoy",
    "earnings_quality", "profitability", "investment_efficiency",
    "triggered rules", "triggered", "coverage:", "rules:", "attention", "normal",
    "LLM completed", "LLM failed", "ready_for_frontend_integration",
]
DIMENSIONS = [
    ("growth", "成長性", "attention", ["COM_GROWTH_002"], "營收成長但獲利成長未跟上（需注意）"),
    ("profitability", "獲利能力", "attention", ["COM_PROFIT_002", "SEM_PROFIT_001"], "毛利率與營業利益率同步下滑（需注意）"),
    ("rd_innovation", "研發與創新", "normal", ["IC_RD_001"], "研發投入維持高投入趨勢（未見明顯異常）"),
    ("operating_efficiency", "營運效率", "normal", [], "目前可用規則均未觸發顯著注意或正向訊號。"),
    ("cash_flow", "現金流品質", "normal", [], "目前可用規則均未觸發顯著注意或正向訊號。"),
    ("financial_structure", "財務結構", "normal", [], "目前可用規則均未觸發顯著注意或正向訊號。"),
    ("earnings_quality", "盈餘品質", "normal", [], "目前可用規則均未觸發顯著注意或正向訊號。"),
    ("investment_efficiency", "投入轉化效率", "normal", [], "目前可用規則均未觸發顯著注意或正向訊號。"),
]
SERVED_NARRATIVE = {
    "executive_summary": (
        "整體呈現營收成長但獲利指標壓縮的混合訊號。其中「營收成長但獲利成長未跟上」顯示營收成長"
        "（營收年增率為 12.32%）但獲利成長未同步跟上（淨利年增率為 -0.95%）。"
    ),
    "dimension_insights": {
        "growth": "成長性面向觸發「需注意」訊號。數據顯示營收年增率為 12.32%，而淨利年增率為 -0.95%。",
        "profitability": "獲利能力面向觸發「需注意」訊號。毛利率較前期百分點變化為 -2.14 個百分點。",
        "earnings_quality": "盈餘品質面向維持「未見明顯異常」訊號。共檢視 1 項規則。",
        "investment_efficiency": "投入轉化效率面向維持「未見明顯異常」訊號。共檢視 3 項規則。",
    },
    "watch_items": ["追蹤營收成長（營收年增率為 12.32%）與獲利成長（淨利年增率為 -0.95%）之間的落差情況。"],
    "limitations": ["未提供投資建議或股價預測。"],
}
MATERIAL_EVENT = {
    "event_id": "8f2c0d", "ticker": "2454", "company_name": "聯發科", "subindustry": "IC 設計",
    "event_date": "2026-09-11", "event_time": "18:04:11",
    "title": "代子公司MediaTek Singapore Pte Ltd依公開發行公司資金貸與及背書保證處理準則公告",
    "category": "financing_or_debt", "source_name": "mops", "source_url": LISTING_URL, "detail_url": None,
    "status": "available", "raw_text": "2454 聯發科 115/09/11 18:04:11 代子公司MediaTek Singapore Pte Ltd依公開發行公司資金貸與及背書保證處理準則公告",
    "summary": "已解析 MOPS 重大訊息清單。", "retrieved_at": "2026-10-06T06:00:00Z",
    "limitations": ["MOPS 清單的「詳細資料」以表單送出、沒有可直接開啟的明細網址；已保存清單列的發言日期、時間與主旨，未取得公告明細全文。"],
    "source_identity": {
        "source_type": "mops_listing", "source_name": "mops", "period": None, "period_basis": "none",
        "document_type": None, "filename": None, "event_date": "2026-09-11", "availability": "available",
        "provenance": {"url": LISTING_URL, "sha256": None, "retrieved_at": "2026-10-06T06:00:00Z"},
    },
}


def run(payload: dict) -> dict:
    completed = subprocess.run(
        ["node", str(HARNESS)], input=json.dumps(payload), capture_output=True, text=True,
        encoding="utf-8", check=True, cwd=ROOT,
    )
    return json.loads(completed.stdout)


def financial_card(**trace) -> dict:
    return {
        "schema_version": "frontend-official-evidence-card-1.3.0", "ticker": "2454", "company_name": "聯發科",
        "subindustry": "IC 設計", "overall_severity": "attention", "evidence_readiness": "ready_for_frontend_integration",
        "financial_snapshot": {
            "ticker": "2454", "company_name": "聯發科", "subindustry": "IC 設計", "overall_severity": "attention",
            "rule_cards": [{
                "rule_id": "COM_GROWTH_002", "name": "營收成長但獲利成長未跟上", "severity": "attention",
                "triggered": True, "explanation": "2025FY 營收年增 12.32%，淨利年增 -0.95%。",
                "evidence_periods": ["2025FY"], "threshold_description": "營收成長且淨利衰退",
                "rule_scope": "common", "logic_expression": "revenue_growth_yoy > 0 AND net_income_growth_yoy < 0",
                "evidence_metrics": ["revenue_growth_yoy"], "actual_values": {"revenue_growth_yoy": 12.3222},
            }],
            "ai_analysis": {
                "source_period_start": 2021, "source_period_end": 2025,
                "dimension_assessments": [
                    {"dimension": key, "label": label, "signal": signal, "coverage_ratio": 1.0,
                     "evaluated_rules": 3, "total_rules": 3, "triggered_rule_ids": ids,
                     "direct_metrics": ["revenue_growth_yoy"], "summary": summary}
                    for key, label, signal, ids, summary in DIMENSIONS
                ],
                "rule_monitoring": [],
                "llm_narrative": SERVED_NARRATIVE if trace.get("status", "completed") == "completed" else None,
                "llm_trace": {"enabled": True, "status": "completed", "provider": "gemini",
                              "effective_model": "gemini-3.5-flash-lite", "prompt_version": "financial-analysis-gemini-v3",
                              "used_rule_ids": ["COM_GROWTH_002", "COM_PROFIT_002"], **trace},
            },
        },
    }


def evidence_card(status: dict | None, events: list | None = None) -> dict:
    card = {"schema_version": "frontend-official-evidence-card-1.3.0", "ticker": "2454", "company_name": "聯發科",
            "investor_conferences": [], "material_events": events or [], "sources": [], "limitations": []}
    if status is not None:
        card["material_event_status"] = status
    return card


def material_group(output: dict, key: str = "text") -> str:
    text = output[key]
    start = text.index("重大訊息 Material Event Evidence")
    return text[start:text.index("官方資料來源 Official Sources", start)]


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page script")
class FinancialNarrativeRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.output = run({"mode": "financial", "card": financial_card()})

    def assert_no_identifiers(self, text: str) -> None:
        for token in FORBIDDEN_PRIMARY:
            self.assertNotRegex(text, rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", token)

    def test_primary_sections_expose_no_internal_identifiers(self) -> None:
        for section in ("summary", "rules", "dimensions", "llm"):
            with self.subTest(section=section):
                self.assert_no_identifiers(self.output[section]["primary_text"])

    def test_all_eight_dimensions_render_chinese_labels_and_statuses(self) -> None:
        primary = self.output["dimensions"]["primary_text"]
        for _key, label, *_rest in DIMENSIONS:
            self.assertIn(label, primary)
        self.assertEqual(primary.count("需注意"), 4)  # two badges + two summaries
        self.assertIn("未見明顯異常", primary)
        self.assertIn("營收成長但獲利成長未跟上（需注意）", primary)

    def test_technical_details_keep_rule_ids_for_audit(self) -> None:
        technical = self.output["dimensions"]["technical_text"]
        self.assertIn("技術與規則細節", technical)
        for token in ("COM_GROWTH_002", "SEM_PROFIT_001", "triggered rules", "earnings_quality", "3/3"):
            self.assertIn(token, technical)
        self.assertIn("COM_GROWTH_002", self.output["rules"]["technical_text"])
        self.assertIn("financial-analysis-gemini-v3", self.output["llm"]["technical_text"])
        self.assertIn("COM_PROFIT_002", self.output["llm"]["technical_text"])

    def test_narrative_insights_are_labelled_in_chinese(self) -> None:
        llm = self.output["llm"]["primary_text"]
        self.assertIn("營收年增率為 12.32%", llm)
        for label in ("成長性", "獲利能力", "盈餘品質", "投入轉化效率"):
            self.assertIn(label, llm)
        self.assertEqual(self.output["llm_state"], "AI 財報解讀已完成")

    def test_summary_and_rule_status_are_human_readable(self) -> None:
        self.assertIn("需注意", self.output["summary"]["primary_text"])
        self.assertIn("財報與官方事件證據已整合", self.output["summary"]["primary_text"])
        self.assertIn("判斷：符合規則條件", self.output["rules"]["primary_text"])

    def test_unavailable_narrative_uses_human_wording(self) -> None:
        output = run({"mode": "financial", "card": financial_card(status="failed", error_type="TimeoutError")})
        self.assertEqual(output["llm_state"], "AI 財報解讀暫時無法取得")
        self.assertIn("AI 財報解讀目前無法取得", output["llm"]["primary_text"])
        self.assert_no_identifiers(output["llm"]["primary_text"])
        self.assertIn("TimeoutError", output["llm"]["technical_text"])


@unittest.skipUnless(shutil.which("node"), "node is required to execute the page script")
class MaterialEventRenderingTests(unittest.TestCase):
    def render(self, status: dict | None, events: list | None = None) -> dict:
        return run({"mode": "evidence", "card": evidence_card(status, events)})

    def test_available_records_render_with_provenance(self) -> None:
        output = self.render({"state": "available", "message": "已取得 1 筆近期重大訊息", "record_count": 1,
                              "latest_event_date": "2026-09-11", "last_checked_at": "2026-10-06T06:00:00Z"},
                             [MATERIAL_EVENT])
        group = material_group(output)
        self.assertIn("已取得 1 筆近期重大訊息", group)
        self.assertIn("最新公告日：2026-09-11", group)
        self.assertIn("代子公司MediaTek Singapore", group)
        self.assertIn("發言時間：18:04:11", group)
        self.assertIn("類別：籌資與負債", group)
        self.assertIn("公開資訊觀測站（MOPS）公告", group)
        self.assertIn("日期：2026-09-11", group)
        self.assertIn(LISTING_URL, output["links"])
        self.assertNotIn("目前未取得重大訊息資料", group)
        self.assertNotIn("financing_or_debt", material_group(output, "primary_text"))

    def test_checked_window_without_records(self) -> None:
        group = material_group(self.render({"state": "no_recent_events", "message": "x", "record_count": 0,
                                            "window_start": "2026-07-08", "window_end": "2026-10-06"}))
        self.assertIn("目前查詢期間內未發現重大訊息", group)
        self.assertIn("查詢期間：2026-07-08 至 2026-10-06", group)

    def test_empty_states_without_a_window_check_never_claim_no_events(self) -> None:
        expected = {
            "not_synced": "重大訊息尚未完成同步",
            "source_unavailable": "官方來源目前無法取得，請稍後再試",
            "needs_refresh": "已檢查當日公告，尚未完成近期歷史查詢",
        }
        for state, wording in expected.items():
            with self.subTest(state=state):
                group = material_group(self.render({"state": state, "message": "x", "record_count": 0}))
                self.assertIn(wording, group)
                self.assertNotIn("未發現", group)
                self.assertNotIn("目前未取得重大訊息資料", group)

    def test_legacy_card_without_status_does_not_imply_no_events(self) -> None:
        group = material_group(self.render(None))
        self.assertIn("不代表公司沒有重大訊息", group)
        self.assertNotIn("未發現", group)

    def test_records_from_another_company_are_not_rendered(self) -> None:
        other = copy.deepcopy(MATERIAL_EVENT)
        other.update(ticker="2408", company_name="南亞科", title="公告本公司取得廠務設備", raw_text="2408 南亞科 公告本公司取得廠務設備")
        card = evidence_card({"state": "available", "message": "x", "record_count": 1}, [other])
        card.update(ticker="2408", company_name="南亞科")
        group = material_group(run({"mode": "evidence", "card": card}))
        self.assertIn("公告本公司取得廠務設備", group)
        self.assertNotIn("MediaTek", group)
        self.assertNotIn("聯發科", group)


if __name__ == "__main__":
    unittest.main()
