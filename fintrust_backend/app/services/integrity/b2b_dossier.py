"""Phase 6 B2B due-diligence preview from one company's read-only Workbench.

The supplied relationship is an unverified user declaration; neither a
trade linkage nor a probability is inferred from financial statements.
"""
from __future__ import annotations

from typing import Any

from app.services.integrity.cross_evidence import compose_corroboration

VERSION = "fintrust_b2b_due_diligence_v1"
RELATIONSHIP_LABELS = {
    "supplier": "使用者自述供應商",
    "customer": "使用者自述客戶",
    "partner": "使用者自述合作夥伴",
    "potential_counterparty": "潛在交易對手（尚無合作證據）",
}


def build_dossier(assessment: dict[str, Any], relationship_type: str) -> dict[str, Any]:
    if relationship_type not in RELATIONSHIP_LABELS:
        raise ValueError("unsupported relationship_type")
    if assessment.get("review_mode") != "CURRENT_REVIEW":
        raise ValueError("a current review is required; historical retrospective studies are excluded")
    cross = compose_corroboration(assessment)
    queue = assessment.get("investigation_priority") or {}
    questions = []
    seen = set()
    for check in assessment.get("next_checks") or []:
        document_list = [str(doc) for doc in (check.get("documents_to_request") or []) if doc]
        if not document_list or check.get("is_risk_conclusion"):
            continue
        check_id = str(check.get("check_id") or "")
        if not check_id or check_id in seen:
            continue
        seen.add(check_id)
        questions.append({
            "check_id": check_id, "triggered_by": check.get("triggered_by"),
            "question": check.get("question_for_counterparty"),
            "requested_documents": document_list,
            "condition": check.get("condition"), "rationale": check.get("rationale"),
        })
    missing = [
        {"section": m.get("section"), "item": m.get("item"), "reasons": m.get("reasons", [])}
        for m in assessment.get("missing_data") or []
    ]
    freshness = assessment.get("freshness") or {}
    return {
        "contract_version": VERSION,
        "ticker": assessment.get("ticker"),
        "company": assessment.get("company"),
        "subindustry": assessment.get("subindustry"),
        "relationship": {
            "type": relationship_type,
            "label": RELATIONSHIP_LABELS[relationship_type],
            "evidence_status": "user_declared_unverified",
            "verified_business_link": False,
            "note": "由使用者自行指定查核對象；系統尚未核實實際採購、供貨或合作關係。",
        },
        "analysis_mode": "CURRENT_REVIEW",
        "generated_at": assessment.get("generated_at"),
        "information_scope": assessment.get("temporal_basis"),
        "latest_fiscal_year": freshness.get("latest_fact_fiscal_year"),
        "stale_finding_ids": freshness.get("stale_findings", []),
        "investigation_queue": {
            "queue": queue.get("queue") or "insufficient_evidence",
            "meaning": queue.get("meaning"),
            "triggered_by": queue.get("triggered_by", []),
        },
        "cross_evidence": cross,
        "document_requests": questions,
        "missing_data": missing,
        "disclaimers": [
            "本報告僅供交易對手盡職調查與補件排序，不是舞弊認定、授信建議或投資建議。",
            "合作關係為使用者輸入，非經外部驗證的供應鏈關係。",
            "資料不足、無篩檢項目或同源數字吻合，均不代表低風險。",
            "沒有估算企業違約、斷鏈、倒閉或供應中斷機率。",
        ],
        "fraud_probability": None,
        "default_probability": None,
        "supply_disruption_probability": None,
        "persisted": False,
    }
