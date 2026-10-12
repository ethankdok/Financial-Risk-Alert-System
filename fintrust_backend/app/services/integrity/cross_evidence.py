"""Phase 4: deterministic cross-evidence corroboration, independent of JSD internals.

No persistence, fraud score, LLM verdict or network fetch. This layer makes the
logical separation between same-issuer agreement and independent confirmation
explicit, preserving lack-of-evidence as a distinct state.
"""
from __future__ import annotations

from typing import Any

VERSION = "fintrust_cross_evidence_v1"
POSITIVE = frozenset({"supported", "descriptive_gap", "within_screening_heuristic", "descriptive_divergence"})
NO_EVIDENCE = frozenset({"unavailable", "not_comparable", "not_computable", "insufficient_evidence", "inconclusive"})


def compose_corroboration(assessment: dict[str, Any]) -> dict[str, Any]:
    """Aggregate by evidence *family*, not by number of findings or issuer URLs."""
    findings = [
        *assessment.get("financial_findings", []),
        *assessment.get("claim_findings", []),
        *assessment.get("narrative_findings", []),
    ]
    records = {r.get("evidence_id"): r for r in assessment.get("evidence_records", [])
               if r.get("evidence_id")}
    source_families: dict[str, dict[str, Any]] = {}
    for finding in findings:
        for family in finding.get("evidence_families", []):
            entry = source_families.setdefault(family, {
                "family": family, "finding_ids": set(), "issuer_reported": False,
                "independent_third_party": False, "evidence_ids": set(),
                "status_counts": {},
            })
            entry["finding_ids"].add(finding.get("finding_id"))
            status = str(finding.get("status") or "unknown")
            entry["status_counts"][status] = entry["status_counts"].get(status, 0) + 1
            for evidence_id in finding.get("evidence_ids", []):
                evidence = records.get(evidence_id) or {}
                if not evidence:
                    continue
                entry["evidence_ids"].add(evidence_id)
                if evidence.get("independence") == "independent_third_party":
                    entry["independent_third_party"] = True
                elif evidence.get("independence") in ("issuer_self_reported", "regulator_published_issuer_data"):
                    entry["issuer_reported"] = True
    families = [
        {**item, "finding_ids": sorted(x for x in item["finding_ids"] if x),
         "evidence_ids": sorted(item["evidence_ids"])}
        for _, item in sorted(source_families.items())
    ]
    shift = assessment.get("data_shift") or {}
    jsd_ready = shift.get("status") == "comparable" and shift.get("calibration_status") == "calibrated"
    matches = [f for f in findings if f.get("status") == "supported"]
    conflicts = [f for f in findings if f.get("status") == "conflicting"]
    missing = [f for f in findings if f.get("status") in NO_EVIDENCE]
    independent_families = [x["family"] for x in families if x["independent_third_party"]]
    return {
        "method_version": VERSION, "ticker": assessment.get("ticker"),
        "review_mode": assessment.get("review_mode"),
        "finding_count": len(findings),
        "issuer_claim_agreement_count": len(matches),
        "issuer_claim_conflict_count": len(conflicts),
        "insufficient_evidence_count": len(missing),
        "evidence_families": families,
        "distinct_evidence_family_count": len(families),
        "independent_third_party_family_count": len(independent_families),
        "independent_third_party_families": independent_families,
        "narrative": {
            "status": shift.get("status") or "unavailable",
            "calibration_status": shift.get("calibration_status") or "not_evaluated",
            "eligible_for_monitoring": jsd_ready,
            "drift_level": shift.get("drift_level") if jsd_ready else None,
            "note": "JSD/Cosine is document drift, not deception detection or an independent financial source.",
        },
        "limitations": [
            "issuer presentation and MOPS financial filing are both issuer-originated, even if different documents.",
            "an issuer claim agreeing with its own financial filing is not independent third-party verification.",
            "related evidence is grouped by family; the count is not a quantitative confidence score.",
            "a missing or uncalibrated JSD measure is not evidence of no change.",
        ],
        "fraud_probability": None,
        "supply_disruption_probability": None,
        "cross_evidence_verdict": "descriptive_research_only",
    }
