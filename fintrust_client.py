"""Small client for connecting the shared Flask app to the FinTrust FastAPI service.

This file is intentionally dependency-light so it can be copied into the shared
Flask project without bringing the whole FastAPI backend with it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class FinTrustClientError(RuntimeError):
    """Raised when the Flask integration cannot reach or parse FinTrust API."""

    def __init__(self, message: str, *, status_code: int | None = None, detail: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


Opener = Callable[[Request, float], Any]


@dataclass(slots=True)
class FinTrustClient:
    """HTTP client used by Flask proxy routes.

    The browser should call Flask routes, not the FastAPI service directly.
    This keeps API URLs, ingestion tokens and future LLM settings on the server
    side. It also keeps the private Flask frontend independent from backend
    implementation details.
    """

    base_url: str | None = None
    ingestion_token: str | None = None
    timeout_seconds: float = 20.0
    opener: Opener | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        self.base_url = (self.base_url or os.getenv("FINTRUST_API_BASE_URL", "")).strip().rstrip("/")
        self.ingestion_token = (self.ingestion_token or os.getenv("FINTRUST_INGESTION_TOKEN", "")).strip()
        if not self.base_url:
            raise FinTrustClientError("FINTRUST_API_BASE_URL is not configured.")

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        clean_path = path if path.startswith("/") else f"/{path}"
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        return f"{self.base_url}{clean_path}" + (f"?{query}" if query else "")

    def _open(self, request: Request) -> Any:
        if self.opener is not None:
            return self.opener(request, self.timeout_seconds)
        return urlopen(request, timeout=self.timeout_seconds)  # noqa: S310 - URL is configured server-side.

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        include_ingestion_token: bool = False,
    ) -> Any:
        body = None
        headers = {"Accept": "application/json"}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if include_ingestion_token and self.ingestion_token:
            headers["X-Ingestion-Token"] = self.ingestion_token

        request = Request(
            self._url(path, params),
            data=body,
            headers=headers,
            method=method.upper(),
        )
        try:
            with self._open(request) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return None
                return json.loads(raw)
        except HTTPError as exc:
            detail = self._safe_error_detail(exc)
            raise FinTrustClientError(
                "FinTrust API returned an error.",
                status_code=exc.code,
                detail=detail,
            ) from exc
        except URLError as exc:
            raise FinTrustClientError(
                "FinTrust API is unreachable.",
                status_code=502,
                detail=str(exc.reason),
            ) from exc
        except (TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise FinTrustClientError(
                "FinTrust API response could not be processed.",
                status_code=502,
                detail=str(exc),
            ) from exc

    @staticmethod
    def _safe_error_detail(error: HTTPError) -> Any:
        try:
            payload = error.read().decode("utf-8")
            return json.loads(payload) if payload else None
        except Exception:  # pragma: no cover - best effort error detail only
            return None

    def health(self) -> Any:
        return self.request("GET", "/api/v1/financial/health")

    def companies(self) -> Any:
        return self.request("GET", "/api/v1/financial/companies")

    def latest_analysis(self, ticker: str) -> Any:
        return self.request("GET", f"/api/v1/financial/companies/{ticker}/analysis/latest")

    def official_evidence(
        self,
        ticker: str,
        *,
        fetch_conference_live: bool = False,
        include_conferences: bool = True,
        include_material_events: bool = True,
    ) -> Any:
        return self.request(
            "GET",
            f"/api/v1/financial/companies/{ticker}/official-evidence",
            params={
                "fetch_conference_live": str(fetch_conference_live).lower(),
                "include_conferences": str(include_conferences).lower(),
                "include_material_events": str(include_material_events).lower(),
            },
        )

    def official_evidence_card(
        self,
        ticker: str,
        *,
        fetch_conference_live: bool = False,
        extract_documents: bool = False,
    ) -> Any:
        return self.request(
            "GET",
            f"/api/v1/financial/companies/{ticker}/official-evidence-card",
            params={
                "fetch_conference_live": str(fetch_conference_live).lower(),
                "extract_documents": str(extract_documents).lower(),
            },
        )

    def conferences(self, ticker: str, *, fetch_live: bool = False) -> Any:
        return self.request(
            "GET",
            f"/api/v1/financial/companies/{ticker}/conferences",
            params={"fetch_live": str(fetch_live).lower()},
        )

    def conference_documents(self, ticker: str, *, fetch_live: bool = True) -> Any:
        return self.request(
            "GET",
            f"/api/v1/financial/companies/{ticker}/conference-documents",
            params={"fetch_live": str(fetch_live).lower()},
        )

    def extract_official_document(
        self,
        ticker: str,
        document_url: str,
        *,
        source_url: str | None = None,
        document_title: str | None = None,
    ) -> Any:
        return self.request(
            "POST",
            "/api/v1/financial/official-documents/extract",
            json_body={
                "ticker": ticker,
                "document_url": document_url,
                "source_url": source_url,
                "document_title": document_title,
            },
        )

    def material_events(self, ticker: str, *, year: int | None = None, title: str | None = None) -> Any:
        return self.request(
            "GET",
            f"/api/v1/financial/companies/{ticker}/material-events",
            params={"year": year, "title": title},
        )

    def metrics(self, ticker: str, *, latest_only: bool = True, limit: int = 1000) -> Any:
        return self.request(
            "GET",
            f"/api/v1/financial/companies/{ticker}/metrics",
            params={"latest_only": str(latest_only).lower(), "limit": limit},
        )

    def analysis_runs(self, ticker: str) -> Any:
        return self.request("GET", f"/api/v1/financial/companies/{ticker}/analysis-runs")

    def refresh_company(
        self,
        ticker: str,
        *,
        years: int = 3,
        end_year: int | None = None,
        trigger: str = "manual",
        source_mode: str = "official",
    ) -> Any:
        return self.request(
            "POST",
            f"/api/v1/financial/admin/companies/{ticker}/refresh",
            params={
                "years": years,
                "end_year": end_year,
                "trigger": trigger,
                "source_mode": source_mode,
            },
            include_ingestion_token=True,
        )


def safe_financial_payload(ticker: str, *, fetch_conference_live: bool = False, extract_documents: bool = False) -> dict[str, Any]:
    """Return a Flask-template-safe payload with partial failure handling."""
    client = FinTrustClient()
    payload: dict[str, Any] = {
        "ticker": ticker,
        "snapshot": None,
        "official_evidence": None,
        "official_evidence_card": None,
        "conferences": [],
        "conference_documents": [],
        "material_events": [],
        "errors": [],
    }
    calls = [
        ("snapshot", lambda: client.latest_analysis(ticker)),
        ("official_evidence", lambda: client.official_evidence(ticker, fetch_conference_live=fetch_conference_live)),
        ("official_evidence_card", lambda: client.official_evidence_card(ticker, fetch_conference_live=fetch_conference_live, extract_documents=extract_documents)),
        ("conferences", lambda: client.conferences(ticker, fetch_live=fetch_conference_live)),
        ("material_events", lambda: client.material_events(ticker)),
    ]
    if extract_documents:
        calls.append(("conference_documents", lambda: client.conference_documents(ticker, fetch_live=fetch_conference_live)))
    for key, call in calls:
        try:
            payload[key] = call()
        except FinTrustClientError as exc:
            payload["errors"].append({"layer": key, "message": str(exc), "status_code": exc.status_code, "detail": exc.detail})
    return payload


def frontend_card_payload(ticker: str, *, fetch_conference_live: bool = False, extract_documents: bool = False) -> dict[str, Any]:
    """Build a compact payload for dashboard/detail cards."""
    payload = safe_financial_payload(ticker, fetch_conference_live=fetch_conference_live, extract_documents=extract_documents)
    backend_card = payload.get("official_evidence_card")
    if isinstance(backend_card, dict):
        backend_card = dict(backend_card)
        backend_card["errors"] = payload.get("errors", [])
        backend_card["raw"] = payload
        return backend_card

    snapshot = payload.get("snapshot") or {}
    evidence = payload.get("official_evidence") or {}
    conferences = payload.get("conferences") or []
    material_events = payload.get("material_events") or []
    return {
        "ticker": ticker,
        "company_name": snapshot.get("company_name") or evidence.get("company_name"),
        "subindustry": snapshot.get("subindustry") or evidence.get("subindustry"),
        "overall_severity": snapshot.get("overall_severity"),
        "summary": snapshot.get("summary"),
        "key_metrics": snapshot.get("key_metrics", [])[:6],
        "rule_cards": snapshot.get("rule_cards", [])[:8],
        "evidence_readiness": evidence.get("readiness"),
        "evidence_layers": evidence.get("evidence_layers", []),
        "official_sources": evidence.get("sources", []),
        "conference_count": len(conferences),
        "material_event_count": len(material_events),
        "limitations": (snapshot.get("limitations") or []) + (evidence.get("limitations") or []),
        "errors": payload.get("errors", []),
        "raw": payload,
    }
