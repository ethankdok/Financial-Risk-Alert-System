"""NFM approval release test: isolated fake files, no protected SQLite or network."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from app.services.integrity.nfm_reviewed_release import VERSION, load_approved_nfm_release

_PDF = b"%PDF-1.7\n" + b"synthetic reviewed PDF bytes " * 5 + b"\n%%EOF"


class ApprovedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "report.pdf").write_bytes(_PDF)
        self.pdf_sha = hashlib.sha256(_PDF).hexdigest()
        self.entry = {
            "ticker": "2454", "fiscal_year": 2024, "measure": "employees",
            "value": "1234", "unit": "persons", "scope": "consolidated",
            "period_basis": "year_end_stock", "measurement_policy": "year_end_headcount",
            "filing_version_id": "mops:2454:2024:approved",
            "source_url": "https://mops.twse.com.tw/annual/report.pdf",
            "source_sha256": self.pdf_sha, "archive_pdf_relative_path": "report.pdf",
            "published_at": "2025-03-31T09:00:00+08:00",
            "review": {
                "status": "approved", "ticker": "2454", "fiscal_year": 2024,
                "pdf_sha256": self.pdf_sha, "scope": "consolidated",
                "review_id": "review-0001",
                "verbatim": "2024 年員工總人數 1,234 人",
                "reviewed_value": "1234", "reviewed_unit": "persons",
                "pdf_page": 3, "reviewed_at": "2026-10-01T08:00:00+08:00",
                "source_origin_confirmed": True, "pdf_page_quote_confirmed": True,
                "fiscal_period_confirmed": True, "metric_definition_confirmed": True,
                "statement_scope_confirmed": True, "positively_scale_related": True,
            },
        }

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, entry=None):
        manifest = {"release_version": VERSION, "records": [entry or self.entry]}
        path = self.root / "approved.json"
        raw = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        path.write_bytes(raw)
        return load_approved_nfm_release(
            path, approved_manifest_sha256=hashlib.sha256(raw).hexdigest(),
            pdf_archive_root=self.root,
        )

    def test_operator_pinned_approved_release_is_explicitly_not_third_party(self):
        result = self.load()
        self.assertEqual(result["status"], "operator_approved_artifact_release")
        self.assertEqual(len(result["records"]), 1)
        self.assertFalse(result["independent_third_party_verified"])
        self.assertTrue(result["records"][0]["source_document_verified"])

    def test_edited_manifest_without_new_operator_pin_is_refused(self):
        manifest = {"release_version": VERSION, "records": [self.entry]}
        path = self.root / "approved.json"
        original = json.dumps(manifest).encode()
        path.write_bytes(original)
        approved_sha = hashlib.sha256(original).hexdigest()
        path.write_bytes(original + b" ")
        with self.assertRaises(ValueError):
            load_approved_nfm_release(path, approved_manifest_sha256=approved_sha, pdf_archive_root=self.root)

    def test_corrupt_original_pdf_is_refused(self):
        (self.root / "report.pdf").write_bytes(_PDF + b"CHANGED")
        with self.assertRaises(ValueError):
            self.load()

    def test_review_flags_are_not_defaulted_to_approved(self):
        entry = deepcopy(self.entry)
        entry["review"]["source_origin_confirmed"] = False
        with self.assertRaises(ValueError):
            self.load(entry)

    def test_nonofficial_host_does_not_count_as_archive_identity(self):
        entry = deepcopy(self.entry)
        entry["source_url"] = "https://mops.twse.com.tw.evil.test/annual/report.pdf"
        with self.assertRaises(ValueError):
            self.load(entry)

    def test_date_only_is_not_promoted_to_a_publication_instant(self):
        entry = deepcopy(self.entry)
        entry["published_at"] = "2025-03-31"
        with self.assertRaises(ValueError):
            self.load(entry)

    def test_missing_page_quote_does_not_qualify(self):
        entry = deepcopy(self.entry)
        entry["review"]["verbatim"] = ""
        with self.assertRaises(ValueError):
            self.load(entry)


if __name__ == "__main__":
    unittest.main()
