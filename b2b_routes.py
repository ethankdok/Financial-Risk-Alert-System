"""Additive Flask facade for standalone B2B page.

Only fixed allowlisted fields reach FastAPI, no arbitrary backend URLs,
tokens, file paths or persistence flags are forwarded.
"""
from __future__ import annotations

import json
import re

from fintrust_client import FinTrustClient, FinTrustClientError

_TICKER = re.compile(r"^[0-9]{4,6}$")
_RELATIONS = frozenset({"supplier", "customer", "partner", "potential_counterparty"})


def create_b2b_blueprint(client: FinTrustClient | None = None):
    from flask import Blueprint, Response, request

    bp = Blueprint("b2b_dossier_proxy", __name__)

    def respond(body, status=200):
        return Response(json.dumps(body, ensure_ascii=False), status=status,
                        mimetype="application/json")

    @bp.get("/api/b2b/companies/<ticker>/source-readiness")
    def readiness(ticker: str):
        if not _TICKER.fullmatch(ticker):
            return respond({"success": False, "error": "Invalid ticker."}, 400)
        try:
            active_client = client if client is not None else FinTrustClient()
            return respond({"success": True, "data": active_client.b2b_source_readiness(ticker)})
        except FinTrustClientError as exc:
            status = exc.status_code if exc.status_code and 400 <= exc.status_code < 600 else 502
            return respond({"success": False, "error": str(exc), "status_code": status}, status)

    @bp.post("/api/b2b/watchlists/preview")
    def watchlist():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {"items", "persist"}:
            return respond({"success": False, "error": "Invalid request."}, 400)
        items = payload.get("items")
        if payload.get("persist") is not False or not isinstance(items, list) or not 1 <= len(items) <= 5:
            return respond({"success": False, "error": "Invalid watchlist size or persist field."}, 400)
        tickers = set()
        clean = []
        for item in items:
            if not isinstance(item, dict) or set(item) - {"ticker", "relationship_type"}:
                return respond({"success": False, "error": "Invalid company fields."}, 400)
            ticker = str(item.get("ticker") or "")
            relation = item.get("relationship_type", "potential_counterparty")
            if not _TICKER.fullmatch(ticker) or ticker in tickers or relation not in _RELATIONS:
                return respond({"success": False, "error": "Invalid or duplicate company."}, 400)
            tickers.add(ticker)
            clean.append({"ticker": ticker, "relationship_type": relation})
        try:
            active_client = client if client is not None else FinTrustClient()
            result = active_client.b2b_watchlist_preview({"items": clean, "persist": False})
            return respond({"success": True, "data": result})
        except FinTrustClientError as exc:
            status = exc.status_code if exc.status_code and 400 <= exc.status_code < 600 else 502
            return respond({"success": False, "error": str(exc), "status_code": status}, status)

    @bp.post("/api/b2b/dossiers/preview")
    def preview():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or set(payload) - {"ticker", "relationship_type", "persist"}:
            return respond({"success": False, "error": "Invalid request fields."}, 400)
        ticker = str(payload.get("ticker") or "")
        relation = payload.get("relationship_type", "potential_counterparty")
        if not _TICKER.fullmatch(ticker) or relation not in _RELATIONS or payload.get("persist") is not False:
            return respond({"success": False, "error": "Invalid ticker, relation or persist flag."}, 400)
        try:
            active_client = client if client is not None else FinTrustClient()
            data = active_client.b2b_dossier_preview(
                {"ticker": ticker, "relationship_type": relation, "persist": False}
            )
            return respond({"success": True, "data": data})
        except FinTrustClientError as exc:
            status = exc.status_code if exc.status_code and 400 <= exc.status_code < 600 else 502
            return respond({"success": False, "error": str(exc),
                            "detail": exc.detail, "status_code": status}, status)

    return bp
