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


    def test_disconnected_visual_groups_do_not_collapse_into_page_bbox(self) -> None:
        def draw(page, fitz):
            page.draw_rect(page.rect, color=None, fill=(0.97, 0.97, 0.97))
            page.insert_text((72, 48), "Revenue by Platform")
            for x0, top, value, period in ((60, 220, "100", "2024"), (120, 190, "120", "2025"), (180, 160, "145", "2026E")):
                page.draw_rect(fitz.Rect(x0, top, x0 + 36, 300), fill=(0.2, 0.4, 0.8))
                page.insert_text((x0 + 4, top - 8), value)
                page.insert_text((x0 + 2, 318), period)
            page.draw_rect(fitz.Rect(400, 160, 600, 320))
            page.draw_line((420, 180), (580, 300))
            page.draw_line((420, 300), (580, 180))

        evidence = flatten(extract_semantic_evidence(pdf_bytes(draw), filename="groups.pdf"))
        regions = [item for item in evidence if item["evidence_type"] not in {"text", "decorative"}]
        page_area = 640 * 480

        self.assertGreaterEqual(len(regions), 2)
        for item in regions:
            box = item["region"]
            self.assertLess((box["x1"] - box["x0"]) * (box["y1"] - box["y0"]) / page_area, 0.8)
        chart = next(item for item in regions if item["evidence_type"] == "chart")
        self.assertLess(chart["region"]["x1"], 400)
        self.assertEqual(chart["mapping_status"], "aligned")
        self.assertEqual(chart["trend"], "increasing")

    def test_repeated_logo_footer_and_separator_are_decorative_and_not_eligible(self) -> None:
        fitz = load_pymupdf()
        document = fitz.open()
        for number in range(3):
            page = document.new_page(width=640, height=480)
            page.insert_text((72, 72), f"Section {number + 1} overview")
            page.draw_rect(fitz.Rect(580, 12, 620, 40), fill=(0.8, 0.1, 0.1))
            page.draw_line((20, 455), (620, 455))
            page.draw_line((60, 240), (580, 240))
            page.insert_text((600, 470), str(number + 1))

        evidence = flatten(extract_semantic_evidence(document.tobytes(), filename="deco.pdf"))
        visual = [item for item in evidence if item["evidence_type"] != "text"]

        self.assertTrue(visual)
        self.assertTrue(all(item["evidence_type"] == "decorative" for item in visual))
        self.assertFalse(any(item["gemini_eligible"] for item in visual))
        reasons = {item["decorative_reason"] for item in visual}
        self.assertIn("repeated_layout_element", reasons)

    def test_period_header_table_maps_rows_to_columns(self) -> None:
        def draw(page, fitz):
            page.insert_text((72, 60), "Financial Highlights")
            page.insert_text((72, 100), "              2024    2025    2026E", fontname="cour", fontsize=10)
            page.insert_text((72, 120), "Revenue       100     120     145", fontname="cour", fontsize=10)
            page.insert_text((72, 140), "Gross Margin  55%     57%     59%", fontname="cour", fontsize=10)

        evidence = flatten(extract_semantic_evidence(pdf_bytes(draw), filename="grid.pdf"))
        table = next(item for item in evidence if item["evidence_type"] == "table")

        self.assertEqual(table["columns"], ["2024", "2025", "2026E"])
        self.assertEqual(table["mapping_status"], "aligned")
        self.assertEqual(table["values"][0]["row_label"], "Revenue")
        self.assertEqual(
            table["values"][0]["cells"],
            [{"column": "2024", "value_text": "100"}, {"column": "2025", "value_text": "120"},
             {"column": "2026E", "value_text": "145"}],
        )
        self.assertEqual(table["values"][1]["cells"][2], {"column": "2026E", "value_text": "59%"})
        self.assertEqual(table["verification_status"], "partially_verified")
        self.assertFalse(table["gemini_eligible"])


if __name__ == "__main__":
    unittest.main()
