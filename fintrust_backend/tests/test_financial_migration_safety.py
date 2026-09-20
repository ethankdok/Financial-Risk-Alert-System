from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.migrate_financial_sqlite_to_firestore import (
    NoValidRunError,
    build_plan,
    build_manifest,
    classify_target,
    collect,
    execute_plan,
    fact_document_id,
    preflight,
    _normalize_payload,
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
    def test_firestore_payload_uses_repository_json_field_names(self) -> None:
        filing = _normalize_payload(
            "financial_filings",
            {"concept_matches_json": {"revenue": "Revenue"}, "warnings_json": []},
        )
        self.assertEqual(filing["concept_matches"], {"revenue": "Revenue"})
        self.assertEqual(filing["warnings"], [])
        self.assertNotIn("concept_matches_json", filing)
        metric = _normalize_payload(
            "calculated_metrics",
            {"comparison_periods_json": ["2025FY"], "source_fields_json": ["revenue"]},
        )
        self.assertEqual(metric["comparison_periods"], ["2025FY"])
        self.assertEqual(metric["source_fields"], ["revenue"])

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
                    run_id TEXT PRIMARY KEY, ticker TEXT, status TEXT,
                    started_at TEXT, completed_at TEXT
                )"""
            )
            connection.execute(
                "INSERT INTO ingestion_runs VALUES (?, ?, ?, ?, ?)",
                ("run-1", "2330", "completed", "2026-08-01T01:02:03+00:00", None),
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
                    run_id TEXT PRIMARY KEY, ticker TEXT, status TEXT, started_at TEXT
                );
                CREATE TABLE calculated_metrics (
                    run_id TEXT, ticker TEXT, analysis_type TEXT, period TEXT,
                    metric_code TEXT
                );
                CREATE TABLE rule_results (
                    run_id TEXT, ticker TEXT, analysis_type TEXT, rule_id TEXT
                );
                CREATE TABLE ingestion_runs (
                    run_id TEXT PRIMARY KEY, ticker TEXT, status TEXT, started_at TEXT
                );
                """
            )
            for suffix, timestamp in (("old", "2026-08-01T00:00:00+00:00"),
                                      ("new", "2026-09-01T00:00:00+00:00")):
                run_id = f"analysis-{suffix}"
                connection.execute(
                    "INSERT INTO analysis_runs VALUES (?, ?, ?, ?)",
                    (run_id, "2330", "completed", timestamp),
                )
                connection.execute(
                    "INSERT INTO calculated_metrics VALUES (?, ?, ?, ?, ?)",
                    (run_id, "2330", "latest", "2026-08", "monthly_revenue_mom"),
                )
                connection.execute(
                    "INSERT INTO rule_results VALUES (?, ?, ?, ?)",
                    (run_id, "2330", "latest", f"rule-{suffix}"),
                )
                connection.execute(
                    "INSERT INTO ingestion_runs VALUES (?, ?, ?, ?)",
                    (f"ingestion-{suffix}", "2330", "completed", timestamp),
                )
            connection.commit()
            connection.close()

            rows = collect(source, ["2330"])
            self.assertEqual([row["run_id"] for row in rows["analysis_runs"]], ["analysis-new"])
            self.assertEqual([row["run_id"] for row in rows["calculated_metrics"]], ["analysis-new"])
            self.assertEqual([row["run_id"] for row in rows["rule_results"]], ["analysis-new"])
            self.assertEqual([row["run_id"] for row in rows["ingestion_runs"]], ["ingestion-new"])

    def test_collect_uses_latest_completed_run_and_deterministic_tie_break(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            connection = sqlite3.connect(source)
            connection.executescript(
                """
                CREATE TABLE analysis_runs (
                    run_id TEXT PRIMARY KEY, ticker TEXT, status TEXT, started_at TEXT
                );
                CREATE TABLE calculated_metrics (
                    run_id TEXT, ticker TEXT, analysis_type TEXT, period TEXT, metric_code TEXT
                );
                CREATE TABLE rule_results (
                    run_id TEXT, ticker TEXT, analysis_type TEXT, rule_id TEXT
                );
                CREATE TABLE ingestion_runs (
                    run_id TEXT PRIMARY KEY, ticker TEXT, status TEXT, started_at TEXT
                );
                """
            )
            timestamp = "2026-09-01T00:00:00+00:00"
            analysis = [
                ("completed-a", "completed", timestamp),
                ("completed-b", "completed", timestamp),
                ("failed-new", "failed", "2026-10-01T00:00:00+00:00"),
                ("running-new", "running", "2026-11-01T00:00:00+00:00"),
            ]
            for run_id, status, started_at in analysis:
                connection.execute(
                    "INSERT INTO analysis_runs VALUES (?, '2330', ?, ?)",
                    (run_id, status, started_at),
                )
                connection.execute(
                    "INSERT INTO calculated_metrics VALUES (?, '2330', 'latest', '2026-08', 'revenue')",
                    (run_id,),
                )
                connection.execute(
                    "INSERT INTO rule_results VALUES (?, '2330', 'latest', ?)",
                    (run_id, f"rule-{run_id}"),
                )
            for run_id, status, started_at in (
                ("ingestion-a", "completed", timestamp),
                ("ingestion-b", "completed", timestamp),
                ("ingestion-failed", "failed", "2026-10-01T00:00:00+00:00"),
            ):
                connection.execute(
                    "INSERT INTO ingestion_runs VALUES (?, '2330', ?, ?)",
                    (run_id, status, started_at),
                )
            connection.commit()
            connection.close()

            rows = collect(source, ["2330"])
            self.assertEqual([row["run_id"] for row in rows["analysis_runs"]], ["completed-b"])
            self.assertEqual([row["run_id"] for row in rows["calculated_metrics"]], ["completed-b"])
            self.assertEqual([row["run_id"] for row in rows["rule_results"]], ["completed-b"])
            self.assertEqual([row["run_id"] for row in rows["ingestion_runs"]], ["ingestion-b"])

    def test_collect_reports_no_valid_completed_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            connection = sqlite3.connect(source)
            connection.execute(
                "CREATE TABLE analysis_runs (run_id TEXT, ticker TEXT, status TEXT, started_at TEXT)"
            )
            connection.execute(
                "INSERT INTO analysis_runs VALUES ('failed', '2330', 'failed', '2026-09-01T00:00:00Z')"
            )
            connection.commit()
            connection.close()
            with self.assertRaisesRegex(NoValidRunError, "no-valid-run"):
                collect(source, ["2330"])

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
            execute_plan(client, plan)
        self.assertEqual(client.events, [])

    def test_divergent_target_blocks_all_writes(self) -> None:
        row = fact_row()
        plan = build_plan({"normalized_financial_facts": [row]})
        client = FakeFirestore()
        target_id = fact_document_id(row)
        client.rows[("normalized_financial_facts", target_id)] = {**row, "value": 999.0}
        with self.assertRaisesRegex(RuntimeError, "newer or divergent"):
            execute_plan(client, plan)
        self.assertEqual(client.events, [])

    def test_legacy_overlap_is_preserved_and_does_not_block_new_v2_write(self) -> None:
        row = fact_row()
        plan = build_plan({"normalized_financial_facts": [row]})
        legacy_id = plan["documents"][0]["legacy_document_ids"][0]
        client = FakeFirestore()
        client.rows[("normalized_financial_facts", legacy_id)] = dict(row)
        result = execute_plan(client, plan)
        self.assertEqual(result["verification"], "PASS")
        self.assertEqual(result["legacy_overlap_count"], 1)
        self.assertEqual(result["legacy_deletes"], 0)
        self.assertIn(("normalized_financial_facts", legacy_id), client.rows)
        self.assertNotIn("delete", [event[0] for event in client.events])

    def test_readback_failure_preserves_legacy_document(self) -> None:
        row = fact_row()
        plan = build_plan({"normalized_financial_facts": [row]})
        legacy_id = plan["documents"][0]["legacy_document_ids"][0]
        client = FakeFirestore()
        client.rows[("normalized_financial_facts", legacy_id)] = dict(row)
        client.corrupt_readback = True
        with self.assertRaisesRegex(RuntimeError, "read-back"):
            execute_plan(client, plan)
        self.assertNotIn("delete", [event[0] for event in client.events])
        self.assertIn(("normalized_financial_facts", legacy_id), client.rows)

    def test_classification_uses_trusted_freshness_and_blocks_unsafe_overwrite(self) -> None:
        older = datetime(2026, 8, 1, tzinfo=timezone.utc)
        newer = datetime(2026, 9, 1, tzinfo=timezone.utc)
        source = {"ticker": "2454", "period": "2025FY", "source_url": "official", "retrieved_at": newer}
        target = {**source, "retrieved_at": older, "warnings": ["old"]}
        self.assertEqual(classify_target("financial_filings", source, target), "SOURCE_NEWER")
        self.assertEqual(classify_target("financial_filings", target, source), "TARGET_NEWER")
        divergent = {**target, "source_url": "different"}
        self.assertEqual(classify_target("financial_filings", source, divergent), "DIVERGENT")

        plan = build_plan({"financial_filings": [source]})
        client = FakeFirestore()
        target_id = plan["documents"][0]["document_id"]
        client.rows[("financial_filings", target_id)] = target
        with self.assertRaisesRegex(RuntimeError, "explicit opt-in"):
            execute_plan(client, plan)
        self.assertEqual(client.events, [])
        result = execute_plan(client, plan, allow_source_newer_overwrite=True)
        self.assertEqual(result["writes"], 1)

    def test_manifest_is_deterministic_and_describes_rollback(self) -> None:
        new_row = fact_row(metric_code="revenue")
        source_newer = {
            "ticker": "2454", "period": "2025FY", "source_url": "official",
            "retrieved_at": datetime(2026, 9, 1, tzinfo=timezone.utc),
        }
        plan = build_plan({
            "normalized_financial_facts": [new_row],
            "financial_filings": [source_newer],
        })
        client = FakeFirestore()
        filing = next(item for item in plan["documents"] if item["collection"] == "financial_filings")
        client.rows[("financial_filings", filing["document_id"])] = {
            **source_newer,
            "retrieved_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        }
        inspection = preflight(client, plan)
        first = build_manifest(plan, inspection)
        second = build_manifest(plan, inspection)
        self.assertEqual(first["manifest_fingerprint"], second["manifest_fingerprint"])
        by_class = {entry["classification"]: entry for entry in first["entries"]}
        self.assertEqual(by_class["NEW"]["rollback_action"], "DELETE_CREATED_DOCUMENT")
        self.assertFalse(by_class["NEW"]["pre_image_backup_required"])
        self.assertEqual(by_class["SOURCE_NEWER"]["rollback_action"], "RESTORE_PRE_IMAGE")
        self.assertTrue(by_class["SOURCE_NEWER"]["pre_image_backup_required"])
        self.assertTrue(all(entry["legacy_documents_preserved"] for entry in first["entries"]))


if __name__ == "__main__":
    unittest.main()
