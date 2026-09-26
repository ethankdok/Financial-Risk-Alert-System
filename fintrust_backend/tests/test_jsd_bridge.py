from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.services.conference_jsd_corpus_adapter import EXTRACTION_METHOD, PREPROCESSING_VERSION, SOURCE_FAMILY
from app.services.jsd_bridge_service import DUAL, NEITHER, SINGLE, UNCALIBRATED_RESULT, JsdBridgeService, evaluate_combined_rule
from app.services.jsd_calibration import (
    JsdCalibrationProfile,
    JsonJsdCalibrationRepository,
    ProfileCalibration,
    ProfileMethod,
    ProfileScope,
    calibration_id_for,
)
from app.services.jsd_method import METHOD_VERSION, SOURCE_RESEARCH_COMMIT, load_calculator
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
from tests.test_conference_jsd_adapter import deck, write_archive
from tests.test_teammate_jsd_contract import TeammateCode

WORDS = {1: "First", 2: "Second", 3: "Third", 4: "Fourth"}


def body(seed: str) -> str:
    return " ".join(f"Revenue from {seed} platforms improved as utilization of advanced nodes rose {i} percent."
                    for i in range(90))


def presentation(ticker: str, year: int, quarter: int, language: str = "en", *, seed: str | None = None) -> dict:
    if language == "en":
        cover, text = f"{year} {WORDS[quarter]} Quarter Earnings Conference", body(seed or f"q{quarter}")
    else:
        cover, text = f"{year}年第{quarter}季法人說明會", "先進製程需求強勁，營收與毛利率表現穩定成長。" * 200
    return {"filename": f"{ticker}{year}{quarter:02d}01{'E' if language == 'en' else 'M'}001.pdf", "language": language,
            "pages": deck(cover, text)}


def profile(*, ticker="2330", document_type="earnings_presentation", language="en",
            preprocessing=PREPROCESSING_VERSION, thresholds=None, history_latest="2024Q4",
            module_sha256=None, status="active") -> JsdCalibrationProfile:
    scope = ProfileScope(ticker=ticker, industry="semiconductor_foundry", document_type=document_type,
                         language=language, source_family=SOURCE_FAMILY)
    method = ProfileMethod(method_version=METHOD_VERSION, calculator_module_sha256=module_sha256 or load_calculator().module_sha256,
                           extraction_method=EXTRACTION_METHOD, preprocessing_version=preprocessing,
                           tokenizer="t", tfidf="t", jsd_log_base=2, comparison="c", minimum_history_pairs=30)
    return JsdCalibrationProfile(
        calibration_id=calibration_id_for(scope, method, history_latest), scope=scope, method=method,
        calibration=ProfileCalibration(history_pair_count=33, history_latest_period=history_latest,
                                       thresholds=thresholds or {"jsd_p90": 0.01, "jsd_p95": 0.02,
                                                                 "cosine_p10": 0.99, "cosine_p05": 0.98}),
        decision_rule={"rule": "JSD >= historical P90 AND Cosine <= historical P10"},
        source_document_hashes=["a" * 64], source_research_commit=SOURCE_RESEARCH_COMMIT,
        created_at="2026-09-27T00:00:00+00:00", status=status)


class BridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "archive"
        self.profiles = Path(self.tmp.name) / "profiles"
        self.profiles.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def archive(self, documents: list[dict], ticker: str = "2330") -> None:
        write_archive(self.root, ticker, 2025, documents)

    def save(self, *items: JsdCalibrationProfile) -> None:
        for item in items:
            (self.profiles / f"{item.calibration_id}.json").write_text(item.model_dump_json(), encoding="utf-8")

    def service(self) -> JsdBridgeService:
        return JsdBridgeService(FileConferencePdfArchiveRepository(self.root), JsonJsdCalibrationRepository(self.profiles))

    # A / N / P / Q / R
    def test_adjacent_pair_uncalibrated_with_official_provenance(self) -> None:
        self.archive([presentation("2330", 2025, 1), presentation("2330", 2025, 2, seed="other")])
        result = self.service().analyze("2330")
        self.assertEqual((result["analysis_status"], result["period_1"], result["period_2"]),
                         ("complete", "2025Q1", "2025Q2"))
        self.assertEqual(result["calibration"]["status"], "unavailable")
        self.assertEqual(result["drift_result"], UNCALIBRATED_RESULT)
        self.assertIsNone(result["combined_rule"])
        self.assertIn("jsd", result["metrics"])
        self.assertTrue(all(doc["source_url"].startswith("https://mopsov.twse.com.tw/") for doc in result["source_documents"]))
        payload = json.dumps(result, ensure_ascii=False)
        for leak in ("gs://", str(self.root), "conference-pdf-archive/", "pages.json"):
            self.assertNotIn(leak, payload)
        self.assertEqual(result["method"]["source_research_commit"], SOURCE_RESEARCH_COMMIT)
        self.assertIsNone(result["terms"])
        self.assertIn("不等同資訊真假", result["warning"])

    # B / C / D / E / O
    def test_pair_selection_rules(self) -> None:
        self.archive([presentation("2330", 2025, 1), presentation("2330", 2025, 3),
                      presentation("2330", 2025, 2, "zh"),
                      {"filename": "233020250601E001.pdf", "pages": deck("2025 Second Quarter Earnings Call Transcript", body("t"))}])
        service = self.service()
        self.assertEqual(service.analyze("2330", "2025Q1", "2025Q3")["reason_code"], "periods_not_adjacent")
        self.assertEqual(service.analyze("2330", "2025Q1", "2025Q2")["reason_code"], "no_same_type_and_language_pair")
        auto = service.analyze("2330")
        self.assertEqual((auto["analysis_status"], auto["reason_code"]), ("insufficient_data", "no_comparable_pair"))
        periods = {(d["period"], d["document_type"], d["language"]) for d in auto["available_documents"]}
        self.assertIn(("2025Q2", "earnings_presentation", "zh-Hant"), periods)
        self.assertIn(("2025Q2", "full_earnings_transcript", "en"), periods)

    def test_not_ready_documents_are_excluded(self) -> None:
        self.archive([presentation("2330", 2025, 1),
                      {"filename": "233020250601E001.pdf", "pages": deck("Company Overview", body("x"))}])
        self.assertEqual(self.service().analyze("2330")["reason_code"], "no_comparable_pair")
        with self.assertRaises(ValueError):
            self.service().analyze("2330", "2025Q1", None)

    # F / G / H / I / K / L / M
    def test_profile_matching_and_rule(self) -> None:
        self.archive([presentation("2330", 2025, 1, seed="automotive"), presentation("2330", 2025, 2, seed="smartphone")])
        self.save(profile(ticker="2454"), profile(document_type="full_earnings_transcript"),
                  profile(preprocessing="tsmc-corpus-extract_pdf@5b914937"), profile(history_latest="2025Q1"),
                  profile(language="zh-Hant"), profile(module_sha256="b" * 64), profile(status="insufficient_history"))
        uncalibrated = self.service().analyze("2330")
        self.assertEqual(uncalibrated["calibration"]["status"], "unavailable")
        reasons = {tuple(item["differs_in"]) for item in uncalibrated["calibration"]["nearest_profiles"]}
        self.assertIn(("document_type",), reasons)
        self.assertIn(("preprocessing_version",), reasons)
        self.assertIn(("language",), reasons)
        self.assertIn(("calculator_module_sha256",), reasons)
        self.assertIn(("history_overlaps_target",), reasons)
        raw = self.service().analyze("2330")["metrics"]
        matching = profile(thresholds={"jsd_p90": raw["jsd"], "jsd_p95": raw["jsd"] * 2,
                                       "cosine_p10": raw["cosine_similarity"], "cosine_p05": raw["cosine_similarity"] / 2})
        self.save(matching)
        calibrated = self.service().analyze("2330")
        self.assertEqual((calibrated["calibration"]["status"], calibrated["calibration"]["calibration_id"]),
                         ("calibrated", matching.calibration_id))
        self.assertEqual(calibrated["calibration"]["source_research_commit"], SOURCE_RESEARCH_COMMIT)
        self.assertEqual(calibrated["drift_result"], DUAL)
        self.assertEqual(evaluate_combined_rule({"jsd": 0.3, "cosine_similarity": 0.9}, {"jsd_p90": 0.2, "cosine_p10": 0.8,
                                                "jsd_p95": 0, "cosine_p05": 0})[1], SINGLE)
        self.assertEqual(evaluate_combined_rule({"jsd": 0.1, "cosine_similarity": 0.95}, {"jsd_p90": 0.2, "cosine_p10": 0.8,
                                                 "jsd_p95": 0, "cosine_p05": 0})[1], NEITHER)

    # J / S
    def test_raw_metrics_use_shared_calculator_and_ignore_legacy_thresholds(self) -> None:
        self.archive([presentation("2330", 2025, 1), presentation("2330", 2025, 2, seed="other")])
        calculator = load_calculator()
        module = calculator.module
        before = self.service().analyze("2330")
        saved = {name: getattr(module, name) for name in ("JSD_P90", "JSD_P95", "JSD_P99", "COSINE_P05", "COSINE_P10",
                                                          "determine_drift_level") if hasattr(module, name)}
        try:
            for name in saved:
                setattr(module, name, 999.0 if name != "determine_drift_level" else _explode)
            after = self.service().analyze("2330")
        finally:
            for name, value in saved.items():
                setattr(module, name, value)
        self.assertEqual(before, after)
        texts = [module.calculate_jsd, module.calculate_cosine_similarity]
        self.assertTrue(all(callable(item) for item in texts))

    # Golden: identical inputs through teammate's unmodified research code.
    def test_golden_metrics_and_calibration_rule_match_teammate_code(self) -> None:
        from scripts.import_jsd_calibration_profile import build_profile

        vocab = ["wafer", "yield", "demand", "capacity", "pricing", "inventory", "margin", "node", "packaging",
                 "automotive", "smartphone", "server", "memory", "tariff", "currency", "depreciation"]

        def varied(seed: int) -> str:
            words = [vocab[(seed * 7 + i * (seed + 3)) % len(vocab)] for i in range(900)]
            return " ".join(words) + " " + body(f"s{seed}")

        periods = ["2023Q1", "2023Q2", "2023Q3", "2023Q4", "2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2"]
        texts = {period: varied(index) for index, period in enumerate(periods)}
        rows = [{"ticker": "2330", "company": "TSMC", "industry": "semiconductor_foundry", "period": period,
                 "document_type": "full_earnings_transcript", "language": "en_may_include_translation",
                 "text": text, "source_page": "https://investor.example/p", "source_pdf": f"https://investor.example/{period}.pdf",
                 "sha256": f"{index:064x}"} for index, (period, text) in enumerate(sorted(texts.items()))]
        with TeammateCode() as teammate:
            report = teammate.calibrate.analyze(rows, "2025Q1", "2025Q2", min_pairs=5)
            direct = (round(teammate.data_shift.calculate_jsd(texts["2025Q1"], texts["2025Q2"]), 6),
                      round(teammate.data_shift.calculate_cosine_similarity(texts["2025Q1"], texts["2025Q2"]), 6))
        self.assertIsNotNone(report["calibration"]["thresholds"])
        imported = build_profile(report, source_family="fixture", extraction_method="fixture-extraction",
                                 preprocessing_version="fixture-v1", source_research_commit=SOURCE_RESEARCH_COMMIT,
                                 module_sha256=load_calculator().module_sha256)
        self.save(imported)
        result = JsdBridgeService(None, JsonJsdCalibrationRepository(self.profiles)).evaluate_pair(
            ticker="2330", company="TSMC", industry="semiconductor_foundry",
            first={"period": "2025Q1", "text": texts["2025Q1"]}, second={"period": "2025Q2", "text": texts["2025Q2"]},
            document_type="full_earnings_transcript", language="en_may_include_translation",
            identity={"source_family": "fixture", "extraction_method": "fixture-extraction", "preprocessing_version": "fixture-v1"},
            source_documents=[])
        self.assertEqual((result["metrics"]["jsd"], result["metrics"]["cosine_similarity"]), direct)
        self.assertEqual((result["metrics"]["jsd"], result["metrics"]["cosine_similarity"]),
                         (report["target"]["metrics"]["jsd"], report["target"]["metrics"]["cosine_similarity"]))
        self.assertEqual(result["calibration"]["status"], "calibrated")
        self.assertEqual(result["calibration"]["thresholds"], report["calibration"]["thresholds"])
        self.assertEqual(result["combined_rule"], report["combined_rule"])
        self.assertEqual(result["drift_result"], report["drift_result"])

    def test_profile_importer_requires_explicit_scope_and_never_overwrites(self) -> None:
        import sys
        import unittest.mock

        from scripts import import_jsd_calibration_profile as importer

        report = {"ticker": "2330", "company": "TSMC", "industry": "semiconductor_foundry", "period_1": "2025Q3",
                  "period_2": "2025Q4", "created_at": "2026-09-27T00:00:00+00:00",
                  "method": {"version": METHOD_VERSION, "tokenizer": "t", "tfidf": "t", "jsd_log_base": 2,
                             "comparison": "c", "min_history_pairs": 30},
                  "calibration": {"history_pair_count": 33, "history_pairs": [{"period_1": "2025Q1", "period_2": "2025Q2"}],
                                  "thresholds": {"jsd_p90": 0.2, "jsd_p95": 0.26, "cosine_p10": 0.85, "cosine_p05": 0.72}},
                  "combined_rule": {"rule": "JSD >= historical P90 AND Cosine <= historical P10"}, "warnings": [],
                  "source_documents": [
                      {"period": "2025Q3", "document_type": "full_earnings_transcript", "language": "en", "sha256": "a" * 64},
                      {"period": "2025Q4", "document_type": "full_earnings_transcript", "language": "en", "sha256": "b" * 64}]}
        mixed = json.loads(json.dumps(report))
        mixed["source_documents"][1]["language"] = "zh-Hant"
        with self.assertRaises(importer.ImportRejected):
            importer.build_profile(mixed, source_family="f", extraction_method="e", preprocessing_version="p",
                                   source_research_commit=SOURCE_RESEARCH_COMMIT, module_sha256="c" * 64)
        missing = {key: value for key, value in report.items() if key != "industry"}
        with self.assertRaises(importer.ImportRejected):
            importer.build_profile(missing, source_family="f", extraction_method="e", preprocessing_version="p",
                                   source_research_commit=SOURCE_RESEARCH_COMMIT, module_sha256="c" * 64)
        report_path = Path(self.tmp.name) / "report.json"
        module = Path(self.tmp.name) / "data_shift.py"
        module.write_text("x = 1\n", encoding="utf-8")

        def run(data: dict) -> int:
            report_path.write_text(json.dumps(data), encoding="utf-8")
            argv = ["import", "--report", str(report_path), "--source-family", "f", "--extraction-method", "e",
                    "--preprocessing-version", "p", "--source-research-commit", SOURCE_RESEARCH_COMMIT,
                    "--method-module", str(module), "--output-dir", str(self.profiles), "--write-json"]
            with unittest.mock.patch.object(sys, "argv", argv):
                return importer.main()

        self.assertEqual(run(report), 0)
        self.assertEqual(run(report), 0)  # idempotent
        changed = json.loads(json.dumps(report))
        changed["calibration"]["thresholds"]["jsd_p90"] = 0.5
        before = sorted(path.read_text(encoding="utf-8") for path in self.profiles.glob("*.json"))
        self.assertEqual(run(changed), 2)  # same id, different thresholds → conflict
        self.assertEqual(sorted(path.read_text(encoding="utf-8") for path in self.profiles.glob("*.json")), before)

    def test_missing_or_changed_method_module_fails_closed(self) -> None:
        from app.services.jsd_method import MethodUnavailable, load_calculator as real_loader

        self.archive([presentation("2330", 2025, 1), presentation("2330", 2025, 2, seed="other")])

        def unavailable():
            raise MethodUnavailable("data_shift.py (JSD method module) was not found")

        result = JsdBridgeService(FileConferencePdfArchiveRepository(self.root), JsonJsdCalibrationRepository(self.profiles),
                                  calculator_loader=unavailable).analyze("2330")
        self.assertEqual((result["analysis_status"], result["metrics"], result["drift_result"]),
                         ("method_unavailable", None, UNCALIBRATED_RESULT))
        changed = Path(self.tmp.name) / "data_shift.py"
        changed.write_text("def calculate_jsd(a, b):\n    return 0.0\n", encoding="utf-8")
        with self.assertRaises(MethodUnavailable):
            real_loader(changed)

    # T
    def test_api_contract(self) -> None:
        from app.main import app
        from app.routers.financial import get_jsd_bridge_service

        self.archive([presentation("2330", 2025, 1), presentation("2330", 2025, 2, seed="other")])
        app.dependency_overrides[get_jsd_bridge_service] = self.service
        try:
            client = TestClient(app)
            ok = client.post("/api/v1/financial/data-shift/analyze", json={"company_code": "2330"})
            explicit = client.post("/api/v1/financial/data-shift/analyze",
                                   json={"company_code": "2330", "period_1": "2025Q1", "period_2": "2025Q2"})
            bad_period = client.post("/api/v1/financial/data-shift/analyze", json={"company_code": "2330", "period_1": "25Q1"})
            half = client.post("/api/v1/financial/data-shift/analyze", json={"company_code": "2330", "period_1": "2025Q1"})
            missing = client.post("/api/v1/financial/data-shift/analyze", json={})
        finally:
            app.dependency_overrides.pop(get_jsd_bridge_service, None)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json(), explicit.json())
        for key in ("ticker", "period_1", "period_2", "document_type", "language", "analysis_status", "metrics",
                    "data_quality", "calibration", "combined_rule", "drift_result", "source_documents", "method",
                    "limitations", "warning"):
            self.assertIn(key, ok.json())
        self.assertEqual((bad_period.status_code, half.status_code, missing.status_code), (422, 422, 422))


def _explode(*args, **kwargs):
    raise AssertionError("legacy determine_drift_level must not be called by the official bridge")


if __name__ == "__main__":
    unittest.main()
