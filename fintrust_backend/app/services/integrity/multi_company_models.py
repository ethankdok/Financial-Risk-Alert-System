"""Phase 2–3 multi-company *research* batch runner.

Runs the already reviewed Beneish/Dechow engines unchanged on frozen Panel
objects. Production use is intentionally disallowed until full company-level
source attestation and Taiwan mapping approval are separately completed.
This is an internal research adapter, not a public scores API.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

from app.services.financial_research import beneish_1999, dechow_2011
from app.services.financial_research.literature_inputs import Panel
from app.services.financial_research.literature_method_registry import APPROVAL_STATUS

VERSION = "fintrust_multi_company_literature_batch_v1"
TICKER = re.compile(r"^[0-9]{4,6}$")
POLICIES = frozenset({"original_only", "latest_available"})


def evaluate_research_panels(
    rows: Sequence[dict[str, Any]], *, mode: str = "RETROSPECTIVE_FORENSIC"
) -> dict[str, Any]:
    """No score without frozen panel, exact release identity and version policy.

    Each input is a *trusted internal* research wrapper:
      ticker, fiscal_year, version_policy, frozen_panel (Panel),
      release_sha256, source_gate_verified, source_identity_verified.

    The booleans are adapter attestations, not cryptographic verification by
    this function; they must never be populated from an external HTTP body.
    """
    if mode != "RETROSPECTIVE_FORENSIC":
        raise ValueError("current reviews must use the Workbench source policy, not research panels")
    results = []
    seen: set[tuple[str, int, str]] = set()
    for i, item in enumerate(rows):
        ticker = str(item.get("ticker") or "")
        year = item.get("fiscal_year")
        policy = item.get("version_policy")
        panel = item.get("frozen_panel")
        sha = str(item.get("release_sha256") or "")
        reasons = []
        if not TICKER.fullmatch(ticker):
            reasons.append("invalid_company_identifier")
        if isinstance(year, bool) or not isinstance(year, int) or not 1990 <= year <= 2100:
            reasons.append("invalid_fiscal_year")
        if policy not in POLICIES:
            reasons.append("invalid_version_policy")
        if not isinstance(panel, Panel) or getattr(panel, "year", None) != year:
            reasons.append("missing_or_mismatched_frozen_literature_panel")
        if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
            reasons.append("invalid_frozen_release_digest")
        if item.get("source_gate_verified") is not True or item.get("source_identity_verified") is not True:
            reasons.append("source_identity_or_line_gate_not_attested")
        if not reasons:
            key = (ticker, year, policy)
            if key in seen:
                reasons.append("duplicate_company_year_version")
            else:
                seen.add(key)
        if reasons:
            results.append({
                "index": i, "ticker": ticker, "fiscal_year": year,
                "version_policy": policy,
                "status": "not_computable", "reasons": reasons, "models": [],
                "release_sha256": sha if re.fullmatch(r"[0-9a-fA-F]{64}", sha) else None,
            })
            continue
        model_results = []
        for model in (beneish_1999, dechow_2011):
            output = model.evaluate(panel)
            model_results.append({
                "model_id": output["model_id"],
                "status": output["status"],
                "score": output.get("score") if output["status"] == "computed" else None,
                "score_kind": output.get("score_kind"),
                "component_coverage": output.get("component_coverage"),
                "missing_input_count": len(output.get("missing_inputs", [])),
                "missing_inputs": output.get("missing_inputs", []),
                "approval_status": output.get("approval_status") or APPROVAL_STATUS,
                "original_paper_scaling_only": True,
                "taiwan_fraud_probability": None,
            })
        results.append({
            "index": i, "ticker": ticker, "fiscal_year": year,
            "version_policy": policy, "status": "research_panel_evaluated",
            "reasons": [], "models": model_results,
            "release_sha256": sha.lower(),
        })
    return {
        "method_version": VERSION, "analysis_mode": mode,
        "method_approval": APPROVAL_STATUS,
        "evaluated_panel_count": sum(r["status"] == "research_panel_evaluated" for r in results),
        "rejected_panel_count": sum(r["status"] == "not_computable" for r in results),
        "rows": results,
        "production_scores_admitted": False,
        "fraud_prediction_validated": False,
        "limitations": [
            "The caller must verify immutable archived source bytes and page/filing identities independently.",
            "The existing Beneish/Dechow engines and coefficients are reused without modification.",
            "Partial components never produce full scores; negative, missing and zero-evidence rules remain unchanged.",
            "This adapter does not import retrospective scores into live company assessments.",
            "Original US-sample model probabilities and cutoffs are not Taiwan-calibrated fraud probabilities.",
        ],
    }
