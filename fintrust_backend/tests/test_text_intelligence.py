from __future__ import annotations

import unittest

from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord
from app.services.text_intelligence import (
    FinancialTextIntelligenceService,
    KeywordBaselineRelevanceModel,
    calculate_text_cosine,
    calculate_word_jsd,
    documents_from_official_events,
    export_annotation_candidates_csv,
    sentence_segment,
    tokenize,
)
from app.text_intelligence_models import OfficialTextDocumentInput


class TextIntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FinancialTextIntelligenceService()

    def test_sentence_segmentation_handles_chinese_english_mixed_numbers(self) -> None:
        text = "公司預期下半年營收成長 12.5%。Inventory correction is ending; capex remains disciplined.\n謝謝。"
        sentences = sentence_segment(text)

        self.assertGreaterEqual(len(sentences), 3)
        self.assertIn("12.5%", tokenize(text))
        self.assertTrue(any("Inventory correction" in sentence for sentence in sentences))

    def test_semantically_relevant_sentence_without_exact_seed_keyword(self) -> None:
        document = OfficialTextDocumentInput(
            ticker="2454",
            company_name="聯發科",
            source_type="investor_conference",
            source_name="synthetic",
            source_url="https://example.test/ir",
            period="2026Q2",
            text="下半年終端客戶調整已逐步接近尾聲，產品動能預期回升。",
        )

        response = self.service.analyze_documents([document])
        sentence = response.documents[0].sentences[0]

        self.assertTrue(sentence.relevant)
        self.assertGreaterEqual(sentence.relevance_score, 0.28)
        self.assertIn("outlook", sentence.topics)

    def test_keyword_false_positive_is_not_high_value_governance(self) -> None:
        document = OfficialTextDocumentInput(
            ticker="2454",
            company_name="聯發科",
            source_type="material_event",
            source_name="synthetic",
            source_url="https://example.test/event",
            text="董事會今日召開例行會議。",
        )

        response = self.service.analyze_documents([document], include_irrelevant_sentences=True)
        sentence = response.documents[0].sentences[0]

        self.assertFalse(sentence.relevant)
        self.assertLess(sentence.relevance_score, 0.28)

    def test_multi_topic_sentence_keeps_multiple_labels(self) -> None:
        document = OfficialTextDocumentInput(
            ticker="2454",
            company_name="聯發科",
            source_type="investor_conference",
            source_name="synthetic",
            source_url="https://example.test/ir",
            text="客戶庫存逐步恢復正常，因此公司預期下半年營收成長。",
        )

        response = self.service.analyze_documents([document])
        topics = set(response.documents[0].sentences[0].topics)

        self.assertIn("demand_inventory", topics)
        self.assertIn("revenue_orders", topics)
        self.assertIn("outlook", topics)

    def test_open_vocabulary_terms_and_data_shift_v2_metrics(self) -> None:
        first = OfficialTextDocumentInput(
            ticker="2330",
            company_name="台積電",
            source_type="investor_conference",
            source_name="synthetic",
            source_url="https://example.test/1",
            period="2026Q1",
            text="公司說明先進封裝需求穩定，資本支出維持紀律。",
        )
        second = OfficialTextDocumentInput(
            ticker="2330",
            company_name="台積電",
            source_type="investor_conference",
            source_name="synthetic",
            source_url="https://example.test/2",
            period="2026Q2",
            text="公司說明矽光子平台開始導入，CoWoS 產能與 AI 加速器需求提升。",
        )

        shift = self.service.narrative_shift(first, second)

        self.assertIn("raw_text_word_jsd", shift.metrics)
        self.assertIn("topic_distribution_jsd", shift.metrics)
        self.assertIn("semantic_tfidf_cosine_similarity", shift.metrics)
        self.assertTrue(any("cowos" in item.term.casefold() or "矽光子" in item.term for item in shift.emerging_terms))
        self.assertIsNone(shift.method["combined_weighted_score"])

    def test_provenance_ids_are_stable(self) -> None:
        document = OfficialTextDocumentInput(
            ticker="2303",
            company_name="聯電",
            source_type="material_event",
            source_name="synthetic",
            source_url="https://example.test/event",
            document_url="https://example.test/event/doc",
            period="2026-09-01",
            text="公告本公司取得新設備以支援特殊製程產能。",
        )

        first = self.service.analyze_documents([document]).documents[0].sentences[0]
        second = self.service.analyze_documents([document]).documents[0].sentences[0]

        self.assertEqual(first.evidence_id, second.evidence_id)
        self.assertEqual(first.document_hash, second.document_hash)
        self.assertEqual(first.text_hash, second.text_hash)

    def test_documents_from_official_events_and_annotation_csv(self) -> None:
        conference = InvestorConferenceRecord(
            event_id="conf-1",
            ticker="2454",
            company_name="聯發科",
            subindustry="IC 設計",
            conference_date="2026-07-31",
            title="MediaTek investor conference",
            source_name="company_official_ir",
            source_url="https://example.test/ir",
            document_url="https://example.test/transcript.pdf",
            document_extract_status="text_extracted",
            document_text_preview="Management expects product momentum and revenue growth to improve.",
        )
        material = MaterialEventRecord(
            event_id="event-1",
            ticker="2454",
            company_name="聯發科",
            subindustry="IC 設計",
            event_date="2026-09-01",
            title="公告本公司董事會決議投資案",
            source_name="twse_openapi",
            source_url="https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
            status="available",
            raw_text="本公司董事會決議策略投資以擴大產品布局。",
        )

        documents = documents_from_official_events(ticker="2454", conferences=[conference], material_events=[material])
        analysis = self.service.analyze_documents(documents, include_irrelevant_sentences=True)
        csv_text = export_annotation_candidates_csv([sentence for doc in analysis.documents for sentence in doc.sentences])

        self.assertEqual(len(documents), 2)
        self.assertIn("sample_id,ticker,company_name", csv_text)
        self.assertIn("2454", csv_text)

    def test_existing_baseline_metric_helpers_remain_available(self) -> None:
        self.assertGreaterEqual(calculate_word_jsd("revenue demand", "capacity capex"), 0.0)
        self.assertGreaterEqual(calculate_text_cosine("revenue demand", "revenue growth"), 0.0)

    def test_keyword_baseline_is_available_but_not_the_only_model(self) -> None:
        baseline = KeywordBaselineRelevanceModel()
        score, explanation = baseline.predict_score("公司預期營收成長。")

        self.assertGreater(score, 0)
        self.assertIn("matched seed terms", explanation)
        self.assertEqual(self.service.relevance_model.model_name, "prototype_semantic_ngram")


if __name__ == "__main__":
    unittest.main()

