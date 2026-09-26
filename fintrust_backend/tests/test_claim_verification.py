from __future__ import annotations

import copy
import json
import unittest

from app.claim_verification_models import ClaimVerifyRequest
from app.models import FinancialFact
from app.services.claim_evidence_adapter import ClaimEvidenceAdapter, classify_column
from app.services.claim_llm import ClaimLLM
from app.services.claim_verification_service import ClaimVerificationService
from app.services.periods import normalize_period

SHA = "a" * 64


def income_table(status: str = "partially_verified", mapping: str = "aligned") -> dict:
    return {
        "filename": "233020251016E001.pdf", "page": 4, "evidence_type": "table",
        "region_id": "233020251016E001.pdf#p4r2", "title": "Selected Items",
        "columns": ["3Q25", "3Q25 Guidance", "2Q25", "3Q24", "3Q25 Over 2Q25", "3Q25 Over 3Q24"],
        "values": [
            {"row_label": "Gross Margin", "values": ["59.5%", "55.5%-57.5%", "58.6%", "57.8%", "+0.9 ppts", "+1.7 ppts"],
             "cells": [{"column": "3Q25", "value_text": "59.5%"},
                       {"column": "3Q25 Guidance", "value_text": "55.5%-57.5%"},
                       {"column": "2Q25", "value_text": "58.6%"},
                       {"column": "3Q24", "value_text": "57.8%"},
                       {"column": "3Q25 Over 2Q25", "value_text": "+0.9 ppts"},
                       {"column": "3Q25 Over 3Q24", "value_text": "+1.7 ppts"}]},
            {"row_label": "Net Revenue", "values": ["989.92", "933.79"],
             "cells": [{"column": "3Q25", "value_text": "989.92"}, {"column": "2Q25", "value_text": "933.79"}]},
        ],
        "extraction_method": "pdf_text_layout", "mapping_status": mapping,
        "verification_status": status, "semantic_provider": "deterministic",
    }


class FakeConferenceRepository:
    def __init__(self, records: list[dict]) -> None:
        self.records = records

    def available_years(self, ticker: str) -> list[int]:
        return [2025] if ticker == "2330" else []

    def latest_manifest(self, ticker: str, year: int) -> dict:
        return {"listing_url": "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1?co_id=2330",
                "documents": [{"filename": "233020251016E001.pdf", "sha256": SHA, "language": "en",
                               "conference_dates": ["114/10/16"],
                               "semantic_path": "C:/local/archive/should-not-leak.semantic.json"}]}

    def semantic(self, ticker: str, year: int, filename: str) -> list[dict]:
        return self.records


class FakeFacts:
    def __init__(self, facts: dict[tuple[str, str], FinancialFact] | None = None) -> None:
        self.facts = facts or {}

    def get_fact(self, ticker: str, metric: str, period: str):
        return self.facts.get((metric, period))


def fact(metric: str, period: str, value: float, unit: str = "%", *, demo: bool = False) -> FinancialFact:
    return FinancialFact(
        ticker="2330", company_name="台積電", semiconductor_subindustry="晶圓代工", metric=metric, period=period,
        value=value, unit=unit, statement_type="income_statement",
        source_kind="mvp_fixture" if demo else "mops_xbrl", source_url="https://mops.twse.com.tw/example",
        is_demo=demo,
    )


class FakeProvider:
    timeout_seconds = 5.0

    def __init__(self, payload=None, exc: Exception | None = None, configured: bool = True) -> None:
        self.payload, self.exc, self.configured, self.calls = payload, exc, configured, 0

    async def generate_structured(self, contents, *, system_instruction, schema, max_output_tokens):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.payload, "fake"


def service(records=None, facts=None, llm=None) -> ClaimVerificationService:
    adapter = ClaimEvidenceAdapter(
        fact_repository=FakeFacts(facts),
        conference_repository=FakeConferenceRepository(records if records is not None else [income_table()]),
    )
    return ClaimVerificationService(adapter, llm=llm)


def verify(claim: str, **kwargs):
    svc = kwargs.pop("svc", None) or service(**kwargs)
    return svc.verify(ClaimVerifyRequest(company_code="2330", claim=claim))


class ClaimVerificationTests(unittest.TestCase):
    # A / B: financial facts
    def test_supported_numeric_financial_fact(self) -> None:
        result = verify("台積電 2023 年全年毛利率為 54.4%", records=[],
                        facts={("gross_margin", "2023FY"): fact("gross_margin", "2023FY", 54.3596)})
        self.assertEqual(result.verdict, "supported")
        item = result.evidence[0]
        self.assertEqual((item.source_type, item.verification_status, item.decisive), ("financial_metric", "verified", True))
        self.assertEqual(result.verification_detail.legacy_verdict, "supported")

    def test_conflicting_numeric_financial_fact(self) -> None:
        result = verify("台積電 2023 年全年毛利率為 60%", records=[],
                        facts={("gross_margin", "2023FY"): fact("gross_margin", "2023FY", 54.3596)})
        self.assertEqual(result.verdict, "conflicting")
        self.assertEqual(result.verification_detail.legacy_verdict, "contradicted")
        self.assertAlmostEqual(result.evidence[0].comparison.difference, 5.6404, places=3)

    # C / D / E
    def test_no_evidence_is_insufficient(self) -> None:
        result = verify("台積電 2025 年第三季 AI 加速器營收占比 30%", records=[])
        self.assertEqual((result.verdict, result.reason_code), ("insufficient_evidence", "no_official_evidence"))
        self.assertEqual(result.evidence, [])

    def test_needs_review_only_is_not_decisive(self) -> None:
        result = verify("台積電 2025 年第三季毛利率為 59.5%", records=[income_table(status="needs_review")])
        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertFalse(any(item.decisive for item in result.evidence))
        demo = verify("台積電 2023 年全年毛利率為 54.4%", records=[],
                      facts={("gross_margin", "2023FY"): fact("gross_margin", "2023FY", 54.3596, demo=True)})
        self.assertEqual((demo.verdict, demo.reason_code), ("insufficient_evidence", "only_needs_review_evidence"))

    def test_unconfirmed_table_mapping_is_not_decisive(self) -> None:
        result = verify("台積電 2025 年第三季毛利率為 59.5%", records=[income_table(mapping="partial")])
        self.assertEqual(result.verdict, "insufficient_evidence")

    def test_wrong_period_does_not_create_verdict(self) -> None:
        result = verify("台積電 2024 年第一季毛利率為 59.5%")
        self.assertEqual((result.verdict, result.reason_code), ("insufficient_evidence", "period_not_aligned"))
        self.assertFalse(any(item.decisive for item in result.evidence))

    # F / G: LLM
    def test_llm_unknown_evidence_id_fails_closed(self) -> None:
        text = {"filename": "233020251016E001.pdf", "page": 2, "evidence_type": "text",
                "region_id": "233020251016E001.pdf#p2r1", "title": "Recap",
                "source_text": "台積電董事會決議買回庫藏股", "verification_status": "verified",
                "extraction_method": "pdf_text_layout"}
        llm = ClaimLLM(FakeProvider({"relations": [
            {"evidence_id": "invented:1", "relation": "supports", "reason": "x"},
            {"evidence_id": "233020251016E001.pdf#p2r1:text", "relation": "supports", "reason": "y"}]}))
        result = verify("台積電董事會決議買回庫藏股", svc=service(records=[text], llm=llm))
        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertTrue(all(item.relation == "context" for item in result.evidence))
        self.assertEqual(result.verification_detail.llm_calls, 1)

    def test_llm_relation_needs_verified_text_and_sets_review(self) -> None:
        text = {"filename": "233020251016E001.pdf", "page": 2, "evidence_type": "text",
                "region_id": "233020251016E001.pdf#p2r1", "source_text": "台積電董事會決議買回庫藏股",
                "verification_status": "verified", "extraction_method": "pdf_text_layout"}
        llm = ClaimLLM(FakeProvider({"relations": [
            {"evidence_id": "233020251016E001.pdf#p2r1:text", "relation": "supports", "reason": "董事會決議"}]}))
        result = verify("台積電董事會決議買回庫藏股", svc=service(records=[text], llm=llm))
        self.assertEqual(result.verdict, "supported")
        self.assertTrue(result.requires_review)
        weak = dict(text, verification_status="needs_review")
        llm_weak = ClaimLLM(FakeProvider({"relations": [
            {"evidence_id": "233020251016E001.pdf#p2r1:text", "relation": "supports", "reason": "x"}]}))
        self.assertEqual(verify("台積電董事會決議買回庫藏股", svc=service(records=[weak], llm=llm_weak)).verdict,
                         "insufficient_evidence")

    def test_gemini_unavailable_keeps_deterministic_path(self) -> None:
        for provider in (FakeProvider(configured=False), FakeProvider(exc=TimeoutError()),
                         FakeProvider({"metric": "gross_margin", "unexpected": 1})):
            with self.subTest(provider=provider):
                result = verify("台積電 2025 年第三季毛利率為 59.5%", svc=service(llm=ClaimLLM(provider)))
                self.assertEqual(result.verdict, "supported")
                missing = verify("台積電最近毛利率很好", svc=service(llm=ClaimLLM(provider)))
                self.assertEqual(missing.verdict, "insufficient_evidence")

    def test_llm_extraction_rejects_numbers_not_in_claim(self) -> None:
        llm = ClaimLLM(FakeProvider({"metric": "gross_margin", "period_text": "2025 年第三季",
                                     "value_text": "59.5", "unit": "%", "direction": "unspecified"}))
        result = verify("台積電 2025 年第三季毛利表現很好", svc=service(llm=llm))
        self.assertIsNone(result.structured_claim.value)
        self.assertEqual(result.verdict, "insufficient_evidence")

    # H / P: provenance and list shape
    def test_provenance_survives_and_evidence_is_a_list(self) -> None:
        result = verify("台積電 2025 年第三季毛利率為 59.5%")
        payload = json.loads(result.model_dump_json())
        self.assertIsInstance(payload["evidence"], list)
        decisive = next(item for item in payload["evidence"] if item["decisive"])
        self.assertEqual((decisive["document"], decisive["page"], decisive["region_id"], decisive["document_sha256"]),
                         ("233020251016E001.pdf", 4, "233020251016E001.pdf#p4r2", SHA))
        self.assertEqual((decisive["period"], decisive["value"], decisive["source_date"]), ("2025Q3", "59.5%", "2025-10-16"))
        self.assertEqual(decisive["provenance"]["supported_by"], ["pdf_text"])
        self.assertNotIn("should-not-leak", json.dumps(payload))
        self.assertIsInstance(verify("台積電保證漲停").model_dump()["evidence"], list)

    # I
    def test_unsupported_claim_type(self) -> None:
        for claim in ("魏哲家推薦的 AI 投資網站保證獲利", "台積電股價下週保證漲停，快買進"):
            result = verify(claim)
            self.assertEqual((result.verdict, result.reason_code), ("insufficient_evidence", "unsupported_claim_type"))
            self.assertEqual(result.structured_claim.claim_type, "unsupported")

    # J
    def test_phase1_evidence_is_not_mutated(self) -> None:
        records = [income_table()]
        before = copy.deepcopy(records)
        verify("台積電 2025 年第三季毛利率為 59.5%", records=records)
        self.assertEqual(records, before)

    # K / L
    def test_english_alias_and_conference_period(self) -> None:
        result = verify("TSMC 3Q25 gross margin was 59.5%")
        self.assertEqual((result.structured_claim.metric_or_topic, result.structured_claim.period), ("gross_margin", "2025Q3"))
        self.assertEqual(result.verdict, "supported")
        for text in ("3Q25", "3Q2025", "2025Q3", "2025 年第三季", "2025年第3季", "Q3 2025"):
            self.assertEqual(normalize_period(text), "2025Q3", text)
        self.assertIsNone(normalize_period("今年"))

    # M / N
    def test_guidance_and_change_columns_are_not_actual_values(self) -> None:
        self.assertEqual(classify_column("3Q25 Guidance"), ("guidance", "2025Q3"))
        self.assertEqual(classify_column("3Q25 業績展望")[0], "guidance")
        self.assertEqual(classify_column("3Q25 Over 2Q25")[0], "change")
        self.assertEqual(classify_column("季變化")[0], "change")
        self.assertEqual(classify_column("1Q25 %"), ("share", "2025Q1"))
        self.assertEqual(classify_column("1Q25 Amount"), ("actual", "2025Q1"))
        # 57% sits inside the guidance range column, and +0.9 is the change column: neither may decide.
        guidance = verify("台積電 2025 年第三季毛利率為 57%")
        self.assertEqual(guidance.verdict, "conflicting")
        self.assertTrue(all(item.value == "59.5%" for item in guidance.evidence if item.decisive))
        change = verify("台積電 2025 年第三季毛利率為 0.9%")
        self.assertTrue(all(item.value == "59.5%" for item in change.evidence if item.decisive))

    def test_rounding_band_is_ambiguous_not_decisive(self) -> None:
        self.assertEqual(verify("台積電 2025 年第三季毛利率為 60%").verdict, "supported")  # 59.5 rounds to 60
        middle = verify("台積電 2025 年第三季毛利率為 60.5%")
        self.assertEqual((middle.verdict, middle.reason_code), ("insufficient_evidence", "value_within_ambiguity_band"))

    def test_trend_recomputed_from_same_table_row(self) -> None:
        up = verify("台積電 2025 年第三季毛利率較上季增加")
        self.assertEqual((up.verdict, up.reason_code), ("supported", "trend_confirmed"))
        down = verify("台積電 2025 年第三季毛利率較上季下降")
        self.assertEqual(down.verdict, "conflicting")

    def test_gemini_only_chart_value_is_not_decisive(self) -> None:
        chart = {"filename": "233020251016E001.pdf", "page": 5, "evidence_type": "chart",
                 "region_id": "233020251016E001.pdf#p5r3", "title": "3Q25 Revenue by Technology",
                 "values": [{"label": "3nm", "value_text": "23%", "supported_by": ["ocr"], "value_supported": True,
                             "mapping_supported": True}],
                 "validation": {"values": [{"mapping_supported_by": ["ocr"]}]},
                 "verification_status": "partially_verified", "semantic_provider": "gemini",
                 "mapping_status": "source_aligned", "extraction_method": "pdf_visual_structure+gemini_multimodal"}
        result = verify("3nm accounted for 23% of wafer revenue in 3Q25", records=[chart])
        self.assertEqual(result.verdict, "insufficient_evidence")
        self.assertFalse(result.evidence[0].decisive)
        confirmed = copy.deepcopy(chart)
        confirmed["values"][0]["supported_by"] = ["pdf_text", "ocr"]
        confirmed["validation"]["values"][0]["mapping_supported_by"] = ["pdf_text", "ocr"]
        self.assertEqual(verify("3nm accounted for 23% of wafer revenue in 3Q25", records=[confirmed]).verdict, "supported")

    # O
    def test_legacy_aliases_normalize(self) -> None:
        request = ClaimVerifyRequest(**{"ticker": "2330", "text": "台積電 2025 年第三季毛利率為 59.5%"})
        self.assertEqual((request.company_code, request.claim), ("2330", "台積電 2025 年第三季毛利率為 59.5%"))
        self.assertEqual(service().verify(request).verdict, "supported")


if __name__ == "__main__":
    unittest.main()
