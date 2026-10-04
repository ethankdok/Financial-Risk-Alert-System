"""P3: result.html Official Evidence shows source, period and summary state per
item, keeps company-IR records and MOPS digests as separate sources, and
prefers card.financial_snapshot. Runs the real script.js render functions."""
from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.test_conference_digest_frontend import fixture_digest

ROOT = Path(__file__).resolve().parents[1]
IR_URL = "https://www.mediatek.com/hubfs/Quarterly%20Earnings%20Release-2026Q2/Transcript.pdf"
MOPS_FILE = "245420251031M001.pdf"
STATE_LABELS = {
    "attached": "已連結同期間 MOPS 法說會文件",
    "standalone_latest": "顯示最新可用的 MOPS 法說會文件",
    "no_matching_archive": "尚無此期間的 MOPS 歸檔法說會文件",
    "archive_unavailable": "MOPS 文件歸檔目前無法讀取",
    "digest_failed": "官方文件摘要產生失敗",
    "digest_timeout": "官方文件摘要處理逾時",
    "not_configured": "此次資料未啟用官方文件摘要",
}


def ir_identity(period: str | None, date: str | None, **overrides) -> dict:
    identity = {"source_type": "company_ir", "source_name": "company_official_ir", "period": period,
                "period_basis": "fiscal_year_quarter" if period else "none", "document_type": None, "filename": None,
                "event_date": date, "availability": "available",
                "provenance": {"url": IR_URL, "sha256": None, "retrieved_at": "2026-09-26T00:00:00Z"}}
    identity.update(overrides)
    return identity


def ir_item(period: str, date: str, **extra) -> dict:
    year, quarter = period.split("Q")
    return {"event_id": f"ir-{period}", "title": f"MediaTek {year} Q{quarter} Results - Investors Conference",
            "status": "available", "conference_date": date, "source_name": "company_official_ir",
            "source_url": "https://www.mediatek.com/zh-tw/investor-relations", "document_url": IR_URL,
            "summary": "公司官方 IR 法說會資料。", "extracted_topics": ["營收"], "source_identity": ir_identity(period, date),
            **extra}


EVENT = {"event_id": "capex", "title": "公告本公司董事會決議資本支出案", "status": "available", "event_date": "2026-09-01",
         "source_name": "twse_openapi", "source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
         "source_identity": {"source_type": "twse_openapi", "source_name": "twse_openapi", "period": None, "period_basis": "none",
                             "document_type": None, "filename": None, "event_date": "2026-09-01", "availability": "available",
                             "provenance": {"url": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L", "sha256": None,
                                            "retrieved_at": None}}}


@unittest.skipUnless(shutil.which("node"), "node is required to execute script.js render functions")
class ResultOfficialSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        digest = fixture_digest()
        source = digest["source"]
        digest["source_identity"] = {
            "source_type": "mops_conference_pdf", "source_name": "MOPS", "period": digest["period"],
            "period_basis": "document_identity", "document_type": digest["document_type"], "filename": source["filename"],
            "event_date": digest["conference_date"], "availability": "available",
            "provenance": {"url": source["listing_url"], "sha256": source["sha256"], "retrieved_at": None},
        }
        cls.digest = digest
        cls.sha = source["sha256"]

    def harness(self, payload: dict) -> dict:
        completed = subprocess.run(["node", str(ROOT / "tests" / "frontend_render_harness.js")],
                                   input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                   capture_output=True, check=True, timeout=60)
        return json.loads(completed.stdout.decode("utf-8"))

    def card(self, **overrides) -> dict:
        card = {"schema_version": "frontend-official-evidence-card-1.2.0", "ticker": "2454", "company_name": "聯發科",
                "financial_snapshot": {"company_name": "聯發科", "summary": "card snapshot", "sources": [], "limitations": []},
                "investor_conferences": [ir_item("2026Q2", "2026-07-31", summary_status="no_matching_archive")],
                "conference_document_digest": copy.deepcopy(self.digest), "conference_summary_state": "standalone_latest",
                "material_events": [copy.deepcopy(EVENT)], "sources": [], "limitations": []}
        card.update(overrides)
        return card

    def evidence(self, card: dict) -> dict:
        output = self.harness({"mode": "evidence", "card": card})
        self.assert_clean(output["text"])
        return output

    def assert_clean(self, rendered: str) -> None:
        self.assertNotRegex(rendered, r"\bundefined\b|\bnull\b|\bNone\b|\bNaN\b|\[object Object\]")

    @staticmethod
    def items(html: str) -> list[str]:
        return re.split(r'(?=<div class="financial-official-item">)', html)[1:]

    def test_2454_company_ir_item_and_standalone_mops_digest_render_as_separate_items(self) -> None:
        output = self.evidence(self.card())
        text = output["text"]
        self.assertIn(f"官方文件摘要狀態：{STATE_LABELS['standalone_latest']}", text)
        conference_items = [item for item in self.items(output["html"]) if "法說會" in item][:2]
        mops_item, ir_html = conference_items
        self.assertIn("MOPS 法說會文件 2025Q3", mops_item)
        self.assertIn("公開資訊觀測站（MOPS）法說會文件", mops_item)
        self.assertIn(f"文件：{MOPS_FILE}", mops_item)
        self.assertIn("期間：2025Q3", mops_item)
        self.assertNotIn("mediatek.com", mops_item)
        self.assertIn("聯發科 公司官方投資人關係（IR）", ir_html)
        self.assertIn("期間：2026Q2", ir_html)
        self.assertIn("狀態：可用", ir_html)
        self.assertIn(STATE_LABELS["no_matching_archive"], ir_html)
        self.assertNotIn(MOPS_FILE, ir_html)
        self.assertNotIn(self.sha, ir_html)

    def test_matched_period_keeps_company_ir_and_mops_source_blocks_apart(self) -> None:
        matched = ir_item("2025Q3", "2025-10-31", summary_status="available", document_digest=copy.deepcopy(self.digest))
        output = self.evidence(self.card(investor_conferences=[matched], conference_document_digest=None,
                                         conference_summary_state="attached"))
        self.assertIn(f"官方文件摘要狀態：{STATE_LABELS['attached']}", output["text"])
        item = self.items(output["html"])[0]
        start = item.index('class="financial-digest-source"')
        end = item.index("技術細節 Technical details")
        ir_block, mops_block = item[:start], item[start:end]
        # Source A: company IR only.
        self.assertIn("法說會資料來源", ir_block)
        self.assertIn("公司官方投資人關係（IR）", ir_block)
        self.assertIn(IR_URL.replace("&", "&amp;"), ir_block)
        self.assertNotIn(MOPS_FILE, ir_block)
        self.assertNotIn(self.sha, ir_block)
        # Source B: MOPS only; the company IR link is never its provenance.
        self.assertIn("MOPS 歸檔法說會文件", mops_block)
        self.assertIn(f"文件：{MOPS_FILE}", mops_block)
        self.assertIn(self.digest["source"]["listing_url"].replace("&", "&amp;"), mops_block)
        self.assertNotIn("mediatek.com", mops_block)
        self.assertIn("官方文件摘要 Official Document Summary", mops_block)

    def test_every_summary_state_and_item_status_has_chinese_wording(self) -> None:
        for state, label in STATE_LABELS.items():
            output = self.evidence(self.card(conference_summary_state=state, conference_document_digest=None))
            self.assertIn(f"官方文件摘要狀態：{label}", output["text"], state)
            self.assertNotIn(state, output["text"])
        item_statuses = {**STATE_LABELS, "available": STATE_LABELS["attached"],
                         "no_conference_period": "此筆資料沒有可比對的期間或日期"}
        item_statuses.pop("attached")
        item_statuses.pop("standalone_latest")
        item_statuses.pop("not_configured")
        for status, label in item_statuses.items():
            item = ir_item("2026Q2", "2026-07-31", summary_status=status)
            output = self.evidence(self.card(investor_conferences=[item], conference_document_digest=None))
            self.assertIn(label, output["text"], status)

    def test_unusual_source_values_render_safely(self) -> None:
        unknown = ir_item("2026Q2", "2026-07-31")
        unknown["source_identity"].update(source_type="unknown", availability="needs_review")
        odd = ir_item("2026Q1", "2026-04-30")
        odd["source_identity"].update(source_type="something_new", availability="something_else")
        demo_event = copy.deepcopy(EVENT)
        demo_event["source_identity"]["source_type"] = "demo_fixture"
        output = self.evidence(self.card(investor_conferences=[unknown, odd], material_events=[demo_event],
                                         conference_document_digest=None, conference_summary_state="no_matching_archive"))
        for label in ("來源未分類", "待人工確認", "示範資料（非官方即時資料）", "狀態未分類"):
            self.assertIn(label, output["text"])
        for raw_value in ("needs_review", "demo_fixture", "something_new", "something_else"):
            self.assertNotIn(raw_value, output["text"])

    def test_null_identity_fields_are_omitted_not_printed(self) -> None:
        bare = ir_item("2026Q2", "2026-07-31")
        bare["source_identity"] = ir_identity(None, None, provenance={"url": None, "sha256": None, "retrieved_at": None})
        output = self.evidence(self.card(investor_conferences=[bare], conference_document_digest=None))
        item = self.items(output["html"])[0]
        for label in ("期間：", "文件類型：", "文件：", "日期："):
            self.assertNotIn(label, item)
        self.assertNotIn('href=""', output["html"])

    def test_schema_110_payload_without_source_identity_still_renders(self) -> None:
        legacy_item = ir_item("2026Q2", "2026-07-31", summary_status="no_matching_archive")
        legacy_item.pop("source_identity")
        legacy_event = {key: value for key, value in EVENT.items() if key != "source_identity"}
        digest = copy.deepcopy(self.digest)
        digest.pop("source_identity")
        card = self.card(investor_conferences=[legacy_item], material_events=[legacy_event], conference_document_digest=digest)
        card.pop("conference_summary_state")
        card["schema_version"] = "frontend-official-evidence-card-1.1.0"
        output = self.evidence(card)
        self.assertNotIn("官方文件摘要狀態", output["text"])
        self.assertIn("來源：company_official_ir", output["text"])
        self.assertIn("日期：2026-07-31", output["text"])
        self.assertIn("MOPS 歸檔法說會文件", output["text"])
        self.assertIn(STATE_LABELS["no_matching_archive"], output["text"])

    def test_financial_snapshot_is_preferred_over_raw_snapshot(self) -> None:
        both = {"financial_snapshot": {"summary": "card snapshot"}, "raw": {"snapshot": {"summary": "raw snapshot"}}}
        self.assertEqual(self.harness({"mode": "snapshot", "card": both})["snapshot"], {"summary": "card snapshot"})
        raw_only = {"raw": {"snapshot": {"summary": "raw snapshot"}}}
        self.assertEqual(self.harness({"mode": "snapshot", "card": raw_only})["snapshot"], {"summary": "raw snapshot"})
        self.assertEqual(self.harness({"mode": "snapshot", "card": {}})["snapshot"], {})

    def test_partial_coverage_reads_as_partial_not_failure(self) -> None:
        self.assertEqual(self.digest["coverage"]["coverage_status"], "partial")
        output = self.evidence(self.card())
        mops_item = self.items(output["html"])[0]
        self.assertIn("涵蓋部分", mops_item)
        self.assertIn("摘要涵蓋部分 / Coverage partial", mops_item)
        self.assertNotIn("失敗", mops_item)
        self.assertNotIn("逾時", mops_item)

    def test_technical_provenance_stays_collapsed_and_jsd_stays_out(self) -> None:
        output = self.evidence(self.card())
        mops_item = self.items(output["html"])[0]
        # SHA only inside the collapsed Provenance details, never in the visible source line.
        provenance_start = mops_item.index("查看原始證據 / Provenance")
        self.assertNotIn(self.sha, mops_item[:provenance_start])
        self.assertIn(self.sha, mops_item[provenance_start:])
        self.assertNotRegex(output["text"], r"(?i)\bjsd\b|cosine")


class ResultScriptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.js = (ROOT / "script.js").read_text(encoding="utf-8")

    def test_snapshot_selection_and_source_rendering_are_wired(self) -> None:
        self.assertIn("const snapshot = selectFinancialSnapshot(card);", self.js)
        self.assertIn("card.financial_snapshot || card.raw?.snapshot || {}", self.js)
        self.assertIn("card.conference_summary_state", self.js)
        self.assertIn("appendSourceIdentity(section, digest.source_identity", self.js)

    def test_digest_block_never_uses_the_record_source_link(self) -> None:
        start = self.js.index("// Source B: the archived MOPS PDF digest")
        end = self.js.index("appendDisclosureClaims(row, item.disclosure_claims);", start)
        self.assertNotIn("buildSourceLink", self.js[start:end])
        self.assertNotRegex(self.js[start:end], r"innerHTML|insertAdjacentHTML|outerHTML")


if __name__ == "__main__":
    unittest.main()
