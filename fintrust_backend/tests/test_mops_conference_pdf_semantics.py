from __future__ import annotations

import unittest

from app.services.mops_conference_pdf_semantics import extract_semantic_evidence, load_pymupdf


def pdf_bytes(draw) -> bytes:
    fitz = load_pymupdf()
    document = fitz.open()
    page = document.new_page(width=640, height=480)
    draw(page, fitz)
    return document.tobytes()


def flatten(pages):
    return [item for page in pages for item in page]


class MopsConferencePdfSemanticTests(unittest.TestCase):
    def test_text_only_page_has_no_visual_semantic_region(self) -> None:
        raw = pdf_bytes(lambda page, fitz: page.insert_text((72, 72), "Business outlook remains constructive."))

        evidence = flatten(extract_semantic_evidence(raw, filename="text.pdf"))

        self.assertTrue(any(item["evidence_type"] == "text" for item in evidence))
        self.assertFalse(any(item["evidence_type"] in {"chart", "image", "decorative", "unknown"} for item in evidence))

    def test_simple_table_keeps_row_labels_and_values(self) -> None:
        def draw(page, fitz):
            page.insert_text((72, 72), "Operating Metrics")
            page.insert_text((72, 112), "Revenue      100      120")
            page.insert_text((72, 136), "Gross Margin 55%      57%")

        evidence = flatten(extract_semantic_evidence(pdf_bytes(draw), filename="table.pdf"))
        table = next(item for item in evidence if item["evidence_type"] == "table")

        self.assertEqual(table["verification_status"], "partially_verified")
        self.assertIn("Revenue", table["labels"])
        self.assertEqual(table["values"][0]["row_label"], "Revenue")
        self.assertEqual(table["values"][0]["values"], ["100", "120"])

    def test_simple_chart_extracts_candidates_and_infers_trend(self) -> None:
        def draw(page, fitz):
            page.insert_text((72, 64), "Quarterly Revenue")
            page.insert_text((100, 118), "2024 100")
            page.insert_text((210, 98), "2025 120")
            page.insert_text((320, 78), "2026E 145")
            page.draw_rect(fitz.Rect(98, 160, 140, 280))
            page.draw_rect(fitz.Rect(208, 130, 250, 280))
            page.draw_rect(fitz.Rect(318, 96, 360, 280))

        evidence = flatten(extract_semantic_evidence(pdf_bytes(draw), filename="chart.pdf"))
        chart = next(item for item in evidence if item["evidence_type"] == "chart")

        self.assertEqual(chart["trend"], "increasing")
        self.assertTrue(any(value["value_text"] == "145" for value in chart["values"]))
        self.assertIn(chart["verification_status"], {"partially_verified", "needs_review"})
        self.assertGreater(chart["confidence"], 0.5)

    def test_small_logo_like_shape_is_decorative_not_chart(self) -> None:
        def draw(page, fitz):
            page.insert_text((72, 72), "Company overview")
            page.draw_rect(fitz.Rect(540, 32, 590, 62))

        evidence = flatten(extract_semantic_evidence(pdf_bytes(draw), filename="decorative.pdf"))

        self.assertTrue(any(item["evidence_type"] == "decorative" for item in evidence))
        self.assertFalse(any(item["evidence_type"] == "chart" for item in evidence))

    def test_large_unlabeled_visual_region_stays_unknown_and_needs_review(self) -> None:
        def draw(page, fitz):
            page.insert_text((72, 72), "Architecture")
            page.draw_rect(fitz.Rect(120, 120, 520, 360))
            page.draw_line((140, 150), (500, 330))
            page.draw_line((140, 330), (500, 150))

        evidence = flatten(extract_semantic_evidence(pdf_bytes(draw), filename="unknown.pdf"))
        unknown = next(item for item in evidence if item["evidence_type"] == "unknown")

        self.assertEqual(unknown["verification_status"], "needs_review")
        self.assertEqual(unknown["values"], [])


if __name__ == "__main__":
    unittest.main()
