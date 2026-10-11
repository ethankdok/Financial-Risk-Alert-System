"""Before/after reproduction of the Phase 3–5 independent-review findings P1-F01, P1-F02, P2-F03, P2-F04.

Run from the repository root (offline; temporary worktree only):

    python docs/development/evidence/phase3_5_debug_repro.py [--before e4fb1e7] [--python <venv python>]

"before" runs the probe inside a temporary ``git worktree`` of the reviewed commit; "after" runs it in the current
working tree. Each probe runs in its own interpreter with ``fintrust_backend/`` as the working directory, so each tree's
own modules are imported unmodified. The worktree is removed afterwards.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PROBE = r'''
import json
from app.services.financial_research.modes import build_context
from app.services.financial_research.input_snapshot import InputSnapshot
from app.services.financial_research import source_reconciliation as sr
from app.services.historical_audit.cloud_config import HistoricalCloudConfig
from app.services.financial_research import result_sync

RECON = build_context("CURRENT_EVIDENCE_RECONCILIATION")
def fact(fy, metric, value, framework="TIFRS", vtype="unknown_revision"):
    return {"fact_id": f"f{fy}{metric}", "ticker": "1785", "period": f"{fy}FY", "fiscal_year": fy, "metric_code": metric,
            "value": value, "unit": "TWD", "statement_type": "x", "statement_scope": "consolidated",
            "accounting_framework": framework, "filing_version_id": f"v{fy}", "filing_version_type": vtype,
            "quality_status": "ok", "effective_available_at": None, "availability_scope": None,
            "availability_evidence_kind": None, "availability_evidence_ref": None, "availability_evidence_hash": None,
            "availability_evidence_url": None, "point_in_time_eligible": False,
            "observation_evidence_status": "no_verified_observation", "artifact_evidence_status": "E0",
            "artifact_reference_status": "included", "artifact_sha256": "a" * 64, "artifact_url": None}
def snap(facts=(), comparisons=(), disclosed=()):
    return InputSnapshot(ticker="1785", context=RECON, start_year=2013, end_year=2025, version_policy="latest_available",
                         backend_name="probe", facts=list(facts), comparisons=list(comparisons), disclosed_values=list(disclosed))
def run_reconcile(s, rows):
    class Backend:
        def list_summary_observations(self, ticker):
            return [dict(r) for r in rows]
    if hasattr(sr, "freeze_dependencies"):
        sr.freeze_dependencies(s, Backend(), None)
        return s.input_digest, sr.reconcile(s)
    return s.input_digest, sr.reconcile(s, Backend())
def summary(v):
    return {"period": "2025FY", "fiscal_year": 2025, "report_period": "2025FY", "observation_role": "current_period",
            "statement_scope": "consolidated", "statement_scope_basis": "x", "accounting_framework": "TIFRS",
            "source_label": "營業收入", "source_metric_code": "r", "canonical_metric": "revenue", "mapping_status": "mapped",
            "value": v, "normalized_value": v, "normalized_unit": "TWD", "content_hash": "e" * 64, "source_url": None,
            "retrieved_at": "2026-10-10T00:00:00+00:00"}
out = {}
d1, o1 = run_reconcile(snap(), [summary("100")])
d2, o2 = run_reconcile(snap(), [summary("200")])
from app.services.financial_research.input_snapshot import digest
out["F01_summary_100_to_200"] = {"input_digest_changed": d1 != d2, "output_digest_changed": digest(o1) != digest(o2)}
comparison = {"period": "2013FY", "fiscal_year": 2013, "statement_scope": "consolidated", "accounting_framework": "TIFRS",
              "statement_type": "income_statement", "pre_label": "營業成本", "post_label": "營業成本",
              "canonical_metric": "cost_of_goods_sold", "sign_factor": -1, "pre_restatement_value": "-32256578",
              "post_restatement_value": "-33223945", "difference": "-967367", "published_unit": "TWD_thousand",
              "disclosed_at": "2016-11-13T21:26:22+08:00", "availability_status": "verified",
              "announcement_key": "mops:20161113:212622:3", "content_hash": "c" * 64, "source_url": None}
row = sr.compare_restatement_post_side(snap([fact(2013, "cost_of_goods_sold", "33223945000", framework="WRONG_FRAMEWORK",
                                                   vtype="restated")], [comparison]))[0]
out["F02_wrong_framework"] = {"outcome": row["outcome"], "reasons": row["reasons"]}
pdf = {"status": "extracted", "unit": "unverified", "pdf_sha256": "f" * 64, "pdf_page_index": 8, "printed_page_label": "8",
       "extractor": "x", "extractor_version": "x", "source_url": None, "artifact_available_at": None,
       "artifact_availability_status": "verified", "reporting_roc_year": 114, "statement_scope": "consolidated",
       "filing_version_id": "v", "filing_version_type": "unknown_revision", "selection_basis": "x", "content_sha256_verified": True,
       "totals": {"total_assets": {"account_code": "1XXX", "label": "x", "value_thousand_twd": "100", "line": "1XXX x 100"}}}
if hasattr(sr, "freeze_dependencies"):
    from app.services.financial_research.pdf_evidence import identity_checks
    pdf["checks"] = identity_checks(pdf, 2025)
check = sr.pdf_check([{"metric": "total_assets", "source_a": {"value_normalized": "100000"},
                       "source_b": {"value_twd": "100000"}}], pdf)["checks"][0]
out["F03_unverified_unit"] = {k: check.get(k) for k in ("status", "equals_filed_xbrl", "equals_board_notice", "reasons")}
config = HistoricalCloudConfig.from_env({"HISTORICAL_CLOUD_SYNC_ENABLED": "true", "HISTORICAL_CLOUD_ENVIRONMENT": "isolated-test",
    "HISTORICAL_CLOUD_PROJECT": "fintrust-research-test", "HISTORICAL_CLOUD_BUCKET": "fintrust-research-test-bucket",
    "HISTORICAL_CLOUD_COLLECTION_PREFIX": "historical_research_staging_abc"})
class Fake:
    def collection(self, name): raise AssertionError("no writes in probe")
out["F04_prefix_staging_abc"] = result_sync.build_cloud_result_store(config, client=Fake()).prefix
print(json.dumps(out, ensure_ascii=False))
'''


def probe(tree: Path, python: str) -> dict:
    result = subprocess.run([python, "-c", PROBE], cwd=tree / "fintrust_backend", capture_output=True, text=True,
                            encoding="utf-8", timeout=300)
    if result.returncode != 0:
        return {"error": result.stderr.strip().splitlines()[-1:]}
    return json.loads(result.stdout.strip().splitlines()[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", default="e4fb1e7943dc59680f087b6e6b3f3abd8590566a")
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    root = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True).stdout.strip())
    with tempfile.TemporaryDirectory() as directory:
        worktree = Path(directory) / "before"
        subprocess.run(["git", "worktree", "add", "--detach", "-q", str(worktree), args.before], cwd=root, check=True)
        try:
            output = {"before": {"commit": args.before, **probe(worktree, args.python)},
                      "after": {"commit": "working tree", **probe(root, args.python)}}
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", str(worktree)], cwd=root, check=False)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
