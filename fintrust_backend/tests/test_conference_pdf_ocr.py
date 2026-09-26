from __future__ import annotations

import unittest

from app.services.conference_pdf_multimodal import GeminiRegionInterpreter, semantic_gating_metrics
from app.services.conference_pdf_ocr import (
    OCRResult,
    OcrUnavailableError,
    RegionOcrRunner,
    normalize_ocr_text,
    parse_min_confidence,
)
from app.services.mops_conference_pdf_pipeline import extract_pages
from app.services.mops_conference_pdf_semantics import extract_semantic_evidence, load_pymupdf
from tests.test_conference_pdf_multimodal import FakeProvider, chart_pdf, chart_response

OCR_FIELDS = {"ocr", "ocr_status"}


def raster_pdf() -> bytes:
    """A slide whose chart exists only as an embedded picture (no selectable values)."""
    fitz = load_pymupdf()
    picture = fitz.open()
    canvas = picture.new_page(width=300, height=200)
    canvas.draw_rect(fitz.Rect(40, 60, 260, 180), fill=(0.2, 0.6, 0.3))
    canvas.insert_text((60, 40), "3nm")
    canvas.insert_text((60, 55), "23%")
    png = canvas.get_pixmap(dpi=72).tobytes("png")
    document = fitz.open()
    page = document.new_page(width=640, height=480)
    page.insert_text((72, 50), "Revenue by Technology")
    page.insert_image(fitz.Rect(120, 120, 420, 320), stream=png)
    return document.tobytes()


class FakeOcrEngine:
    engine_name = "fake-ocr"
    extraction_method = "fake_ocr"

    def __init__(self, results: list[tuple[str, float]] | None = None, exc: Exception | None = None) -> None:
        self.results = results or []
        self.exc = exc
        self.calls = 0

    def engine_version(self) -> str:
        return "fake 1.0"

    def recognize(self, image_bytes: bytes) -> list[OCRResult]:
        self.calls += 1
        if self.exc is not None:
            raise self.exc
        # Stack tokens vertically in one column, as labels above values on a pie slice.
        return [
            OCRResult(text, (100.0, 60.0 + 40 * index, 160.0, 90.0 + 40 * index), confidence)
            for index, (text, confidence) in enumerate(self.results)
        ]


def pie_response(value: str) -> dict:
    response = chart_response([("3nm", value)], trend="unknown")
    response.update(chart_type="pie", title=None, unit=None)
    return response


def run(raw: bytes, *, engine: FakeOcrEngine | None, provider: FakeProvider | None, **ocr_options):
    runner = RegionOcrRunner(engine, **ocr_options) if engine else None
    interpreter = GeminiRegionInterpreter(provider) if provider else None
    try:
        pages = extract_semantic_evidence(raw, filename="deck.pdf", interpreter=interpreter, region_ocr=runner)
    finally:
        if interpreter:
            interpreter.close()
        if runner:
            runner.close()
    return [item for page in pages for item in page]


def raster_record(evidence: list[dict]) -> dict:
    return next(item for item in evidence if item["region"]["x0"] == 120.0)


class ConferencePdfOcrTests(unittest.TestCase):
    def test_gating_ocr_only_raster_regions(self) -> None:
        text_engine = FakeOcrEngine([("anything", 0.99)])
        run(chart_pdf(), engine=text_engine, provider=None)
        self.assertEqual(text_engine.calls, 0)

        raster_engine = FakeOcrEngine([("3nm", 0.99)])
        evidence = run(raster_pdf(), engine=raster_engine, provider=None)
        self.assertEqual(raster_engine.calls, 1)
        record = raster_record(evidence)
        self.assertTrue(record["ocr_eligible"])
        self.assertEqual(record["ocr_status"], "completed")
        self.assertFalse(any(item["ocr_eligible"] for item in evidence if item is not record))

    def test_ocr_supports_gemini_value_absent_from_pdf_text(self) -> None:
        provider = FakeProvider(pie_response("23%"))
        record = raster_record(run(raster_pdf(), engine=FakeOcrEngine([("3nm", 0.99), ("23%", 0.97)]),
                                   provider=provider))

        value = record["values"][0]
        self.assertTrue(value["value_supported"])
        self.assertEqual(value["supported_by"], ["ocr"])
        self.assertEqual(value["ocr_confidence"], 0.97)
        self.assertTrue(value["mapping_supported"])
        self.assertEqual(record["verification_status"], "partially_verified")
        ocr = record["ocr"]
        self.assertEqual((ocr["engine"], ocr["engine_version"], ocr["extraction_method"]),
                         ("fake-ocr", "fake 1.0", "fake_ocr"))
        self.assertEqual(ocr["source_region"], record["region"])
        candidate = ocr["candidates"][1]
        self.assertEqual((candidate["raw_text"], candidate["confidence"], candidate["accepted"]), ("23%", 0.97, True))
        self.assertIsNotNone(candidate["bbox"])
        self.assertIsNotNone(candidate["pixel_bbox"])
        # OCR tokens reach the Gemini request as candidates.
        self.assertIn('"23%"', provider.requests[0][0]["parts"][1]["text"])

    def test_ocr_gemini_disagreement_fails_closed(self) -> None:
        record = raster_record(run(raster_pdf(), engine=FakeOcrEngine([("3nm", 0.99), ("28%", 0.97)]),
                                   provider=FakeProvider(pie_response("23%"))))

        self.assertEqual(record["verification_status"], "needs_review")
        self.assertIn("ocr_disagrees_with_provider", record["validation"]["review_reasons"])
        self.assertEqual(record["values"][0]["value_text"], "23%")
        self.assertEqual(record["values"][0]["ocr_disagreement"], ["28%"])
        self.assertIn("28%", [item["raw_text"] for item in record["ocr"]["candidates"]])

    def test_low_confidence_ocr_does_not_support(self) -> None:
        record = raster_record(run(raster_pdf(), engine=FakeOcrEngine([("3nm", 0.99), ("23%", 0.5)]),
                                   provider=FakeProvider(pie_response("23%")), min_confidence=0.85))

        value = record["values"][0]
        self.assertFalse(value["value_supported"])
        self.assertEqual(value["ocr_low_confidence_match"], 0.5)
        self.assertEqual(record["verification_status"], "needs_review")
        self.assertFalse(record["ocr"]["candidates"][1]["accepted"])

    def test_ocr_unavailable_or_failing_preserves_other_evidence(self) -> None:
        baseline = raster_record(run(raster_pdf(), engine=None, provider=FakeProvider(pie_response("23%"))))
        for exc, expected in ((OcrUnavailableError("no models"), "unavailable"), (RuntimeError("boom"), "failed")):
            with self.subTest(expected=expected):
                record = raster_record(run(raster_pdf(), engine=FakeOcrEngine(exc=exc),
                                           provider=FakeProvider(pie_response("23%"))))
                self.assertEqual(record["ocr_status"], expected)
                self.assertEqual(record["semantic_provider_status"], "completed")
                for key, value in baseline.items():
                    if key not in OCR_FIELDS:
                        self.assertEqual(record.get(key), value, key)

        runner = RegionOcrRunner(FakeOcrEngine(exc=OcrUnavailableError("missing")))
        try:
            pages, problems = extract_pages(raster_pdf(), filename="deck.pdf", region_ocr=runner)
        finally:
            runner.close()
        records = [item for page in pages for item in page["semantic_evidence"]]
        self.assertEqual(semantic_gating_metrics(records)["ocr_unavailable"], 1)
        self.assertIn("page_1:visual_review_required", problems)

    def test_pdf_native_values_need_no_ocr_and_stay_unchanged(self) -> None:
        response = chart_response([("1Q25", "100"), ("2Q25", "120"), ("3Q25", "145")])
        without = run(chart_pdf(), engine=None, provider=FakeProvider(response))
        engine = FakeOcrEngine([("999", 0.99)])
        with_ocr = run(chart_pdf(), engine=engine, provider=FakeProvider(response))

        self.assertEqual(engine.calls, 0)
        self.assertEqual(len(without), len(with_ocr))
        for before, after in zip(without, with_ocr):
            self.assertEqual({k: v for k, v in before.items() if k not in OCR_FIELDS},
                             {k: v for k, v in after.items() if k not in OCR_FIELDS})
        chart = next(item for item in with_ocr if item.get("semantic_provider_status") == "completed")
        self.assertEqual(chart["values"][0]["supported_by"], ["pdf_text"])

    def test_multi_word_ocr_label_confirms_mapping(self) -> None:
        response = chart_response([("0.25um and above", "0%")], trend="unknown")
        response.update(chart_type="pie", title=None, unit=None, labels=[])
        record = raster_record(run(raster_pdf(), engine=FakeOcrEngine([("0.25um and above", 0.99), ("0%", 0.99)]),
                                   provider=FakeProvider(response)))

        self.assertTrue(record["values"][0]["mapping_supported"])
        self.assertEqual(record["verification_status"], "partially_verified")

    def test_gemini_plus_ocr_never_becomes_verified(self) -> None:
        evidence = run(raster_pdf(), engine=FakeOcrEngine([("3nm", 1.0), ("23%", 1.0)]),
                       provider=FakeProvider(pie_response("23%")))

        derived = [item for item in evidence if item["semantic_provider"] == "gemini" or item["ocr_status"] != "not_requested"]
        self.assertTrue(derived)
        self.assertFalse(any(item["verification_status"] == "verified" for item in derived))

    def test_normalization_is_conservative(self) -> None:
        self.assertEqual(normalize_ocr_text("２３％"), "23%")
        self.assertEqual(normalize_ocr_text("−5.0%"), "-5.0%")
        self.assertEqual(normalize_ocr_text("  1O  nm "), "1O nm")
        self.assertEqual(parse_min_confidence("85"), 0.85)
        self.assertEqual(parse_min_confidence("0.9"), 0.9)


if __name__ == "__main__":
    unittest.main()
