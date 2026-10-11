"""Phase 3 research runs and the review fixture (local; read-only on the approved archive).

    python -m scripts.run_financial_research run --kind restatement_bridge --mode RETROSPECTIVE_FORENSIC
    python -m scripts.run_financial_research run --kind financial_signals --mode STRICT_AS_OF \\
        --cutoff 2016-05-13T00:00:00+08:00 --start-year 2011 --end-year 2016 --version-policy latest_available
    python -m scripts.run_financial_research run ... --persist          # append-only result store
    python -m scripts.run_financial_research fixture --out <dir>         # small source-linked review fixture

Dry-run (no write) unless ``--persist``. ``--persist`` writes only to the separate result store
(``data/historical_audit/research_results.sqlite3`` by default), never to the historical database.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.services.financial_research.case_labels import labels_for_retrospective_evaluation
from app.services.financial_research.modes import AnalysisRequestError, build_context
from app.services.financial_research.result_store import DEFAULT_RESULTS_DATABASE, SqliteResearchResultStore
from app.services.financial_research.service import ResearchConfig, ResearchService

FIXTURE_VERSION = "phase3_review_fixture_v1"


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _dump(path: Path, payload: Any) -> str:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _run_header(run: dict[str, Any]) -> dict[str, Any]:
    return {k: run[k] for k in ("run_id", "result_kind", "analysis_mode", "cutoff_at", "method_version",
                                "approval_status", "input_digest", "output_digest")} | {"snapshot": run["snapshot"]}


def build_fixture(service: ResearchService, out: Path, commit: str | None) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}

    retro = build_context("RETROSPECTIVE_FORENSIC")
    bridge_run = service.build_run("restatement_bridge", "1785", retro, scope="consolidated")
    bridge = bridge_run["output"]
    files["01_restatement_bridge_2011_2015_consolidated.json"] = _dump(out / "01_restatement_bridge_2011_2015_consolidated.json", {
        "fixture": "M1 retrospective restatement bridge (consolidated, FY2011–FY2015)", "run": _run_header(bridge_run),
        "status": bridge["status"], "hindsight": bridge["hindsight"], "warning": bridge["warning"],
        "integrity_all_scopes": service.bridge("1785", retro)["integrity"], "method": bridge["method"],
        "year_bridges": bridge["year_bridges"], "heatmap": bridge["heatmap"],
        "example_rows": [r for r in bridge["rows"] if r["period"] == "2013FY" and r["canonical_metric"]],
        "hypothesis_links": bridge["hypothesis_links"], "inventory_note": bridge["inventory_note"]})

    strict = build_context("STRICT_AS_OF", "2016-05-13T00:00:00+08:00")
    strict_run = service.build_run("financial_signals", "1785", strict, start_year=2011, end_year=2016)
    output = strict_run["output"]
    files["02_strict_pre_revelation_2016-05-13.json"] = _dump(out / "02_strict_pre_revelation_2016-05-13.json", {
        "fixture": "M2 STRICT_AS_OF before the 2016-05-13 revelation", "run": _run_header(strict_run),
        "status": output["status"], "strict_note": output["strict_note"], "counts": output["counts"],
        "timeline_before_cutoff": {k: v for k, v in service.timeline("1785", strict, limit=0).items() if k != "events"},
        "sample_features": [f for f in output["features"] if f["fiscal_year"] == 2015][:4],
        "literature_models": {m["model_id"]: m["full_model_status"] for m in output["literature_models"]["models"]}})

    recon = build_context("CURRENT_EVIDENCE_RECONCILIATION")
    recon_run = service.build_run("source_reconciliation", "1785", recon)
    result = recon_run["output"]
    files["03_fy2025_source_discrepancy.json"] = _dump(out / "03_fy2025_source_discrepancy.json", {
        "fixture": "M3 FY2025 board notice vs filed XBRL vs audited PDF p.8", "run": _run_header(recon_run),
        "counts": result["counts"], "discrepancies": result["discrepancies"],
        "fy2025_board_notice_comparisons": [r for r in result["comparisons"]
                                            if r["comparison_type"] == "board_notice_vs_filed_xbrl" and r["period"] == "2025FY"],
        "explanation_limits": result["explanation_limits"], "routes_to_risk_score": result["routes_to_risk_score"]})

    text = service.text("1785", retro)
    files["04_conference_jsd_readiness.json"] = _dump(out / "04_conference_jsd_readiness.json", {
        "fixture": "Conference archive and JSD readiness (no JSD computed)",
        **{k: v for k, v in text.items() if k != "documents"},
        "documents": [{k: d[k] for k in ("announcement_year", "filename", "sha256", "document_type", "language", "period",
                                          "period_validation_status", "page_count", "text_pages", "jsd_ready",
                                          "readiness_issues")} for d in text["documents"]]})

    manifest = {"fixture_version": FIXTURE_VERSION, "git_commit": commit, "ticker": "1785",
                "approved_baseline": bridge_run["snapshot"]["approved_baseline"],
                "files": {name: {"sha256": sha, "bytes": (out / name).stat().st_size} for name, sha in sorted(files.items())},
                "notes": ["Derived research outputs from the approved archive; no private records, no research verdicts.",
                          "Every value carries its official source identity (announcement key / SHA-256 / URL)."]}
    _dump(out / "MANIFEST.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--kind", required=True, choices=("financial_signals", "restatement_bridge", "source_reconciliation"))
    run.add_argument("--ticker", default="1785")
    run.add_argument("--mode", required=True)
    run.add_argument("--cutoff")
    run.add_argument("--start-year", type=int)
    run.add_argument("--end-year", type=int)
    run.add_argument("--version-policy", default="latest_available")
    run.add_argument("--scope", default="all")
    run.add_argument("--persist", action="store_true")
    run.add_argument("--results-db", default=DEFAULT_RESULTS_DATABASE)
    run.add_argument("--with-labels", action="store_true", help="also record retrospective case labels (RETRO only)")
    fixture = sub.add_parser("fixture")
    fixture.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    config = ResearchConfig.from_env()
    if args.database:
        config.database = args.database
    service = ResearchService(config)
    commit = git_commit()
    try:
        if args.command == "fixture":
            print(json.dumps(build_fixture(service, args.out, commit), ensure_ascii=False, indent=2))
            return 0
        context = build_context(args.mode, args.cutoff)
        record = service.build_run(args.kind, args.ticker, context, start_year=args.start_year, end_year=args.end_year,
                                   version_policy=args.version_policy, scope=args.scope, git_commit=commit)
        summary = {**_run_header(record), "status": record["status"], "persisted": False}
        if args.persist:
            store = SqliteResearchResultStore(args.results_db, protected=(config.database,))
            run_id, created = store.record_run(record)
            summary.update(persisted=True, created=created, projections=store.projection_counts(run_id))
            if args.with_labels:
                summary["labels_recorded"] = store.record_labels(args.ticker, labels_for_retrospective_evaluation(args.ticker, context))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except AnalysisRequestError as exc:
        print(json.dumps(exc.as_dict(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
