"""Flask proxy routes for the Financial Integrity Workbench (Phase 1).

Flask only validates and forwards to the FastAPI service configured server-side (the browser cannot choose a
backend URL or send secrets). Tickers are pattern-checked, the request body is whitelisted, ``persist`` is
always false, and FastAPI error statuses (403 / 404 / 409 / 422 / 503) pass through with their structured detail.
"""

from __future__ import annotations

import json
import re
from typing import Any

from fintrust_client import FinTrustClient, FinTrustClientError

_TICKER = re.compile(r"^\d{4,6}$")
_MODES = ("CURRENT_REVIEW", "STRICT_AS_OF")
_SECTIONS = ("financial_checks", "literature", "jsd", "claims")
_CASE_POLICIES = ("latest_available", "original_only")


def create_integrity_blueprint(client: FinTrustClient | None = None):
    from flask import Blueprint, Response, request

    blueprint = Blueprint("integrity_proxy", __name__)

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

    def call(fn, *args):
        try:
            return respond({"success": True, "data": fn(*args)})
        except FinTrustClientError as exc:
            return failure(exc)

    @blueprint.get("/api/integrity/companies")
    def integrity_companies():
        return call(get_client().integrity_companies)

    @blueprint.get("/api/integrity/companies/<ticker>/readiness")
    def integrity_readiness(ticker: str):
        if not _TICKER.fullmatch(ticker):
            return invalid("Invalid ticker.")
        return call(get_client().integrity_readiness, ticker)

    @blueprint.post("/api/integrity/assessments/preview")
    def integrity_preview():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not _TICKER.fullmatch(str(payload.get("ticker", ""))):
            return invalid("Invalid ticker.")
        if payload.get("persist") not in (None, False):
            return invalid("persist is not available from the browser.")
        body: dict[str, Any] = {"ticker": payload["ticker"]}
        mode = payload.get("review_mode")
        if mode is not None:
            if mode not in _MODES:
                return invalid("Invalid review mode.")
            body["review_mode"] = mode
        sections = payload.get("sections")
        if sections is not None:
            if not isinstance(sections, list) or not sections or any(s not in _SECTIONS for s in sections):
                return invalid("Invalid sections.")
            body["sections"] = list(dict.fromkeys(sections))
        return call(get_client().integrity_preview, body)

    @blueprint.get("/api/integrity/research-cases/<ticker>/summary")
    def integrity_research_case(ticker: str):
        policy = request.args.get("version_policy", "")
        if not _TICKER.fullmatch(ticker) or policy not in _CASE_POLICIES:
            return invalid("Invalid ticker or version policy.")
        return call(get_client().integrity_research_case, ticker, policy)

    return blueprint
