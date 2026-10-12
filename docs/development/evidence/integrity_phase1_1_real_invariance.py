"""Gate A invariance: genuine 2330 / 2454 / 3711 results after the Phase 1.1 hardening vs the accepted 0c51a74
real outputs (read-only; the pipeline DB is served from a SHA-verified temporary copy).

    (cwd = fintrust_backend) python integrity_phase1_1_real_invariance.py --reference <integrity_phase1_real_outputs.json> --out <json>

Compares every decision-relevant field and lists each difference; exits 1 on any unexplained difference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
DATA = Path.cwd() / "data"
# Fields added by the hardening (absent before) are reported as additions, not as differences.
NEW_FINDING_FIELDS = {"latest_fact_fiscal_year", "latest_period_status", "freshness_status", "last_computable"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finding_core(f):
    return {k: f[k] for k in ("check_id", "status", "review_queue", "period", "evidence_ids", "reasons")} | {
        "computed": {k: v for k, v in f["computed"].items() if k != "cfo_minus_net_income_twd"},
        "series": [{k: s.get(k) for k in ("period", "status", "evidence_ids")}
                   | {"computed": {k: v for k, v in (s.get("computed") or {}).items() if k != "cfo_minus_net_income_twd"}}
                   for s in f["series"]]}


def core(result):
    return {
        "financial_findings": [finding_core(f) for f in result["financial_findings"]],
        "claims": [{k: c.get(k) for k in ("claim_id", "verdict", "reason_code", "precision_check")} for c in result["claim_checks"]],
        "paper_models": [{k: m[k] for k in ("model_id", "status", "raw_score", "missing_input_count")} for m in result["paper_models"]],
        "data_shift": {k: (result["data_shift"] or {}).get(k) for k in ("status", "period_1", "period_2", "metrics",
                                                                         "calibration_status", "drift_level")},
        "queue": result["investigation_priority"]["queue"],
        "triggered_by": result["investigation_priority"]["triggered_by"],
        "evidence_ids": sorted(r["evidence_id"] for r in result["evidence_records"]),
        "overview": [(r["fiscal_period"], r["metric"], r["value_twd"]) for r in result["financial_overview"]["rows"]],
    }


def diff(a, b, path=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in sorted(set(a) | set(b)):
            out += diff(a.get(key), b.get(key), f"{path}.{key}")
        return out
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [{"path": path, "accepted_0c51a74": a, "now": b}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    from app.services.analysis_repository import SqliteAnalysisRepository
    from app.services.claim_evidence_adapter import ClaimEvidenceAdapter
    from app.services.claim_verification_service import ClaimVerificationService
    from app.services.integrity.contracts import AssessmentRequest
    from app.services.integrity.service import IntegrityWorkbench
    from app.services.jsd_bridge_service import JsdBridgeService
    from app.services.jsd_calibration import build_jsd_calibration_repository
    from app.services.mops_conference_pdf_repository import FileConferencePdfArchiveRepository
    from app.services.pipeline_evidence_repository import PipelineEvidenceRepository

    original = DATA / "financial_pipeline.sqlite3"
    before = sha(original)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "pipeline_copy.sqlite3"
        shutil.copyfile(original, copy)
        assert sha(copy) == before
        repo = SqliteAnalysisRepository(str(copy))
        archive = FileConferencePdfArchiveRepository(DATA / "official-ir-pdfs-live-test")
        claims = ClaimVerificationService(ClaimEvidenceAdapter(fact_repository=PipelineEvidenceRepository(repo),
                                                               conference_repository=archive, event_repository=repo), llm=None)
        workbench = IntegrityWorkbench(repo, jsd_bridge=JsdBridgeService(archive, build_jsd_calibration_repository()),
                                       conference_repository=archive, claim_service=claims,
                                       literature_database=str(DATA / "literature_models" / "literature_inputs.sqlite3"))
        now = {t: workbench.assess(AssessmentRequest(ticker=t)) for t in ("2454", "2330", "3711")}
    reference = json.loads(Path(args.reference).read_text(encoding="utf-8"))["outputs"]
    report = {"pipeline_db_sha256_before": before, "pipeline_db_sha256_after": sha(original), "tickers": {}}
    problems = []
    for ticker, key in (("2454", "2454"), ("2330", "2330"), ("3711", "3711_no_snapshot")):
        differences = diff(core(reference[key]), core(now[ticker]))
        additions = {f["check_id"]: {k: f.get(k) for k in NEW_FINDING_FIELDS} for f in now[ticker]["financial_findings"]
                     if f["check_id"].startswith(("F1", "F2"))}
        quotes = {c["claim_id"]: (c.get("quote_extraction") or {}).get("result") for c in now[ticker]["claim_checks"]}
        report["tickers"][ticker] = {"differences": differences, "new_fields": additions, "quote_extraction": quotes,
                                     "untrusted_or_demo_exclusions": [e for e in now[ticker]["source_coverage"]["excluded_fact_records"]
                                                                      if not e["reason"].startswith("period_type_")]}
        problems += [f"{ticker}{d['path']}" for d in differences]
    report["db_unchanged"] = report["pipeline_db_sha256_after"] == before
    report["result"] = "IDENTICAL" if not problems and report["db_unchanged"] else "DIFFERENT"
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({t: {"differences": len(v["differences"]), "quote_extraction": v["quote_extraction"],
                          "new_fields": v["new_fields"], "exclusions": v["untrusted_or_demo_exclusions"]}
                      for t, v in report["tickers"].items()}, ensure_ascii=False, indent=1))
    for ticker, value in report["tickers"].items():
        for d in value["differences"]:
            print("DIFF", ticker, d)
    print("db unchanged:", report["db_unchanged"], "| RESULT:", report["result"])
    return 0 if report["result"] == "IDENTICAL" else 1


if __name__ == "__main__":
    sys.exit(main())
