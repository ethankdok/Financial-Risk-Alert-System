"""Read-only bounded user-supplied B2B watchlist composition.

No inferred supplier/customer network, no persistent watchlist or risk score.
"""
from __future__ import annotations

from typing import Any, Sequence

from app.services.integrity.b2b_dossier import build_dossier

VERSION = "fintrust_b2b_watchlist_preview_v1"
QUEUE_DISPLAY = {
    "requires_verification": "需要文件確認",
    "monitor": "持續監測",
    "insufficient_evidence": "資料不足",
    "no_item_triggered": "未觸發查核項目（不代表低風險）",
}


def preview_watchlist(
    assessments: Sequence[dict[str, Any]],
    relation_types: Sequence[str],
) -> dict[str, Any]:
    """Use 1–5 already read-only per-company assessments, preserving order."""
    if len(assessments) != len(relation_types) or not 1 <= len(assessments) <= 5:
        raise ValueError("watchlist requires one to five assessment/relation pairs")
    tickers = [a.get("ticker") for a in assessments]
    if any(not isinstance(t, str) or not t for t in tickers) or len(set(tickers)) != len(tickers):
        raise ValueError("ticker must be unique and non-empty")
    dossiers = [build_dossier(data, relation) for data, relation in zip(assessments, relation_types)]
    overview = []
    for dossier in dossiers:
        queue = dossier["investigation_queue"]["queue"]
        overview.append({
            "ticker": dossier["ticker"],
            "company": dossier["company"],
            "relationship": dossier["relationship"],
            "investigation_queue": queue,
            "investigation_queue_label": QUEUE_DISPLAY.get(queue, "資料不足"),
            "document_request_count": len(dossier["document_requests"]),
            "missing_section_count": len(dossier["missing_data"]),
            "latest_fiscal_year": dossier["latest_fiscal_year"],
            "is_a_fraud_or_supply_risk_rank": False,
        })
    return {
        "contract_version": VERSION,
        "count": len(dossiers),
        "status": "read_only_user_declared_batch",
        "overview": overview,
        "dossiers": dossiers,
        "persisted": False,
        "relationship_graph_inferred": False,
        "fraud_probability": None,
        "default_probability": None,
        "supply_disruption_probability": None,
        "limitations": [
            "All companies and relations were explicitly selected by the user; no trade graph is inferred.",
            "Each company's investigation queue is a document-workflow label, not a cross-company risk rank.",
            "Missing data and no triggered item are not evidence that a counterparty is safe.",
            "This response is not persisted; no external credit, trade or delivery information was queried.",
        ],
    }
