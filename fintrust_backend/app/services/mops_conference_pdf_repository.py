from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class ConferencePdfArchiveRepository(Protocol):
    backend_name: str

    def available_years(self, ticker: str) -> list[int]: ...
    def latest_manifest(self, ticker: str, year: int) -> dict[str, Any] | None: ...
    def document(self, ticker: str, year: int, filename: str) -> dict[str, Any] | None: ...
    def pages(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]: ...
    def analysis(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]: ...
    def semantic(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]: ...


class FileConferencePdfArchiveRepository:
    backend_name = "file"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _manifest_path(self, ticker: str, year: int) -> Path:
        return self.root / ticker / str(year) / "manifest.json"

    @staticmethod
    def _read_json(path: Path, default):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def available_years(self, ticker: str) -> list[int]:
        """Announcement years that have an archived manifest for this company, newest first."""
        company = self.root / ticker
        if not company.is_dir():
            return []
        years = [int(item.name) for item in company.iterdir() if item.name.isdigit() and (item / "manifest.json").is_file()]
        return sorted(years, reverse=True)

    def latest_manifest(self, ticker: str, year: int) -> dict[str, Any] | None:
        path = self._manifest_path(ticker, year)
        if not path.is_file():
            return None
        manifest = self._read_json(path, None)
        if isinstance(manifest, dict):
            manifest["storage_contract"] = {
                "backend": self.backend_name,
                "durability": "local_file_archive_only",
                "is_durable": False,
                "survives_container_replacement": False,
                "warning": "Local file archive is for development and verification only; Cloud Run instance or container replacement can discard it, so it must not be treated as durable production evidence.",
                "cloud_ready_contract": "Store PDFs and page artifacts in durable object storage, persist manifest metadata in Firestore, and keep paths as replaceable storage URIs.",
            }
            return manifest
        return None

    def document(self, ticker: str, year: int, filename: str) -> dict[str, Any] | None:
        manifest = self.latest_manifest(ticker, year)
        if manifest is None:
            return None
        for document in manifest.get("documents", []):
            if document.get("filename") == filename:
                return document
        return None

    def pages(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]:
        document = self.document(ticker, year, filename)
        if not document or not document.get("pages_path"):
            return []
        pages = self._read_json(Path(str(document["pages_path"])), [])
        return pages if isinstance(pages, list) else []

    def analysis(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]:
        document = self.document(ticker, year, filename)
        if not document or not document.get("analysis_path"):
            return []
        analysis = self._read_json(Path(str(document["analysis_path"])), [])
        return analysis if isinstance(analysis, list) else []

    def semantic(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]:
        document = self.document(ticker, year, filename)
        if not document:
            return []
        if document.get("semantic_path"):
            semantic = self._read_json(Path(str(document["semantic_path"])), [])
            return semantic if isinstance(semantic, list) else []
        return [
            item
            for page in self.pages(ticker, year, filename)
            for item in page.get("semantic_evidence", [])
        ]


def build_conference_pdf_archive_repository() -> ConferencePdfArchiveRepository:
    backend = os.getenv("CONFERENCE_PDF_ARCHIVE_BACKEND", "file").strip().lower()
    if backend != "file":
        raise ValueError(f"Unsupported CONFERENCE_PDF_ARCHIVE_BACKEND: {backend}")
    root = os.getenv("CONFERENCE_PDF_ARCHIVE_ROOT", "./data/official-ir-pdfs")
    return FileConferencePdfArchiveRepository(root)
