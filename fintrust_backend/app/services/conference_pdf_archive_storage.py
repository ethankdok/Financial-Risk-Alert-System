"""Durable object storage for the MOPS conference-PDF archive.

Google Cloud Storage holds the canonical archive package under a deterministic
layout that mirrors the local archive::

    <prefix>/<ticker>/<year>/manifest.json
    <prefix>/<ticker>/<year>/listing-page-<n>.html
    <prefix>/<ticker>/<year>/<stem>.pdf | .txt | .pages.json | .analysis.json | .semantic.json

The manifest stored in GCS is *portable*: its per-document ``*_path`` fields are
archive-relative object names, never local filesystem paths. Artifacts are
resolved by archive identity (ticker, year, filename), so the same repository
contract works locally and in Cloud Run. Authentication uses Application
Default Credentials or the Cloud Run service identity; no key file is used.

Publishing is copy-only and idempotent: an object with the same SHA-256 is
skipped, a different existing object is a conflict unless overwrite is
explicitly requested, and new objects are created with a create-only
precondition so concurrent writers cannot silently replace each other.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)

DEFAULT_PREFIX = "conference-pdf-archive"
DOCUMENT_ARTIFACTS = (
    ("pdf", ".pdf", "application/pdf"),
    ("text", ".txt", "text/plain; charset=utf-8"),
    ("pages", ".pages.json", "application/json"),
    ("analysis", ".analysis.json", "application/json"),
    ("semantic", ".semantic.json", "application/json"),
)
PATH_FIELDS = {
    "pdf_path": ".pdf", "text_path": ".txt", "pages_path": ".pages.json",
    "analysis_path": ".analysis.json", "semantic_path": ".semantic.json",
}
PIPELINE_NAME = "mops_conference_pdf_pipeline"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _segment(value: Any) -> str:
    text = str(value)
    if not _SAFE_SEGMENT.fullmatch(text) or text in {".", ".."}:
        raise ValueError("Unsafe archive path segment")
    return text


def portable_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Replace local artifact paths with archive-relative names."""
    portable = json.loads(json.dumps(manifest))
    portable.pop("storage_contract", None)
    portable.pop("manifest_path", None)
    for document in portable.get("documents", []):
        stem = str(document.get("filename", "")).removesuffix(".pdf")
        for key, suffix in PATH_FIELDS.items():
            if key in document:
                document[key] = f"{stem}{suffix}"
    return portable


def manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")


# --- repository ---------------------------------------------------------------------------


def _is_not_found(exc: Exception) -> bool:
    return type(exc).__name__ == "NotFound" or getattr(exc, "code", None) == 404


class _TtlCache:
    def __init__(self, seconds: float, max_entries: int = 64) -> None:
        self.seconds, self.max_entries = seconds, max_entries
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            item = self._data.get(key)
            if item and time.monotonic() - item[0] < self.seconds:
                return item[1]
            self._data.pop(key, None)
            return None

    def put(self, key: str, value: Any) -> None:
        if self.seconds <= 0:
            return
        with self._lock:
            if len(self._data) >= self.max_entries:
                self._data.pop(next(iter(self._data)))
            self._data[key] = (time.monotonic(), value)


_SHARED_CACHES: dict[float, _TtlCache] = {}
_SHARED_CACHES_LOCK = threading.Lock()


def shared_cache(seconds: float = 300.0) -> _TtlCache:
    """Process-wide read cache (repositories are built per request)."""
    with _SHARED_CACHES_LOCK:
        return _SHARED_CACHES.setdefault(float(seconds), _TtlCache(seconds=float(seconds)))


class GcsConferencePdfArchiveRepository:
    """ConferencePdfArchiveRepository backed by Google Cloud Storage (read path)."""

    backend_name = "gcs"

    def __init__(self, bucket: str, prefix: str = DEFAULT_PREFIX, *, client: Any | None = None,
                 project: str | None = None, timeout_seconds: float = 15.0,
                 cache: _TtlCache | None = None) -> None:
        if not bucket:
            raise ValueError("A GCS bucket is required for the gcs conference archive backend")
        self.bucket_name = bucket
        self.prefix = prefix.strip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client
        self._project = project
        self._cache = cache if cache is not None else shared_cache()
        self._manifests: dict[tuple[str, int], dict[str, Any] | None] = {}

    def _get_client(self) -> Any:
        if self._client is None:
            from google.cloud import storage

            self._client = storage.Client(project=self._project) if self._project else storage.Client()
        return self._client

    def _object_name(self, ticker: str, year: int, name: str) -> str:
        return "/".join(filter(None, [self.prefix, _segment(ticker), _segment(year), _segment(name)]))

    def _read_json(self, object_name: str, default: Any) -> Any:
        cached = self._cache.get(f"{self.bucket_name}/{object_name}")
        if cached is not None:
            return cached
        try:
            blob = self._get_client().bucket(self.bucket_name).blob(object_name)
            payload = json.loads(blob.download_as_bytes(timeout=self.timeout_seconds).decode("utf-8"))
        except Exception as exc:  # missing object, permission, network, bad JSON
            if not _is_not_found(exc):
                logger.warning("conference archive read failed: %s", type(exc).__name__)
            return default
        self._cache.put(f"{self.bucket_name}/{object_name}", payload)
        return payload

    def available_years(self, ticker: str) -> list[int]:
        prefix = "/".join(filter(None, [self.prefix, _segment(ticker)])) + "/"
        try:
            iterator = self._get_client().list_blobs(self.bucket_name, prefix=prefix, delimiter="/",
                                                     timeout=self.timeout_seconds)
            for _ in iterator:  # prefixes are populated while pages are consumed
                pass
            prefixes = list(getattr(iterator, "prefixes", []) or [])
        except Exception as exc:
            logger.warning("conference archive listing failed: %s", type(exc).__name__)
            return []
        years = []
        for item in prefixes:
            segment = item[len(prefix):].strip("/")
            if segment.isdigit():
                years.append(int(segment))
        return sorted(years, reverse=True)

    def latest_manifest(self, ticker: str, year: int) -> dict[str, Any] | None:
        key = (ticker, int(year))
        if key not in self._manifests:
            manifest = self._read_json(self._object_name(ticker, year, "manifest.json"), None)
            self._manifests[key] = manifest if isinstance(manifest, dict) else None
        manifest = self._manifests[key]
        if manifest is None:
            return None
        result = json.loads(json.dumps(manifest))
        result["storage_contract"] = {
            "backend": self.backend_name,
            "durability": "object_storage",
            "is_durable": True,
            "survives_container_replacement": True,
            "layout": "<prefix>/<ticker>/<year>/<artifact>",
        }
        return result

    def document(self, ticker: str, year: int, filename: str) -> dict[str, Any] | None:
        manifest = self.latest_manifest(ticker, year)
        if manifest is None:
            return None
        return next((doc for doc in manifest.get("documents", []) if doc.get("filename") == filename), None)

    def _artifact(self, ticker: str, year: int, filename: str, suffix: str) -> list[dict[str, Any]]:
        if self.document(ticker, year, filename) is None:
            return []
        payload = self._read_json(self._object_name(ticker, year, filename.removesuffix(".pdf") + suffix), [])
        # Callers get their own copy so the shared read cache cannot be mutated.
        return copy.deepcopy(payload) if isinstance(payload, list) else []

    def pages(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]:
        return self._artifact(ticker, year, filename, ".pages.json")

    def analysis(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]:
        return self._artifact(ticker, year, filename, ".analysis.json")

    def semantic(self, ticker: str, year: int, filename: str) -> list[dict[str, Any]]:
        return self._artifact(ticker, year, filename, ".semantic.json")


# --- archive package / publishing ----------------------------------------------------------------


@dataclass
class ArchiveArtifact:
    name: str
    artifact_type: str
    content_type: str
    loader: Callable[[], bytes]
    source_filename: str | None = None
    _data: bytes | None = field(default=None, repr=False)

    @property
    def data(self) -> bytes:
        if self._data is None:
            self._data = self.loader()
        return self._data


def plan_archive_package(directory: Path, *, include_review_images: bool = False) -> tuple[dict[str, Any], list[ArchiveArtifact]]:
    """Canonical artifacts of one local <ticker>/<year> archive directory.

    Raises ValueError when a PDF no longer matches the SHA-256 recorded in the
    manifest, so a corrupted local archive is never published.
    """
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    portable = portable_manifest(manifest)
    artifacts = [ArchiveArtifact("manifest.json", "manifest", "application/json",
                                 lambda: manifest_bytes(portable))]
    for listing in sorted(directory.glob("listing-page-*.html")):
        artifacts.append(ArchiveArtifact(listing.name, "listing_snapshot", "text/html; charset=utf-8",
                                         listing.read_bytes))
    for document in manifest.get("documents", []):
        if "sha256" not in document:
            continue
        filename = _segment(document["filename"])
        stem = filename.removesuffix(".pdf")
        for artifact_type, suffix, content_type in DOCUMENT_ARTIFACTS:
            path = directory / f"{stem}{suffix}"
            if not path.is_file():
                continue
            artifact = ArchiveArtifact(path.name, artifact_type, content_type, path.read_bytes, filename)
            if artifact_type == "pdf" and _sha256(artifact.data) != document["sha256"]:
                raise ValueError(f"PDF does not match the manifest SHA-256: {filename}")
            artifacts.append(artifact)
        if include_review_images:
            for image in sorted((directory / f"{stem}-review").glob("page-*.png")):
                artifacts.append(ArchiveArtifact(f"{stem}-review/{image.name}", "review_image", "image/png",
                                                 image.read_bytes, filename))
    return portable, artifacts


def _blob_sha256(blob: Any, timeout: float) -> str:
    metadata = getattr(blob, "metadata", None) or {}
    if metadata.get("sha256"):
        return metadata["sha256"]
    return _sha256(blob.download_as_bytes(timeout=timeout))


def publish_archive(
    *,
    client: Any,
    bucket: str,
    prefix: str,
    ticker: str,
    year: int,
    directory: Path,
    execute: bool = False,
    overwrite: bool = False,
    include_review_images: bool = False,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Copy one archive package to GCS. Dry-run unless execute=True."""
    portable, artifacts = plan_archive_package(directory, include_review_images=include_review_images)
    base = "/".join(filter(None, [prefix.strip("/"), _segment(ticker), _segment(year)]))
    bucket_ref = client.bucket(bucket)
    report: dict[str, Any] = {
        "ticker": ticker, "year": year, "bucket": bucket, "prefix": base, "mode": "execute" if execute else "dry_run",
        "planned": 0, "planned_bytes": 0, "uploaded": 0, "uploaded_bytes": 0, "skipped_same_sha256": 0,
        "conflicts": [], "overwritten": [], "errors": [], "objects": [],
    }
    for artifact in artifacts:
        object_name = f"{base}/{artifact.name}"
        data = artifact.data
        digest = _sha256(data)
        report["planned"] += 1
        report["planned_bytes"] += len(data)
        entry = {"object": object_name, "type": artifact.artifact_type, "bytes": len(data), "sha256": digest}
        try:
            existing = bucket_ref.get_blob(object_name, timeout=timeout_seconds)
        except Exception as exc:
            if not _is_not_found(exc):
                report["errors"].append({"object": object_name, "error": type(exc).__name__})
                entry["action"] = "error"
                report["objects"].append(entry)
                continue
            existing = None
        if existing is not None:
            try:
                same = _blob_sha256(existing, timeout_seconds) == digest
            except Exception as exc:
                report["errors"].append({"object": object_name, "error": type(exc).__name__})
                entry["action"] = "error"
                report["objects"].append(entry)
                continue
            if same:
                report["skipped_same_sha256"] += 1
                entry["action"] = "skip_same_sha256"
                report["objects"].append(entry)
                continue
            if not overwrite:
                report["conflicts"].append(object_name)
                entry["action"] = "conflict"
                report["objects"].append(entry)
                continue
        entry["action"] = ("overwrite" if existing is not None else "upload") + ("" if execute else "_planned")
        report["objects"].append(entry)
        if not execute:
            continue
        blob = bucket_ref.blob(object_name)
        blob.metadata = {
            "ticker": ticker, "year": str(year), "artifact_type": artifact.artifact_type, "sha256": digest,
            "source_filename": artifact.source_filename or artifact.name,
            "ingested_at": str(portable.get("retrieved_at") or ""), "pipeline": PIPELINE_NAME,
        }
        try:
            blob.upload_from_string(
                data, content_type=artifact.content_type, timeout=timeout_seconds,
                if_generation_match=existing.generation if existing is not None else 0,
            )
        except Exception as exc:
            report["errors"].append({"object": object_name, "error": type(exc).__name__})
            entry["action"] = "error"
            continue
        report["uploaded"] += 1
        report["uploaded_bytes"] += len(data)
        if existing is not None:
            report["overwritten"].append(object_name)
    report["status"] = "failed" if report["errors"] or report["conflicts"] else "ok"
    return report


def verify_archive(*, client: Any, bucket: str, prefix: str, ticker: str, year: int, directory: Path,
                   include_review_images: bool = False, timeout_seconds: float = 60.0) -> dict[str, Any]:
    """Check every expected object exists with the same size and SHA-256, and manifest references resolve."""
    portable, artifacts = plan_archive_package(directory, include_review_images=include_review_images)
    base = "/".join(filter(None, [prefix.strip("/"), _segment(ticker), _segment(year)]))
    bucket_ref = client.bucket(bucket)
    report: dict[str, Any] = {"expected": len(artifacts), "verified": 0, "missing": [], "size_mismatch": [],
                              "sha256_mismatch": [], "errors": [], "unresolved_manifest_references": []}
    present = set()
    for artifact in artifacts:
        object_name = f"{base}/{artifact.name}"
        try:
            blob = bucket_ref.get_blob(object_name, timeout=timeout_seconds)
            if blob is None:
                report["missing"].append(object_name)
                continue
            remote = blob.download_as_bytes(timeout=timeout_seconds)
        except Exception as exc:
            if _is_not_found(exc):
                report["missing"].append(object_name)
            else:
                report["errors"].append({"object": object_name, "error": type(exc).__name__})
            continue
        if blob.size is not None and int(blob.size) != len(artifact.data):
            report["size_mismatch"].append(object_name)
        elif _sha256(remote) != _sha256(artifact.data):
            report["sha256_mismatch"].append(object_name)
        else:
            report["verified"] += 1
            present.add(artifact.name)
    for document in portable.get("documents", []):
        for key in PATH_FIELDS:
            if key in document and document[key] not in present:
                report["unresolved_manifest_references"].append(f"{document.get('filename')}:{key}")
    report["status"] = "ok" if report["verified"] == report["expected"] and not report[
        "unresolved_manifest_references"] else "failed"
    return report


def publish_after_ingestion(result: dict[str, Any], directory: Path, *, client: Any | None = None,
                            environ: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Opt-in write-through after a finished local ingestion.

    Enabled by CONFERENCE_PDF_ARCHIVE_PUBLISH=true with CONFERENCE_PDF_ARCHIVE_GCS_BUCKET.
    Only a complete archive package is copied (every listed PDF downloaded, no
    acquisition errors); strict visual-review status does not block archiving.
    Storage problems are reported, never raised, so local processing is unaffected.
    """
    import os

    env = environ if environ is not None else os.environ
    if str(env.get("CONFERENCE_PDF_ARCHIVE_PUBLISH", "")).strip().lower() not in {"1", "true", "yes"}:
        return None
    bucket = str(env.get("CONFERENCE_PDF_ARCHIVE_GCS_BUCKET", "")).strip()
    if not bucket:
        return {"status": "failed", "error_type": "BucketNotConfigured"}
    expected = int(result.get("expected_pdfs") or 0)
    if not expected or result.get("downloaded_pdfs") != expected or result.get("errors"):
        return {"status": "skipped", "reason": "archive_incomplete"}
    try:
        report = publish_archive(
            client=client or storage_client(str(env.get("GOOGLE_CLOUD_PROJECT", "")).strip() or None),
            bucket=bucket,
            prefix=str(env.get("CONFERENCE_PDF_ARCHIVE_GCS_PREFIX", "")).strip() or DEFAULT_PREFIX,
            ticker=str(result["ticker"]), year=int(result["year"]), directory=directory, execute=True,
        )
    except Exception as exc:
        logger.warning("conference archive publish failed: %s", type(exc).__name__)
        return {"status": "failed", "error_type": type(exc).__name__}
    return {
        "status": report["status"], "uploaded": report["uploaded"],
        "skipped_same_sha256": report["skipped_same_sha256"], "conflicts": len(report["conflicts"]),
        "errors": len(report["errors"]),
    }


def storage_client(project: str | None = None) -> Any:
    from google.cloud import storage

    return storage.Client(project=project) if project else storage.Client()


def summarize_objects(report: dict[str, Any]) -> Iterable[str]:
    for entry in report.get("objects", []):
        yield f"{entry['action']:>18}  {entry['bytes']:>10,d}  {entry['object']}"
