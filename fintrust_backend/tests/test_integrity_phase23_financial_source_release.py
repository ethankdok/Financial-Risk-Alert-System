"""Synthetic archived iXBRL provenance release tests; no existing SQLite touched."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from app.services.integrity.financial_source_release import (
    VERSION, load_approved_financial_source_release, overlay_approved_revenue,
)
from tests.test_integrity_phase23_nfm_bridge import financial_index

HTML = b"<!doctype html>\n<html><body>synthetic archived annual revenue line</body></html>\n"


class FinancialSourceReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "filing.html").write_bytes(HTML)
        self.sha = hashlib.sha256(HTML).hexdigest()
        self.original_index = financial_index()
        self.source = self.original_index[("revenue", 2024)]
        self.record = {
            "ticker": "2454", "fiscal_year": 2024, "evidence_id": self.source["evidence_id"],
            "filing_version": self.source["filing_version"],
            "source_url": self.source["source_url"], "source_sha256": self.sha,
            "archive_relative_path": "filing.html",
            "value_twd": self.source["value_twd"],
            "published_at": "2025-03-31T13:00:00+08:00",
            "review": {
                "status": "approved", "ticker": "2454", "fiscal_year": 2024,
                "evidence_id": self.source["evidence_id"], "source_sha256": self.sha,
                "review_id": "source-review-1", "verbatim_line": "2024 年營業收入 1000 元",
                "reviewed_value_twd": self.source["value_twd"],
                "reviewed_at": "2026-10-01T12:00:00+08:00",
                "official_download_confirmed": True, "company_identity_confirmed": True,
                "filing_year_confirmed": True, "revenue_statement_line_confirmed": True,
                "consolidated_scope_confirmed": True, "amount_and_unit_confirmed": True,
            },
        }

    def tearDown(self):
        self.temp.cleanup()

    def load(self, row=None):
        payload = {"release_version": VERSION, "records": [row or self.record]}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        path = self.root / "source_release.json"
        path.write_bytes(raw)
        return load_approved_financial_source_release(
            path, approved_manifest_sha256=hashlib.sha256(raw).hexdigest(),
            archive_root=self.root,
        )

    def test_verified_source_overlay_is_readonly_and_value_preserving(self):
        release = self.load()
        rows = deepcopy(self.original_index)
        rows[("revenue", 2024)].pop("source_sha256", None)
        rows[("revenue", 2024)].pop("source_document_verified", None)
        output = overlay_approved_revenue(rows, release["records"], ticker="2454")
        self.assertTrue(output[("revenue", 2024)]["source_document_verified"])
        self.assertEqual(output[("revenue", 2024)]["source_sha256"], self.sha)
        self.assertEqual(output[("revenue", 2024)]["value_twd"], "1000")
        self.assertEqual(rows[("revenue", 2024)]["source_sha256"] if "source_sha256" in rows[("revenue", 2024)] else None, None)
        self.assertFalse(release["independent_third_party_verified"])

    def test_overlay_rejects_any_amount_change(self):
        release = self.load()
        rows = deepcopy(self.original_index)
        rows[("revenue", 2024)]["value_twd"] = "1000.01"
        with self.assertRaises(ValueError):
            overlay_approved_revenue(rows, release["records"], ticker="2454")

    def test_operator_review_is_required(self):
        row = deepcopy(self.record)
        row["review"]["amount_and_unit_confirmed"] = False
        with self.assertRaises(ValueError):
            self.load(row)

    def test_unofficial_or_wrong_company_mops_link_is_rejected(self):
        row = deepcopy(self.record)
        row["source_url"] = "https://mops.twse.com.tw.evil.test/server-java/FileDownLoad"
        with self.assertRaises(ValueError):
            self.load(row)

    def test_corrupted_archived_html_is_rejected(self):
        (self.root / "filing.html").write_bytes(HTML + b"changed")
        with self.assertRaises(ValueError):
            self.load()

    def test_publication_date_without_instant_is_rejected(self):
        row = deepcopy(self.record)
        row["published_at"] = "2025-03-31"
        with self.assertRaises(ValueError):
            self.load(row)


if __name__ == "__main__":
    unittest.main()
