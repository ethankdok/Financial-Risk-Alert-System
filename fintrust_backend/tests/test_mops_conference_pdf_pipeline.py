from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from app.services.mops_conference_pdf_pipeline import parse_listing, run_mops_pdf_pipeline
from app.services.official_ir_pdf_archive import AcquisitionError


def listing(*, extra_page: bool = False, bad_link: bool = False) -> bytes:
    link = ('document.fm_fileDownload.fileName.value=&quot;233020250116M001.pdf&quot;;'
            'document.fm_fileDownload.submit();')
    if bad_link:
        link = 'alert(&quot;broken&quot;);'
    return (f'<form action="/server-java/FileDownLoad"></form>'
            '<table><thead><tr><th>公司代號</th><th>法人說明會簡報內容</th></tr></thead>'
            '<tbody><tr data-type="body"><td>2330</td><td>台積電</td>'
            '<td>114/01/16</td><td>x</td><td>x</td><td>x</td>'
            f'<td><a onclick="{link}">233020250116M001.pdf</a></td><td></td></tr>'
            '<tr data-type="body"><td>2330</td><td>台積電</td>'
            '<td>114/01/16</td><td>x</td><td>x</td><td>x</td>'
            f'<td><a onclick="{link}">233020250116M001.pdf</a></td><td></td></tr></tbody></table>'
            f'<input onclick="page(1)" value="1">'
            f'{"<input onclick=\"page(2)\" value=\"2\">" if extra_page else ""}').encode()


def pdf(*, chart: bool = False) -> bytes:
    from reportlab.pdfgen import canvas

    output = io.BytesIO()
    document = canvas.Canvas(output)
    document.drawString(72, 720, "Investor conference statement with sufficient selectable text")
    if chart:
        document.rect(72, 600, 100, 100)
    document.save()
    return output.getvalue()


class FixtureTransport:
    def __init__(self, document: bytes | None, html: bytes | None = None) -> None:
        self.document = document
        self.html = html or listing()
        self.download_calls = 0

    def listing(self, ticker: str, roc_year: int, market: str) -> bytes:
        assert (ticker, roc_year, market) == ("2330", 114, "sii")
        return self.html

    def pdf(self, filename: str, referer: str) -> bytes:
        assert filename == "233020250116M001.pdf"
        self.download_calls += 1
        return self.document or b"<html>Access denied</html>"


class ConferencePdfPipelineTests(unittest.TestCase):
    def test_duplicate_rows_download_once_and_repeated_sync_records_hash_change(self) -> None:
        transport = FixtureTransport(pdf())
        with tempfile.TemporaryDirectory() as root:
            kwargs = dict(ticker="2330", year=2025, output_dir=Path(root), transport=transport)
            first = run_mops_pdf_pipeline(**kwargs)
            self.assertEqual((first["rows"], first["expected_pdfs"], transport.download_calls), (2, 1, 1))
            self.assertEqual(first["status"], "complete")
            self.assertEqual(first["documents"][0]["change"], "new")
            again = run_mops_pdf_pipeline(**kwargs)
            self.assertEqual(again["documents"][0]["change"], "unchanged")
            pages = json.loads(Path(again["documents"][0]["pages_path"]).read_text())
            self.assertGreater(pages[0]["text_length"], 30)

    def test_missing_pdf_causes_batch_failure(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = run_mops_pdf_pipeline(ticker="2330", year=2025, output_dir=Path(root),
                                           transport=FixtureTransport(None))
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["downloaded_pdfs"], 0)
            self.assertTrue(result["errors"])

    def test_chart_is_archived_but_strict_batch_fails_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            result = run_mops_pdf_pipeline(ticker="2330", year=2025, output_dir=Path(root),
                                           transport=FixtureTransport(pdf(chart=True)))
            self.assertEqual((result["status"], result["downloaded_pdfs"]), ("failed", 1))
            doc = result["documents"][0]
            self.assertEqual(doc["status"], "needs_review")
            page = json.loads(Path(doc["pages_path"]).read_text())[0]
            self.assertTrue(Path(page["review_image_path"]).is_file())

    def test_unverified_pagination_and_broken_links_are_rejected(self) -> None:
        for html in (listing(extra_page=True), listing(bad_link=True)):
            with self.subTest(html=html[-120:]):
                with self.assertRaises(AcquisitionError):
                    parse_listing(html, ticker="2330", roc_year=114)


if __name__ == "__main__":
    unittest.main()
