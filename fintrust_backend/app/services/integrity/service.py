"""Financial Integrity Workbench orchestration (Phase 1, preview only, read-only).

``CURRENT_REVIEW`` reviews the information archived now. It is not a point-in-time reconstruction: publication
instants of the pipeline facts are not recorded, so ``STRICT_AS_OF`` is refused (409) rather than approximated.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.services.integrity import adapters as ad
from app.services.integrity import alignment as al
from app.services.integrity import composer as cp
from app.services.integrity import financial_checks as fc
from app.services.integrity import nfm_evidence_bridge as nfm
from app.services.integrity.contracts import (
    CONTRACT_VERSION,
    METHOD_APPROVAL,
    AssessmentRequest,
    ClaimCheck,
    DataShift,
    EvidenceRecord,
    Finding,
    Independence,
    PaperModel,
    ReviewMode,
    Section,
)

DISCLAIMERS = [
    "本頁為財務可信度查核輔助（screening / due diligence support），不是舞弊認定、不是投資建議，也不輸出舞弊機率。",
    "所有數字為發行人自行申報或自行發布；經 MOPS 公告不等於銀行、客戶或第三方獨立查證。",
    "「不可計算」「資料不足」「未觸發」都不代表低風險。",
    "研究方法（文獻移植、台灣會計對照、門檻）仍待方法負責人審核：DRAFT_PENDING_METHOD_OWNER_REVIEW。",
]


ASSUMPTIONS = [
    "合併口徑由 MOPS t164sb01 下載連結的 report_id=C 推定（僅在已審查樣本確認）。",
    "會計年度假設 12 月 31 日結束（已審查公司皆為曆年制）。",
    "管線事實沒有來源檔 SHA-256 與公告時間；因此不支援 STRICT_AS_OF。",
    "只有通過驗證的 MOPS 申報連結（HTTPS、白名單主機與路徑、co_id 與公司代號一致）才會取得官方來源身分。",
]


class UnsupportedTicker(LookupError):
    pass


class ReviewModeNotSupported(ValueError):
    def as_dict(self) -> dict[str, Any]:
        return {"error_code": "review_mode_not_supported", "message": str(self),
                "supported_modes": [ReviewMode.CURRENT_REVIEW.value]}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _claim_record(check: dict[str, Any], ticker: str, issuer: str | None,
                  registry: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    from app.services.verifier import MONEY_SCALES

    statement = check.get("statement") or {}
    if not statement or not check.get("source_verification", {}).get("verified"):
        return None
    expected = registry.get(check["claim_id"], {}).get("expected_parse", {})
    scale = MONEY_SCALES.get(expected.get("unit") or "")
    value = al.to_decimal(expected.get("value"))
    value_twd = value * al.to_decimal(repr(float(scale))) if value is not None and scale is not None else None
    parsed = al.parse_period(expected.get("period") or "")
    family = {"accounts_receivable": "receivables"}.get(expected.get("metric"), expected.get("metric") or "unknown")
    return {
        "evidence_id": f"claim:{check['claim_id']}", "ticker": ticker, "fiscal_period": expected.get("period") or "unknown",
        "period_start": parsed["start"], "period_end": parsed["end"], "period_type": parsed["period_type"],
        "document_type": statement.get("document_type") or "unknown", "language": statement.get("language"),
        "concept": expected.get("metric") or "unknown", "source_concept": statement.get("excerpt"),
        "value": expected.get("value"), "unit": expected.get("unit"), "value_twd": al.text(value_twd),
        "scope": "unknown", "scope_basis": "presentation_scope_not_recorded_in_registry",
        "filing_version": None, "filing_policy": "issuer_presentation_preliminary",
        "issuer": issuer, "publisher": "公開資訊觀測站（TWSE MOPS）法說會資料",
        "independence": Independence.issuer_self_reported.value, "source_sha256": statement.get("document_sha256"),
        "source_identity": f"{statement.get('document')}#page={statement.get('page')}", "source_url": None,
        "locator": {"document": statement.get("document"), "page": statement.get("page"),
                    "excerpt": statement.get("excerpt"), "context_excerpt": statement.get("context_excerpt")},
        "published_at": statement.get("published_on"), "effective_available_at": statement.get("published_on"),
        "effective_available_at_precision": "date", "ingested_at": None,
        "provenance": "archived_mops_conference_pdf_page_text", "evidence_family": family,
        "method_version": ad.CLAIMS_ADAPTER_VERSION, "pit_eligible": True,
        "pit_reason": "date_precision_admitted_only_after_end_of_day_asia_taipei",
        "missing_fields": ["source_url", "ingested_at", "filing_version"],
        "source_trust": "archived_issuer_document",
    }


class IntegrityWorkbench:
    def __init__(self, repository: Any, *, jsd_bridge: Any | None = None, conference_repository: Any | None = None,
                 claim_service: Any | None = None, literature_database: str | None = None,
                 nfm_records: list[dict[str, Any]] | None = None) -> None:
        self.repository = repository
        self.facts = ad.FactsAdapter(repository)
        self.literature = ad.LiteratureAdapter(literature_database)
        self.jsd = ad.JsdAdapter(jsd_bridge)
        self.claims = ad.ClaimsAdapter(conference_repository, claim_service)
        self.sources = ad.OfficialSourcesAdapter(repository)
        self.conference_repository = conference_repository
        self.nfm_records = nfm_records or []  # default is empty until official document review

    def _nfm_for_ticker(self, ticker: str) -> list[dict[str, Any]]:
        """The shared archive can hold many companies; the strict checker receives one company only."""
        return [record for record in self.nfm_records
                if isinstance(record, dict) and record.get("ticker") == ticker]

    # ------------------------------------------------------------------------------------- companies
    @staticmethod
    def resolve(ticker: str) -> Any:
        from app.services.company_registry import SEED_COMPANIES

        company = SEED_COMPANIES.get(ticker)
        if company is None:
            raise UnsupportedTicker(ticker)
        return company

    def companies(self) -> list[dict[str, Any]]:
        from app.services.company_registry import SEED_COMPANIES

        out = []
        for ticker, company in sorted(SEED_COMPANIES.items()):
            try:
                snapshot = self.repository.get_latest_snapshot(ticker)
            except Exception as exc:
                raise ad.IntegrityDataUnavailable(f"repository unavailable: {type(exc).__name__}") from exc
            out.append({"ticker": ticker, "name": company.name, "subindustry": company.subindustry,
                        "persisted_snapshot": snapshot is not None})
        return out

    def readiness(self, ticker: str) -> dict[str, Any]:
        company = self.resolve(ticker)
        facts = self.facts.collect(ticker)
        index = facts["index"]
        years = sorted({y for _m, y in index})
        f1 = fc.check_revenue_receivables(index)
        f2 = fc.check_net_income_cfo(index)
        f4 = nfm.check_revenue_nfm_strict(index, self._nfm_for_ticker(ticker), ticker=ticker)
        count, store_problem = self.literature.frozen_observation_count(ticker)
        registry = [s for s in ad.load_registry(self.claims.registry_path).get("statements", [])
                    if s.get("ticker") == ticker]
        jsd_docs = None
        if self.conference_repository is not None:
            try:
                from app.services.conference_jsd_corpus_adapter import build_records, comparable_pairs

                records = build_records(self.conference_repository, ticker)
                jsd_docs = {"documents": len(records), "jsd_ready": sum(1 for r in records if r.jsd_ready),
                            "comparable_pairs": len(comparable_pairs(records))}
            except Exception as exc:
                jsd_docs = {"error": type(exc).__name__}
        return {
            "ticker": ticker, "company": company.name, "subindustry": company.subindustry,
            "review_modes": {"CURRENT_REVIEW": "supported", "STRICT_AS_OF": "not_supported_publication_times_unknown"},
            "modules": {
                "financial_facts": {"annual_years": years, "annual_records": len(index),
                                    "excluded_records": len(facts["excluded"]),
                                    "availability": "available" if index else "unavailable"},
                "F1_revenue_receivables": {"status": f1["status"], "period": f1["period"]},
                "F2_net_income_cfo": {"status": f2["status"], "period": f2["period"]},
                "F4_revenue_nfm": {"status": f4["status"], "reason": ", ".join(f4["reasons"]) or None,
                                   "method_version": nfm.BRIDGE_VERSION},
                "literature_models": {"availability": "not_computable", "frozen_observation_count": count,
                                      "reason": store_problem or ("no_frozen_literature_inputs_for_ticker" if not count
                                                                  else "historical_research_case_only")},
                "issuer_claims": {"registered_statements": len(registry)},
                "jsd": {"archive_configured": self.conference_repository is not None, **(jsd_docs or {})},
            },
            "method_approval": METHOD_APPROVAL, "contract_version": CONTRACT_VERSION,
        }

    # ------------------------------------------------------------------------------------- assessment
    def assess(self, request: AssessmentRequest) -> dict[str, Any]:
        if request.review_mode != ReviewMode.CURRENT_REVIEW:
            raise ReviewModeNotSupported(
                "STRICT_AS_OF is not served in Phase 1: the persisted facts carry no verified publication instant, "
                "so no input could be admitted before a cutoff. Use CURRENT_REVIEW.")
        company = self.resolve(request.ticker)
        sections = set(request.sections)
        facts = self.facts.collect(request.ticker)
        index = facts["index"]
        years = sorted({y for _m, y in index})
        latest_year = years[-1] if years else None
        missing: list[dict[str, Any]] = []

        findings: list[dict[str, Any]] = []
        if Section.financial_checks in sections:
            findings += [fc.check_revenue_receivables(index), fc.check_net_income_cfo(index),
                         nfm.check_revenue_nfm_strict(index, self._nfm_for_ticker(request.ticker), ticker=request.ticker)]
            findings += cp.data_quality_findings(facts)
            for finding in findings:
                if finding["status"] in ("not_computable", "not_comparable", "unavailable"):
                    missing.append({"section": "financial_checks", "item": finding["check_id"],
                                    "reasons": finding["reasons"]})

        paper_models: list[dict[str, Any]] = []
        literature_meta: dict[str, Any] = {}
        if Section.literature in sections:
            literature = self.literature.assess(request.ticker, latest_year, index)
            paper_models = literature["models"]
            literature_meta = {k: v for k, v in literature.items() if k != "models"}
            missing.append({"section": "literature", "item": "beneish_1999_full8_v1 / dechow_2011_model1_v1",
                            "reasons": [literature["reason"]]})

        shift: dict[str, Any] = {}
        if Section.jsd in sections:
            shift = self.jsd.assess(request.ticker)
            if shift["status"] != "comparable" or shift["calibration_status"] != "calibrated":
                missing.append({"section": "jsd", "item": "drift_level",
                                "reasons": [shift.get("reason") or shift["status"]]})
            narrative = cp.narrative_finding(shift)
            if narrative:
                findings.append(narrative)

        claim_checks: list[dict[str, Any]] = []
        claims_meta: dict[str, Any] = {}
        if Section.claims in sections:
            claims = self.claims.assess(request.ticker, index)
            claim_checks = claims["checks"]
            claims_meta = {k: v for k, v in claims.items() if k != "checks"}
            findings += [cp.claim_finding(check) for check in claim_checks]
            if not claim_checks:
                missing.append({"section": "claims", "item": "issuer_statements", "reasons": [claims["reason"]]})

        records = {r["evidence_id"]: ad.public_record(r) for r in index.values()}
        registry = ({s["statement_id"]: s for s in ad.load_registry(self.claims.registry_path).get("statements", [])}
                    if claim_checks else {})
        for check in claim_checks:
            record = _claim_record(check, request.ticker, company.name, registry)
            if record:
                records[record["evidence_id"]] = record
        records = {eid: EvidenceRecord.model_validate(r).model_dump(mode="json") for eid, r in sorted(records.items())}

        sources = self.sources.assess(request.ticker)
        overview_rows = [
            {"fiscal_period": rec["fiscal_period"], "metric": rec["concept"], "value_twd": rec["value_twd"],
             "unit_as_stored": rec["unit"], "scope": rec["scope"], "filing_version": rec["filing_version"],
             "source_url": rec["source_url"], "evidence_id": rec["evidence_id"]}
            for (metric, _year), rec in sorted(index.items(), key=lambda kv: (kv[0][1], kv[0][0]))
            if metric in ad.OVERVIEW_METRICS]
        ingested = sorted(filter(None, (r.get("ingested_at") for r in records.values())))
        priority = cp.investigation_priority(findings, records, paper_models)
        validated_findings = [Finding.model_validate(f).model_dump(mode="json") for f in findings]
        payload_inputs = {"evidence_records": records, "registry_sha256": ad.registry_sha256(self.claims.registry_path),
                          "f1_heuristic": fc.f1_heuristic()}
        response = {
            "contract_version": CONTRACT_VERSION, "ticker": request.ticker, "company": company.name,
            "subindustry": company.subindustry, "review_mode": request.review_mode.value,
            "temporal_basis": "latest_archived_information_at_request_time",
            "point_in_time_supported": False, "hindsight": False,
            "hindsight_note": "CURRENT_REVIEW 檢視目前已歸檔資訊，不能用來主張過去任一時點當時可知的內容。",
            "generated_at": datetime.now(timezone.utc).isoformat(), "persist": False,
            "sections": sorted(s.value for s in sections),
            "data_latest_available_at": None,
            "data_latest_available_at_note": "pipeline facts do not record publication instants",
            "data_latest_ingested_at": ingested[-1] if ingested else None,
            "method_approval": METHOD_APPROVAL, "disclaimers": DISCLAIMERS, "assumptions": ASSUMPTIONS,
            "freshness": {
                "latest_fact_fiscal_year": fc.latest_fact_year(index),
                "stale_findings": [f["finding_id"] for f in validated_findings
                                   if f.get("freshness_status") == "latest_period_not_computable"],
                "rule": "the current review describes the latest fiscal year; an older computable year is history only",
            },
            "source_coverage": {
                "annual_years": years, "annual_fact_records": len(index), "excluded_fact_records": facts["excluded"],
                "official_sources": {k: sources.get(k) for k in ("status", "readiness", "live_fetch",
                                                                 "non_allowlisted_links_withheld")},
                "issuer_statements": {"registered": len(claim_checks), **claims_meta},
                "jsd": {"status": shift.get("status"), "calibration_status": shift.get("calibration_status")},
                "literature": literature_meta,
                "independent_third_party_sources": 0,
            },
            "financial_overview": {"currency": "TWD", "rows": overview_rows, "official_sources": sources},
            "paper_models": [PaperModel.model_validate(m).model_dump(mode="json") for m in paper_models],
            "financial_findings": [f for f in validated_findings if f["check_id"].startswith(("F1", "F2", "F4"))
                                   or f["family"] == "data_quality"],
            "claim_checks": [ClaimCheck.model_validate(c).model_dump(mode="json") for c in claim_checks],
            "claim_findings": [f for f in validated_findings if f["check_id"] == "F3_ISSUER_CLAIM_VERIFICATION"],
            "narrative_findings": [f for f in validated_findings if f["family"] == "narrative_change"],
            "data_shift": DataShift.model_validate(shift).model_dump(mode="json") if shift else None,
            "evidence_records": list(records.values()),
            "investigation_priority": priority,
            "next_checks": cp.next_checks(findings, shift),
            "missing_data": missing,
            "method_versions": {
                "contract": CONTRACT_VERSION, "alignment": al.ALIGNMENT_VERSION, "f1": fc.F1_VERSION,
                "f1_heuristic": fc.F1_HEURISTIC_VERSION, "f2": fc.F2_VERSION, "f4": nfm.BRIDGE_VERSION,
                "composer": cp.COMPOSER_VERSION, "review_queue_rule": cp.QUEUE_RULE_VERSION,
                "facts_adapter": ad.FACTS_ADAPTER_VERSION, "literature_adapter": ad.LITERATURE_ADAPTER_VERSION,
                "jsd_adapter": ad.JSD_ADAPTER_VERSION, "claims_adapter": ad.CLAIMS_ADAPTER_VERSION,
                "literature_method_registry": literature_meta.get("method_registry_version"),
                "jsd_method": (shift.get("method") or {}).get("method_version"),
            },
            "dependency_digests": {
                "input_digest": _digest(payload_inputs),
                "evidence_records_digest": _digest(records),
                "issuer_statement_registry_sha256": ad.registry_sha256(self.claims.registry_path),
                "jsd_calculator_module_sha256": (shift.get("method") or {}).get("calculator_module_sha256"),
            },
        }
        return response
