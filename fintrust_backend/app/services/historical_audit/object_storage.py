"""Content-addressed, immutable object storage for historical research evidence.

Object names are ``<prefix>/<namespace>/<ticker>/sha256/<aa>/<sha256>.<ext>``:
identical bytes always map to one object (no duplicate storage), and an object
is never replaced. Writes are create-only (GCS ``if_generation_match=0``, local
``O_EXCL``); an existing object with the same SHA-256 is ``exists_same`` and a
different one is a ``conflict``. Reads re-hash the bytes. Principles follow
``conference_pdf_archive_storage`` (SHA-256 metadata, create-only preconditions,
ADC, dry-run by default) and reuse its helpers.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from app.services.conference_pdf_archive_storage import _is_not_found, _sha256
from app.services.historical_audit.cloud_config import NAMESPACES


_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EXTENSIONS = {"xml", "html", "pdf", "xls", "zip", "json", "csv", "bin"}
TRANSIENT_ERRORS = ("ServiceUnavailable", "TooManyRequests", "InternalServerError", "GatewayTimeout",
                    "DeadlineExceeded", "ConnectionError", "Timeout", "TransportError")


class ObjectIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class PutResult:
    object_name: str
    status: str  # created | exists_same | conflict | error | planned
    sha256: str
    size: int
    error: str | None = None


def object_name(namespace: str, ticker: str, sha256: str, extension: str, *, prefix: str = "") -> str:
    if namespace not in NAMESPACES:
        raise ValueError(f"Unknown namespace {namespace}")
    if not _SAFE.fullmatch(ticker) or not _HEX64.fullmatch(sha256) or extension not in _EXTENSIONS:
        raise ValueError("Unsafe object name component")
    parts = [prefix.strip("/"), NAMESPACES[namespace], ticker, "sha256", sha256[:2], f"{sha256}.{extension}"]
    return "/".join(part for part in parts if part)


def package_object_name(ticker: str, content_digest: str, *, prefix: str = "") -> str:
    return object_name("research_packages", ticker, content_digest, "zip", prefix=prefix)


class ObjectStore(Protocol):
    backend_name: str

    def put_if_absent(self, name: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> PutResult: ...
    def stat(self, name: str) -> dict[str, Any] | None: ...
    def get_verified(self, name: str, expected_sha256: str) -> bytes: ...


def _with_retries(operation: Callable[[], Any], *, attempts: int, backoff: float, sleep=time.sleep) -> Any:
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            transient = any(marker in type(exc).__name__ for marker in TRANSIENT_ERRORS)
            if not transient or attempt == attempts:
                raise
            sleep(min(30.0, backoff * 2 ** (attempt - 1)))
    raise AssertionError("unreachable")


class LocalObjectStore:
    """Filesystem implementation with the same create-only contract (tests, offline mirrors)."""

    backend_name = "local"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _path(self, name: str) -> Path:
        path = (self.root / name).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Object name escapes the store root")
        return path

    def put_if_absent(self, name: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> PutResult:
        digest = _sha256(data)
        path = self._path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
        except FileExistsError:
            existing = path.read_bytes()
            status = "exists_same" if _sha256(existing) == digest else "conflict"
            return PutResult(name, status, digest, len(data))
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        return PutResult(name, "created", digest, len(data))

    def stat(self, name: str) -> dict[str, Any] | None:
        path = self._path(name)
        if not path.is_file():
            return None
        data = path.read_bytes()
        return {"size": len(data), "sha256": _sha256(data)}

    def get_verified(self, name: str, expected_sha256: str) -> bytes:
        path = self._path(name)
        data = path.read_bytes()
        if _sha256(data) != expected_sha256:
            raise ObjectIntegrityError(f"SHA-256 mismatch for {name}")
        return data


class GcsObjectStore:
    """Google Cloud Storage implementation; the client is injected or built via ADC by the caller."""

    backend_name = "gcs"

    def __init__(self, client: Any, bucket: str, *, timeout_seconds: float = 60.0, attempts: int = 3,
                 backoff_seconds: float = 1.0, sleep=time.sleep) -> None:
        if not bucket:
            raise ValueError("A bucket is required")
        self.client = client
        self.bucket_name = bucket
        self.timeout = timeout_seconds
        self.attempts = attempts
        self.backoff = backoff_seconds
        self.sleep = sleep

    def _bucket(self):
        return self.client.bucket(self.bucket_name)

    def _retry(self, operation):
        return _with_retries(operation, attempts=self.attempts, backoff=self.backoff, sleep=self.sleep)

    def stat(self, name: str) -> dict[str, Any] | None:
        try:
            blob = self._retry(lambda: self._bucket().get_blob(name, timeout=self.timeout))
        except Exception as exc:
            if _is_not_found(exc):
                return None
            raise
        if blob is None:
            return None
        return {"size": blob.size, "sha256": (blob.metadata or {}).get("sha256"), "generation": blob.generation}

    def put_if_absent(self, name: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> PutResult:
        digest = _sha256(data)
        try:
            existing = self.stat(name)
        except Exception as exc:
            return PutResult(name, "error", digest, len(data), type(exc).__name__)
        if existing is not None:
            remote_sha = existing.get("sha256")
            if remote_sha is None:  # written without metadata: decide by the bytes themselves
                try:
                    remote_sha = _sha256(self._retry(lambda: self._bucket().blob(name).download_as_bytes(timeout=self.timeout)))
                except Exception as exc:
                    return PutResult(name, "error", digest, len(data), type(exc).__name__)
            same = remote_sha == digest and existing.get("size") in (None, len(data))
            return PutResult(name, "exists_same" if same else "conflict", digest, len(data))
        blob = self._bucket().blob(name)
        blob.metadata = {**metadata, "sha256": digest}
        try:
            self._retry(lambda: blob.upload_from_string(data, content_type=content_type, timeout=self.timeout,
                                                        if_generation_match=0))
        except Exception as exc:
            if type(exc).__name__ in {"PreconditionFailed"} or getattr(exc, "code", None) == 412:
                # Someone created it concurrently: decide by content, never overwrite.
                current = self.stat(name)
                same = current is not None and current.get("sha256") == digest
                return PutResult(name, "exists_same" if same else "conflict", digest, len(data))
            return PutResult(name, "error", digest, len(data), type(exc).__name__)
        return PutResult(name, "created", digest, len(data))

    def get_verified(self, name: str, expected_sha256: str) -> bytes:
        data = self._retry(lambda: self._bucket().blob(name).download_as_bytes(timeout=self.timeout))
        if _sha256(data) != expected_sha256:
            raise ObjectIntegrityError(f"SHA-256 mismatch for {name}")
        return data
