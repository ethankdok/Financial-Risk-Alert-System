from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.migrate_financial_sqlite_to_firestore import (
    build_plan,
    collect,
    execute_plan,
    fact_document_id,
)
from scripts.audit_database_contract import audit


class FakeSnapshot:
    def __init__(self, payload: dict | None) -> None:
        self._payload = payload
        self.exists = payload is not None

    def to_dict(self) -> dict | None:
        return None if self._payload is None else dict(self._payload)


class FakeDocument:
    def __init__(self, client: "FakeFirestore", collection: str, document_id: str) -> None:
        self.client = client
        self.collection_name = collection
        self.document_id = document_id

    def get(self) -> FakeSnapshot:
        return FakeSnapshot(self.client.rows.get((self.collection_name, self.document_id)))


class FakeCollection:
    def __init__(self, client: "FakeFirestore", name: str) -> None:
        self.client = client
        self.name = name

    def document(self, document_id: str) -> FakeDocument:
        return FakeDocument(self.client, self.name, document_id)


class FakeBatch:
    def __init__(self, client: "FakeFirestore") -> None:
        self.client = client
        self.operations: list[tuple[str, FakeDocument, dict | None]] = []

    def set(self, ref: FakeDocument, payload: dict, merge: bool = False) -> None:
        self.operations.append(("set", ref, dict(payload)))

    def delete(self, ref: FakeDocument) -> None:
        self.operations.append(("delete", ref, None))

    def commit(self) -> None:
        for operation, ref, payload in self.operations:
            key = (ref.collection_name, ref.document_id)
            self.client.events.append((operation, *key))
            if operation == "set":
                assert payload is not None
                stored = dict(payload)
                if self.client.corrupt_readback:
                    stored["value"] = -999
                self.client.rows[key] = stored
            else:
                self.client.rows.pop(key, None)


class FakeFirestore:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], dict] = {}
        self.events: list[tuple[str, str, str]] = []
        self.corrupt_readback = False

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, name)

    def batch(self) -> FakeBatch:
        return FakeBatch(self)


def fact_row(**overrides: object) -> dict:
    row = {
        "fact_id": "legacy-row",
        "ticker": "2330",
        "company_name": "台積電",
        "subindustry": "晶圓代工",
        "analysis_type": "latest",
        "period": "2026-07",
        "metric_code": "monthly_revenue",
        "value": 100.0,
        "unit": "新台幣仟元",
        "source_kind": "twse_openapi",
        "source_url": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
        "taxonomy_concept": None,
        "retrieved_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "statement_type": "monthly_revenue",
        "statement_scope": "unknown",
        "filed_at": None,
        "is_demo": 0,
        "source_field": "monthly_revenue",
        "fact_key_version": "financial-fact-v2",
    }
    row.update(overrides)
    return row


class FinancialMigrationSafetyTests(unittest.TestCase):
    def test_audit_reports_missing_tables_instead_of_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "empty.sqlite3"
            sqlite3.connect(source).close()
            result = audit(source)
            self.assertEqual(result["gate"], "BLOCKED")
            self.assertEqual(result["checks"]["fact_count"], 0)
            self.assertTrue(any(item["code"] == "missing_tables" for item in result["findings"]))

    def test_collect_is_read_only_and_converts_timestamp_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            connection = sqlite3.connect(source)
            connection.execute(
                """CREATE TABLE ingestion_runs (
                    run_id TEXT PRIMARY KEY, ticker TEXT, started_at TEXT, completed_at TEXT
                )"""
            )
            connection.execute(
                "INSERT INTO ingestion_runs VALUES (?, ?, ?, ?)",
                ("run-1", "2330", "2026-08-01T01:02:03+00:00", None),
            )
            connection.commit()
            connection.close()

            before = source.read_bytes()
            rows = collect(source, ["2330"])
            after = source.read_bytes()
            self.assertEqual(before, after)
            self.assertEqual(rows["ingestion_runs"][0]["started_at"].tzinfo, timezone.utc)

    def test_collect_selects_only_latest_run_scoped_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            connection = sqlite3.connect(source)
            connection.executescript(
                """
                CREATE TABLE analysis_runs (
                    run_id TEXT PRIMARY KEY, ticker TEXT, started_at TEXT
                );
                CREATE TABLE calculated_metrics (
                    run_id TEXT, ticker TEXT, analysis_type TEXT, period TEXT,
                    metric_code TEXT
                );
                CREATE TABLE rule_results (
                    run_id TEXT, ticker TEXT, analysis_type TEXT, rule_id TEXT
                );
                CREATE TABLE ingestion_runs (
                    run_id TEXT PRIMARY KEY, ticker TEXT, started_at TEXT
                );
                """
            )
            for suffix, timestamp in (("old", "2026-08-01T00:00:00+00:00"),
                                      ("new", "2026-09-01T00:00:00+00:00")):
                run_id = f"analysis-{suffix}"
                connection.execute("INSERT INTO analysis_runs VALUES (?, ?, ?)", (run_id, "2330", timestamp))
                connection.execute(
                    "INSERT INTO calculated_metrics VALUES (?, ?, ?, ?, ?)",
                    (run_id, "2330", "latest", "2026-08", "monthly_revenue_mom"),
                )
                connection.execute(
                    "INSERT INTO rule_results VALUES (?, ?, ?, ?)",
                    (run_id, "2330", "latest", f"rule-{suffix}"),
                )
                connection.execute(
                    "INSERT INTO ingestion_runs VALUES (?, ?, ?)",
                    (f"ingestion-{suffix}", "2330", timestamp),
                )
            connection.commit()
            connection.close()

            rows = collect(source, ["2330"])
            self.assertEqual([row["run_id"] for row in rows["analysis_runs"]], ["analysis-new"])
            self.assertEqual([row["run_id"] for row in rows["calculated_metrics"]], ["analysis-new"])
            self.assertEqual([row["run_id"] for row in rows["rule_results"]], ["analysis-new"])
            self.assertEqual([row["run_id"] for row in rows["ingestion_runs"]], ["ingestion-new"])

    def test_snapshot_document_id_is_ticker_and_plan_is_deterministic(self) -> None:
        rows = {collection: [] for collection in (
            "companies", "financial_filings", "normalized_financial_facts",
            "analysis_runs", "calculated_metrics", "rule_results",
            "latest_analysis_snapshots", "ingestion_runs",
        )}
        rows["latest_analysis_snapshots"] = [{"ticker": "2454", "summary": "ok"}]
        first = build_plan(rows)
        second = build_plan(rows)
        self.assertEqual(first["fingerprint"], second["fingerprint"])
        self.assertEqual(first["documents"][0]["document_id"], "2454")

    def test_source_key_collision_blocks_before_firestore_access(self) -> None:
        first = fact_row(analysis_type="latest", value=100.0)
        second = fact_row(analysis_type="ingested", value=101.0)
        plan = build_plan({"normalized_financial_facts": [first, second]})
        self.assertEqual(len(plan["source_conflicts"]), 1)
        client = FakeFirestore()
        with self.assertRaisesRegex(RuntimeError, "collide"):
            execute_plan(client, plan, delete_legacy=False)
        self.assertEqual(client.events, [])

    def test_target_conflict_blocks_all_writes(self) -> None:
        row = fact_row()
        plan = build_plan({"normalized_financial_facts": [row]})
        client = FakeFirestore()
        target_id = fact_document_id(row)
        client.rows[("normalized_financial_facts", target_id)] = {**row, "value": 999.0}
        with self.assertRaisesRegex(RuntimeError, "target conflicts"):
            execute_plan(client, plan, delete_legacy=False)
        self.assertEqual(client.events, [])

    def test_legacy_requires_explicit_flag_and_is_deleted_after_readback(self) -> None:
        row = fact_row()
        plan = build_plan({"normalized_financial_facts": [row]})
        legacy_id = plan["documents"][0]["legacy_document_ids"][0]
        client = FakeFirestore()
        client.rows[("normalized_financial_facts", legacy_id)] = dict(row)
        with self.assertRaisesRegex(RuntimeError, "Legacy fact documents"):
            execute_plan(client, plan, delete_legacy=False)
        self.assertEqual(client.events, [])

        result = execute_plan(client, plan, delete_legacy=True)
        self.assertEqual(result["verification"], "PASS")
        operations = [event[0] for event in client.events]
        self.assertLess(operations.index("set"), operations.index("delete"))

    def test_readback_failure_never_deletes_legacy_document(self) -> None:
        row = fact_row()
        plan = build_plan({"normalized_financial_facts": [row]})
        legacy_id = plan["documents"][0]["legacy_document_ids"][0]
        client = FakeFirestore()
        client.rows[("normalized_financial_facts", legacy_id)] = dict(row)
        client.corrupt_readback = True
        with self.assertRaisesRegex(RuntimeError, "read-back"):
            execute_plan(client, plan, delete_legacy=True)
        self.assertNotIn("delete", [event[0] for event in client.events])


if __name__ == "__main__":
    unittest.main()
