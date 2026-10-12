"""Compose findings into an investigation work queue, deduplicated by evidence family, and B2B due-diligence checks.

Rules are transparent templates (no LLM decides anything). ``investigation_priority`` is a review-queue order,
not a risk level: there is no fraud probability, no supply-disruption probability and no high/low alert.
Findings that rest on the same underlying figures (same evidence family) are cited, never counted twice; issuer
documents and regulator-published issuer filings are never counted as independent third-party corroboration.
"""

from __future__ import annotations

from typing import Any

from app.services.integrity.contracts import FindingFamily, FindingStatus, ReviewQueue

COMPOSER_VERSION = "integrity_composer_v2"
QUEUE_RULE_VERSION = "integrity_review_queue_rule_v2"
QUEUE_RULE = ("requires_verification if any finding meets its documented document-request rule (F1 gap above the "
              "uncalibrated heuristic, or a conflicting issuer claim); otherwise monitor if any finding asks for "
              "monitoring (F2 latest-year CFO below net income); otherwise insufficient_evidence when no financial "
              "check could be computed for the latest fiscal year; otherwise no_item_triggered (which is not a "
              "low-risk statement). A finding whose latest fiscal year is not computable is stale: it only queues "
              "insufficient_evidence and its older computable year never triggers or clears the present-day queue.")
_RANK = {ReviewQueue.requires_verification.value: 0, ReviewQueue.monitor.value: 1}


def claim_finding(check: dict[str, Any]) -> dict[str, Any]:
    verdict = check["verdict"]
    queue = ReviewQueue.requires_verification.value if verdict == FindingStatus.conflicting.value else (
        ReviewQueue.insufficient_evidence.value if verdict in (FindingStatus.insufficient_evidence.value,
                                                               FindingStatus.inconclusive.value) else None)
    parsed = check.get("parsed_claim") or {}
    families = {"revenue": "revenue", "net_income": "net_income", "operating_cash_flow": "operating_cash_flow",
                "accounts_receivable": "receivables"}
    family = families.get(str(parsed.get("metric") or ""), str(parsed.get("metric") or "unknown"))
    statement = check.get("statement") or {}
    return {
        "finding_id": f"F3_ISSUER_CLAIM:{check['claim_id']}", "check_id": "F3_ISSUER_CLAIM_VERIFICATION",
        "family": FindingFamily.source_discrepancy.value, "title": "發行人簡報主張與申報財報比對（F3）",
        "status": verdict, "review_queue": queue, "implementation_tier": "implemented",
        "method_version": "integrity_claims_adapter_v1+claim_verification_service", "literature_basis": None,
        "period": parsed.get("period"), "evidence_families": [family, "issuer_presentation"],
        "evidence_ids": [f"claim:{check['claim_id']}"] + [e["evidence_id"] for e in check.get("evidence", [])],
        "inputs": {"excerpt": statement.get("excerpt"), "page": statement.get("page"),
                   "document": statement.get("document"), "normalized_claim": check.get("normalized_claim")},
        "formula": "existing deterministic claim verifier, then printed-precision check |official − claimed| ≤ ½ unit",
        "computed": {"precision_check": check.get("precision_check"), "reason_code": check.get("reason_code")},
        "heuristic": None, "series": [], "reasons": [r for r in [check.get("reason_code")] if r],
        "legitimate_explanations": ["簡報為初步（未查核）數字，年報可能有期後調整", "四捨五入或單位換算差異"],
        "limitations": [t for t in check.get("limitations", []) + [check.get("corroboration", {}).get("explanation")] if t],
        "not_independent_of": [],
    }


def narrative_finding(shift: dict[str, Any]) -> dict[str, Any] | None:
    """Only a calibrated, compatible JSD result can enter the work queue (monitor), never as a risk level."""
    if shift.get("calibration_status") != "calibrated" or not shift.get("drift_level"):
        return None
    dual = "雙指標" in str(shift["drift_level"])
    return {
        "finding_id": f"NARRATIVE_SHIFT:{shift.get('period_2')}", "check_id": "JSD_NARRATIVE_SHIFT",
        "family": FindingFamily.narrative_change.value, "title": "官方文件跨期文字分布變化（JSD／Cosine）",
        "status": FindingStatus.descriptive_gap.value, "review_queue": ReviewQueue.monitor.value if dual else None,
        "implementation_tier": "implemented", "method_version": str((shift.get("method") or {}).get("method_version")),
        "literature_basis": None, "period": shift.get("period_2"), "evidence_families": ["conference_text"],
        "evidence_ids": [d.get("sha256") for d in shift.get("source_documents", [])], "inputs": {},
        "formula": "teammate combined rule: JSD ≥ historical P90 AND Cosine ≤ historical P10",
        "computed": {"metrics": shift.get("metrics"), "drift_level": shift.get("drift_level")}, "heuristic": None,
        "series": [], "reasons": [], "legitimate_explanations": ["產品組合、季節或簡報格式改版"],
        "limitations": shift.get("limitations", []), "not_independent_of": [],
    }


def data_quality_findings(facts: dict[str, Any]) -> list[dict[str, Any]]:
    findings = []
    for issue in facts.get("quality", []):
        findings.append({
            "finding_id": f"DATA_QUALITY:{issue['concept']}:{issue['fiscal_period']}", "check_id": "DATA_QUALITY",
            "family": FindingFamily.data_quality.value, "title": "同一期間同一科目存在不一致的重複數值",
            "status": FindingStatus.not_comparable.value, "review_queue": ReviewQueue.insufficient_evidence.value,
            "implementation_tier": "implemented", "method_version": "integrity_facts_adapter_v1",
            "literature_basis": None, "period": issue["fiscal_period"], "evidence_families": [issue["concept"]],
            "evidence_ids": issue["evidence_ids"], "inputs": {"values": issue["values"]}, "formula": None,
            "computed": {}, "heuristic": None, "series": [], "reasons": ["conflicting_duplicate_values"],
            "legitimate_explanations": ["不同版本或不同擷取批次"], "limitations": ["兩個數值都不採用（fail closed）。"],
            "not_independent_of": [],
        })
    return findings


def investigation_priority(findings: list[dict[str, Any]], records: dict[str, dict[str, Any]],
                           paper_models: list[dict[str, Any]]) -> dict[str, Any]:
    triggering = [f for f in findings if f.get("review_queue") in _RANK]
    triggering.sort(key=lambda f: (_RANK[f["review_queue"]], f["finding_id"]))
    financial = [f for f in findings if f["check_id"] in ("F1_REVENUE_RECEIVABLES_ALIGNMENT", "F2_NET_INCOME_CFO_ALIGNMENT")]
    computed_financial = [f for f in financial if f.get("freshness_status", "current") == "current" and f["status"] in (
        FindingStatus.descriptive_divergence.value, FindingStatus.within_screening_heuristic.value,
        FindingStatus.descriptive_gap.value)]
    stale = [f["finding_id"] for f in financial if f.get("freshness_status") == "latest_period_not_computable"]
    if any(f["review_queue"] == ReviewQueue.requires_verification.value for f in triggering):
        queue = ReviewQueue.requires_verification.value
    elif triggering:
        queue = ReviewQueue.monitor.value
    elif not computed_financial:
        queue = ReviewQueue.insufficient_evidence.value
    else:
        queue = ReviewQueue.no_item_triggered.value
    # Evidence-family deduplication: a family counts once however many findings / model components cite it.
    family_citations: dict[str, list[str]] = {}
    for finding in triggering:
        for family in finding["evidence_families"]:
            family_citations.setdefault(family, []).append(finding["finding_id"])
    computed_components = {m["model_id"] for m in paper_models if m.get("status") == "computed"}
    for finding in triggering:
        for reference in finding.get("not_independent_of", []):
            if reference.split(":")[0] in computed_components:
                for family in finding["evidence_families"]:
                    family_citations.setdefault(family, []).append(reference)
    independent = sorted({eid for f in triggering for eid in f["evidence_ids"]
                          if records.get(eid, {}).get("independence") == "independent_third_party"})
    return {
        "rule_version": QUEUE_RULE_VERSION, "rule": QUEUE_RULE, "queue": queue,
        "triggered_by": [{"finding_id": f["finding_id"], "review_queue": f["review_queue"], "status": f["status"]}
                         for f in triggering],
        "distinct_evidence_families": sorted(family_citations),
        "evidence_family_citations": {family: sorted(set(ids)) for family, ids in sorted(family_citations.items())},
        "distinct_evidence_family_count": len(family_citations),
        "independent_third_party_corroboration_count": len(independent),
        "stale_findings": stale,
        "meaning": "查核優先順序（需要補件確認／持續監測／資料不足），不是舞弊機率或風險等級。",
        "fraud_probability": None,
    }


# ------------------------------------------------------------------------------------- B2B next checks
def next_checks(findings: list[dict[str, Any]], shift: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(check_id: str, finding: dict[str, Any] | None, condition: str, question: str, documents: list[str],
            rationale: str) -> None:
        checks.append({"check_id": check_id, "triggered_by": finding["finding_id"] if finding else None,
                       "condition": condition, "question_for_counterparty": question,
                       "documents_to_request": documents, "rationale": rationale,
                       "is_risk_conclusion": False})

    by_check = {f["check_id"]: f for f in findings}
    f1 = by_check.get("F1_REVENUE_RECEIVABLES_ALIGNMENT")
    if f1 and f1["status"] == FindingStatus.descriptive_divergence.value:
        c = f1["computed"]
        add("B2B_AR_TERMS", f1,
            f"{f1['period']} 應收帳款成長 {c.get('ar_growth')}，營收成長 {c.get('sales_growth')}，"
            f"差距 {c.get('gap_percentage_points')} 個百分點（超過未校準篩檢門檻）",
            "應收帳款增加是否來自付款條件／授信期間變更、特定大客戶或期末集中出貨？",
            ["應收帳款帳齡表（本期與前期期末）", "前十大客戶授信條件與變更紀錄", "期後收款明細", "關係人應收帳款明細"],
            "簽約或授信前確認對方收款品質；本項只表示需要補件，不代表財報不實。")
    elif f1 and f1["status"] == FindingStatus.within_screening_heuristic.value:
        add("B2B_AR_BASELINE", f1,
            f"{f1['period']} 應收與營收成長差距 {f1['computed'].get('gap_percentage_points')} 個百分點（未超過篩檢門檻）",
            "可選：請對方說明主要客戶付款條件是否於近期調整。", ["最近一期應收帳款帳齡表"],
            "未觸發篩檢項目不等於低風險，仍可作為一般盡職調查。")
    f2 = by_check.get("F2_NET_INCOME_CFO_ALIGNMENT")
    for finding in (f1, f2):
        if finding and finding.get("freshness_status") == "latest_period_not_computable":
            history = finding.get("last_computable") or {}
            add("B2B_LATEST_PERIOD_DATA", finding,
                f"{finding['period']} 為最新年度但無法計算（{', '.join(finding['reasons'][1:]) or '資料不足'}）；"
                f"較早的 {history.get('period', '—')} 結果只供歷史參考",
                "請提供最新年度完整財務報表（含應收帳款與現金流量表），以便重新檢查。",
                ["最新年度經查核財務報告"], "最新年度不足時，不以較早年度的結果作為目前的查核結論。")
    if f2 and f2["status"] == FindingStatus.descriptive_gap.value and f2["computed"].get("direction") == "cfo_below_net_income":
        streak = f2["computed"].get("consecutive_latest_years_cfo_below_net_income")
        add("B2B_WORKING_CAPITAL", f2, f"{f2['period']} 營業現金流低於淨利（連續 {streak} 年）",
            "淨利與營業現金流差距來自哪些營運資金項目或非現金損益？",
            ["現金流量表營運資金變動附註", "存貨與應收帳款週轉資料", "一次性損益說明"],
            "了解獲利的現金實現程度；差距本身不代表異常。")
    for finding in findings:
        if finding["check_id"] == "F3_ISSUER_CLAIM_VERIFICATION" and finding["status"] == FindingStatus.conflicting.value:
            add("B2B_CLAIM_BASIS", finding, f"簡報主張與申報財報不一致（{finding['period']}）",
                "主張數字的口徑（合併／個體、期間、未查核／已查核）與計算方式為何？",
                ["主張所引用之完整簡報頁", "對應期間經查核財報"],
                "比對口徑後才可判斷差異原因；不一致不等於造假。")
        if finding["check_id"] == "F3_ISSUER_CLAIM_VERIFICATION" and finding["status"] == FindingStatus.supported.value:
            add("B2B_INDEPENDENT_CONFIRMATION", finding, "簡報數字與申報財報一致（同一發行人自報）",
                "若交易金額重大，是否能取得會計師查核報告或第三方確認（如銀行往來證明）？", ["會計師查核報告", "第三方確認文件"],
                "同源一致不構成獨立佐證。")
    if shift.get("status") != "comparable" or shift.get("calibration_status") != "calibrated":
        add("B2B_NARRATIVE_NOT_USED", None, "文字差異未校準或不可比較", "（不需向對方詢問）",
            [], "JSD／Cosine 未校準時不作為查核依據，也不代表文字無變化。")
    add("B2B_NO_NETWORK_INFERENCE", None, "未提供經查證之往來關係", "（使用者如有實際往來，可自行提供交易對手清單）", [],
        "沒有已證實的供應關係或使用者明示輸入時，不估計停供或供應鏈中斷機率。")
    return checks
