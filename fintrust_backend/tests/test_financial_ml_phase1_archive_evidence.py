"""Offline legal-evidence archive controls. No network or actual PDF needed."""
import json
import tempfile
import unittest
from pathlib import Path

from research.financial_ml.phase1_archive_evidence import stage_evidence


class Phase1EvidenceArchiveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.seed = Path(__file__).resolve().parents[1] / "research" / "financial_ml" / "phase1_case_sources_seed.json"
        self.html = self.root / "local_judgment.html"
        self.html.write_text("<html>fixture for offline source archive</html>", encoding="utf-8")
        self.output = self.root / "archive"

    def test_archive_sha_and_no_label_admission(self):
        result = stage_evidence(self.seed, "judicial_3027_trial_2025",
                                self.html, self.output)
        self.assertEqual(result["status"],
                         "BYTES_ARCHIVED_ORIGINAL_SOURCE_IDENTITY_NOT_VERIFIED")
        self.assertEqual(result["training_label_admitted"], False)
        self.assertEqual(result["independently_verified_original_source"], False)
        self.assertEqual(result["normal_label_created"], False)
        self.assertEqual(result["network_requests"], 0)
        self.assertEqual(stage_evidence(self.seed, "judicial_3027_trial_2025",
                                        self.html, self.output)["archive_sha256"],
                         result["archive_sha256"])
        self.assertTrue(Path(result["local_file"]).is_file())

    def test_archive_never_overwrites_different_evidence(self):
        record = stage_evidence(self.seed, "judicial_3027_trial_2025",
                                self.html, self.output)
        self.html.write_text("different file contents", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "blocked_existing_archive_mismatch"):
            stage_evidence(self.seed, "judicial_3027_trial_2025",
                           self.html, self.output)
        self.assertNotEqual(Path(record["local_file"]).read_text(),
                            self.html.read_text())

    def test_fake_source_secondary_news_or_non_document_blocked(self):
        with self.assertRaisesRegex(ValueError, "source_id_not"):
            stage_evidence(self.seed, "unknown_source", self.html, self.output)
        with self.assertRaisesRegex(ValueError, "secondary_news"):
            stage_evidence(self.seed, "public_8299_2016_press", self.html, self.output)
        executable = self.root / "download.exe"
        executable.write_bytes(b"test")
        with self.assertRaisesRegex(ValueError, "unsupported_evidence_extension"):
            stage_evidence(self.seed, "judicial_3027_trial_2025", executable, self.output)


if __name__ == "__main__":
    unittest.main()
