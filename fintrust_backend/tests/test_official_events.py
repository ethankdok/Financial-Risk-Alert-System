from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.services.analysis_repository import SqliteAnalysisRepository
from app.services.official_evidence_service import OfficialEvidenceService
from app.services.official_event_sources import (
    classify_material_event,
    investor_conference_identity,
    material_event_identity,
    parse_twse_material_event_rows,
    parse_investor_conference_html,
    parse_material_event_detail_html,
    parse_material_event_list_html,
)
from app.services.official_company_ir_sources import parse_mediatek_quarterly_earnings_html


CONFERENCE_HTML = """
<html><body><table>
<tr><th>日期</th><th>公司</th><th>說明</th><th>附件</th></tr>
<tr>
  <td>2024/08/01</td>
  <td>2454 聯發科</td>
  <td>法人說明會簡報：展望 demand、inventory、產品 roadmap</td>
  <td><a href="/mops/web/ajax_t100sb07?file=2454_presentation.pdf">簡報 PDF</a></td>
</tr>
</table></body></html>
"""

MATERIAL_LIST_HTML = """
<html><body><table>
<tr><th>日期</th><th>時間</th><th>公司代號</th><th>公司名稱</th><th>主旨</th><th>詳細資料</th></tr>
<tr>
  <td>2024/09/20</td>
  <td>17:35:00</td>
  <td>2454</td>
  <td>聯發科</td>
  <td>公告本公司董事會決議資本支出與研發投資案</td>
  <td><a href="/mops/web/t05st01?co_id=2454&spoke_date=20240920&spoke_time=173500&seq_no=1">詳細資料</a></td>
</tr>
</table></body></html>
"""

MATERIAL_DETAIL_HTML = """
<html><body>
<h1>重大訊息</h1>
<p>主旨：公告本公司董事會決議資本支出與研發投資案</p>
<p>事實發生日：2024/09/20</p>
<p>說明：本案涉及資本支出、研發與營運需求，內容均以公開資訊觀測站公告為準。</p>
</body></html>
"""

TWSE_OPENAPI_ROWS = [
    {
        "出表日期": "1150901",
        "發言日期": "1150831",
        "發言時間": "150001",
        "公司代號": "2454",
        "公司名稱": "聯發科",
        "主旨 ": "公告本公司受邀參加法人說明會，說明營運展望",
        "符合條款": "第12款",
        "事實發生日": "1150902",
        "說明": "法人說明會擇要訊息：說明本公司財務及營運展望。",
    }
]

MEDIATEK_IR_HTML = """
<html><body>
<div class="quarterly_ern_acc_item active">
  <h4><a href="javascript:%20void(0);">Q2 </a></h4>
  <a href="https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/Quarterly%20Earnings%20Release/2026/Quarterly%20Earnings%20Release-2026Q2/MediaTek%20Inc.%20to%20Webcast%202Q26%20Result%20Conference%20Call%20on%20July%2031%202026.pdf" target="_blank"></a>
  <span>Earnings call invitation</span>
  <a href="https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/Quarterly%20Earnings%20Release/2026/Quarterly%20Earnings%20Release-2026Q2/Presentation.pdf" target="_blank"></a>
  <span>Presentation</span>
  <a href="https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/Quarterly%20Earnings%20Release/2026/Quarterly%20Earnings%20Release-2026Q2/Transcript.pdf" target="_blank"></a>
  <span>Transcript</span>
</div>
</body></html>
"""


class OfficialEventTests(unittest.TestCase):
    def test_conference_parser_extracts_document_topics_and_identity(self) -> None:
        records = parse_investor_conference_html("2454", CONFERENCE_HTML, source_url="https://mops.example/conference")

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.ticker, "2454")
        self.assertEqual(record.conference_date, "2024-08-01")
        self.assertEqual(record.document_extract_status, "document_link_found")
        self.assertTrue(record.document_url)
        self.assertIn("庫存、需求與產品去化", record.extracted_topics)
        self.assertEqual(record.event_id, investor_conference_identity(record))

    def test_material_event_parser_and_classifier_extract_live_row_fields(self) -> None:
        detail_text = parse_material_event_detail_html(MATERIAL_DETAIL_HTML)
        self.assertIsNotNone(detail_text)

        records = parse_material_event_list_html("2454", MATERIAL_LIST_HTML, source_url="https://mops.example/material")
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.event_date, "2024-09-20")
        self.assertEqual(record.event_time, "17:35:00")
        self.assertEqual(record.category, "capacity_or_capex")
        self.assertTrue(record.risk_related)
        self.assertTrue(record.detail_url)
        self.assertEqual(record.event_id, material_event_identity(record))

        category, metrics, risk_related = classify_material_event(record.title, record.raw_text)
        self.assertEqual(category, "capacity_or_capex")
        self.assertIn("capex_intensity", metrics)
        self.assertTrue(risk_related)

    def test_twse_openapi_rows_map_to_existing_material_event_model(self) -> None:
        records = parse_twse_material_event_rows("2454", TWSE_OPENAPI_ROWS)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.source_name, "twse_openapi")
        self.assertEqual(record.source_url, "https://openapi.twse.com.tw/v1/opendata/t187ap04_L")
        self.assertEqual(record.event_date, "2026-09-02")
        self.assertEqual(record.event_time, "15:00:01")
        self.assertIn("第12款", record.summary or "")
        self.assertEqual(record.event_id, material_event_identity(record))

    def test_mediatek_ir_parser_extracts_official_quarterly_documents(self) -> None:
        records = parse_mediatek_quarterly_earnings_html(MEDIATEK_IR_HTML)

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.source_name, "company_official_ir")
        self.assertEqual(record.fiscal_year, 2026)
        self.assertEqual(record.quarter, 2)
        self.assertEqual(record.conference_date, "2026-07-31")
        self.assertEqual(record.document_title, "Transcript")
        self.assertTrue(record.document_url and record.document_url.endswith("/Transcript.pdf"))
        self.assertEqual(record.event_id, investor_conference_identity(record))

    def test_official_event_persistence_is_idempotent_and_aggregate_reads_persisted_data(self) -> None:
        conferences = parse_investor_conference_html("2454", CONFERENCE_HTML, source_url="https://mops.example/conference")
        material_events = parse_material_event_list_html("2454", MATERIAL_LIST_HTML, source_url="https://mops.example/material")
        with tempfile.TemporaryDirectory() as tmp:
            repository = SqliteAnalysisRepository(str(Path(tmp) / "pipeline.sqlite3"))
            refreshed_at = datetime.now(timezone.utc)
            repository.save_official_events(
                ticker="2454",
                investor_conferences=conferences,
                material_events=material_events,
                refreshed_at=refreshed_at,
            )
            repository.save_official_events(
                ticker="2454",
                investor_conferences=conferences,
                material_events=material_events,
                refreshed_at=refreshed_at,
            )

            persisted_conferences = repository.list_investor_conferences("2454")
            persisted_material_events = repository.list_material_events("2454")
            summary = OfficialEvidenceService(repository=repository).build("2454")

        self.assertEqual(len(persisted_conferences), 1)
        self.assertEqual(len(persisted_material_events), 1)
        self.assertEqual(len(summary.investor_conferences), 1)
        self.assertEqual(len(summary.material_events), 1)
        self.assertIn("investor_conference", summary.evidence_layers)
        self.assertIn("material_event", summary.evidence_layers)


if __name__ == "__main__":
    unittest.main()
