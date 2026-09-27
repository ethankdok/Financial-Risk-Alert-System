"""Calibrate one exact MOPS conference scope with the FROZEN teammate method.

The teammate's ``data_shift.py`` and ``scripts/calibrate_tsmc_shift.py`` are read
with ``git show <SOURCE_RESEARCH_COMMIT>:<path>`` into a temporary directory and
imported unmodified. Their ``analyze()`` (quality rule, adjacent-pair history
before the target, percentiles, combined rule) runs directly on FinTrust corpus
records that are already filtered to one exact scope. The transcript-only
``load()`` is never used and records keep their real document_type.

Outputs (no document text):
  <out>/<ticker>-<type>-<lang>.teammate-analyze.json  raw analyze() result
  <out>/<ticker>-<type>-<lang>.report.json            import report + provenance + stability

Run from fintrust_backend:
  python -m scripts.calibrate_conference_scope --archive-root data/historical-conference-pdfs \\
      --ticker 2454 --document-type earnings_presentation --language en \\
      --target 2025Q2 2025Q3 --output-dir ../docs/data/calibration
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from statistics import mean
from typing import Any

from app.services.conference_jsd_corpus_adapter import (
    EXTRACTION_METHOD,
    PREPROCESSING_VERSION,
    SOURCE_FAMILY,
    JsdCorpusRecord,
    build_records,
)
from app.services.jsd_method import (
    JSD_LOG_BASE,
    METHOD_VERSION,
    REFERENCE_MODULE_SHA256,
    SOURCE_RESEARCH_COMMIT,
    TFIDF,
    TOKENIZER,
)
from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository

REPO_ROOT = Path(__file__).resolve().parents[2]
TEAMMATE_FILES = ("data_shift.py", "scripts/calibrate_tsmc_shift.py")
ROW_FIELDS = ("ticker", "company", "industry", "period", "document_type", "language", "text",
              "source_page", "source_pdf", "sha256")


class ScopeRejected(ValueError):
    def __init__(self, status: str, detail: str) -> None:
        super().__init__(f"{status}: {detail}")
        self.status = status
        self.detail = detail


def quarter_index(period: str) -> int:
    return int(period[:4]) * 4 + int(period[-1]) - 1


class FrozenTeammateMethod:
    """Unmodified teammate modules at a pinned commit, loaded from a throwaway directory."""

    def __init__(self, commit: str = SOURCE_RESEARCH_COMMIT, reader=None) -> None:
        self.commit = commit
        self.reader = reader or self._git_show

    def _git_show(self, path: str) -> bytes:
        result = subprocess.run(["git", "show", f"{self.commit}:{path}"], cwd=REPO_ROOT, capture_output=True, timeout=60)
        if result.returncode != 0:
            raise ScopeRejected("method_unavailable", f"cannot read {path} at {self.commit}")
        return result.stdout

    def __enter__(self) -> "FrozenTeammateMethod":
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        (root / "scripts").mkdir()
        for path in TEAMMATE_FILES:
            (root / path).write_bytes(self.reader(path))
        self.module_sha256 = hashlib.sha256((root / "data_shift.py").read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if self.module_sha256 != REFERENCE_MODULE_SHA256:
            self.__exit__(None, None, None)
            raise ScopeRejected("method_unavailable", f"data_shift.py hash {self.module_sha256} != reference")
        self._saved = sys.modules.pop("data_shift", None)
        sys.path.insert(0, str(root))
        self.data_shift = self._load("data_shift", root / "data_shift.py")
        self.calibrate = self._load("frozen_calibrate_tsmc_shift", root / "scripts" / "calibrate_tsmc_shift.py")
        return self

    @staticmethod
    def _load(name: str, path: Path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def __exit__(self, *exc) -> bool:
        sys.path[:] = [item for item in sys.path if item != self._tmp.name]
        sys.modules.pop("frozen_calibrate_tsmc_shift", None)
        sys.modules.pop("data_shift", None)
        if getattr(self, "_saved", None) is not None:
            sys.modules["data_shift"] = self._saved
        self._tmp.cleanup()
        return False


def scope_rows(records: list[JsdCorpusRecord], *, ticker: str, document_type: str, language: str) -> list[dict]:
    """Exact-scope, jsd_ready, non-quarantined rows sorted by fiscal quarter; fails on ambiguity."""
    selected = []
    for item in records:
        record, provenance = item.record, item.provenance
        if (record["ticker"], record["document_type"], record["language"]) != (ticker, document_type, language):
            continue
        if not item.jsd_ready or provenance.get("quarantined"):
            continue
        if (provenance["extraction_method"], provenance["preprocessing_version"]) != (EXTRACTION_METHOD,
                                                                                      PREPROCESSING_VERSION):
            raise ScopeRejected("scope_mismatch", "record extraction/preprocessing differs from production")
        selected.append({key: record[key] for key in ROW_FIELDS})
    periods = [row["period"] for row in selected]
    hashes = [row["sha256"] for row in selected]
    if len(set(periods)) != len(periods):
        raise ScopeRejected("duplicate_period_ambiguity", "several documents for one fiscal period")
    if len(set(hashes)) != len(hashes):
        raise ScopeRejected("duplicate_sha_conflict", "one PDF appears under several periods")
    return sorted(selected, key=lambda row: quarter_index(row["period"]))


def rejected_history_pairs(method: FrozenTeammateMethod, rows: list[dict], period_1: str) -> list[dict]:
    """Adjacent pairs before the target that the unmodified teammate pair() rejects."""
    by_index = {quarter_index(row["period"]): row for row in rows}
    limit = quarter_index(period_1)
    rejected = []
    for index in sorted(by_index):
        if index + 1 < limit and index + 1 in by_index:
            result = method.calibrate.pair(by_index[index], by_index[index + 1])
            if not result["passed"]:
                rejected.append({"period_1": result["period_1"], "period_2": result["period_2"],
                                 "data_quality": result["data_quality"]})
    return rejected


def _percentile_rank(values: list[float], value: float) -> float:
    return round(sum(1 for item in values if item <= value) / len(values), 4)


def stability(report: dict, rows: list[dict]) -> dict[str, Any]:
    history = report["calibration"]["history_pairs"]
    if not history:
        return {"history_pairs": 0}
    lengths = {row["period"]: len(row["text"].strip()) for row in rows}
    enriched = [{**pair, "length_1": lengths[pair["period_1"]], "length_2": lengths[pair["period_2"]],
                 "length_ratio": round(min(lengths[pair["period_1"]], lengths[pair["period_2"]])
                                       / max(lengths[pair["period_1"]], lengths[pair["period_2"]]), 4)}
                for pair in history]
    jsd = [pair["metrics"]["jsd"] for pair in history]
    cosine = [pair["metrics"]["cosine_similarity"] for pair in history]
    by_year: dict[str, list[dict]] = {}
    for pair in enriched:
        by_year.setdefault(pair["period_2"][:4], []).append(pair)
    top_jsd = sorted(enriched, key=lambda pair: -pair["metrics"]["jsd"])[:3]
    low_cosine = sorted(enriched, key=lambda pair: pair["metrics"]["cosine_similarity"])[:3]
    thresholds = report["calibration"]["thresholds"] or {}
    return {
        "history_pairs": len(history),
        "jsd": {"min": min(jsd), "mean": round(mean(jsd), 6), "max": max(jsd), "sorted": sorted(jsd)},
        "cosine": {"min": min(cosine), "mean": round(mean(cosine), 6), "max": max(cosine), "sorted": sorted(cosine)},
        "thresholds": thresholds,
        "top_jsd_pairs": top_jsd,
        "lowest_cosine_pairs": low_cosine,
        "pairs_over_jsd_p90": [pair for pair in enriched if thresholds and pair["metrics"]["jsd"] >= thresholds["jsd_p90"]],
        "pairs_under_cosine_p10": [pair for pair in enriched
                                   if thresholds and pair["metrics"]["cosine_similarity"] <= thresholds["cosine_p10"]],
        "by_year": {year: {"pairs": len(items),
                           "mean_jsd": round(mean(item["metrics"]["jsd"] for item in items), 6),
                           "mean_cosine": round(mean(item["metrics"]["cosine_similarity"] for item in items), 6),
                           "mean_length": round(mean((item["length_1"] + item["length_2"]) / 2 for item in items))}
                    for year, items in sorted(by_year.items())},
        "target_percentile_rank": {
            "jsd": _percentile_rank(jsd, report["target"]["metrics"]["jsd"]),
            "cosine": _percentile_rank(cosine, report["target"]["metrics"]["cosine_similarity"]),
        },
        "document_lengths": {"min": min(lengths.values()), "max": max(lengths.values()),
                             "by_period": dict(sorted(lengths.items(), key=lambda item: quarter_index(item[0])))},
    }


def build_import_report(raw: dict, rows: list[dict], *, document_type: str, language: str) -> dict[str, Any]:
    """The raw analyze() result with FinTrust method descriptors and corpus provenance.

    analyze()'s own method strings describe transcripts; the functions themselves were
    applied unchanged to presentation records, so the FinTrust descriptors are stated.
    """
    by_period = {row["period"]: row for row in rows}
    history = raw["calibration"]["history_pairs"]
    history_hashes = [{"period_1": pair["period_1"], "period_2": pair["period_2"],
                       "sha256": [by_period[pair["period_1"]]["sha256"], by_period[pair["period_2"]]["sha256"]]}
                      for pair in history]
    report = json.loads(json.dumps(raw))
    report["method"].update(
        version=METHOD_VERSION, jsd_log_base=JSD_LOG_BASE, tokenizer=TOKENIZER, tfidf=TFIDF,
        comparison=f"Same-company adjacent-quarter official MOPS {document_type} ({language}), exact scope",
    )
    report["history_source_documents"] = history_hashes
    report["corpus_provenance"] = {
        "source_family": SOURCE_FAMILY, "extraction_method": EXTRACTION_METHOD,
        "preprocessing_version": PREPROCESSING_VERSION,
        "note": "FinTrust official MOPS corpus; not produced by the teammate research branch.",
    }
    report["method_reference"] = {
        "source_research_commit": SOURCE_RESEARCH_COMMIT,
        "functions_used_unmodified": ["calibrate_tsmc_shift.analyze", "calibrate_tsmc_shift.pair",
                                      "data_shift.calculate_jsd", "data_shift.calculate_cosine_similarity"],
        "teammate_method_strings": raw["method"],
    }
    report["warnings"] = [
        "Textual change only; not a fraud, legality or financial-risk verdict.",
        "Thresholds are specific to this company, document type, language, extraction and method version.",
        f"Calibrated on {document_type} records with the unmodified teammate analyze(); the teammate's own "
        "validation used full earnings-call transcripts.",
    ]
    return report


def calibrate_scope(records: list[JsdCorpusRecord], *, ticker: str, document_type: str, language: str,
                    period_1: str, period_2: str, method: FrozenTeammateMethod) -> dict[str, Any]:
    rows = scope_rows(records, ticker=ticker, document_type=document_type, language=language)
    present = {row["period"] for row in rows}
    outcome: dict[str, Any] = {"ticker": ticker, "document_type": document_type, "language": language,
                               "target": {"period_1": period_1, "period_2": period_2},
                               "scope_documents": len(rows), "scope_periods": sorted(present, key=quarter_index)}
    if period_1 not in present or period_2 not in present:
        return {**outcome, "status": "source_gap", "detail": "target pair not present in exact scope"}
    try:
        raw = method.calibrate.analyze(rows, period_1, period_2)
    except ValueError as exc:
        status = "quality_insufficient" if "quality" in str(exc).lower() else "source_gap"
        return {**outcome, "status": status, "detail": str(exc)}
    history = raw["calibration"]["history_pairs"]
    leakage = [pair for pair in history if quarter_index(pair["period_2"]) >= quarter_index(period_1)]
    if leakage:
        raise ScopeRejected("target_leakage", json.dumps(leakage))
    accepted = raw["calibration"]["thresholds"] is not None and len(history) >= method.calibrate.MIN_HISTORY_PAIRS
    report = build_import_report(raw, rows, document_type=document_type, language=language)
    latest = max((pair["period_2"] for pair in history), key=quarter_index, default=None)
    return {
        **outcome,
        "status": "accepted" if accepted else "insufficient_history",
        "history_pair_count": len(history),
        "history_latest_period": latest,
        "no_leakage_proof": {"history_latest_period": latest, "target_period_1": period_1,
                             "all_history_before_target": not leakage},
        "rejected_history_pairs": rejected_history_pairs(method, rows, period_1),
        "target_metrics": raw["target"].get("metrics"),
        "thresholds": raw["calibration"]["thresholds"],
        "drift_result": raw["drift_result"],
        "calculator_module_sha256": method.module_sha256,
        "stability": stability(raw, rows),
        "raw_analyze": raw,
        "import_report": report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--document-type", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--target", nargs=2, default=["2025Q2", "2025Q3"])
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    records = build_records(FileConferencePdfArchiveRepository(args.archive_root), args.ticker)
    try:
        with FrozenTeammateMethod() as method:
            result = calibrate_scope(records, ticker=args.ticker, document_type=args.document_type,
                                     language=args.language, period_1=args.target[0], period_2=args.target[1],
                                     method=method)
    except ScopeRejected as exc:
        result = {"ticker": args.ticker, "document_type": args.document_type, "language": args.language,
                  "status": exc.status, "detail": exc.detail}
    stem = f"{args.ticker}-{args.document_type}-{args.language}"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = result.pop("raw_analyze", None)
    report = result.pop("import_report", None)
    if raw is not None:
        (args.output_dir / f"{stem}.teammate-analyze.json").write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output_dir / f"{stem}.import-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output_dir / f"{stem}.calibration.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = {key: result.get(key) for key in ("ticker", "document_type", "language", "status", "detail",
                                                "scope_documents", "history_pair_count", "history_latest_period",
                                                "target_metrics", "thresholds", "drift_result")}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
