"""Official conference-document shift analysis (JSD Method A bridge).

official archive → JSD corpus adapter → comparable target pair → shared
teammate calculator (unchanged) → exact-scope calibration profile → result.

Rules:
* pairs are same ticker, same document type, same language, adjacent fiscal
  quarters, both jsd_ready;
* thresholds come only from a matching calibration profile; no profile is a
  normal ``uncalibrated`` result with raw metrics and no drift level;
* legacy STRUX runtime thresholds and ``determine_drift_level`` are never used;
* provenance is the official source URL, never storage paths.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from app.services.conference_jsd_corpus_adapter import (
    EXTRACTION_METHOD,
    PREPROCESSING_VERSION,
    SOURCE_FAMILY,
    JsdCorpusRecord,
    build_records,
    comparable_pairs,
)
from app.services.jsd_calibration import JsdCalibrationRepository, JsdCalibrationProfile, _quarter_index
from app.services.jsd_method import METHOD_VERSION, MethodUnavailable, load_calculator

WARNING = "JSD / Cosine 只衡量跨期文字分布差異，不等同資訊真假、詐騙認定或財務風險。"
UNCALIBRATED_RESULT = "尚無相符歷史校準，不判定漂移等級"
# Teammate combined-rule outcomes (calibrate_tsmc_shift.analyze).
DUAL = "雙指標顯著文字漂移（需人工確認）"
SINGLE = "單一指標異常（待觀察）"
NEITHER = "未達雙指標歷史漂移門檻"
RULE_TEXT = "JSD >= historical P90 AND Cosine <= historical P10"
TYPE_PREFERENCE = [
    "full_earnings_transcript", "earnings_presentation", "financial_results_release", "investor_presentation",
    "analyst_conference_presentation", "other_official_conference_document",
]
LANGUAGE_PREFERENCE = ["en", "en_may_include_translation", "zh-Hant", "bilingual"]
PERIOD_RE = re.compile(r"^20\d{2}Q[1-4]$")


def evaluate_combined_rule(metrics: dict[str, float], thresholds: dict[str, float]) -> tuple[dict[str, Any], str]:
    """Teammate rule: both indicators beyond historical percentiles → dual; one → single; none → below."""
    high = metrics["jsd"] >= thresholds["jsd_p90"] and metrics["jsd"] > 0
    low = metrics["cosine_similarity"] <= thresholds["cosine_p10"] and metrics["cosine_similarity"] < 1
    decision = {"jsd_high": bool(high), "cosine_low": bool(low), "rule": RULE_TEXT}
    return decision, DUAL if high and low else SINGLE if high or low else NEITHER


def _rank(values: list[str], item: str) -> int:
    return values.index(item) if item in values else len(values)


def _source_document(item: JsdCorpusRecord) -> dict[str, Any]:
    return {
        "period": item.record["period"],
        "document": item.provenance.get("filename"),
        "document_type": item.record["document_type"],
        "language": item.record["language"],
        "source_url": item.record["source_pdf"],
        "source_page": item.record["source_page"],
        "sha256": item.record["sha256"],
        "text_length": item.record["text_length"],
    }


class JsdBridgeService:
    def __init__(self, conference_repository: Any, calibration_repository: JsdCalibrationRepository,
                 calculator_loader: Callable[[], Any] = load_calculator) -> None:
        self.conference_repository = conference_repository
        self.calibration_repository = calibration_repository
        self.calculator_loader = calculator_loader

    # --- pair selection ---------------------------------------------------------------

    def select_pair(self, records: list[JsdCorpusRecord], period_1: str | None, period_2: str | None
                    ) -> tuple[tuple[JsdCorpusRecord, JsdCorpusRecord] | None, str | None]:
        ready = [item for item in records if item.jsd_ready]
        if period_1 and period_2:
            if _quarter_index(period_2) != _quarter_index(period_1) + 1:
                return None, "periods_not_adjacent"
            first = {(i.record["document_type"], i.record["language"]): i for i in ready if i.record["period"] == period_1}
            second = {(i.record["document_type"], i.record["language"]): i for i in ready if i.record["period"] == period_2}
            if not first or not second:
                return None, "period_not_available"
            common = sorted(set(first) & set(second),
                            key=lambda key: (_rank(TYPE_PREFERENCE, key[0]), _rank(LANGUAGE_PREFERENCE, key[1])))
            if not common:
                return None, "no_same_type_and_language_pair"
            return (first[common[0]], second[common[0]]), None
        pairs = comparable_pairs(records)
        if not pairs:
            return None, "no_comparable_pair"
        best = max(pairs, key=lambda pair: (_quarter_index(pair["period_2"]), -_rank(TYPE_PREFERENCE, pair["document_type"]),
                                            -_rank(LANGUAGE_PREFERENCE, pair["language"])))
        by_hash = {item.record["sha256"]: item for item in ready}
        return (by_hash[best["sha256_1"]], by_hash[best["sha256_2"]]), None

    # --- analysis ------------------------------------------------------------------------

    def analyze(self, ticker: str, period_1: str | None = None, period_2: str | None = None) -> dict[str, Any]:
        for value in (period_1, period_2):
            if value is not None and not PERIOD_RE.fullmatch(value):
                raise ValueError("Periods must look like 2025Q3")
        if bool(period_1) != bool(period_2):
            raise ValueError("Provide both period_1 and period_2, or neither for the latest comparable pair")
        records = build_records(self.conference_repository, ticker)
        pair, reason = self.select_pair(records, period_1, period_2)
        if pair is None:
            return self._insufficient(ticker, records, reason, period_1, period_2)
        first, second = pair
        identity = {
            "source_family": first.provenance.get("source_family", SOURCE_FAMILY),
            "extraction_method": first.provenance.get("extraction_method", EXTRACTION_METHOD),
            "preprocessing_version": first.provenance.get("preprocessing_version", PREPROCESSING_VERSION),
        }
        return self.evaluate_pair(
            ticker=ticker, company=first.record["company"], industry=first.record["industry"],
            first={"period": first.record["period"], "text": first.record["text"]},
            second={"period": second.record["period"], "text": second.record["text"]},
            document_type=first.record["document_type"], language=first.record["language"],
            identity=identity, source_documents=[_source_document(first), _source_document(second)],
        )

    def evaluate_pair(self, *, ticker: str, company: str, industry: str, first: dict[str, str], second: dict[str, str],
                      document_type: str, language: str, identity: dict[str, str],
                      source_documents: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ticker": ticker, "company": company, "industry": industry,
            "period_1": first["period"], "period_2": second["period"],
            "document_type": document_type, "language": language,
            "analysis_status": "complete", "metrics": None, "data_quality": None,
            "calibration": {"status": "unavailable"}, "combined_rule": None, "drift_result": None,
            "terms": None, "source_documents": source_documents,
            "method": {"method_version": METHOD_VERSION, **identity},
            "limitations": [], "warning": WARNING,
        }
        try:
            calculator = self.calculator_loader()
        except MethodUnavailable as exc:
            result.update(analysis_status="method_unavailable", drift_result=UNCALIBRATED_RESULT)
            result["limitations"].append(f"JSD 計算模組不可用或版本不符：{exc}")
            return result
        result["method"].update(calculator.identity)
        quality = calculator.data_quality(first["text"], second["text"])
        result["data_quality"] = quality
        if not quality.get("passed"):
            result.update(analysis_status="quality_insufficient", drift_result=UNCALIBRATED_RESULT)
            result["calibration"] = {"status": "not_evaluated", "reason": "data_quality_failed"}
            result["limitations"].append("文字資料品質未通過方法門檻（長度或長度比），未計算指標。")
            return result
        metrics = calculator.metrics(first["text"], second["text"])
        result["metrics"] = metrics
        scope = dict(ticker=ticker, document_type=document_type, language=language,
                     extraction_method=identity["extraction_method"],
                     preprocessing_version=identity["preprocessing_version"], method_version=METHOD_VERSION,
                     calculator_module_sha256=calculator.module_sha256, target_period_1=first["period"])
        try:
            profile = self.calibration_repository.find_matching_profile(**scope)
        except Exception:
            profile = None
            result["limitations"].append("校準資料庫暫時無法讀取，僅提供原始指標。")
        if profile is None:
            result["calibration"] = self._unavailable(scope)
            result["drift_result"] = UNCALIBRATED_RESULT
            result["limitations"].append(
                "已完成文字分布量測，但目前沒有相同公司／文件類型／方法版本的足夠歷史資料，因此不判定漂移等級。")
            return result
        thresholds = profile.calibration.thresholds.model_dump()
        decision, drift = evaluate_combined_rule(metrics, thresholds)
        result["calibration"] = self._calibrated(profile)
        result["combined_rule"] = decision
        result["drift_result"] = drift
        result["limitations"] += list(profile.warnings)
        return result

    # --- helpers -------------------------------------------------------------------------

    def _unavailable(self, scope: dict[str, Any]) -> dict[str, Any]:
        mismatches = []
        try:
            for profile in self.calibration_repository.list_profiles(scope["ticker"]):
                differs = [name for name, ours, theirs in (
                    ("document_type", scope["document_type"], profile.scope.document_type),
                    ("language", scope["language"], profile.scope.language),
                    ("extraction_method", scope["extraction_method"], profile.method.extraction_method),
                    ("preprocessing_version", scope["preprocessing_version"], profile.method.preprocessing_version),
                    ("method_version", scope["method_version"], profile.method.method_version),
                    ("calculator_module_sha256", scope["calculator_module_sha256"], profile.method.calculator_module_sha256),
                ) if ours != theirs]
                if not profile.usable:
                    differs.append(f"profile_status:{profile.status}")
                history_end = profile.calibration.history_latest_period
                if history_end and _quarter_index(history_end) >= _quarter_index(scope["target_period_1"]):
                    differs.append("history_overlaps_target")
                mismatches.append({"calibration_id": profile.calibration_id, "differs_in": differs})
        except Exception:
            pass
        return {"status": "unavailable", "reason": "no_matching_profile",
                "profiles_for_ticker": len(mismatches), "nearest_profiles": mismatches[:10]}

    @staticmethod
    def _calibrated(profile: JsdCalibrationProfile) -> dict[str, Any]:
        return {
            "status": "calibrated",
            "calibration_id": profile.calibration_id,
            "history_pair_count": profile.calibration.history_pair_count,
            "history_latest_period": profile.calibration.history_latest_period,
            "thresholds": profile.calibration.thresholds.model_dump(),
            "method_version": profile.method.method_version,
            "extraction_method": profile.method.extraction_method,
            "preprocessing_version": profile.method.preprocessing_version,
            "source_research_commit": profile.source_research_commit,
            "scope": profile.scope.model_dump(),
        }

    @staticmethod
    def _insufficient(ticker: str, records: list[JsdCorpusRecord], reason: str | None,
                      period_1: str | None, period_2: str | None) -> dict[str, Any]:
        available = sorted({(i.record["period"] or "未確認期間", i.record["document_type"], i.record["language"], i.jsd_ready)
                            for i in records})
        return {
            "ticker": ticker, "company": records[0].record["company"] if records else None,
            "period_1": period_1, "period_2": period_2,
            "analysis_status": "insufficient_data", "reason_code": reason or "no_comparable_pair",
            "metrics": None, "calibration": {"status": "not_evaluated"}, "drift_result": None, "terms": None,
            "available_documents": [{"period": p, "document_type": t, "language": l, "jsd_ready": r}
                                    for p, t, l, r in available],
            "source_documents": [],
            "limitations": ["需要同公司、同文件類型、同語言、相鄰季度且通過驗證的兩份官方文件。"],
            "warning": WARNING,
        }
