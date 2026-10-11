"""Flask read/proxy routes for the historical research API (Phase 4).

Flask only validates and forwards; every research calculation stays in the FastAPI service. Query parameters are
whitelisted per route, tickers and run ids are pattern-checked, the browser can never persist a run, and FastAPI
error statuses (404 / 409 / 422 / 503) are passed through with their structured detail.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fintrust_client import FinTrustClient, FinTrustClientError

_TICKER = re.compile(r"^\d{4,6}$")
_RUN_ID = re.compile(r"^rrun1_[0-9a-f]{32}$")
_MODE_PARAMS = ("analysis_mode", "cutoff_at")
_VIEWS = {
    "timeline": _MODE_PARAMS + ("evidence_tier", "limit", "offset"),
    "restatement-bridge": _MODE_PARAMS + ("scope",),
    "feature-registry": _MODE_PARAMS,
    "source-discrepancies": _MODE_PARAMS,
    "text-readiness": _MODE_PARAMS,
}
_COMPUTE_FIELDS = ("ticker", "analysis_mode", "cutoff_at", "start_year", "end_year", "version_policy")


def create_research_blueprint(client: FinTrustClient | None = None):
    from flask import Blueprint, Response, request

    blueprint = Blueprint("research_proxy", __name__)

    def get_client() -> FinTrustClient:
        return client or FinTrustClient()

    def respond(payload: Any, status: int = 200):
        return Response(json.dumps(payload, ensure_ascii=False), status=status, mimetype="application/json; charset=utf-8")

    def failure(error: FinTrustClientError):
        status = error.status_code if error.status_code and error.status_code >= 400 else 502
        detail = error.detail.get("detail", error.detail) if isinstance(error.detail, dict) else error.detail
        return respond({"success": False, "error": str(error), "detail": detail, "status_code": status}, status)

    def invalid(message: str):
        return respond({"success": False, "error": message, "status_code": 400}, 400)

    def forward(path: str, allowed: tuple[str, ...] = ()):
        params = {key: request.args.get(key) for key in allowed if request.args.get(key) not in (None, "")}
        try:
            return respond({"success": True, "data": get_client().research_get(path, params)})
        except FinTrustClientError as exc:
            return failure(exc)

    @blueprint.get("/api/research/health")
    def research_health():
        return forward("/health")

    @blueprint.get("/api/research/cases")
    def research_cases():
        return forward("/cases")

    @blueprint.get("/api/research/cases/<ticker>")
    def research_case(ticker: str):
        if not _TICKER.fullmatch(ticker):
            return invalid("Invalid ticker.")
        return forward(f"/cases/{ticker}")

    @blueprint.get("/api/research/cases/<ticker>/<view>")
    def research_view(ticker: str, view: str):
        if not _TICKER.fullmatch(ticker) or view not in _VIEWS:
            return invalid("Invalid ticker or research view.")
        return forward(f"/cases/{ticker}/{view}", _VIEWS[view])

    @blueprint.post("/api/research/financial-signals/compute")
    def research_compute():
        payload = request.get_json(silent=True) or {}
        if not isinstance(payload, dict) or not _TICKER.fullmatch(str(payload.get("ticker", ""))):
            return invalid("Invalid ticker.")
        body = {key: payload[key] for key in _COMPUTE_FIELDS if payload.get(key) not in (None, "")}
        try:
            return respond({"success": True, "data": get_client().research_compute(body)})
        except FinTrustClientError as exc:
            return failure(exc)

    @blueprint.get("/api/research/runs/<run_id>")
    def research_run(run_id: str):
        if not _RUN_ID.fullmatch(run_id):
            return invalid("Invalid run id.")
        return forward(f"/runs/{run_id}")

    return blueprint
