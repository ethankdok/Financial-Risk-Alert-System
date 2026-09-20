from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.services.fact_repository import FirestoreFinancialFactRepository
from app.services.firestore_analysis_repository import FirestoreAnalysisRepository
from app.services.analysis_repository import legacy_fact_document_ids


class FakeSnapshot:
    def __init__(self, payload: dict, document_id: str) -> None:
        self.payload = payload
        self.id = document_id

    def to_dict(self) -> dict:
        payload = dict(self.payload)
        payload.pop("_test_document_id", None)
        return payload


class FakeQuery:
    def __init__(self, rows: list[dict], filters: list[tuple[str, object]] | None = None) -> None:
        self.rows = rows
        self.filters = filters or []

    def where(self, *, filter: object) -> "FakeQuery":
        return FakeQuery(self.rows, [*self.filters, (filter.field_path, filter.value)])

    def stream(self) -> list[FakeSnapshot]:
        return [
            FakeSnapshot(row, str(row.get("_test_document_id") or index))
            for index, row in enumerate(self.rows)
            if all(row.get(field) == value for field, value in self.filters)
        ]


class FakeClient:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def collection(self, name: str) -> FakeQuery:
        if name != "normalized_financial_facts":
            raise AssertionError(f"unexpected collection: {name}")
        return FakeQuery(self.rows)


def fact_row(**overrides: object) -> dict:
    row = {
        "ticker": "2454",
        "company_name": "聯發科",
        "subindustry": "IC 設計",
        "analysis_type": "latest",
        "period": "2025FY",
        "metric_code": "revenue",
        "value": 100.0,
        "unit": "TWD",
        "source_kind": "mops_xbrl",
        "source_url": "https://example.test/2454/2025",
        "taxonomy_concept": "Revenue",
        "retrieved_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def repositories(rows: list[dict]) -> tuple[FirestoreAnalysisRepository, FirestoreFinancialFactRepository]:
    client = FakeClient(rows)
    analysis = FirestoreAnalysisRepository.__new__(FirestoreAnalysisRepository)
    analysis.client = client
    direct = FirestoreFinancialFactRepository.__new__(FirestoreFinancialFactRepository)
    direct.client = client
    return analysis, direct


class FirestoreFactCompatibilityTests(unittest.TestCase):
    def test_legacy_only_remains_readable(self) -> None:
        analysis, direct = repositories([fact_row(value=101.0)])
        listed = analysis.list_facts("2454")
        self.assertEqual(len(listed), 1)
        self.assertEqual(analysis.get_fact("2454", "revenue", "2025FY").value, 101.0)
        self.assertEqual(direct.get("2454", "revenue", "2025FY").value, 101.0)

    def test_v2_only_remains_readable(self) -> None:
        v2 = fact_row(
            value=202.0,
            fact_key_version="financial-fact-v2",
            statement_scope="consolidated",
            statement_type="income_statement",
        )
        analysis, direct = repositories([v2])
        self.assertEqual(len(analysis.list_facts("2454")), 1)
        self.assertEqual(analysis.get_fact("2454", "revenue", "2025FY").value, 202.0)
        self.assertEqual(direct.get("2454", "revenue", "2025FY").value, 202.0)

    def test_legacy_and_v2_coexist_without_logical_duplicate_and_v2_wins(self) -> None:
        legacy = fact_row(value=101.0)
        v2 = fact_row(
            value=202.0,
            fact_key_version="financial-fact-v2",
            statement_scope="unknown",
            statement_type="income_statement",
            retrieved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        for rows in ([legacy, v2], [v2, legacy]):
            analysis, direct = repositories(rows)
            listed = analysis.list_facts("2454")
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["value"], 202.0)
            self.assertNotIn("_document_id", listed[0])
            self.assertEqual(analysis.get_fact("2454", "revenue", "2025FY").value, 202.0)
            self.assertEqual(direct.get("2454", "revenue", "2025FY").value, 202.0)

    def test_mixed_legacy_v2_keeps_unmatched_and_distinct_v2_variants(self) -> None:
        overlapping_legacy = fact_row(value=101.0)
        matching_v2 = fact_row(
            value=202.0,
            fact_key_version="financial-fact-v2",
            statement_scope="unknown",
            statement_type="income_statement",
        )
        standalone_v2 = fact_row(
            value=303.0,
            fact_key_version="financial-fact-v2",
            statement_scope="standalone",
            statement_type="income_statement",
        )
        unmatched_legacy = fact_row(
            metric_code="net_income",
            value=404.0,
            taxonomy_concept="NetIncome",
        )
        analysis, _ = repositories(
            [unmatched_legacy, standalone_v2, overlapping_legacy, matching_v2]
        )
        listed = analysis.list_facts("2454")
        self.assertEqual(len(listed), 3)
        self.assertEqual(sorted(row["value"] for row in listed), [202.0, 303.0, 404.0])

    def test_legacy_document_id_maps_known_source_url_schema_correction(self) -> None:
        v2 = fact_row(
            value=202.0,
            source_url="https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci",
            fact_key_version="financial-fact-v2",
            statement_scope="unknown",
            statement_type="balance_sheet",
        )
        legacy = fact_row(
            value=101.0,
            source_url="https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
            _test_document_id=legacy_fact_document_ids(v2)[0],
        )
        analysis, direct = repositories([legacy, v2])
        self.assertEqual([row["value"] for row in analysis.list_facts("2454")], [202.0])
        self.assertEqual(analysis.get_fact("2454", "revenue", "2025FY").value, 202.0)
        self.assertEqual(direct.get("2454", "revenue", "2025FY").value, 202.0)


if __name__ == "__main__":
    unittest.main()
