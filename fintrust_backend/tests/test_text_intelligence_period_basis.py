"""Hardening round 3: Text Intelligence comparison periods say what they are.

A fiscal quarter and a document date keep their own values and are labelled with their
own basis; nothing converts a date into a quarter, and the metrics do not change.
"""
from __future__ import annotations

import unittest

from app.official_event_models import InvestorConferenceRecord, MaterialEventRecord
from app.services.text_intelligence import (
    FinancialTextIntelligenceService,
    documents_from_official_events,
    period_basis,
)
from app.text_intelligence_models import OfficialTextDocumentInput

CONFERENCE_TEXT = "公司說明先進封裝需求穩定，資本支出維持紀律，AI 加速器營收持續成長。"
EVENT_TEXT = "董事會決議資本支出案，擴充先進製程產能，以因應 AI 晶片需求提升。"


def document(*, source_type: str, period: str | None, event_date: str | None, text: str) -> OfficialTextDocumentInput:
    return OfficialTextDocumentInput(ticker="2454", company_name="聯發科", source_type=source_type,
                                     source_name="synthetic", source_url="https://example.test/doc",
                                     period=period, event_date=event_date, text=text)


class PeriodBasisTests(unittest.TestCase):
    def test_each_document_kind_gets_its_own_basis(self) -> None:
        cases = [
            (document(source_type="investor_conference", period="2026Q2", event_date="2026-07-31", text="x"), "fiscal_quarter"),
            (document(source_type="investor_conference", period="2026-07-31", event_date="2026-07-31", text="x"), "conference_date"),
            (document(source_type="material_event", period="2026-08-31", event_date="2026-08-31", text="x"), "announcement_date"),
            (document(source_type="uploaded_text", period="2026-08-31", event_date="2026-08-31", text="x"), "event_date"),
            (document(source_type="material_event", period=None, event_date="2026-08-31", text="x"), "unspecified"),
            (document(source_type="uploaded_text", period="FY2026 H1", event_date=None, text="x"), "unspecified"),
            (document(source_type="uploaded_text", period="2026-08-31", event_date=None, text="x"), "unspecified"),
        ]
        for doc, expected in cases:
            with self.subTest(source=doc.source_type, period=doc.period, event_date=doc.event_date):
                self.assertEqual(period_basis(doc), expected)

    def test_official_events_build_quarter_and_date_documents(self) -> None:
        conference = InvestorConferenceRecord(
            event_id="ir-2026q2", ticker="2454", company_name="聯發科", subindustry="IC 設計", fiscal_year=2026, quarter=2,
            conference_date="2026-07-31", title="MediaTek 2026 Q2 Results", summary=CONFERENCE_TEXT,
            source_name="company_official_ir", source_url="https://example.test/ir", status="available")
        undated_quarter = InvestorConferenceRecord(
            event_id="ir-dated", ticker="2454", company_name="聯發科", subindustry="IC 設計",
            conference_date="2026-04-30", title="法說會", summary=CONFERENCE_TEXT,
            source_name="company_official_ir", source_url="https://example.test/ir2", status="available")
        event = MaterialEventRecord(
            event_id="me-1", ticker="2454", company_name="聯發科", subindustry="IC 設計", event_date="2026-08-31",
            title="公告董事會決議資本支出案", summary=EVENT_TEXT, source_name="twse_openapi",
            source_url="https://example.test/me", status="available")
        documents = documents_from_official_events(ticker="2454", conferences=[conference, undated_quarter], material_events=[event])
        by_id = {doc.document_id: doc for doc in documents}
        self.assertEqual((by_id["ir-2026q2"].period, period_basis(by_id["ir-2026q2"])), ("2026Q2", "fiscal_quarter"))
        self.assertEqual((by_id["ir-dated"].period, period_basis(by_id["ir-dated"])), ("2026-04-30", "conference_date"))
        self.assertEqual((by_id["me-1"].period, period_basis(by_id["me-1"])), ("2026-08-31", "announcement_date"))


class NarrativeShiftPeriodFieldsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = FinancialTextIntelligenceService()

    def test_date_and_quarter_keep_their_values_and_bases(self) -> None:
        event = document(source_type="material_event", period="2026-08-31", event_date="2026-08-31", text=EVENT_TEXT)
        conference = document(source_type="investor_conference", period="2026Q2", event_date="2026-07-31", text=CONFERENCE_TEXT)
        shift = self.service.narrative_shift(event, conference)
        self.assertEqual((shift.period_1, shift.period_1_basis, shift.period_1_source_type),
                         ("2026-08-31", "announcement_date", "material_event"))
        self.assertEqual((shift.period_2, shift.period_2_basis, shift.period_2_source_type),
                         ("2026Q2", "fiscal_quarter", "investor_conference"))

    def test_two_quarters_share_the_fiscal_quarter_basis(self) -> None:
        first = document(source_type="investor_conference", period="2026Q1", event_date="2026-04-30", text=EVENT_TEXT)
        second = document(source_type="investor_conference", period="2026Q2", event_date="2026-07-31", text=CONFERENCE_TEXT)
        shift = self.service.narrative_shift(first, second)
        self.assertEqual((shift.period_1_basis, shift.period_2_basis), ("fiscal_quarter", "fiscal_quarter"))

    def test_metrics_do_not_depend_on_period_labels(self) -> None:
        labelled = self.service.narrative_shift(
            document(source_type="material_event", period="2026-08-31", event_date="2026-08-31", text=EVENT_TEXT),
            document(source_type="investor_conference", period="2026Q2", event_date="2026-07-31", text=CONFERENCE_TEXT))
        unlabelled = self.service.narrative_shift(
            document(source_type="material_event", period=None, event_date=None, text=EVENT_TEXT),
            document(source_type="investor_conference", period=None, event_date=None, text=CONFERENCE_TEXT))
        self.assertEqual(labelled.metrics, unlabelled.metrics)
        self.assertEqual([change.model_dump() for change in labelled.topic_changes],
                         [change.model_dump() for change in unlabelled.topic_changes])
        self.assertEqual((unlabelled.period_1_basis, unlabelled.period_2_basis), ("unspecified", "unspecified"))

    def test_serialized_response_keeps_old_keys_and_adds_basis_fields(self) -> None:
        shift = self.service.narrative_shift(
            document(source_type="material_event", period="2026-08-31", event_date="2026-08-31", text=EVENT_TEXT),
            document(source_type="investor_conference", period="2026Q2", event_date="2026-07-31", text=CONFERENCE_TEXT))
        payload = shift.model_dump(mode="json")
        for key in ("ticker", "period_1", "period_2", "metrics", "data_quality", "topic_changes", "emerging_terms",
                    "disappearing_terms", "supporting_sentences", "method", "limitations", "schema_version"):
            self.assertIn(key, payload)
        self.assertEqual(payload["schema_version"], "narrative-shift-v2.0")
        self.assertEqual(payload["period_1_basis"], "announcement_date")
        self.assertEqual(payload["period_2_basis"], "fiscal_quarter")


if __name__ == "__main__":
    unittest.main()
