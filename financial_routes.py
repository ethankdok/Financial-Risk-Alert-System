"""Flask proxy routes for the shared Financial Risk Alert System.

Copy this file into the shared Flask project and register the blueprint in
app.py. The routes keep the browser connected to the shared Flask host while the
Flask server calls the FinTrust FastAPI service behind the scenes.
"""

from __future__ import annotations

from typing import Any, Callable

from fintrust_client import FinTrustClient, FinTrustClientError, frontend_card_payload, safe_financial_payload


def create_financial_blueprint(client: FinTrustClient | None = None, admin_required: Callable | None = None):
    """Create a Flask Blueprint with FinTrust proxy endpoints.

    Flask is imported inside the factory so this integration package can still be
    linted or unit-tested without installing Flask in the FastAPI repository.
    """

    import json
    from flask import Blueprint, Response, request

    blueprint = Blueprint("financial_proxy", __name__)
    protect_admin = admin_required or (lambda fn: fn)

    def get_client() -> FinTrustClient:
        return client or FinTrustClient()

    def to_response(payload: Any, status_code: int = 200):
        return Response(
            json.dumps(payload, ensure_ascii=False),
            status=status_code,
            mimetype="application/json; charset=utf-8",
    )

    def handle_error(error: FinTrustClientError):
        status = error.status_code or 502
        if status < 400:
            status = 502
        return to_response(
            {
                "success": False,
                "error": str(error),
                "detail": error.detail,
                "status_code": status,
            },
            status,
        )

    def bool_param(payload: dict[str, Any], name: str, default: bool) -> bool:
        value = payload.get(name, request.args.get(name))
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @blueprint.get("/api/financial/health")
    def health():
        try:
            return to_response({"success": True, "data": get_client().health()})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.get("/api/financial/companies")
    def companies():
        try:
            return to_response({"success": True, "data": get_client().companies()})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.get("/api/financial/companies/<ticker>/card")
    def frontend_card(ticker: str):
        live = request.args.get("live", "false").lower() == "true"
        extract = request.args.get("extract", "false").lower() == "true"
        payload = frontend_card_payload(ticker, fetch_conference_live=live, extract_documents=extract)
        return to_response({"success": not bool(payload.get("errors")), "data": payload}, 207 if payload.get("errors") else 200)

    @blueprint.get("/api/financial/companies/<ticker>/raw")
    def raw_layers(ticker: str):
        live = request.args.get("live", "false").lower() == "true"
        extract = request.args.get("extract", "false").lower() == "true"
        payload = safe_financial_payload(ticker, fetch_conference_live=live, extract_documents=extract)
        return to_response({"success": not bool(payload.get("errors")), "data": payload}, 207 if payload.get("errors") else 200)

    @blueprint.get("/api/financial/companies/<ticker>/analysis/latest")
    def latest_analysis(ticker: str):
        try:
            return to_response({"success": True, "data": get_client().latest_analysis(ticker)})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.get("/api/financial/companies/<ticker>/official-evidence")
    def official_evidence(ticker: str):
        try:
            live = request.args.get("live", "false").lower() == "true"
            return to_response({"success": True, "data": get_client().official_evidence(ticker, fetch_conference_live=live)})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.get("/api/financial/companies/<ticker>/official-evidence-card")
    def official_evidence_card(ticker: str):
        try:
            live = request.args.get("live", "false").lower() == "true"
            extract = request.args.get("extract", "false").lower() == "true"
            return to_response({"success": True, "data": get_client().official_evidence_card(ticker, fetch_conference_live=live, extract_documents=extract)})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.get("/api/financial/companies/<ticker>/conferences")
    def conferences(ticker: str):
        try:
            live = request.args.get("live", "false").lower() == "true"
            return to_response({"success": True, "data": get_client().conferences(ticker, fetch_live=live)})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.get("/api/financial/companies/<ticker>/conference-documents")
    def conference_documents(ticker: str):
        try:
            live = request.args.get("live", "true").lower() != "false"
            return to_response({"success": True, "data": get_client().conference_documents(ticker, fetch_live=live)})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.post("/api/financial/claims/verify")
    def verify_claim():
        payload = request.get_json(silent=True) or {}
        company_code = str(payload.get("company_code") or "").strip()
        claim = str(payload.get("claim") or "").strip()
        if not company_code or len(claim) < 2:
            return to_response(
                {"success": False, "error": "請提供公司代號與想查證的說法。", "status_code": 400},
                400,
            )
        if len(claim) > 5000:
            return to_response({"success": False, "error": "說法內容過長（上限 5000 字）。", "status_code": 400}, 400)
        try:
            return to_response({"success": True, "data": get_client().verify_claim(company_code, claim)})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.post("/api/financial/official-documents/extract")
    def extract_official_document():
        try:
            payload = request.get_json(silent=True) or {}
            return to_response(
                {
                    "success": True,
                    "data": get_client().extract_official_document(
                        str(payload.get("ticker", "")),
                        str(payload.get("document_url", "")),
                        source_url=payload.get("source_url"),
                        document_title=payload.get("document_title"),
                    ),
                }
            )
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.get("/api/financial/companies/<ticker>/material-events")
    def material_events(ticker: str):
        try:
            year = request.args.get("year")
            return to_response({"success": True, "data": get_client().material_events(ticker, year=int(year) if year else None)})
        except (ValueError, FinTrustClientError) as exc:
            if isinstance(exc, FinTrustClientError):
                return handle_error(exc)
            return to_response({"success": False, "error": "Invalid year parameter."}, 400)

    @blueprint.get("/api/financial/companies/<ticker>/metrics")
    def metrics(ticker: str):
        try:
            latest_only = request.args.get("latest_only", "true").lower() != "false"
            limit = int(request.args.get("limit", "1000"))
            return to_response(
                {
                    "success": True,
                    "data": get_client().metrics(ticker, latest_only=latest_only, limit=limit),
                }
            )
        except (ValueError, FinTrustClientError) as exc:
            if isinstance(exc, FinTrustClientError):
                return handle_error(exc)
            return to_response({"success": False, "error": "Invalid limit parameter."}, 400)

    @blueprint.get("/api/financial/companies/<ticker>/analysis-runs")
    def analysis_runs(ticker: str):
        try:
            return to_response({"success": True, "data": get_client().analysis_runs(ticker)})
        except FinTrustClientError as exc:
            return handle_error(exc)

    @blueprint.post("/api/financial/admin/companies/<ticker>/official-events/refresh")
    @protect_admin
    def refresh_official_events(ticker: str):
        try:
            payload = request.get_json(silent=True) or {}
            year = payload.get("material_event_year") or request.args.get("material_event_year")
            return to_response(
                {
                    "success": True,
                    "data": get_client().refresh_official_events(
                        ticker,
                        include_conferences=bool_param(payload, "include_conferences", True),
                        include_material_events=bool_param(payload, "include_material_events", True),
                        material_event_year=int(year) if year else None,
                        extract_documents=bool_param(payload, "extract_documents", True),
                        material_fetch_details=bool_param(payload, "material_fetch_details", True),
                    ),
                }
            )
        except (ValueError, FinTrustClientError) as exc:
            if isinstance(exc, FinTrustClientError):
                return handle_error(exc)
            return to_response({"success": False, "error": "Invalid official-events refresh parameters."}, 400)

    @blueprint.post("/api/financial/admin/companies/<ticker>/refresh")
    @protect_admin
    def refresh_company(ticker: str):
        try:
            payload = request.get_json(silent=True) or {}
            end_year = payload.get("end_year") or request.args.get("end_year")
            return to_response(
                {
                    "success": True,
                    "data": get_client().refresh_company(
                        ticker,
                        years=int(payload.get("years", request.args.get("years", 3))),
                        end_year=int(end_year) if end_year else None,
                        trigger=payload.get("trigger", request.args.get("trigger", "manual")),
                        source_mode=payload.get("source_mode", request.args.get("source_mode", "official")),
                    ),
                }
            )
        except (ValueError, FinTrustClientError) as exc:
            if isinstance(exc, FinTrustClientError):
                return handle_error(exc)
            return to_response({"success": False, "error": "Invalid refresh parameters."}, 400)

    @blueprint.post("/api/financial/admin/companies/<ticker>/unified-refresh")
    @protect_admin
    def unified_refresh_company(ticker: str):
        try:
            payload = request.get_json(silent=True) or {}
            end_year = payload.get("end_year") or request.args.get("end_year")
            return to_response(
                {
                    "success": True,
                    "data": get_client().unified_refresh_company(
                        ticker,
                        years=int(payload.get("years", request.args.get("years", 3))),
                        end_year=int(end_year) if end_year else None,
                        trigger=payload.get("trigger", request.args.get("trigger", "manual")),
                        source_mode=payload.get("source_mode", request.args.get("source_mode", "official")),
                        include_gemini=bool_param(payload, "include_gemini", True),
                    ),
                }
            )
        except (ValueError, FinTrustClientError) as exc:
            if isinstance(exc, FinTrustClientError):
                return handle_error(exc)
            return to_response({"success": False, "error": "Invalid unified refresh parameters."}, 400)

    return blueprint
