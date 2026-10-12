"""Offline synthetic tests for NFM staging; no live data or writes to databases."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.services.integrity.nfm_candidate_extraction import scan_employee_candidates
from scripts.scan_nfm_archive import stage

_PDF = b"%PDF-1.4\n" + b"synthetic archive bytes" * 10 + b"\n%%EOF"


class NfmCandidateTests(unittest.TestCase):
    def test_chinese_count_has_verbatim_page_but_is_unverified(self):
        rows = [{"page_number": 12, "text": "2025 年員工總人數：1,234 人\n其他內容"}]
        result = scan_employee_candidates(
            rows, ticker="2454", expected_fiscal_year=2025, source_sha256="a" * 64
        )
        self.assertEqual(result["candidate_count"], 1)
        hit = result["candidates"][0]
        self.assertEqual((hit["candidate_value"], hit["page_number"]), ("1234", 12))
        self.assertEqual(hit["year_mentions_in_excerpt"], [2025])
        self.assertFalse(hit["source_document_verified"])
        self.assertFalse(hit["eligible_as_f4_input"])

    def test_no_year_in_excerpt_does_not_infer_a_year(self):
        result = scan_employee_candidates(
            [{"page_number": 1, "text": "Number of employees: 12,456"}],
            ticker="2454", expected_fiscal_year=2025, source_sha256="a" * 64,
        )
        self.assertEqual(result["candidates"][0]["year_mentions_in_excerpt"], [])
        self.assertFalse(result["candidates"][0]["eligible_as_f4_input"])

    def test_does_not_match_arbitrary_financial_number(self):
        result = scan_employee_candidates(
            [{"page_number": 1, "text": "營業收入：1,234 百萬元\n"},
             {"page_number": 2, "text": "Number of stores: 37"}],
            ticker="2454", expected_fiscal_year=2025, source_sha256="b" * 64,
        )
        self.assertEqual(result["candidate_count"], 0)

    def test_rejects_duplicate_page_and_malformed_values(self):
        result = scan_employee_candidates(
            [{"page": 1, "text": "員工人數：1,234 人"},
             {"page": 1, "text": "員工人數：8,888 人"},
             {"page": 2, "text": "員工人數：1,23 人"}],
            ticker="2454", expected_fiscal_year=2025, source_sha256="a" * 64,
        )
        self.assertEqual(result["candidate_count"], 1)
        self.assertIn("duplicate_page_number", [r["reason"] for r in result["rejected"]])
        self.assertIn("invalid_digit_grouping", [r["reason"] for r in result["rejected"]])

    def test_rejects_invalid_company_digest_and_oversized_page_list(self):
        with self.assertRaises(ValueError):
            scan_employee_candidates([], ticker="bad", expected_fiscal_year=2025, source_sha256="a" * 64)
        with self.assertRaises(ValueError):
            scan_employee_candidates([], ticker="2454", expected_fiscal_year=2025, source_sha256="bad")


class ArchiveStagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "sample.pdf").write_bytes(_PDF)
        self.pdf_sha = hashlib.sha256(_PDF).hexdigest()
        self.json_bytes = json.dumps({
            "pages": [{"page_number": 2, "text": "2024 年員工人數 135 人"}]
        }, ensure_ascii=False).encode("utf-8")
        (self.root / "sample.pages.json").write_bytes(self.json_bytes)
        self.pages_sha = hashlib.sha256(self.json_bytes).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def run_stage(self, **kwargs):
        request = {
            "pdf_name": "sample.pdf", "pdf_sha256": self.pdf_sha,
            "pages_name": "sample.pages.json", "pages_sha256": self.pages_sha,
            "ticker": "2454", "fiscal_year": 2024,
        }
        request.update(kwargs)
        return stage(self.root, **request)

    def test_two_hashes_qualify_archive_but_not_f4(self):
        result = self.run_stage()
        self.assertEqual(result["status"], "review_candidates_only")
        self.assertEqual(result["candidate_count"], 1)
        self.assertTrue(result["pdf_bytes_match"])
        self.assertTrue(result["pages_json_bytes_match"])
        self.assertFalse(result["official_issuer_and_publication_verified"])
        self.assertFalse(result["eligible_as_f4_input"])

    def test_digest_mismatch_stops_extraction(self):
        self.assertEqual(self.run_stage(pages_sha256="f" * 64)["reason"], "pages_digest_mismatch")
        self.assertEqual(self.run_stage(pdf_sha256="e" * 64)["reason"], "digest_mismatch")

    def test_path_escape_is_refused(self):
        with self.assertRaises(ValueError):
            self.run_stage(pages_name="../sample.pages.json")


if __name__ == "__main__":
    unittest.main()
