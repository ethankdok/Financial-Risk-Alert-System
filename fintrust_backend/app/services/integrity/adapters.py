"""Read-only adapters from existing FinTrust services into Integrity Workbench evidence.

Each adapter reuses an existing service in-process (never this API's own HTTP URL) and never triggers a live
fetch, document extraction, LLM call, ingestion or persistence:

* ``FactsAdapter``        persisted pipeline facts (``AnalysisRepository.list_facts``) → typed EvidenceRecords
* ``LiteratureAdapter``   published-model readiness through the unchanged Beneish / Dechow engines
* ``JsdAdapter``          the existing ``JsdBridgeService`` (teammate calculator untouched), re-checked for scope
* ``ClaimsAdapter``       verbatim issuer statements → existing ``ClaimVerificationService`` (deterministic only)
* ``OfficialSourcesAdapter`` the existing ``OfficialEvidenceService`` with live fetch forced off
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

from app.services.integrity import alignment as al
from app.services.integrity.contracts import Availability, FindingStatus, Independence

FACTS_ADAPTER_VERSION = "integrity_facts_adapter_v2"
LITERATURE_ADAPTER_VERSION = "integrity_literature_readiness_adapter_v1"
JSD_ADAPTER_VERSION = "integrity_jsd_adapter_v1"
CLAIMS_ADAPTER_VERSION = "integrity_claims_adapter_v2"
SOURCES_ADAPTER_VERSION = "integrity_official_sources_adapter_v1"
REGISTRY_PATH = Path(__file__).with_name("issuer_statements.json")

# Pipeline metric → (evidence family, statement) used by the workbench.
FACT_METRICS = {
    "revenue": ("revenue", "income_statement"),
    "accounts_receivable": ("receivables", "balance_sheet"),
    "net_income": ("net_income", "income_statement"),
    "operating_cash_flow": ("operating_cash_flow", "cash_flow"),
    "total_assets": ("total_assets", "balance_sheet"),
    "cost_of_goods_sold": ("cost_of_goods_sold", "income_statement"),
    "current_assets": ("current_assets", "balance_sheet"),
    "current_liabilities": ("current_liabilities", "balance_sheet"),
    "cash_and_cash_equivalents": ("cash", "balance_sheet"),
    "inventory": ("inventory", "balance_sheet"),
    "total_liabilities": ("total_liabilities", "balance_sheet"),
}
OVERVIEW_METRICS = ("revenue", "accounts_receivable", "net_income", "operating_cash_flow", "total_assets")
MOPS_PUBLISHER = "公開資訊觀測站（TWSE MOPS）"


class IntegrityDataUnavailable(RuntimeError):
    """The persisted fact store could not be read (mapped to HTTP 503)."""


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------- facts
class FactsAdapter:
    """Persisted pipeline facts → typed records, partitioned before any selection (review CR-01 / CR-03):

    demo fixtures and non-annual periods are excluded first, then rows whose ``source_url`` is not a validated
    MOPS filing of *this* ticker are rejected (kept with their reason, never given an official identity), and
    only the remaining official candidates are compared. Different amounts → ``conflicting_duplicate_values``;
    the same amount from incompatible filing versions / scopes / policies → ``incompatible_candidate_versions``;
    both fail closed. Identical official observations are deduplicated deterministically by evidence id (never
    by retrieval time). A listing that reaches the read limit fails closed as possibly truncated.
    """

    FACT_LIMIT = 5000

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def _rows(self, ticker: str) -> list[dict[str, Any]]:
        try:
            return list(self.repository.list_facts(ticker, limit=self.FACT_LIMIT))
        except Exception as exc:  # repository/backend unavailable
            raise IntegrityDataUnavailable(f"fact repository unavailable: {type(exc).__name__}") from exc

    @staticmethod
    def record(row: dict[str, Any], ticker: str | None = None) -> dict[str, Any]:
        metric = str(row.get("metric_code"))
        family, _statement = FACT_METRICS.get(metric, (metric, "unknown"))
        period = str(row.get("period"))
        parsed = al.parse_period(period)
        value = al.to_decimal(row.get("value"))
        unit = row.get("unit")
        source_url = row.get("source_url")
        expected = ticker or str(row.get("ticker"))
        identity = al.mops_filing_identity(source_url, ticker=expected)
        trusted = bool(identity.get("recognised"))
        if trusted:
            scope, scope_basis = al.derive_scope(row.get("statement_scope"), source_url, ticker=expected)
        else:
            scope, scope_basis = "unknown", "untrusted_source_scope_not_derived"
        is_demo = bool(row.get("is_demo")) or row.get("source_kind") == "mvp_fixture"
        missing = ["source_sha256", "published_at", "effective_available_at"]
        if not row.get("taxonomy_concept"):
            missing.append("source_concept")
        if not trusted:
            missing.append("filing_version")
        if not al.is_float64_exact(al.to_twd(value, unit)):
            missing.append("exact_value_beyond_float64_integer_precision")
        key = {"ticker": row.get("ticker"), "metric": metric, "period": period, "value": al.text(value), "unit": unit,
               "source_url": source_url, "retrieved_at": row.get("retrieved_at")}
        if is_demo:  # a demo row may duplicate an official row field for field; keep the two ids distinct
            key["is_demo"] = True
        return {
            "evidence_id": f"fact:{row.get('ticker')}:{metric}:{period}:{_sha(key)[:12]}",
            "ticker": str(row.get("ticker")), "fiscal_period": period,
            "period_start": parsed["start"] if parsed["period_type"] != "unknown" else None,
            "period_end": parsed["end"], "period_type": parsed["period_type"],
            "document_type": "mops_ifrs_financial_report_xbrl" if trusted else str(row.get("source_kind") or "unknown"),
            "language": None, "concept": metric, "source_concept": row.get("taxonomy_concept"),
            "value": al.text(value), "unit": unit, "value_twd": al.text(al.to_twd(value, unit)),
            "scope": scope, "scope_basis": scope_basis,
            "filing_version": identity.get("filing_version"),
            "filing_policy": al.filing_policy(period, source_url, ticker=expected) if trusted else None,
            "issuer": row.get("company_name"), "publisher": MOPS_PUBLISHER if trusted else None,
            "independence": (Independence.regulator_published_issuer_data.value if trusted
                             else Independence.unverified_source.value),
            "source_trust": "validated_mops_filing" if trusted else "untrusted_source",
            "source_rejection_reason": identity.get("reason"),
            "source_sha256": None, "source_identity": identity.get("filing_version") or "unverified_source",
            "source_url": al.official_url(source_url) if trusted else None,
            "locator": {"xbrl_concept": row.get("taxonomy_concept"), "pipeline_fact_id": row.get("fact_id"),
                        "source_field": row.get("source_field")},
            "published_at": row.get("filed_at"), "effective_available_at": None,
            "effective_available_at_precision": "unknown", "ingested_at": row.get("retrieved_at"),
            "provenance": "persisted_pipeline_fact:" + str(row.get("source_kind") or "unknown"),
            "evidence_family": family, "method_version": FACTS_ADAPTER_VERSION,
            "pit_eligible": False, "pit_reason": "effective_available_at_unknown",
            "missing_fields": missing, "candidate_evidence_ids": [], "selection_policy": None,
            "is_demo": is_demo, "analysis_type": row.get("analysis_type"),
        }

    def collect(self, ticker: str) -> dict[str, Any]:
        """Annual index (metric, year) → record, plus excluded rows with reasons (never silently dropped)."""
        rows = self._rows(ticker)
        records = [self.record(row, ticker) for row in rows if row.get("metric_code") in FACT_METRICS]
        index: dict[tuple[str, int], dict[str, Any]] = {}
        excluded: list[dict[str, Any]] = []
        quality: list[dict[str, Any]] = []
        if len(rows) >= self.FACT_LIMIT:
            quality.append({"issue": "fact_listing_at_read_limit_possible_truncation", "concept": "*",
                            "fiscal_period": "*", "values": [str(len(rows))],
                            "evidence_ids": [r["evidence_id"] for r in records]})
            excluded += [{"evidence_id": r["evidence_id"], "reason": "fact_listing_possibly_truncated"} for r in records]
            return {"index": index, "records": records, "excluded": excluded, "quality": quality, "truncated": True}
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for record in records:
            if record["is_demo"]:
                reason = "demo_fixture_value"
            elif record["period_type"] != "annual":
                reason = "period_type_" + record["period_type"] + "_not_used"
            elif record["source_trust"] != "validated_mops_filing":
                reason = "untrusted_source:" + str(record["source_rejection_reason"])
            else:
                grouped.setdefault((record["concept"], record["fiscal_period"]), []).append(record)
                continue
            excluded.append({"evidence_id": record["evidence_id"], "reason": reason})
        for (metric, period), items in sorted(grouped.items()):
            ids = sorted(i["evidence_id"] for i in items)
            values = {item["value_twd"] or f"{item['value']} {item['unit']}" for item in items}
            if len(values) > 1:
                quality.append({"issue": "conflicting_duplicate_values", "concept": metric, "fiscal_period": period,
                                "values": sorted(values), "evidence_ids": ids})
                excluded += [{"evidence_id": i, "reason": "conflicting_duplicate_values"} for i in ids]
                continue
            versions = {(i["filing_version"], i["scope"], i["filing_policy"]) for i in items}
            if len(versions) > 1:
                quality.append({"issue": "incompatible_candidate_versions", "concept": metric, "fiscal_period": period,
                                "values": sorted("|".join(map(str, v)) for v in versions), "evidence_ids": ids})
                excluded += [{"evidence_id": i, "reason": "incompatible_candidate_versions"} for i in ids]
                continue
            chosen = dict(next(i for i in items if i["evidence_id"] == ids[0]))
            chosen["candidate_evidence_ids"] = ids
            chosen["selection_policy"] = ("single_official_candidate" if len(ids) == 1
                                          else "identical_official_observations_lowest_evidence_id")
            excluded += [{"evidence_id": i, "reason": "duplicate_of:" + ids[0]} for i in ids[1:]]
            index[(metric, int(period[:4]))] = chosen
        return {"index": index, "records": records, "excluded": excluded, "quality": quality, "truncated": False}


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key not in ("is_demo", "analysis_type", "source_rejection_reason")}


# ---------------------------------------------------------------------------------------- literature
# Published-model input → pipeline metric that would be its closest persisted fact (availability only).
MODEL_INPUT_TO_PIPELINE = {
    "sales": "revenue", "cogs": "cost_of_goods_sold", "receivables": "accounts_receivable",
    "current_assets": "current_assets", "total_assets": "total_assets", "current_liabilities": "current_liabilities",
    "cash": "cash_and_cash_equivalents", "inventory": "inventory", "total_liabilities": "total_liabilities",
    "earnings": "net_income",
}
SHARED_INPUTS = {
    "beneish_1999_full8_v1": ["F1_REVENUE_RECEIVABLES_ALIGNMENT ↔ DSRI (receivables, sales)",
                              "F2_NET_INCOME_CFO_ALIGNMENT ↔ TATA (accruals)"],
    "dechow_2011_model1_v1": ["F1_REVENUE_RECEIVABLES_ALIGNMENT ↔ ch_rec (receivables)",
                              "F2_NET_INCOME_CFO_ALIGNMENT ↔ rsst_acc (accruals)"],
}


class LiteratureAdapter:
    """Runs the accepted engines on the ticker's *frozen literature inputs*. Production tickers have none, so the
    engines themselves return ``not_computable`` with their full missing-input list; pipeline facts are shown for
    availability only and are never admitted (they were not frozen under the literature input-evidence policy)."""

    def __init__(self, literature_database: str | None) -> None:
        self.literature_database = literature_database

    def frozen_observation_count(self, ticker: str) -> tuple[int | None, str | None]:
        path = Path(self.literature_database or "")
        if not path.is_file():
            return None, "literature_input_store_not_available"
        try:
            connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
            try:
                row = connection.execute("SELECT COUNT(*) FROM literature_line_observations WHERE ticker = ?",
                                         (ticker,)).fetchone()
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return None, f"literature_input_store_unreadable:{type(exc).__name__}"
        return int(row[0]), None

    def assess(self, ticker: str, fiscal_year: int | None, index: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
        from app.services.financial_research import beneish_1999, dechow_2011
        from app.services.financial_research.literature_inputs import Panel
        from app.services.financial_research.literature_method_registry import (
            APPROVAL_STATUS,
            PAPER_SOURCES,
            REGISTRY_VERSION,
        )

        count, store_problem = self.frozen_observation_count(ticker)
        if store_problem:
            reason = store_problem
        elif count:
            reason = "frozen_inputs_exist_only_as_historical_research_case_use_research_api"
        else:
            reason = "no_frozen_literature_inputs_for_ticker"
        if fiscal_year is None:  # no annual period at all: the engines only supply the required-input list
            reason = "no_annual_financial_periods_for_ticker"
        year = fiscal_year or 0
        models = []
        for module, paper_key, title in ((beneish_1999, "beneish_1999", "Beneish (1999) M-Score（8 變數）"),
                                         (dechow_2011, "dechow_2011", "Dechow, Ge, Larson & Sloan (2011) F-Score Model 1")):
            # An empty panel: the unchanged engine reports every input as missing for this reason.
            result = module.evaluate(Panel(year, "TIFRS", {}, {}, {year: reason}))
            missing_metrics = sorted({m["metric"] for m in result["missing_inputs"]})
            availability = []
            for metric in missing_metrics:
                pipeline = MODEL_INPUT_TO_PIPELINE.get(metric)
                availability.append({
                    "model_input": metric, "pipeline_metric": pipeline,
                    "pipeline_fact_t": bool(pipeline and (pipeline, year) in index),
                    "pipeline_fact_t_minus_1": bool(pipeline and (pipeline, year - 1) in index),
                    "admitted_as_model_input": False,
                    "reason": "pipeline facts are not frozen under the literature input-evidence policy "
                              "(source gate, statement anchors, zero proofs)" if pipeline else "no_pipeline_metric",
                })
            models.append({
                "model_id": result["model_id"], "paper": title, "paper_doi": result["paper_doi"],
                "status": "not_computable" if result["score"] is None else "computed",
                "availability": Availability.not_computable.value if result["score"] is None else Availability.available.value,
                "raw_score": result["score"], "fiscal_year": fiscal_year, "approval_status": APPROVAL_STATUS,
                "component_coverage": result["component_coverage"],
                "missing_input_count": len(result["missing_inputs"]), "missing_metrics": missing_metrics,
                "missing_reasons": [reason] if fiscal_year is None else
                sorted({r for m in result["missing_inputs"] for r in m.get("reasons", [])}),
                "pipeline_fact_availability": availability, "shares_inputs_with": SHARED_INPUTS[result["model_id"]],
                "limitations": [
                    "未以 1785 歷史研究案例分數或任何其他公司分數替代。",
                    "已凍結的文獻模型輸入目前只存在於歷史研究案例；正式公司需另行建立同等來源閘門的凍結輸入。",
                    "方法對照（COMPUSTAT→台灣科目）仍為 DRAFT，待方法負責人審核。",
                    f"文獻來源：{PAPER_SOURCES[paper_key]['doi']}",
                ],
            })
        return {"models": models, "frozen_observation_count": count, "reason": reason,
                "method_registry_version": REGISTRY_VERSION, "adapter_version": LITERATURE_ADAPTER_VERSION}


# ----------------------------------------------------------------------------------------------- JSD
def _quarter_index(period: str | None) -> int | None:
    parsed = al.parse_period(period or "")
    return parsed["year"] * 4 + parsed["quarter"] - 1 if parsed["period_type"] == "quarter" else None


def verify_shift_compatibility(ticker: str, result: dict[str, Any]) -> dict[str, bool | None]:
    """Independent re-check of the pair the bridge selected (same ticker, type, language; adjacent quarters)."""
    docs = result.get("source_documents") or []
    q1, q2 = _quarter_index(result.get("period_1")), _quarter_index(result.get("period_2"))
    two = len(docs) == 2
    return {
        "same_ticker": result.get("ticker") == ticker,
        "two_source_documents": two,
        "same_document_type": two and all(d.get("document_type") == result.get("document_type") for d in docs),
        "same_language": two and all(d.get("language") == result.get("language") for d in docs),
        "adjacent_quarters": None if q1 is None or q2 is None else q2 == q1 + 1,
        "documents_match_periods": two and [d.get("period") for d in docs] == [result.get("period_1"), result.get("period_2")],
        "source_hashes_present": two and all(d.get("sha256") for d in docs),
    }


class JsdAdapter:
    def __init__(self, bridge: Any | None) -> None:
        self.bridge = bridge

    def assess(self, ticker: str) -> dict[str, Any]:
        base: dict[str, Any] = {"status": "unavailable", "reason": None, "period_1": None, "period_2": None,
                                "document_type": None, "language": None, "compatibility_checks": {}, "metrics": None,
                                "calibration_status": "not_evaluated", "drift_level": None, "calibration": {},
                                "source_documents": [], "method": {"adapter_version": JSD_ADAPTER_VERSION},
                                "limitations": [],
                                "warning": "JSD / Cosine 只衡量跨期文字分布差異，不等同資訊真假、舞弊或財務風險。"}
        if self.bridge is None or getattr(self.bridge, "conference_repository", None) is None:
            return {**base, "reason": "official_conference_archive_not_configured"}
        try:
            result = self.bridge.analyze(ticker)
        except Exception as exc:
            return {**base, "reason": f"jsd_bridge_error:{type(exc).__name__}"}
        base["warning"] = result.get("warning") or base["warning"]
        base["limitations"] = list(result.get("limitations") or [])
        base["method"].update(result.get("method") or {})
        if result.get("analysis_status") == "insufficient_data":
            return {**base, "reason": result.get("reason_code") or "no_comparable_pair",
                    "limitations": base["limitations"] + [
                        f"可用文件：{len(result.get('available_documents') or [])} 份；需同公司、同文件類型、同語言、相鄰季度。"]}
        checks = verify_shift_compatibility(ticker, result)
        docs = [{"period": d.get("period"), "document": d.get("document"), "document_type": d.get("document_type"),
                 "language": d.get("language"), "source_url": al.official_url(d.get("source_url")),
                 "source_page": d.get("source_page"), "sha256": d.get("sha256"), "text_length": d.get("text_length")}
                for d in result.get("source_documents") or []]
        common = {**base, "period_1": result.get("period_1"), "period_2": result.get("period_2"),
                  "document_type": result.get("document_type"), "language": result.get("language"),
                  "compatibility_checks": checks, "source_documents": docs}
        if not all(value is True for value in checks.values()):
            failed = sorted(name for name, value in checks.items() if value is not True)
            return {**common, "status": "not_comparable", "reason": "compatibility_failed:" + ",".join(failed)}
        status = result.get("analysis_status")
        if status == "method_unavailable":
            return {**common, "status": "method_unavailable", "reason": "jsd_calculator_unavailable"}
        if status == "quality_insufficient":
            return {**common, "status": "quality_insufficient", "reason": "data_quality_failed"}
        metrics = result.get("metrics") or {}
        common["metrics"] = {name: al.text(al.to_decimal(value)) for name, value in metrics.items()}
        calibration = result.get("calibration") or {}
        scope = calibration.get("scope") or {}
        calibrated = (calibration.get("status") == "calibrated" and scope.get("ticker") == ticker
                      and scope.get("document_type") == result.get("document_type")
                      and scope.get("language") == result.get("language"))
        common["calibration"] = {k: calibration.get(k) for k in ("status", "reason", "calibration_id",
                                                                  "history_pair_count", "history_latest_period",
                                                                  "profiles_for_ticker", "nearest_profiles")
                                 if k in calibration}
        if calibrated:
            return {**common, "status": "comparable", "calibration_status": "calibrated",
                    "drift_level": result.get("drift_result"), "reason": None}
        if calibration.get("status") == "calibrated":
            common["limitations"].append("校準設定的範圍與本配對不一致，已捨棄漂移等級。")
        return {**common, "status": "comparable", "calibration_status": "uncalibrated", "drift_level": None,
                "reason": "no_matching_calibration_profile"}


# --------------------------------------------------------------------------------------------- claims
def _normalize_space(value: str) -> str:
    return " ".join(str(value or "").split())


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def registry_sha256(path: Path = REGISTRY_PATH) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def printed_precision_check(parsed: dict[str, Any], official_twd: Decimal | None) -> tuple[str, dict[str, Any]]:
    """Stricter than the verifier's relative tolerance: the official value must round to the printed claim."""
    from app.services.verifier import MONEY_SCALES

    scale = MONEY_SCALES.get(parsed.get("unit") or "")
    value_text = str(parsed.get("value_text") or "").replace(",", "")
    claimed = al.to_decimal(value_text)
    if scale is None or claimed is None or official_twd is None:
        return "not_evaluated", {}
    decimals = len(value_text.split(".")[1]) if "." in value_text else 0
    with localcontext() as ctx:
        ctx.prec = al.PRECISION
        unit = al.to_decimal(repr(float(scale)))
        claimed_twd = claimed * unit
        half_step = unit * Decimal(1).scaleb(-decimals) / 2
        difference = abs(official_twd - claimed_twd)
    detail = {"claimed_twd": al.text(claimed_twd), "official_twd": al.text(official_twd),
              "difference_twd": al.text(difference), "printed_precision_half_step_twd": al.text(half_step)}
    return ("within_printed_precision" if difference <= half_step else "outside_printed_precision"), detail


# ------------------------------------------------------------------------------------- quote lineage
# Table-header units an issuer presentation may state, as a multiplier to NT$1.
HEADER_UNITS = {"millions": Decimal(1_000_000), "billions": Decimal(1_000_000_000), "thousands": Decimal(1_000)}
HEADER_UNIT_RE = re.compile(r"In NT\$ (thousands|millions|billions)", re.I)
NUMBER_TOKEN_RE = re.compile(r"^[+-]?\(?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?%?$|^[+-]?\(?\d+(?:\.\d+)?\)?%?$")
CLAIM_UNITS = {"百萬": Decimal(1_000_000), "億": Decimal(100_000_000), "元": Decimal(1)}
QUOTE_EXTRACTION_VERSION = "integrity_quote_extraction_v1"


def _token_value(token: str) -> Decimal | None:
    text = token.strip().rstrip("%").replace(",", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    number = al.to_decimal(text)
    return -number if negative and number is not None else number


def derive_quote(statement: dict[str, Any], page_text: str) -> dict[str, Any]:
    """Re-derive a pinned claim's number from the archived page: row label → column → printed token →
    table-header unit → Decimal NT$ → the normalized claim value (review CR-04).

    ``verified`` only when every step is unique and agrees. Ambiguity (several matching rows or units, an
    inconsistent YoY column) or a disagreement is ``inconclusive``; a missing row / spec is ``insufficient``.
    """
    spec = statement.get("quote_extraction")
    out: dict[str, Any] = {"method_version": QUOTE_EXTRACTION_VERSION, "result": "insufficient", "reason": None,
                           "page": statement.get("page"), "row_label": None, "column_label": None,
                           "original_token": None, "header_unit": None, "extracted_value_twd": None,
                           "normalized_claim_value_twd": None, "yoy_check": None}
    if not spec:
        return {**out, "reason": "no_quote_extraction_spec"}
    out.update(row_label=spec["row_label"], column_label=spec["column_label"])
    lines = [_normalize_space(line) for line in (page_text or "").splitlines()]
    units = {match.group(1).lower() for match in HEADER_UNIT_RE.finditer(page_text or "")}
    if _normalize_space(spec["header_unit_excerpt"]) not in _normalize_space(page_text or ""):
        return {**out, "reason": "header_unit_excerpt_not_on_page"}
    if len(units) != 1:
        return {**out, "result": "inconclusive" if units else "insufficient",
                "reason": "ambiguous_header_units" if units else "no_header_unit"}
    unit = units.pop()
    out["header_unit"] = f"NT$ {unit}"
    period_line = _normalize_space(spec["period_label_excerpt"])
    if period_line not in _normalize_space(page_text or "") or spec["column_label"] not in period_line:
        return {**out, "reason": "period_label_not_on_page"}
    label = _normalize_space(spec["row_label"])
    rows = []
    for line in lines:
        if not line.startswith(label + " "):
            continue
        tokens = line[len(label):].split()
        if tokens and NUMBER_TOKEN_RE.match(tokens[0]):
            rows.append(tokens)
    if len(rows) != 1:
        return {**out, "result": "inconclusive" if rows else "insufficient",
                "reason": "ambiguous_row_label" if rows else "row_label_not_found"}
    tokens = rows[0]
    position = int(spec["column_position"])
    numbers = [t for t in tokens if NUMBER_TOKEN_RE.match(t) and not t.endswith("%")]
    if len(numbers) < position:
        return {**out, "reason": "column_not_present"}
    token = numbers[position - 1]
    out["original_token"] = token
    if token != spec["original_token"]:
        return {**out, "result": "inconclusive", "reason": "printed_token_differs_from_registry"}
    percents = [t for t in tokens if t.endswith("%")]
    if percents and len(numbers) >= 2:
        current, prior = _token_value(numbers[0]), _token_value(numbers[1])
        printed = _token_value(percents[0])
        decimals = len(percents[0].rstrip("%").split(".")[1]) if "." in percents[0] else 0
        with localcontext() as ctx:
            ctx.prec = al.PRECISION
            implied = ((current / prior - 1) * 100).quantize(Decimal(1).scaleb(-decimals)) if prior else None
        consistent = implied is not None and implied == printed
        out["yoy_check"] = {"printed": percents[0], "implied_from_columns_1_2": al.text(implied),
                            "column_1_is_current_year": consistent}
        if not consistent:
            return {**out, "result": "inconclusive", "reason": "yoy_column_order_not_confirmed"}
    elif not spec.get("column_order_from_period_label"):
        return {**out, "result": "inconclusive", "reason": "column_order_not_confirmed"}
    with localcontext() as ctx:
        ctx.prec = al.PRECISION
        extracted = _token_value(token) * HEADER_UNITS[unit]
        expected = statement.get("expected_parse") or {}
        claim_scale = CLAIM_UNITS.get(expected.get("unit") or "")
        claim_value = al.to_decimal(expected.get("value"))
        normalized = claim_value * claim_scale if claim_scale is not None and claim_value is not None else None
    out.update(extracted_value_twd=al.text(extracted), normalized_claim_value_twd=al.text(normalized))
    if normalized is None or normalized != extracted:
        return {**out, "result": "inconclusive", "reason": "normalized_claim_differs_from_source"}
    if al.text(claim_value) not in statement.get("normalized_claim", "").replace(",", ""):
        return {**out, "result": "inconclusive", "reason": "normalized_claim_text_lacks_value"}
    return {**out, "result": "verified"}


class ClaimsAdapter:
    """Verbatim issuer statements, verified at the source, checked with the existing deterministic verifier."""

    def __init__(self, conference_repository: Any | None, claim_service: Any | None,
                 registry_path: Path = REGISTRY_PATH) -> None:
        self.conference_repository = conference_repository
        self.claim_service = claim_service
        self.registry_path = registry_path

    def verify_source(self, statement: dict[str, Any]) -> dict[str, Any]:
        result = {"document_found": False, "sha256_matches_pin": False, "page_found": False,
                  "excerpt_found": False, "context_found": False, "archive_sha256": None, "period_validation": None,
                  "verified": False, "reason": None}
        repo = self.conference_repository
        if repo is None:
            return {**result, "reason": "official_conference_archive_not_configured"}
        try:
            document = repo.document(statement["ticker"], int(statement["archive_year"]), statement["document"])
            pages = repo.pages(statement["ticker"], int(statement["archive_year"]), statement["document"]) if document else []
        except Exception as exc:
            return {**result, "reason": f"archive_read_error:{type(exc).__name__}"}
        if not document:
            return {**result, "reason": "document_not_in_archive"}
        result["document_found"] = True
        result["archive_sha256"] = document.get("sha256")
        result["period_validation"] = document.get("period_validation_status")
        result["sha256_matches_pin"] = document.get("sha256") == statement["document_sha256"]
        page = next((p for p in pages if p.get("page") == statement["page"]), None)
        if page is not None:
            result["page_found"] = True
            page_text = _normalize_space(page.get("text") or "")
            result["excerpt_found"] = _normalize_space(statement["excerpt"]) in page_text
            result["context_found"] = _normalize_space(statement["context_excerpt"]) in page_text
            result["_page_text"] = page.get("text") or ""
        checks = ("sha256_matches_pin", "page_found", "excerpt_found", "context_found")
        failed = [name for name in checks if not result[name]]
        result["verified"] = not failed
        result["reason"] = None if not failed else "source_check_failed:" + ",".join(failed)
        return result

    @staticmethod
    def _parsed(structured: dict[str, Any]) -> dict[str, Any]:
        return {"metric": structured.get("metric_or_topic"), "period": structured.get("period"),
                "value": al.text(al.to_decimal(structured.get("value_text") or structured.get("value"))),
                "value_text": structured.get("value_text"), "unit": structured.get("unit"),
                "claim_type": structured.get("claim_type")}

    def _check(self, statement: dict[str, Any], official_index: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
        source = self.verify_source(statement)
        page_text = source.pop("_page_text", "")
        public_statement = {key: statement[key] for key in (
            "statement_id", "ticker", "document", "document_sha256", "document_type", "language", "page",
            "published_on", "published_on_basis", "statement_kind", "context_excerpt", "excerpt")}
        public_statement["source_url"] = None  # the archive records MOPS download fields, not a stable public URL
        check = {"claim_id": statement["statement_id"], "statement": public_statement, "source_verification": source,
                 "normalized_claim": statement["normalized_claim"], "normalization": statement["normalization"],
                 "verdict": FindingStatus.insufficient_evidence.value, "reason_code": "", "parsed_claim": None,
                 "evidence": [], "corroboration": {
                     "type": "same_issuer_self_reported",
                     "independent_corroboration": False,
                     "explanation": "簡報與 MOPS 財報皆由同一發行人提供；一致只代表發行人前後說法一致，不是第三方獨立查證。"},
                 "limitations": ["簡報表格標示為未經查核（Unaudited）時，與經查核年報一致不代表簡報本身經過查核。"
                                 if statement["statement_kind"].endswith("unaudited") else
                                 "簡報摘要數字為發行人自行彙整。"]}
        if not source["verified"]:
            return {**check, "reason_code": source["reason"] or "source_not_verified"}
        quote = derive_quote(statement, page_text)
        check["quote_extraction"] = quote
        if quote["result"] != "verified":
            verdict = FindingStatus.inconclusive if quote["result"] == "inconclusive" else FindingStatus.insufficient_evidence
            return {**check, "verdict": verdict.value, "reason_code": f"quote_extraction_{quote['result']}:{quote['reason']}"}
        if self.claim_service is None:
            return {**check, "reason_code": "claim_verifier_not_available"}
        from app.claim_verification_models import ClaimVerifyRequest

        try:
            response = self.claim_service.verify(
                ClaimVerifyRequest(company_code=statement["ticker"], claim=statement["normalized_claim"])
            ).model_dump(mode="json")
        except Exception as exc:
            return {**check, "reason_code": f"claim_verifier_error:{type(exc).__name__}"}
        parsed = self._parsed(response["structured_claim"])
        check["parsed_claim"] = parsed
        expected = statement["expected_parse"]
        mismatched = [field for field in ("metric", "period", "unit") if parsed.get(field) != expected[field]]
        if al.to_decimal(parsed.get("value")) != al.to_decimal(expected["value"]):
            mismatched.append("value")
        evidence = []
        for item in response.get("evidence") or []:
            if item.get("source_type") == "financial_fact" or item.get("decisive"):
                evidence.append({key: item.get(key) for key in (
                    "evidence_id", "relation", "decisive", "source_type", "source_title", "period", "metric", "value",
                    "unit", "page", "document", "document_sha256", "verification_status")}
                    | {"source_reference": al.official_url(item.get("source_reference")),
                       "comparison": item.get("comparison")})
        check["evidence"] = evidence
        if mismatched:
            return {**check, "verdict": FindingStatus.inconclusive.value,
                    "reason_code": "claim_parse_mismatch:" + ",".join(sorted(mismatched))}
        verdict = response.get("verdict")
        reason = response.get("reason_code") or ""
        if verdict == "supported":
            year = int(expected["period"][:4])
            official = official_index.get((expected["metric"], year))
            precision, detail = printed_precision_check(parsed, al.to_decimal(official["value_twd"]) if official else None)
            check["precision_check"] = detail | {"result": precision}
            if precision != "within_printed_precision":
                return {**check, "verdict": FindingStatus.inconclusive.value,
                        "reason_code": f"verifier_supported_but_{precision}"}
            return {**check, "verdict": FindingStatus.supported.value, "reason_code": reason}
        if verdict == "conflicting":
            return {**check, "verdict": FindingStatus.conflicting.value, "reason_code": reason}
        return {**check, "verdict": FindingStatus.insufficient_evidence.value, "reason_code": reason or "insufficient"}

    def assess(self, ticker: str, official_index: dict[tuple[str, int], dict[str, Any]]) -> dict[str, Any]:
        try:
            registry = load_registry(self.registry_path)
        except (OSError, json.JSONDecodeError) as exc:
            return {"checks": [], "status": "unavailable", "reason": f"statement_registry_unreadable:{type(exc).__name__}",
                    "registry_version": None}
        statements = [s for s in registry.get("statements", []) if s.get("ticker") == ticker]
        checks = []
        for statement in statements:
            try:
                checks.append(self._check(statement, official_index))
            except Exception as exc:  # one bad entry never fails the whole assessment
                checks.append({"claim_id": statement.get("statement_id", "unknown"), "statement": {},
                               "source_verification": {"verified": False}, "normalized_claim": "",
                               "normalization": "", "verdict": FindingStatus.insufficient_evidence.value,
                               "reason_code": f"claim_check_error:{type(exc).__name__}", "parsed_claim": None,
                               "evidence": [], "corroboration": {"type": "same_issuer_self_reported",
                                                                 "independent_corroboration": False},
                               "limitations": []})
        status = "available" if any(c["verdict"] in ("supported", "conflicting") for c in checks) else \
            ("insufficient_evidence" if checks else "unavailable")
        return {"checks": checks, "status": status,
                "reason": None if checks else "no_registered_issuer_statement_for_ticker",
                "registry_version": registry.get("registry_version")}


# ------------------------------------------------------------------------------------ official sources
class OfficialSourcesAdapter:
    """Official evidence summary with live MOPS fetch forced off (persisted records only)."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def assess(self, ticker: str) -> dict[str, Any]:
        from app.services.official_evidence_service import OfficialEvidenceService

        try:
            summary = OfficialEvidenceService(repository=self.repository).build(
                ticker, include_conferences=True, include_material_events=True, fetch_conference_live=False)
        except Exception as exc:
            return {"status": "unavailable", "reason": f"official_evidence_error:{type(exc).__name__}",
                    "adapter_version": SOURCES_ADAPTER_VERSION}
        payload = summary.model_dump(mode="json")
        snapshot = payload.get("financial_snapshot") or {}
        events = [{"event_date": e.get("event_date"), "title": e.get("title"), "status": e.get("status"),
                   "source_url": al.official_url(e.get("detail_url") or e.get("source_url"))}
                  for e in payload.get("material_events") or []]
        conferences = [{"conference_date": c.get("conference_date") or c.get("event_date"), "title": c.get("title"),
                        "status": c.get("status"), "source_url": al.official_url(c.get("document_url") or c.get("source_url"))}
                       for c in payload.get("investor_conferences") or []]
        sources = [{"source_name": s.get("source_name"), "status": s.get("status"),
                    "source_url": al.official_url(s.get("source_url"))} for s in payload.get("sources") or []]
        withheld = sum(1 for s in sources if s["source_url"] is None)
        rules = [{"rule_id": r.get("rule_id"), "name": r.get("name"), "triggered": r.get("triggered"),
                  "severity": r.get("severity")} for r in snapshot.get("rule_cards") or []]
        return {"status": "available", "readiness": payload.get("readiness"), "rule_version": snapshot.get("rule_version"),
                "rule_signals": rules, "rule_signals_triggered": sum(1 for r in rules if r["triggered"]),
                "snapshot_data_updated_at": snapshot.get("data_updated_at"), "material_events": events,
                "investor_conferences": conferences, "sources": [s for s in sources if s["source_url"]],
                "non_allowlisted_links_withheld": withheld, "adapter_version": SOURCES_ADAPTER_VERSION,
                "live_fetch": False}
