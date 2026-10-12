"""Synthetic temporary-file tests for archive byte checks; never touch protected data."""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
import unittest

from app.services.integrity.official_archive_integrity import verify_pdf_archive

PDF = b"%PDF-1.7\n" + b"synthetic test page data" * 4 + b"\n%%EOF"


class ArchiveIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "one.pdf").write_bytes(PDF)
        self.digest = hashlib.sha256(PDF).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def test_bytes_verified_but_official_identity_still_unknown(self):
        result = verify_pdf_archive(self.root, "one.pdf", expected_sha256=self.digest)
        self.assertEqual(result["status"], "archive_bytes_verified")
        self.assertTrue(result["file_bytes_match"])
        self.assertFalse(result["official_identity_verified"])
        self.assertFalse(result["eligible_as_model_source"])

    def test_rejects_wrong_digest(self):
        result = verify_pdf_archive(self.root, "one.pdf", expected_sha256="a" * 64)
        self.assertEqual(result["reason"], "digest_mismatch")

    def test_rejects_absolute_and_parent_traversal(self):
        for path in ("../one.pdf", "/etc/passwd", "C:\\Users\\test.pdf", "./one.pdf"):
            with self.subTest(path=path):
                self.assertEqual(
                    verify_pdf_archive(self.root, path, expected_sha256=self.digest)["reason"],
                    "invalid_relative_path",
                )

    def test_rejects_file_without_pdf_magic(self):
        (self.root / "not-a-pdf.pdf").write_bytes(b"not actually a PDF" * 3)
        result = verify_pdf_archive(self.root, "not-a-pdf.pdf",
                                    expected_sha256=hashlib.sha256((b"not actually a PDF" * 3)).hexdigest())
        self.assertEqual(result["reason"], "missing_pdf_signature")

    def test_rejects_symlink(self):
        link = self.root / "alias.pdf"
        try:
            link.symlink_to(self.root / "one.pdf")
        except (OSError, NotImplementedError):
            self.skipTest("OS does not permit symlinks for the current user")
        self.assertEqual(
            verify_pdf_archive(self.root, "alias.pdf", expected_sha256=self.digest)["reason"],
            "symlink_not_allowed",
        )


if __name__ == "__main__":
    unittest.main()
