from __future__ import annotations

import io
import json
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from app.services.mops_conference_pdf_pipeline import ListedAttachment, parse_listing, run_mops_pdf_pipeline
from app.services.official_ir_pdf_archive import AcquisitionError


def listing(*, extra_page: bool = False, bad_link: bool = False, filename: str = "233020250116M001.pdf") -> bytes:
    link = ('document.fm_fileDownload.fileName.value=&quot;233020250116M001.pdf&quot;;'
            'document.fm_fileDownload.filePath.value=&quot;/home/html/nas/STR/&quot;;'
            'document.fm_fileDownload.functionName.value=&quot;t100sb02_1&quot;;'
            'document.fm_fileDownload.submit();')
    link = link.replace("233020250116M001.pdf", filename)
    if bad_link:
        link = 'alert(&quot;broken&quot;);'
    return (f'<form action="/server-java/FileDownLoad"></form>'
            '<table><thead><tr><th>公司代號</th><th>法人說明會簡報內容</th></tr></thead>'
            '<tbody><tr data-type="body"><td>2330</td><td>台積電</td>'
            '<td>114/01/16</td><td>x</td><td>x</td><td>x</td>'
            f'<td><a onclick="{link}">{filename}</a></td><td></td></tr>'
            '<tr data-type="body"><td>2330</td><td>台積電</td>'
            '<td>114/01/16</td><td>x</td><td>x</td><td>x</td>'
            f'<td><a onclick="{link}">{filename}</a></td><td></td></tr></tbody></table>'
            f'<input onclick="page(1)" value="1">'
            f'{"<input onclick=\"page(2)\" value=\"2\">" if extra_page else ""}').encode()


def mixed_listing(second: str) -> bytes:
    """Row 1: the fixture PDF. Row 2: another official attachment named ``second``."""
    def link(name: str) -> str:
        return (f'document.fm_fileDownload.fileName.value=&quot;{name}&quot;;'
                'document.fm_fileDownload.filePath.value=&quot;/home/html/nas/STR/&quot;;'
                'document.fm_fileDownload.functionName.value=&quot;t100sb02_1&quot;;'
                'document.fm_fileDownload.submit();')

    rows = "".join(
        '<tr data-type="body"><td>2330</td><td>台積電</td><td>114/01/16</td><td>x</td><td>x</td>'
        f'<td>公布本公司財務報告</td><td><a onclick="{link(name)}">{name}</a></td><td></td></tr>'
        for name in ("233020250116M001.pdf", second)
    )
    return ('<form action="/server-java/FileDownLoad"></form>'
            '<table><thead><tr><th>公司代號</th><th>法人說明會簡報內容</th></tr></thead>'
            f'<tbody>{rows}</tbody></table><input onclick="page(1)" value="1">').encode()


def pdf(*, chart: bool = False) -> bytes:
    return b"%PDF-1.4\n% fintrust fixture\n%%EOF\n"


def extracted_pages(*, chart: bool = False):
    page = {
        "page": 1,
        "text": "Investor conference statement with revenue 100 and gross margin 55%",
        "text_length": 65,
        "text_extraction_method": "selectable_text",
        "analysis_results": [
            {
                "kind": "numeric_text",
                "filename": "233020250116M001.pdf",
                "page": 1,
                "value_text": "100",
                "source_excerpt": "revenue 100 and gross margin 55%",
                "extraction_method": "selectable_text",
                "confidence": "medium",
                "verification_status": "needs_context_review",
            }
        ],
        "numeric_candidate_count": 1,
        "table_candidate_count": 0,
        "visual_review_required": False,
    }
    if chart:
        page["visual_review_required"] = True
        page["analysis_results"].append({
            "kind": "chart_or_image_region",
            "filename": "233020250116M001.pdf",
            "page": 1,
            "region": "full_page_visual_layer",
            "extraction_method": "pdf_visual_heuristic",
            "confidence": "low",
            "verification_status": "needs_manual_chart_value_verification",
        })
        return [page], ["page_1:visual_review_required", "page_1:chart_values_unverified"]
    return [page], []


class FixtureTransport:
    def __init__(self, document: bytes | None, html: bytes | None = None) -> None:
        self.document = document
        self.html = html or listing()
        self.download_calls = 0

    def listing(self, ticker: str, roc_year: int, market: str, page: int = 1) -> bytes:
        assert (ticker, roc_year, market) == ("2330", 114, "sii")
        return self.html

    def pdf(self, attachment: ListedAttachment, referer: str) -> bytes:
        assert attachment.filename == "233020250116M001.pdf"
        assert attachment.file_path == "/home/html/nas/STR/"
        assert attachment.function_name == "t100sb02_1"
        self.download_calls += 1
        return self.document or b"<html>Access denied</html>"


class PagedTransport(FixtureTransport):
    def __init__(self) -> None:
        super().__init__(pdf(), html=listing(extra_page=True, filename="233020250116M001.pdf"))
        self.pages_seen: list[int] = []

    def listing(self, ticker: str, roc_year: int, market: str, page: int = 1) -> bytes:
        self.pages_seen.append(page)
        if page == 2:
            return listing(filename="233020250117M002.pdf")
        return self.html

    def pdf(self, attachment: ListedAttachment, referer: str) -> bytes:
        self.download_calls += 1
        return self.document or b"<html>Access denied</html>"


class ConferencePdfPipelineTests(unittest.TestCase):
    def test_duplicate_rows_download_once_and_repeated_sync_records_hash_change(self) -> None:
        transport = FixtureTransport(pdf())
        with tempfile.TemporaryDirectory() as root:
            kwargs = dict(ticker="2330", year=2025, output_dir=Path(root), transport=transport)
            with unittest.mock.patch(
                "app.services.mops_conference_pdf_pipeline.extract_pages",
                return_value=extracted_pages(),
            ):
                first = run_mops_pdf_pipeline(**kwargs)
                again = run_mops_pdf_pipeline(**kwargs)
            self.assertEqual((first["rows"], first["expected_pdfs"], transport.download_calls), (2, 1, 2))
            self.assertEqual(first["status"], "complete")
            self.assertEqual(first["documents"][0]["change"], "new")
            self.assertEqual(again["documents"][0]["change"], "unchanged")
            pages = json.loads(Path(again["documents"][0]["pages_path"]).read_text())
            self.assertGreater(pages[0]["text_length"], 30)
            self.assertTrue(Path(again["documents"][0]["analysis_path"]).is_file())
            self.assertGreaterEqual(again["documents"][0]["analysis_results"], 0)

    def test_multiple_listing_pages_are_fetched_before_batch_can_pass(self) -> None:
        transport = PagedTransport()
        with tempfile.TemporaryDirectory() as root:
            with unittest.mock.patch(
                "app.services.mops_conference_pdf_pipeline.extract_pages",
                return_value=extracted_pages(),
            ):
                result = run_mops_pdf_pipeline(ticker="2330", year=2025, output_dir=Path(root), transport=transport)

        self.assertEqual(result["listing_pages"], [1, 2])
        self.assertEqual(result["expected_pdfs"], 2)
        self.assertEqual(result["downloaded_pdfs"], 2)
        self.assertIn(2, transport.pages_seen)
        self.assertEqual(result["status"], "complete")

    def test_missing_pdf_causes_batch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = run_mops_pdf_pipeline(ticker="2330", year=2025, output_dir=Path(root),
                                           transport=FixtureTransport(None))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["downloaded_pdfs"], 0)
            self.assertTrue(result["errors"])

    def test_chart_is_archived_but_strict_batch_fails_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            with unittest.mock.patch(
                "app.services.mops_conference_pdf_pipeline.extract_pages",
                return_value=extracted_pages(chart=True),
            ), unittest.mock.patch("app.services.mops_conference_pdf_pipeline.render_review_pages"):
                result = run_mops_pdf_pipeline(ticker="2330", year=2025, output_dir=Path(root),
                                               transport=FixtureTransport(pdf(chart=True)))
            self.assertEqual((result["status"], result["downloaded_pdfs"]), ("failed", 1))
            doc = result["documents"][0]
            self.assertEqual(doc["status"], "needs_review")
            page = json.loads(Path(doc["pages_path"]).read_text())[0]
            self.assertTrue(any(item["verification_status"] == "needs_manual_chart_value_verification"
                                for item in page["analysis_results"]))

    def test_official_powerpoint_attachment_is_a_recorded_source_gap_never_downloaded(self) -> None:
        html = mixed_listing("233020191017E001.pptx")
        with self.assertRaisesRegex(AcquisitionError, "Unexpected attachment filename"):
            parse_listing(html, ticker="2330", roc_year=114)  # strict default is unchanged

        gaps: list[dict] = []
        attachments, rows = parse_listing(html, ticker="2330", roc_year=114, non_pdf=gaps)
        self.assertEqual(([item.filename for item in attachments], rows), (["233020250116M001.pdf"], 2))
        self.assertEqual([(gap["filename"], gap["language"]) for gap in gaps], [("233020191017E001.pptx", "zh")])

        transport = FixtureTransport(pdf(), html=html)
        with tempfile.TemporaryDirectory() as root, unittest.mock.patch(
            "app.services.mops_conference_pdf_pipeline.extract_pages", return_value=extracted_pages(),
        ):
            result = run_mops_pdf_pipeline(ticker="2330", year=2025, output_dir=Path(root), transport=transport)
        self.assertEqual((result["expected_pdfs"], transport.download_calls), (1, 1))  # FixtureTransport asserts the PDF name
        self.assertEqual([(gap["filename"], gap["format"], gap["status"]) for gap in result["non_pdf_attachments"]],
                         [("233020191017E001.pptx", "pptx", "source_gap_non_pdf_format")])

    def test_unknown_or_foreign_attachment_names_still_fail_closed(self) -> None:
        for name in ("233020191017E001.exe", "245420191017E001.pptx", "slides-final.pptx"):
            with self.subTest(name=name), self.assertRaisesRegex(AcquisitionError, "Unexpected attachment filename"):
                parse_listing(mixed_listing(name), ticker="2330", roc_year=114, non_pdf=[])

    def test_no_data_page_is_no_listing_not_a_parser_failure(self) -> None:
        from app.services.mops_conference_pdf_pipeline import discover_mops_conference_documents

        page = "<html><body><h4 align='center'><font color='red'>查無資料</font></h4></body></html>".encode("utf-8")
        with self.assertRaisesRegex(AcquisitionError, "查無資料"):
            parse_listing(page, ticker="2330", roc_year=114)
        result = discover_mops_conference_documents(ticker="2330", year=2025, transport=FixtureTransport(None, html=page))
        self.assertEqual(result["status"], "no_listing")

    def test_text_only_extraction_keeps_page_text_identical(self) -> None:
        import pymupdf

        from app.services.mops_conference_pdf_pipeline import extract_pages

        document = pymupdf.open()
        for number in range(2):
            page = document.new_page(width=960, height=540)
            page.insert_text((60, 80), f"Quarterly results page {number + 1}: revenue 100, gross margin 55%")
            for offset in range(6):
                page.draw_rect(pymupdf.Rect(100 + offset * 40, 300 - offset * 20, 130 + offset * 40, 400))
        raw = document.tobytes()

        with unittest.mock.patch("app.services.mops_conference_pdf_pipeline.extract_semantic_evidence",
                                 wraps=__import__("app.services.mops_conference_pdf_pipeline", fromlist=["x"])
                                 .extract_semantic_evidence) as semantic:
            full, _ = extract_pages(raw, filename="233020250116E001.pdf")
            text_only, _ = extract_pages(raw, filename="233020250116E001.pdf", semantic_analysis=False)

        self.assertEqual(semantic.call_count, 1)
        self.assertEqual([page["text"] for page in text_only], [page["text"] for page in full])
        self.assertTrue(all(not page.get("semantic_evidence") for page in text_only))

    def test_broken_links_are_rejected(self) -> None:
        for html in (listing(bad_link=True),):
            with self.subTest(html=html[-120:]):
                with self.assertRaises(AcquisitionError):
                    parse_listing(html, ticker="2330", roc_year=114)


if __name__ == "__main__":
    unittest.main()
