from __future__ import annotations

import asyncio
import json
import unittest

from app.services.conference_pdf_multimodal import (
    GeminiRegionInterpreter,
    semantic_gating_metrics,
)
from app.services.mops_conference_pdf_pipeline import extract_pages
from app.services.mops_conference_pdf_semantics import extract_semantic_evidence, load_pymupdf

PROVIDER_FIELDS = {
    "semantic_provider", "semantic_provider_status", "semantic_provider_error", "verification_status",
}


def chart_pdf() -> bytes:
    """Bar chart whose extra growth annotation stops deterministic pairing."""
    fitz = load_pymupdf()
    document = fitz.open()
    page = document.new_page(width=640, height=480)
    page.insert_text((72, 50), "Quarterly Revenue (NT$ bn)")
    for x0, top, value, period in ((120, 220, "100", "1Q25"), (220, 200, "120", "2Q25"), (320, 170, "145", "3Q25")):
        page.draw_rect(fitz.Rect(x0, top, x0 + 40, 300), fill=(0.2, 0.4, 0.8))
        page.insert_text((x0 + 8, top - 8), value)
        page.insert_text((x0 + 4, 318), period)
    page.insert_text((350, 150), "+45%")
    return document.tobytes()


def chart_response(values: list[tuple[str, str]], trend: str = "increasing") -> dict:
    return {
        "region_type": "chart",
        "chart_type": "bar",
        "title": "Quarterly Revenue (NT$ bn)",
        "labels": [label for label, _ in values],
        "values": [{"label": label, "value_text": value, "series": None} for label, value in values],
        "unit": "NT$ bn",
        "series": [],
        "trend": trend,
        "is_forecast": False,
        "confidence": 0.9,
        "requires_review": False,
    }


class FakeProvider:
    timeout_seconds = 5.0

    def __init__(self, payload: dict | None = None, exc: Exception | None = None, configured: bool = True) -> None:
        self.payload = payload
        self.exc = exc
        self.configured = configured
        self.requests: list = []

    async def generate_structured(self, contents, *, system_instruction, schema, max_output_tokens):
        self.requests.append(contents)
        if self.exc is not None:
            raise self.exc
        return self.payload, "fake-gemini"


def flatten(pages):
    return [item for page in pages for item in page]


def chart_record(provider: FakeProvider | None) -> dict:
    interpreter = GeminiRegionInterpreter(provider) if provider else None
    try:
        evidence = flatten(extract_semantic_evidence(chart_pdf(), filename="chart.pdf", interpreter=interpreter))
    finally:
        if interpreter:
            interpreter.close()
    return next(item for item in evidence if item["region"]["x0"] == 120.0 and item["evidence_type"] != "text")


class ConferencePdfMultimodalTests(unittest.TestCase):
    def test_deterministic_chart_is_eligible_when_pairing_is_uncertain(self) -> None:
        record = chart_record(None)

        self.assertEqual(record["evidence_type"], "chart")
        self.assertEqual(record["mapping_status"], "candidates_only")
        self.assertTrue(record["gemini_eligible"])
        self.assertEqual(record["verification_status"], "needs_review")
        self.assertEqual(record["semantic_provider_status"], "not_requested")

    def test_structured_chart_response_is_parsed_and_source_validated(self) -> None:
        provider = FakeProvider(chart_response([("1Q25", "100"), ("2Q25", "120"), ("3Q25", "145")]))

        record = chart_record(provider)

        self.assertEqual(len(provider.requests), 1)
        parts = provider.requests[0][0]["parts"]
        self.assertTrue(parts[0]["inline_data"]["data"].startswith(b"\x89PNG"))
        request = json.loads(parts[1]["text"])
        self.assertIn("145", request["deterministic_evidence"]["numeric_candidates"])
        self.assertEqual(record["semantic_provider_status"], "completed")
        self.assertEqual(record["chart_type"], "bar")
        self.assertEqual(record["unit"], "NT$ bn")
        self.assertEqual([v["label"] for v in record["values"]], ["1Q25", "2Q25", "3Q25"])
        self.assertTrue(record["validation"]["mapping_established"])
        self.assertTrue(record["trend_supported"])
        self.assertEqual(record["trend"], "increasing")
        self.assertEqual(record["verification_status"], "partially_verified")
        self.assertIn("gemini_multimodal", record["extraction_method"])

    def test_hallucinated_numeric_value_stays_needs_review(self) -> None:
        provider = FakeProvider(chart_response([("1Q25", "100"), ("2Q25", "120"), ("3Q25", "999")]))

        record = chart_record(provider)

        self.assertEqual(record["verification_status"], "needs_review")
        self.assertIn("unsupported_numeric_value", record["validation"]["review_reasons"])
        unsupported = [v for v in record["values"] if not v["value_supported"]]
        self.assertEqual([v["value_text"] for v in unsupported], ["999"])
        self.assertFalse(record["trend_supported"])

    def test_unmapped_trend_claim_is_not_upgraded(self) -> None:
        response = chart_response([], trend="increasing")
        response["values"] = [{"label": None, "value_text": "100", "series": None}]

        record = chart_record(FakeProvider(response))

        self.assertEqual(record["trend"], "increasing")
        self.assertFalse(record["trend_supported"])
        self.assertEqual(record["verification_status"], "needs_review")

    def test_provider_failures_preserve_deterministic_evidence(self) -> None:
        baseline = chart_record(None)
        invalid_schema = chart_response([("1Q25", "100")])
        invalid_schema["region_type"] = "pie"
        cases = {
            "unavailable": FakeProvider(configured=False),
            "timeout": FakeProvider(exc=asyncio.TimeoutError()),
            "quota": FakeProvider(exc=RuntimeError("429 RESOURCE_EXHAUSTED")),
            "invalid_json": FakeProvider(exc=json.JSONDecodeError("bad", "{", 0)),
            "schema": FakeProvider(invalid_schema),
        }
        for name, provider in cases.items():
            with self.subTest(name=name):
                record = chart_record(provider)
                expected = "unavailable" if name == "unavailable" else "failed"
                self.assertEqual(record["semantic_provider_status"], expected)
                self.assertEqual(record["verification_status"], "needs_review")
                self.assertNotIn("provider_interpretation", record)
                for key, value in baseline.items():
                    if key not in PROVIDER_FIELDS:
                        self.assertEqual(record.get(key), value, key)
        self.assertEqual(cases["unavailable"].requests, [])

    def test_extract_pages_survives_provider_errors_and_reports_metrics(self) -> None:
        interpreter = GeminiRegionInterpreter(FakeProvider(exc=ConnectionError("network down")))
        try:
            pages, problems = extract_pages(chart_pdf(), filename="chart.pdf", interpreter=interpreter)
        finally:
            interpreter.close()

        records = [item for page in pages for item in page["semantic_evidence"]]
        metrics = semantic_gating_metrics(records)
        self.assertEqual(metrics["gemini_calls"], metrics["gemini_eligible"])
        self.assertEqual(metrics["gemini_failures"], metrics["gemini_calls"])
        self.assertEqual(metrics["gemini_successes"], 0)
        self.assertIn("page_1:visual_review_required", problems)

    def test_call_budget_limits_gemini_calls(self) -> None:
        provider = FakeProvider(chart_response([("1Q25", "100")]))
        interpreter = GeminiRegionInterpreter(provider, max_calls=0)
        try:
            evidence = flatten(extract_semantic_evidence(chart_pdf(), filename="chart.pdf", interpreter=interpreter))
        finally:
            interpreter.close()

        self.assertEqual(provider.requests, [])
        self.assertTrue(any(item["semantic_provider_status"] == "skipped" for item in evidence))
        self.assertGreaterEqual(semantic_gating_metrics(evidence)["gemini_budget_skipped"], 1)


if __name__ == "__main__":
    unittest.main()
