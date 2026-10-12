"""R01/R02 hardening evidence for 1785 (read-only over the approved archive and the literature sidecar).

    cd fintrust_backend && python ../docs/development/evidence/literature_hardening_evidence.py \
        --current <dir from literature_evidence.py> --reference <df0fc44 evidence dir> --out <file.json>

- R01 audit: for every selected filing of both version series, every statement anchor and every period the filing
  presents: how many anchor candidates are present, whether they agree and pass the source gate, and whether the
  former first-present-candidate rule would have decided differently.
- R02 audit: every frozen zero-evidence record of both series re-verified at its point of use (``check_zero_proof``).
- Comparison with the df0fc44 evidence: every model-year status/score and every coverage-matrix row (status, value,
  evidence type, reasons), the zero-proof operands, and the strict cutoffs.
No network, no writes outside ``--out``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path.cwd()
sys.path.insert(0, str(BACKEND))

from app.services.financial_research.literature_inputs import (  # noqa: E402
    ANCHORS,
    FilingLines,
    _agreeing,
    _anchor,
    check_zero_proof,
)
from app.services.financial_research.literature_method_registry import BENEISH_MODEL_ID, DECHOW_MODEL_ID  # noqa: E402
from app.services.financial_research.modes import build_context  # noqa: E402
from app.services.financial_research.service import ResearchService  # noqa: E402

MODELS = [BENEISH_MODEL_ID, DECHOW_MODEL_ID]
POLICIES = ("latest_available", "original_only")
RETRO = build_context("RETROSPECTIVE_FORENSIC")
ROW_FIELDS = ("readiness", "input_status", "evidence_type", "value_twd", "missing_reason", "filing_version_id")


def anchor_audit(snapshot) -> dict:
    rows, counts = [], Counter()
    for record in snapshot.literature_filings:
        filing = record["filing"]
        if not filing:
            continue
        fid, framework = filing["filing_version_id"], filing["accounting_framework"]
        lines = FilingLines([o for o in snapshot.literature_observations if o["filing_version_id"] == fid])
        periods = sorted({period for (_, period) in lines.values} | {period for (_, period) in lines.conflicts})
        for anchor, target in ANCHORS.get(framework, {}).items():
            candidates = list(target) if isinstance(target, tuple) else [target]
            for period in periods:
                present = [c for c in candidates if lines.present(c, period)]
                if not present:
                    continue
                status, reasons, _ = _anchor(lines, framework, anchor, period)
                obs, problem = lines.get(present[0], period)  # the df0fc44 rule: first present candidate only
                former = "ambiguous_version" if problem else (lines.gate(obs) or (None,))[0]
                key = f"{framework}|{anchor}|{len(present)}_present|{status or 'usable'}"
                counts[key] += 1
                if len(present) > 1 or status:
                    _, _, _, listed = _agreeing(lines, present, period)
                    rows.append({"filing_version_id": fid, "fiscal_year": filing["fiscal_year"], "framework": framework,
                                 "anchor": anchor, "period": period, "present_candidates": listed,
                                 "status": status or "usable", "reasons": reasons, "df0fc44_rule_status": former or "usable",
                                 "decision_changed": (status or "usable") != (former or "usable")})
    return {"counts": dict(sorted(counts.items())), "multi_candidate_or_blocked": rows,
            "decisions_changed": sum(r["decision_changed"] for r in rows)}


def proof_audit(snapshot) -> dict:
    frameworks = {r["filing"]["filing_version_id"]: r["filing"]["accounting_framework"]
                  for r in snapshot.literature_filings if r["filing"]}
    checked = []
    for record in snapshot.literature_zero_evidence:
        fid = record["filing_version_id"]
        lines = FilingLines([o for o in snapshot.literature_observations if o["filing_version_id"] == fid],
                            [z for z in snapshot.literature_zero_evidence if z["filing_version_id"] == fid])
        verified, reason = check_zero_proof(lines, frameworks[fid], record["metric"], record["period"], record["rule"])
        checked.append({"filing_version_id": fid, "metric": record["metric"], "period": record["period"],
                        "stored_status": record["status"], "rule_version": record["rule_version"],
                        "evidence_fingerprint": record["evidence_fingerprint"],
                        "point_of_use": "accepted" if verified else reason,
                        "operand_ids": [o["observation_id"] for o in record["operands"]]})
    return {"counts": dict(Counter(f"{c['stored_status']}|{c['point_of_use']}" for c in checked)), "records": checked}


def compare(current: Path, reference: Path) -> dict:
    new = json.loads((current / "literature_case_study_1785_results.json").read_text(encoding="utf-8"))
    old = json.loads((reference / "literature_case_study_1785_results.json").read_text(encoding="utf-8"))
    cells, matrix, proofs = [], {}, {}
    for policy in POLICIES:
        for model in MODELS:
            before = {r["fiscal_year"]: r for r in old[policy]["results"][model]}
            for row in new[policy]["results"][model]:
                prior = before[row["fiscal_year"]]
                cells.append({"version_policy": policy, "model_id": model, "fiscal_year": row["fiscal_year"],
                              "df0fc44_status": prior["status"], "df0fc44_score": prior["score"],
                              "status": row["status"], "score": row["score"],
                              "identical": (prior["status"], prior["score"], prior["missing_inputs"])
                              == (row["status"], row["score"], row["missing_inputs"])})
        old_m = json.loads((reference / f"literature_coverage_matrix_{policy}.json").read_text(encoding="utf-8"))
        new_m = json.loads((current / f"literature_coverage_matrix_{policy}.json").read_text(encoding="utf-8"))
        key = lambda r: (r["model_id"], r["variable"], r["fiscal_year"], r["relative_period"], r["formula_component"])  # noqa: E731
        old_rows, new_rows = {key(r): r for r in old_m["rows"]}, {key(r): r for r in new_m["rows"]}
        changed = []
        for k in sorted(set(old_rows) | set(new_rows), key=str):
            a, b = old_rows.get(k), new_rows.get(k)
            fields = ([f for f in ROW_FIELDS if a.get(f) != b.get(f)] if a and b else ["row_added_or_removed"])
            if a and b and [s.get("observation_id") for s in a["sources"]] != [s.get("observation_id") for s in b["sources"]]:
                fields.append("source_observation_ids")
            if fields:
                changed.append({"key": list(k), "fields": fields,
                                "df0fc44": {f: (a or {}).get(f) for f in ROW_FIELDS},
                                "hardened": {f: (b or {}).get(f) for f in ROW_FIELDS}})
        matrix[policy] = {"rows": len(new_rows), "df0fc44_rows": len(old_rows), "changed": changed,
                          "input_status_counts_identical": old_m["input_status_counts"] == new_m["input_status_counts"]}
        strip = lambda z: {k: v for k, v in z.items() if k not in ("rule_version", "evidence_fingerprint")}  # noqa: E731
        proofs[policy] = {"records": len(new_m["zero_evidence_records"]),
                          "identical_except_rule_version_and_fingerprint":
                              [strip(z) for z in old_m["zero_evidence_records"]]
                              == [strip(z) for z in new_m["zero_evidence_records"]],
                          "rule_versions": sorted({z["rule_version"] for z in new_m["zero_evidence_records"]}),
                          "df0fc44_rule_versions": sorted({z["rule_version"] for z in old_m["zero_evidence_records"]})}
    computed = Counter(c["status"] == "computed" for c in cells)
    return {"cells": cells, "counts": {"computed": computed[True], "not_computable": computed[False],
                                       "identical_cells": sum(c["identical"] for c in cells), "total": len(cells)},
            "coverage_matrix": matrix, "zero_proofs": proofs,
            "strict_identical": old["strict"] == new["strict"], "strict": new["strict"],
            "runs": {p: {"df0fc44_run_id": old[p]["run_id"], "df0fc44_input_digest": old[p]["input_digest"],
                         "df0fc44_method_version": old[p]["method_version"], "run_id": new[p]["run_id"],
                         "input_digest": new[p]["input_digest"], "output_digest": new[p]["output_digest"],
                         "method_version": new[p]["method_version"], "supersedes_run_id": new[p]["supersedes_run_id"]}
                     for p in POLICIES}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    service = ResearchService()
    audits = {}
    for policy in POLICIES:
        snapshot = service.literature_snapshot("1785", RETRO, start_year=2011, end_year=2025, version_policy=policy)
        audits[policy] = {"r01_anchor_candidates": anchor_audit(snapshot), "r02_zero_proofs": proof_audit(snapshot)}
    report = {"audits": audits, "comparison_with_df0fc44": compare(args.current, args.reference)}
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    summary = {p: {"anchor_counts": a["r01_anchor_candidates"]["counts"],
                   "anchor_decisions_changed": a["r01_anchor_candidates"]["decisions_changed"],
                   "proofs": a["r02_zero_proofs"]["counts"]} for p, a in audits.items()}
    c = report["comparison_with_df0fc44"]
    summary["comparison"] = {"counts": c["counts"], "strict_identical": c["strict_identical"],
                             "matrix_changed_rows": {p: len(m["changed"]) for p, m in c["coverage_matrix"].items()},
                             "zero_proofs": c["zero_proofs"], "runs": c["runs"]}
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
