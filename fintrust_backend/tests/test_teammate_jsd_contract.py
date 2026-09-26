"""Ephemeral compatibility tests against the teammate's UNMODIFIED JSD research code.

The teammate files are read with ``git show`` from the research branch into a
temporary directory for the duration of the test only; nothing is copied into
this repository. The tests skip when the ref or its dependencies are missing.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from app.services.conference_jsd_corpus_adapter import build_records, export_corpus
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
from tests.test_conference_jsd_adapter import deck, write_archive

TEAMMATE_REF = "origin/feature/tsmc-quarterly-corpus"
REPO_ROOT = Path(__file__).resolve().parents[2]
LONG = " ".join(f"Management discussed demand trend {i} for advanced nodes and packaging." for i in range(160))


def _git_show(path: str) -> str | None:
    try:
        result = subprocess.run(["git", "show", f"{TEAMMATE_REF}:{path}"], cwd=REPO_ROOT, capture_output=True,
                                timeout=30)
    except Exception:
        return None
    return result.stdout.decode("utf-8") if result.returncode == 0 else None


class TeammateCode:
    """Loads teammate modules from a throwaway directory with the original layout."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        data_shift = _git_show("data_shift.py")
        calibrate = _git_show("scripts/calibrate_tsmc_shift.py")
        if not data_shift or not calibrate:
            self.tmp.cleanup()
            raise unittest.SkipTest(f"{TEAMMATE_REF} is not available locally")
        (root / "scripts").mkdir()
        (root / "data_shift.py").write_text(data_shift, encoding="utf-8")
        (root / "scripts" / "calibrate_tsmc_shift.py").write_text(calibrate, encoding="utf-8")
        self.saved = sys.modules.pop("data_shift", None)
        sys.path.insert(0, str(root))
        try:
            self.data_shift = self._load("data_shift", root / "data_shift.py")
            self.calibrate = self._load("teammate_calibrate_tsmc_shift", root / "scripts" / "calibrate_tsmc_shift.py")
        except ImportError as exc:
            self.__exit__(None, None, None)
            raise unittest.SkipTest(f"teammate dependencies missing: {exc}")
        return self

    @staticmethod
    def _load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def __exit__(self, *exc):
        sys.path[:] = [item for item in sys.path if item != self.tmp.name]
        sys.modules.pop("teammate_calibrate_tsmc_shift", None)
        sys.modules.pop("data_shift", None)
        if self.saved is not None:
            sys.modules["data_shift"] = self.saved
        self.tmp.cleanup()
        return False


class TeammateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # S
    def test_adapter_pair_runs_through_unmodified_analyze_data_shift(self) -> None:
        write_archive(self.root, "2330", 2025, [
            {"filename": "233020250417E001.pdf", "pages": deck("2025 First Quarter Earnings Conference", LONG)},
            {"filename": "233020250717E001.pdf",
             "pages": deck("2025 Second Quarter Earnings Conference", LONG.replace("advanced", "mature"))}])
        first, second = build_records(FileConferencePdfArchiveRepository(self.root), "2330")
        with TeammateCode() as teammate:
            result = teammate.data_shift.analyze_data_shift(
                first.record["text"], second.record["text"], ticker="2330",
                source_type=first.record["document_type"],
                period_1=first.record["period"], period_2=second.record["period"],
            )
        self.assertIn("data_quality", result)
        self.assertTrue(result["data_quality"]["passed"])
        self.assertIsInstance(result["metrics"]["jsd"], float)
        self.assertIsInstance(result["metrics"]["cosine_similarity"], float)

    # T
    def test_exported_corpus_is_readable_by_unmodified_calibration_loader(self) -> None:
        write_archive(self.root, "2454", 2025, [
            {"filename": "245420250201E001.pdf", "pages": deck("MediaTek 4Q24 Earnings Call Transcript", LONG)},
            {"filename": "245420250501E001.pdf", "pages": deck("MediaTek 1Q25 Earnings Call Transcript", LONG)}])
        write_archive(self.root, "2330", 2025, [
            {"filename": "233020250417E001.pdf", "pages": deck("2025 First Quarter Earnings Conference", LONG)}])
        transcripts = build_records(FileConferencePdfArchiveRepository(self.root), "2454")
        presentations = build_records(FileConferencePdfArchiveRepository(self.root), "2330")
        transcript_csv = export_corpus(transcripts, self.root / "t", parquet=False)["csv"]
        presentation_csv = export_corpus(presentations, self.root / "p", parquet=False)["csv"]
        with TeammateCode() as teammate:
            rows = teammate.calibrate.load(Path(transcript_csv), "2454")
            self.assertEqual([row["period"] for row in rows], ["2024Q4", "2025Q1"])
            with self.assertRaisesRegex(ValueError, "No full earnings transcripts"):
                teammate.calibrate.load(Path(presentation_csv), "2330")


if __name__ == "__main__":
    unittest.main()
