"""Exact-scope presentation calibration with the FROZEN teammate method (loaded ephemerally).

Synthetic official-style presentation decks only. The teammate code is read with
``git show`` at the pinned research commit; the tests skip when it is unavailable.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.jsd_bridge_service import JsdBridgeService
from app.services.jsd_calibration import JsonJsdCalibrationRepository
from app.services.jsd_method import normalized_sha256
from app.services.conference_jsd_corpus_adapter import build_records
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
from scripts.calibrate_conference_scope import FrozenTeammateMethod, ScopeRejected, calibrate_scope, scope_rows
from scripts.import_jsd_calibration_profile import build_profile, main as import_main
from tests.test_conference_jsd_adapter import deck, write_archive
from tests.test_jsd_bridge import profile as bridge_profile

REPO_ROOT = Path(__file__).resolve().parents[2]
WORDS = {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}
VOCABULARY = ("wafer", "node", "demand", "capacity", "margin", "inventory", "smartphone", "server", "automotive",
              "packaging", "pricing", "utilization", "customer", "shipment", "guidance", "depreciation", "currency",
              "memory", "display", "consumer", "network", "cloud", "industrial", "yield")


def quarters(first: str, count: int) -> list[tuple[int, int]]:
    index = int(first[:4]) * 4 + int(first[-1]) - 1
    return [((index + offset) // 4, (index + offset) % 4 + 1) for offset in range(count)]


def text_for(year: int, quarter: int, *, short: bool = False) -> str:
    seed = year * 4 + quarter
    words = [VOCABULARY[(seed * 7 + i * (seed % 5 + 1)) % len(VOCABULARY)] for i in range(40)]
    sentences = [f"Management discussed {words[i % 40]} and {words[(i * 3) % 40]} trends for {words[(i * 7) % 40]} "
                 f"markets in segment {i % (seed % 9 + 3)}." for i in range(20 if short else 110)]
    return " ".join(sentences)


def archive_decks(root: Path, ticker: str, periods: list[tuple[int, int]], *, language: str = "en",
                  short: set[tuple[int, int]] = frozenset()) -> None:
    by_year: dict[int, list[dict]] = {}
    for year, quarter in periods:
        cover = (f"{year} {WORDS[quarter]} Quarter Earnings Conference" if language == "en"
                 else f"{year}年第{quarter}季法人說明會")
        by_year.setdefault(year, []).append({
            "filename": f"{ticker}{year}{quarter:02d}01{'E' if language == 'en' else 'M'}001.pdf", "language": language,
            "pages": deck(cover, text_for(year, quarter, short=(year, quarter) in short))})
    for year, documents in by_year.items():
        write_archive(root, ticker, year, documents)


def keys_of(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in keys_of(item)}
    if isinstance(value, list):
        return {key for item in value for key in keys_of(item)}
    return set()


class _FrozenMethodCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.method = FrozenTeammateMethod().__enter__()
        except ScopeRejected as exc:
            raise unittest.SkipTest(f"frozen teammate code unavailable: {exc}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.method.__exit__(None, None, None)

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "archive"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def calibrate(self, ticker: str = "2454", **kwargs):
        records = build_records(FileConferencePdfArchiveRepository(self.root), ticker)
        return calibrate_scope(records, ticker=ticker, document_type="earnings_presentation", language="en",
                               period_1="2025Q2", period_2="2025Q3", method=self.method, **kwargs)


class FrozenMethodCalibrationTests(_FrozenMethodCase):
    def test_frozen_module_hash_is_the_production_reference(self) -> None:
        self.assertEqual(self.method.module_sha256, normalized_sha256(REPO_ROOT / "data_shift.py"))

    def test_presentation_scope_accepted_with_unmodified_analyze_and_no_leakage(self) -> None:
        archive_decks(self.root, "2454", quarters("2017Q1", 35))  # 2017Q1..2025Q3

        result = self.calibrate()

        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["history_pair_count"], 32)
        self.assertEqual(result["history_latest_period"], "2025Q1")
        self.assertTrue(result["no_leakage_proof"]["all_history_before_target"])
        self.assertTrue(all(pair["period_2"] < "2025Q2" for pair in result["raw_analyze"]["calibration"]["history_pairs"]))
        self.assertIsNotNone(result["thresholds"])
        # Records keep their real type; nothing is relabelled as a transcript.
        self.assertEqual({doc["document_type"] for doc in result["raw_analyze"]["source_documents"]},
                         {"earnings_presentation"})
        self.assertNotIn("text", keys_of(result["import_report"]) | keys_of(result["raw_analyze"]))

    def test_twenty_nine_history_pairs_are_insufficient(self) -> None:
        archive_decks(self.root, "2454", quarters("2017Q4", 32))  # 2017Q4..2025Q3 -> 29 history pairs

        result = self.calibrate()

        self.assertEqual((result["status"], result["history_pair_count"], result["thresholds"]),
                         ("insufficient_history", 29, None))

    def test_quality_failing_target_never_produces_a_profile(self) -> None:
        archive_decks(self.root, "2454", quarters("2017Q1", 35), short={(2025, 3)})

        result = self.calibrate()

        self.assertEqual(result["status"], "quality_insufficient")
        self.assertNotIn("import_report", result)

    def test_short_history_documents_are_rejected_pairs(self) -> None:
        archive_decks(self.root, "2454", quarters("2017Q1", 35), short={(2019, 2)})

        result = self.calibrate()

        self.assertEqual(result["history_pair_count"], 30)
        self.assertEqual({(pair["period_1"], pair["period_2"]) for pair in result["rejected_history_pairs"]},
                         {("2019Q1", "2019Q2"), ("2019Q2", "2019Q3")})

    def test_exact_scope_excludes_other_languages_and_fails_on_duplicate_periods(self) -> None:
        archive_decks(self.root, "2454", quarters("2024Q1", 7))
        archive_decks(self.root, "2454", quarters("2024Q1", 7), language="zh")
        records = build_records(FileConferencePdfArchiveRepository(self.root), "2454")

        rows = scope_rows(records, ticker="2454", document_type="earnings_presentation", language="en")
        self.assertEqual(len(rows), 7)
        self.assertEqual({row["language"] for row in rows}, {"en"})

        english = [item for item in records if item.record["language"] == "en"]
        twin = dataclasses.replace(english[0], record={**english[0].record, "sha256": "f" * 64})
        with self.assertRaises(ScopeRejected) as raised:
            scope_rows(english + [twin], ticker="2454", document_type="earnings_presentation", language="en")
        self.assertEqual(raised.exception.status, "duplicate_period_ambiguity")


class ProfileCoexistenceAndIsolationTests(_FrozenMethodCase):
    def import_profile(self, result: dict):
        return build_profile(result["import_report"], source_family="mops_t100sb02_1_conference_pdf",
                             extraction_method=result["import_report"]["corpus_provenance"]["extraction_method"],
                             preprocessing_version=result["import_report"]["corpus_provenance"]["preprocessing_version"],
                             source_research_commit=result["import_report"]["method_reference"]["source_research_commit"],
                             module_sha256=self.method.module_sha256)

    def test_raw_metrics_unchanged_profiles_coexist_and_other_tickers_stay_uncalibrated(self) -> None:
        archive_decks(self.root, "2330", quarters("2017Q1", 35))
        archive_decks(self.root, "2303", quarters("2025Q1", 3))
        result = self.calibrate("2330")
        presentation = self.import_profile(result)
        transcript = bridge_profile(ticker="2330", document_type="full_earnings_transcript",
                                    language="en_may_include_translation", history_latest="2025Q2")
        self.assertNotEqual(presentation.calibration_id, transcript.calibration_id)
        self.assertEqual(len(presentation.source_document_hashes), 2 + 33)  # target pair + 33 history documents

        profiles = Path(self.tmp.name) / "profiles"
        profiles.mkdir()
        repository = FileConferencePdfArchiveRepository(self.root)
        before = JsdBridgeService(repository, JsonJsdCalibrationRepository(profiles)).analyze("2330")
        for item in (presentation, transcript):
            (profiles / f"{item.calibration_id}.json").write_text(item.model_dump_json(), encoding="utf-8")
        service = JsdBridgeService(repository, JsonJsdCalibrationRepository(profiles))
        after = service.analyze("2330")

        self.assertEqual(before["calibration"]["status"], "unavailable")
        self.assertEqual(after["calibration"]["status"], "calibrated")
        self.assertEqual(after["calibration"]["calibration_id"], presentation.calibration_id)
        self.assertEqual(after["metrics"], before["metrics"])  # calibration never changes the raw measurement
        self.assertEqual(after["metrics"], result["target_metrics"])
        self.assertEqual(service.analyze("2303")["calibration"]["status"], "unavailable")

    def test_profile_import_is_idempotent_and_conflicts_are_refused(self) -> None:
        archive_decks(self.root, "2454", quarters("2017Q1", 35))
        result = self.calibrate()
        report = Path(self.tmp.name) / "report.json"
        report.write_text(json.dumps(result["import_report"]), encoding="utf-8")
        out = Path(self.tmp.name) / "profiles"
        argv = ["import", "--report", str(report), "--source-family", "mops_t100sb02_1_conference_pdf",
                "--extraction-method", result["import_report"]["corpus_provenance"]["extraction_method"],
                "--preprocessing-version", result["import_report"]["corpus_provenance"]["preprocessing_version"],
                "--source-research-commit", result["import_report"]["method_reference"]["source_research_commit"],
                "--method-module", str(REPO_ROOT / "data_shift.py"), "--output-dir", str(out), "--write-json"]
        with patch.object(sys, "argv", argv):
            self.assertEqual(import_main(), 0)
            self.assertEqual(import_main(), 0)  # unchanged, not rewritten
        self.assertEqual(len(list(out.glob("*.json"))), 1)
        changed = json.loads(report.read_text(encoding="utf-8"))
        changed["calibration"]["thresholds"]["jsd_p90"] += 0.01
        report.write_text(json.dumps(changed), encoding="utf-8")
        with patch.object(sys, "argv", argv):
            self.assertEqual(import_main(), 2)


if __name__ == "__main__":
    unittest.main()
