from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from app.services.official_ir_pdf_archive import AcquisitionError, acquire_page, discover_pdfs


def _sample_pdf() -> bytes:
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        raise unittest.SkipTest("reportlab is needed to generate the PDF fixture")
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer)
    page.drawString(72, 720, "Quarterly earnings conference statement")
    page.save()
    return buffer.getvalue()


class OfficialIrPdfArchiveTests(unittest.TestCase):
    def test_discovery_only_selects_allowed_real_pdf_links(self) -> None:
        html = ('<a href="/reports/2025%20Q4.pdf">Transcript</a>'
                '<a href="https://evil.example/report.pdf">Other</a>'
                '<a href="/results">Presentation</a>')
        matches = discover_pdfs(html, "https://investor.tsmc.com/english/quarterly-results/2025/q4")
        self.assertEqual([item.url for item in matches], ["https://investor.tsmc.com/reports/2025%20Q4.pdf"])

    def test_acquisition_records_hash_text_and_provenance(self) -> None:
        page_url = "https://investor.tsmc.com/english/quarterly-results/2025/q4"
        pdf_url = "https://investor.tsmc.com/reports/test.pdf"
        pdf = _sample_pdf()

        def fetch(url: str) -> tuple[str, str, bytes]:
            if url == page_url:
                return url, "text/html", b'<a href="/reports/test.pdf">Earnings Transcript</a>'
            if url == pdf_url:
                return url, "application/pdf", pdf
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as directory:
            result = acquire_page(ticker="2330", company_name="TSMC", page_url=page_url,
                                  output_dir=Path(directory), as_of="2026-01-16", fetch=fetch)
            document = result["documents"][0]
            self.assertEqual(document["status"], "text_extracted")
            self.assertTrue(Path(document["pdf_path"]).read_bytes().startswith(b"%PDF-"))
            self.assertIn("Quarterly earnings conference", Path(document["text_path"]).read_text())
            self.assertEqual(len(document["sha256"]), 64)
            self.assertFalse(result["as_of_verified"])
            self.assertTrue(Path(result["manifest_path"]).exists())

    def test_redirect_outside_official_hosts_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(AcquisitionError):
                acquire_page(ticker="2330", company_name="TSMC",
                             page_url="https://investor.tsmc.com/english/quarterly-results/2025/q4",
                             output_dir=Path(directory),
                             fetch=lambda _: ("https://evil.example/page", "text/html", b""))

    def test_html_returned_from_pdf_link_is_not_mislabeled_as_pdf(self) -> None:
        page_url = "https://investor.tsmc.com/english/quarterly-results/2025/q4"
        with tempfile.TemporaryDirectory() as directory:
            result = acquire_page(ticker="2330", company_name="TSMC", page_url=page_url,
                                  output_dir=Path(directory), fetch=lambda url: (
                                      url, "text/html", b'<a href="/broken.pdf">Presentation</a>'
                                      if url == page_url else b"<html>Access denied</html>"))
            self.assertEqual(result["documents"][0]["status"], "acquisition_failed")
            self.assertIn("PDF magic missing", result["documents"][0]["error"])


if __name__ == "__main__":
    unittest.main()
