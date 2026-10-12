"""1785 光洋科 retrospective case view (``RETROSPECTIVE_CASE``) for the Integrity Workbench — read-only.

Reuses the accepted historical research layer in-process: ``ResearchService.build_run`` (dry run, never persisted)
recomputes the Beneish (1999) / Dechow et al. (2011) comparison with the unchanged engines on the frozen literature
inputs, and its run id is compared with the accepted 872c856 evidence. ``STRICT_AS_OF`` at the 2016-05-13 public
revelation is computed the same way to show, honestly, that no published score was available before the event.

This mode is never mixed with ``CURRENT_REVIEW``: it serves only the registered research case, includes later
restated filings (hindsight), and is not a pre-event prediction. Events come from the teammate research slides
(``case_1785_events.json``) and are shown as verified only when an archived official record carries them.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.services.integrity import alignment as al
from app.services.integrity.contracts import METHOD_APPROVAL

CASE_VERSION = "integrity_case_1785_view_v1"
CASE_TICKER = "1785"
REVIEW_MODE = "RETROSPECTIVE_CASE"
VERSION_POLICIES = ("latest_available", "original_only")
START_YEAR, END_YEAR = 2011, 2025
STRICT_CUTOFF = "2016-05-13T00:00:00+08:00"
BANNER = "事後研究／包含後續申報版本，不代表事件曝光前可用資訊"
EVENT_REGISTRY_PATH = Path(__file__).with_name("case_1785_events.json")
# Accepted literature evidence (872c856, handoff_r0102): run ids and the 60-cell baseline.
ACCEPTED_RUNS = {"latest_available": "rrun1_3aee901dc66e02346710d41e9fd0bc02",
                 "original_only": "rrun1_2120551b6b6763dd65b49439602a28f4"}
ACCEPTED_BASELINE = {"cells": 60, "computed": 26, "not_computable": 34,
                     "withdrawn_latest_available_dechow": [2015, 2023], "original_only_dechow_fy2012": "0.892005"}
MODELS = {"beneish_1999_full8_v1": "Beneish (1999) M-Score（8 變數）",
          "dechow_2011_model1_v1": "Dechow, Ge, Larson & Sloan (2011) F-Score Model 1"}
TRACKED = {"GMI": "beneish_1999_full8_v1", "TATA": "beneish_1999_full8_v1", "ch_inv": "dechow_2011_model1_v1",
           "rsst_acc": "dechow_2011_model1_v1", "soft_assets": "dechow_2011_model1_v1"}
PAGE_RE = re.compile(r"pdf_page=(\d+)")
MAX_OBSERVATIONS_PER_COMPONENT = 4  # bounded payload; the full list stays in the research run


class UnsupportedResearchCase(LookupError):
    pass


def _probability(row: dict[str, Any]) -> str | None:
    return row.get("probit_probability_original_sample") or row.get("probability_original_model")


def _observations(component: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for item in component.get("inputs") or []:
        for obs in item.get("source_observations") or []:
            page = PAGE_RE.search(str(obs.get("locator") or ""))
            out.append({"metric": item.get("metric"), "relative_period": item.get("relative_period"),
                        "fiscal_year": item.get("fiscal_year"), "observation_id": obs.get("observation_id"),
                        "line_key": obs.get("line_key"), "published_value": obs.get("published_value"),
                        "published_unit": obs.get("published_unit"), "raw_sha256": obs.get("raw_sha256"),
                        "pdf_page": int(page.group(1)) if page else None,
                        "extraction_method": obs.get("extraction_method"),
                        "source_url": al.official_url(obs.get("source_url"))})
    return out


def _cell(row: dict[str, Any]) -> dict[str, Any]:
    components = row.get("components") or []
    missing = row.get("missing_inputs") or []
    return {
        "model_id": row.get("model_id"), "fiscal_year": row.get("fiscal_year"), "status": row.get("status"),
        "score": row.get("score"), "score_exact": row.get("score_exact"), "score_kind": row.get("score_kind"),
        "probability_original_model": _probability(row),
        "component_coverage": row.get("component_coverage"),
        "components": [{"variable": c.get("variable"), "status": c.get("status"), "value": c.get("value"),
                        "reasons": [r.get("code") if isinstance(r, dict) else r for r in c.get("reasons") or []],
                        "observations": (obs := _observations(c))[:MAX_OBSERVATIONS_PER_COMPONENT],
                        "observations_total": len(obs),
                        "input_metrics": sorted(f"{i.get('metric')}@{i.get('relative_period')}" for i in c.get("inputs") or []
                                                if i.get("status") == "computed")} for c in components],
        "missing_reasons": sorted({m.get("status") for m in missing if m.get("status")}
                                  | {str(r) for r in row.get("reasons") or []}),
        "missing_inputs": [{k: m.get(k) for k in ("component", "metric", "relative_period", "fiscal_year", "status")}
                           for m in missing][:60],
        "filing_versions": [{k: (al.official_url(v.get(k)) if k == "source_url" else v.get(k)) for k in (
            "filing_version_id", "fiscal_year", "filing_version_type", "statement_scope", "accounting_framework",
            "content_hash", "available_at", "availability_status", "source_url")}
            for v in row.get("input_filing_versions") or [] if isinstance(v, dict)],
        "observation": {k: (row.get("observation") or {}).get(k) for k in (
            "filing_version_id", "filing_version_type", "accounting_framework", "statement_scope", "version_policy")},
        "source_observation_ids": row.get("source_observation_ids") or [],
        "zero_evidence_used": row.get("zero_evidence_used"),
        "validation_warnings": row.get("validation_warnings"),
    }


def _component(cell: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((c for c in cell["components"] if c["variable"] == name), None)


def _inventory_turnover_readiness(beneish: dict[str, Any] | None, dechow: dict[str, Any] | None) -> dict[str, Any]:
    """COGS_t / average(inventory_t, inventory_t-1) needs all three from the same frozen filing; readiness only."""
    gmi = _component(beneish, "GMI") if beneish else None
    inv = _component(dechow, "ch_inv") if dechow else None
    cogs = "cogs@t" in (gmi or {}).get("input_metrics", [])
    stock = {p: f"inventory@{p}" in (inv or {}).get("input_metrics", []) for p in ("t", "t-1")}
    missing = [name for name, ok in (("cogs_t", gmi and gmi["status"] == "computed" and cogs),
                                     ("inventory_t", inv and inv["status"] == "computed" and stock["t"]),
                                     ("inventory_t_minus_1", inv and inv["status"] == "computed" and stock["t-1"])) if not ok]
    filings = {v["filing_version_id"] for cell in (beneish, dechow) if cell for v in cell.get("filing_versions", [])}
    same_filing = len({(beneish or {}).get("observation", {}).get("filing_version_id"),
                       (dechow or {}).get("observation", {}).get("filing_version_id")} - {None}) == 1
    return {"status": "inputs_available_same_filing" if not missing and same_filing else "not_ready",
            "missing": missing + ([] if same_filing or missing else ["inputs_not_from_one_filing"]),
            "filing_version_ids": sorted(filings), "value": None,
            "note": "readiness_only：存貨科目對照仍為 DRAFT，未經方法負責人核准前不計算週轉率數值。"}


def crosswalk_rows() -> list[dict[str, Any]]:
    """Method → case question → implementation → evidence → limitations (slide page 11 feature mapping)."""
    return [
        {"feature": "GMI", "method": "Beneish (1999) Gross Margin Index", "source": "literature_engine",
         "case_question": "毛利率是否惡化（成本或損失未於適當期間認列，可能使毛利高估）", "slide_page": 11,
         "implementation": "implemented", "tier": "engine_component",
         "evidence": "Beneish 引擎 GMI 元件：營收與營業成本（t、t−1）凍結官方輸入", "variable": "GMI",
         "limitations": ["事後計算；含後續重編版本（latest_available）", "COMPUSTAT→台灣科目對照為 DRAFT"]},
        {"feature": "TATA", "method": "Beneish (1999) Total Accruals to Total Assets", "source": "literature_engine",
         "case_question": "應計項目是否異常（損失遞延認列）", "slide_page": 11, "implementation": "implemented",
         "tier": "engine_component", "variable": "TATA",
         "evidence": "Beneish 引擎 TATA 元件：資產負債表法應計項目（非現金流量表法）",
         "limitations": ["Beneish 原文以資產負債表變動計算應計，與 CFO−NI 不同", "COMPUSTAT→台灣科目對照為 DRAFT"]},
        {"feature": "ΔInventory", "method": "Dechow et al. (2011) ch_inv", "source": "literature_engine",
         "case_question": "存貨是否出現異常變動（貴金屬存貨跌價認列不足）", "slide_page": 11, "implementation": "implemented",
         "tier": "engine_component", "variable": "ch_inv",
         "evidence": "Dechow 引擎 ch_inv 元件：存貨變動 / 平均總資產", "limitations": ["事後計算；不是事前預警"]},
        {"feature": "RSST Accruals", "method": "Dechow et al. (2011) rsst_acc", "source": "literature_engine",
         "case_question": "應計項目是否有異常變動", "slide_page": 11, "implementation": "implemented",
         "tier": "engine_component", "variable": "rsst_acc",
         "evidence": "Dechow 引擎 rsst_acc 元件（Richardson et al. 2005 應計定義）",
         "limitations": ["需 t、t−1 兩期完整資產負債表科目；缺漏時不可計算"]},
        {"feature": "Soft Assets", "method": "Dechow et al. (2011) soft_assets", "source": "literature_engine",
         "case_question": "資產結構與會計估計空間（研究簡報第 9 頁）", "slide_page": 9, "implementation": "implemented",
         "tier": "engine_component", "variable": "soft_assets",
         "evidence": "Dechow 引擎 soft_assets 元件", "limitations": ["事後計算；不是事前預警"]},
        {"feature": "存貨週轉率", "method": "COGS_t / ((Inventory_t + Inventory_t−1) / 2)", "source": "supplemental_ratio",
         "case_question": "存貨與銷貨成本的關係（存貨管理異常）", "slide_page": 11, "implementation": "readiness_only",
         "tier": "readiness_only", "variable": None,
         "evidence": "只檢查同一凍結申報版本是否同時具備 COGS_t、Inventory_t、Inventory_t−1（各年度見下表）",
         "limitations": ["存貨與營業成本的台灣科目對照仍為 DRAFT；不以單一期末存貨計算",
                         "待方法負責人核准後才輸出數值"]},
        {"feature": "CFO − NI", "method": "營業現金流 − 淨利（延伸財務比率）", "source": "supplemental_ratio",
         "case_question": "營業現金流與淨利是否背離", "slide_page": 11, "implementation": "not_available_in_frozen_inputs",
         "tier": "not_available", "variable": None,
         "evidence": "凍結的文獻輸入對照沒有營業現金流科目（只作為現金流量表身分錨點），因此無法以同一證據基礎計算",
         "limitations": ["正負號：本欄為 CFO − NI，與 Workbench F2 的 NI − CFO 互為相反數",
                         "需要新增經核准的科目對照與重新凍結輸入"]},
    ]


class RetrospectiveCaseService:
    def __init__(self, research_service: Any, registry_path: Path = EVENT_REGISTRY_PATH) -> None:
        self.research = research_service
        self.registry_path = registry_path

    # ------------------------------------------------------------------------------- availability
    def _unavailable(self, reason: str, policy: str) -> dict[str, Any]:
        return {"case_version": CASE_VERSION, "ticker": CASE_TICKER, "review_mode": REVIEW_MODE, "status": "source_unavailable",
                "reason": reason, "version_policy": policy, "banner": BANNER, "persist": False,
                "method_approval": METHOD_APPROVAL, "cells": [], "series": {}, "events": [],
                "instructions": "需要本機已核准的歷史稽核資料庫（historical_audit.sqlite3）與文獻輸入庫"
                                "（literature_inputs.sqlite3）；請由研究資料管理者提供唯讀副本。本頁不會改用其他公司的資料。"}

    def summary(self, ticker: str, version_policy: str) -> dict[str, Any]:
        from app.services.financial_research.modes import build_context

        if ticker != CASE_TICKER:
            raise UnsupportedResearchCase(ticker)
        if version_policy not in VERSION_POLICIES:
            raise ValueError("version_policy")
        try:
            health = self.research.health()
        except Exception as exc:
            return self._unavailable(f"research_layer_error:{type(exc).__name__}", version_policy)
        if not (health.get("dataset_available") and health.get("literature_inputs_available")):
            return self._unavailable("historical_dataset_or_literature_inputs_unavailable", version_policy)
        try:
            retro = build_context("RETROSPECTIVE_FORENSIC")
            runs = {p: self.research.build_run("literature_comparison", CASE_TICKER, retro, start_year=START_YEAR,
                                               end_year=END_YEAR, version_policy=p) for p in VERSION_POLICIES}
            strict = self.research.build_run("literature_comparison", CASE_TICKER, build_context("STRICT_AS_OF", STRICT_CUTOFF),
                                             start_year=START_YEAR, end_year=2016, version_policy="latest_available")
            timeline = self.research.timeline(CASE_TICKER, retro, limit=1000)
            overview = self.research.case_overview(CASE_TICKER)
        except Exception as exc:
            return self._unavailable(f"research_computation_error:{type(exc).__name__}", version_policy)
        run = runs[version_policy]
        models = run["output"]["models"]
        cells = [_cell(row) for model in MODELS for row in models["results"].get(model, [])]
        index = {(c["model_id"], c["fiscal_year"]): c for c in cells}
        years = list(range(START_YEAR, END_YEAR + 1))
        series = {var: [{"fiscal_year": y, **({k: comp[k] for k in ("status", "value", "reasons")}
                                              if (comp := _component(index[(model, y)], var)) else
                                              {"status": index[(model, y)]["status"], "value": None, "reasons": []})}
                        for y in years if (model, y) in index]
                  for var, model in TRACKED.items()}
        turnover = [{"fiscal_year": y, **_inventory_turnover_readiness(index.get(("beneish_1999_full8_v1", y)),
                                                                        index.get(("dechow_2011_model1_v1", y)))}
                    for y in years]
        counts = {}
        for policy, item in runs.items():
            rows = [r for model in MODELS for r in item["output"]["models"]["results"].get(model, [])]
            counts[policy] = {"computed": sum(r["status"] == "computed" for r in rows),
                              "not_computable": sum(r["status"] != "computed" for r in rows), "cells": len(rows)}
        total = {k: sum(c[k] for c in counts.values()) for k in ("computed", "not_computable", "cells")}
        withdrawn = sorted(r["fiscal_year"] for r in runs["latest_available"]["output"]["models"]["results"]
                           ["dechow_2011_model1_v1"] if r["fiscal_year"] in (2015, 2023) and r["status"] != "computed")
        fy2012 = next((r for r in runs["original_only"]["output"]["models"]["results"]["dechow_2011_model1_v1"]
                       if r["fiscal_year"] == 2012), {})
        baseline_check = {
            "accepted": ACCEPTED_BASELINE, "observed": {**total, "withdrawn_latest_available_dechow": withdrawn,
                                                        "original_only_dechow_fy2012": fy2012.get("score")},
            "run_ids_match_accepted": {p: runs[p]["run_id"] == ACCEPTED_RUNS[p] for p in VERSION_POLICIES},
        }
        baseline_check["matches"] = (baseline_check["observed"] == {**ACCEPTED_BASELINE}
                                     and all(baseline_check["run_ids_match_accepted"].values()))
        strict_models = strict["output"]["models"]
        return {
            "case_version": CASE_VERSION, "ticker": CASE_TICKER, "company": overview.get("company_name"),
            "case_id": overview.get("case_id"), "status": "available", "review_mode": REVIEW_MODE,
            "underlying_analysis_mode": "RETROSPECTIVE_FORENSIC", "hindsight": True, "point_in_time_supported": False,
            "banner": BANNER, "persist": False, "method_approval": METHOD_APPROVAL,
            "usage_policy": models.get("usage_policy"),
            "separation": "與 CURRENT_REVIEW（正式公司目前資料）完全分開；本頁只服務已登錄的歷史研究案例，"
                          "不把事後分數用於任何公司的目前查核，也不是事件前預測。",
            "version_policy": version_policy, "fiscal_years": {"start": START_YEAR, "end": END_YEAR},
            "dataset_identity": {
                "run_id": run["run_id"], "input_digest": run["input_digest"], "output_digest": run["output_digest"],
                "method_version": run["method_version"], "accepted_run_id": ACCEPTED_RUNS[version_policy],
                "matches_accepted_run": run["run_id"] == ACCEPTED_RUNS[version_policy],
                "research_layer_version": health.get("research_layer_version"),
                "approved_baseline_commit": health.get("approved_baseline_commit"), "persisted": False},
            "counts": counts, "baseline_check": baseline_check, "models": MODELS, "cells": cells, "series": series,
            "inventory_turnover_readiness": turnover, "crosswalk": crosswalk_rows(),
            "strict_pre_event": {"cutoff_at": STRICT_CUTOFF, "status": strict_models.get("status"),
                                 "counts": strict_models.get("counts"), "note": strict_models.get("strict_note"),
                                 "run_id": strict["run_id"],
                                 "conclusion": "事件公開前（2016-05-13 截點）沒有任何可驗證的文獻模型分數；"
                                               "因此不能宣稱模型曾在事前預警。"},
            "events": self.events(timeline), "event_registry": self._registry_meta(),
            "restatement_evidence": {"restatement_comparisons": (overview.get("coverage") or {}).get("restatement_comparisons"),
                                     "research_view": "historical-research.html#bridge",
                                     "note": "重編前後差異請見既有歷史研究頁「2011–2015 重編橋接」視圖。"},
            "limitations": [
                "事後研究：latest_available 包含後續重編版本，original_only 只用原始申報；兩者都不是事件前可用資訊。",
                "原始申報 FY2012 Dechow 0.892005 依賴 verified_zero（權益區段完整列舉）零值規則，尚待方法負責人核准。",
                "latest_available FY2015、FY2023 Dechow 因跨申報重疊期不一致而撤回（不可計算）。",
                "研究簡報為團隊成員的研究參考，不是已驗證的事件來源；未經官方封存佐證的事件不進入任何計算。",
                "黃金不法轉出（實體資產損失）與 2011–2015 財報重編（多年度報導不實）是不同事件，損失口徑不可相加或等同。",
            ],
        }

    # ------------------------------------------------------------------------------------- events
    def _registry(self) -> dict[str, Any]:
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _registry_meta(self) -> dict[str, Any]:
        registry = self._registry()
        return {k: registry.get(k) for k in ("registry_version", "source_document", "verification_rule",
                                             "incident_distinction", "slide_references_unverified",
                                             "excluded_archive_records")}

    def events(self, timeline: dict[str, Any]) -> list[dict[str, Any]]:
        registry = self._registry()
        excluded = {e["event_key"] for e in registry.get("excluded_archive_records", [])}
        archived: dict[str, list[dict[str, Any]]] = {}
        for row in timeline.get("events", []):
            if row["event_key"] not in excluded:
                archived.setdefault(row["event_key"], []).append(row)

        def records(keys: list[str]) -> list[dict[str, Any]]:
            return [{"event_key": key, "evidence_tier": row["evidence_tier"], "title": row["title"],
                     "publication_at": row["publication_at"], "available_from": row["available_from"],
                     "content_hash": row["content_hash"], "source_url": al.official_url(row["source_url"])}
                    for key in keys for row in archived.get(key, [])]

        out = []
        for event in registry["events"]:
            verifying = records(event["verifying_event_keys"])
            tiers = {r["evidence_tier"] for r in verifying}
            if any(t.startswith("E2") for t in tiers):
                status = "verified_official_document"
            elif tiers:
                status = "official_listing_only"
            else:
                status = "needs_source_verification"
            missing_keys = [k for k in event["verifying_event_keys"] if k not in archived]
            out.append({**{k: event[k] for k in ("event_id", "date", "date_precision", "title", "event_class",
                                                  "slide_pages", "slide_claims", "verification_scope")},
                        "verification_status": status, "verifying_records": verifying,
                        "related_records": records(event["related_event_keys"]),
                        "expected_records_missing_from_archive": missing_keys,
                        "used_in_model_calculation": False})
        return out
