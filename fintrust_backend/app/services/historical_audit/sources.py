"""Bounded acquisition from official sources and case-manifest loading."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx

from app.services.historical_audit.models import CaseManifest, utc_now
from app.services.historical_audit.xbrl_document import detect_format
from app.services.mops_inline_xbrl import (
    FILING_NOT_FOUND,
    SOURCE_INVALID_CONTENT,
    SOURCE_UNAVAILABLE,
    classify_mops_non_ixbrl_body,
)


OFFICIAL_HOSTS = frozenset({"mopsov.twse.com.tw", "mops.twse.com.tw", "doc.twse.com.tw"})
MOPS_ANNUAL_XBRL_URL = (
    "https://mopsov.twse.com.tw/server-java/FileDownLoad"
    "?functionName=t164sb01&step=9&co_id={ticker}&year={fiscal_year}&season=4&report_id={report_id}"
)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_KEPT_HEADERS = ("content-type", "content-length", "date", "last-modified", "etag", "content-disposition")


class SourceNotAllowedError(ValueError):
    pass


def ensure_official_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in OFFICIAL_HOSTS:
        raise SourceNotAllowedError(f"Not an allowlisted official HTTPS source: {url}")
    return url


def mops_annual_url(ticker: str, fiscal_year: int, report_id: str = "C") -> str:
    return MOPS_ANNUAL_XBRL_URL.format(ticker=ticker, fiscal_year=fiscal_year, report_id=report_id)


@dataclass
class FetchResult:
    status: str  # "ok" | filing_not_found | source_unavailable | source_invalid_content
    url: str
    final_url: str | None = None
    content: bytes | None = None
    detected_format: str | None = None
    retrieved_at: datetime | None = None
    http_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    attempts: int = 0
    error: str | None = None

    def metadata(self) -> dict[str, Any]:
        """Response metadata safe to persist: no request headers, cookies or credentials."""
        return {
            "source_url": self.url,
            "final_url": self.final_url,
            "retrieved_at": self.retrieved_at.isoformat() if self.retrieved_at else None,
            "http_status": self.http_status,
            "response_headers": self.response_headers,
            "attempts": self.attempts,
            "detected_format": self.detected_format,
        }


def classify_body(content: bytes, *, expect: tuple[str, ...]) -> tuple[str, str | None]:
    detected = detect_format(content)
    if detected in expect:
        return "ok", detected
    if detected is None:
        return classify_mops_non_ixbrl_body(content), None
    return SOURCE_INVALID_CONTENT, detected


class OfficialSourceFetcher:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = 60.0,
        max_attempts: int = 3,
        backoff_seconds: float = 2.0,
        max_backoff_seconds: float = 30.0,
        min_interval_seconds: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        user_agent: str = "FinTrust-HistoricalAudit/1.0 (research archive)",
    ) -> None:
        if not 1 <= max_attempts <= 5:
            raise ValueError("max_attempts must be between 1 and 5.")
        self.transport = transport
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.min_interval_seconds = min_interval_seconds
        self.sleep = sleep
        self.user_agent = user_agent
        self._spacing_lock = asyncio.Lock()
        self._last_request = 0.0

    async def _respect_interval(self) -> None:
        async with self._spacing_lock:
            wait = self.min_interval_seconds - (time.monotonic() - self._last_request)
            if wait > 0:
                await self.sleep(wait)
            self._last_request = time.monotonic()

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        current = ensure_official_url(url)
        for _ in range(4):
            response = await client.get(current)
            if response.status_code in {301, 302, 303, 307, 308} and response.headers.get("location"):
                current = ensure_official_url(urljoin(current, response.headers["location"]))
                continue
            return response
        raise httpx.TooManyRedirects("Too many redirects", request=response.request)

    async def fetch(self, url: str, *, expect: tuple[str, ...]) -> FetchResult:
        ensure_official_url(url)
        result = FetchResult(status=SOURCE_UNAVAILABLE, url=url)
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=False,
            verify=True,
            transport=self.transport,
            headers={"User-Agent": self.user_agent, "Referer": "https://mopsov.twse.com.tw/mops/web/t203sb01"},
        ) as client:
            for attempt in range(1, self.max_attempts + 1):
                result.attempts = attempt
                await self._respect_interval()
                retryable = False
                try:
                    response = await self._get(client, url)
                    result.http_status = response.status_code
                    result.final_url = str(response.url)
                    result.retrieved_at = utc_now()
                    result.response_headers = {
                        name: response.headers[name] for name in _KEPT_HEADERS if name in response.headers
                    }
                    if response.status_code == 200:
                        status, detected = classify_body(response.content, expect=expect)
                        result.status, result.detected_format = status, detected
                        result.content = response.content
                        result.error = None if status == "ok" else f"{status} ({len(response.content)} bytes)"
                        # A throttle page is retried once; the exact not-found page is final.
                        retryable = status == SOURCE_INVALID_CONTENT and detected is None
                    else:
                        result.status = SOURCE_UNAVAILABLE
                        result.content = None
                        result.error = f"HTTP {response.status_code}"
                        retryable = response.status_code in _RETRYABLE_STATUS
                except SourceNotAllowedError:
                    raise
                except httpx.HTTPError as exc:
                    result.status = SOURCE_UNAVAILABLE
                    result.content = None
                    result.retrieved_at = utc_now()
                    result.error = f"{type(exc).__name__}: {exc}"
                    retryable = True
                if result.status in {"ok", FILING_NOT_FOUND} or not retryable or attempt == self.max_attempts:
                    return result
                await self.sleep(min(self.max_backoff_seconds, self.backoff_seconds * 2 ** (attempt - 1)))
        return result


def load_manifest(path: str | Path) -> tuple[CaseManifest, Path]:
    manifest_path = Path(path)
    manifest = CaseManifest.model_validate(json.loads(manifest_path.read_text(encoding="utf-8")))
    for document in manifest.documents:
        if document.source_url and document.source_kind != "test_fixture":
            ensure_official_url(document.source_url)
        if document.filing_version_type != "unknown_revision" and not document.verification_evidence:
            raise ValueError(
                f"{document.period}: filing_version_type={document.filing_version_type} requires verification_evidence."
            )
        if document.available_at is not None and not (document.availability_basis and document.verification_evidence):
            raise ValueError(
                f"{document.period}: available_at requires availability_basis and verification_evidence."
            )
    return manifest, manifest_path.parent
