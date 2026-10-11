"""Generate the literature-model evidence set (read-only over the approved archive + the literature sidecar).

    cd fintrust_backend && python ../docs/development/evidence/literature_evidence.py --out <dir>

Writes: coverage matrices (both version policies), the 1785 case-study results (both policies + strict cutoffs),
the 2016-notice 'pre' cross-check against the original FY2011-2012 annual reports, the method status ledger and the
research OpenAPI snapshot. No network, no writes outside ``--out``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path

BACKEND = Path.cwd()
sys.path.insert(0, str(BACKEND))

from app.services.financial_research import decimal_math as dm  # noqa: E402
from app.services.financial_research.literature_method_registry import (  # noqa: E402
    BENEISH_MODEL_ID,
    DECHOW_MODEL_ID,
    registry_payload,
)
from app.services.financial_research.modes import build_context  # noqa: E402
from app.services.financial_research.service import ResearchService  # noqa: E402

MODELS = [BENEISH_MODEL_ID, DECHOW_MODEL_ID]
RETRO = build_context("RETROSPECTIVE_FORENSIC")
# canonical metric of the 2016 notice -> TW-GAAP line of the original annual report
NOTICE_TO_LINE = {"revenue": "code:4100", "cost_of_goods_sold": "code:5000", "gross_profit": "code:5910",
                  "current_assets": "code:11XX", "total_assets": ("code:1XXX", "label:資產總計"),
                  "current_liabilities": "code:21XX", "total_liabilities": "code:2XXX", "equity": "code:3XXX",
                  "inventory": "code:120X", "net_income": "code:9600", "accounts_receivable": "code:1140"}


def slim(result: dict) -> dict:
    keep = ("fiscal_year", "status", "score", "probability_original_model", "probit_probability_original_sample",
            "predicted_value", "component_coverage", "validation_warnings", "reasons", "observation")
    row = {k: result.get(k) for k in keep}
    row["components"] = {c["variable"]: {"status": c["status"], "value": c["value"],
                                         "reasons": [r["code"] for r in c.get("reasons", [])]}
                         for c in result.get("components", [])}
    row["missing_inputs"] = [{k: m.get(k) for k in ("component", "metric", "relative_period", "fiscal_year", "status")}
                             for m in result.get("missing_inputs", [])]
    return row


def notice_crosscheck(service: ResearchService) -> dict:
    comparisons = [c for c in service.backend.list_restatement_comparisons("1785")
                   if c["fiscal_year"] in (2011, 2012) and c["statement_scope"] == "consolidated" and c["canonical_metric"]]
    observations = service.literature_store.list_observations("1785")
    original = {o["filing_version_id"] for o in observations if o["filing_version_type"] == "original"}
    rows = []
    for c in comparisons:
        lines = NOTICE_TO_LINE.get(c["canonical_metric"])
        if lines is None:
            continue
        candidates = [o for o in observations if o["filing_version_id"] in original
                      and o["line_key"] in (lines if isinstance(lines, tuple) else (lines,))
                      and o["period_end"] == f"{c['fiscal_year']}-12-31" and o["filing_fiscal_year"] == c["fiscal_year"]]
        pre = dm.parse_decimal(c["pre_restatement_value"])
        pre_twd = dm.mul(dm.to_twd(pre, c["published_unit"]), Decimal(c["sign_factor"])) if pre is not None else None
        value = dm.parse_decimal(candidates[0]["value"]) if candidates else None
        if value is not None and pre_twd is not None and c["canonical_metric"] == "cost_of_goods_sold":
            pre_twd = abs(pre_twd)
        rows.append({"fiscal_year": c["fiscal_year"], "metric": c["canonical_metric"], "notice_pre_label": c["pre_label"],
                     "notice_pre_twd": dm.text(pre_twd), "original_report_line": candidates[0]["source_concept"] if candidates else None,
                     "original_report_twd": dm.text(value),
                     "outcome": "no_original_line" if value is None or pre_twd is None
                     else "equal" if value == pre_twd else "differs",
                     "difference_twd": dm.text(dm.sub(pre_twd, value)) if value is not None and pre_twd is not None
                     and value != pre_twd else None})
    return {"purpose": ("Checks whether the 2016 notice 'pre' values equal the archived original FY2011-2012 consolidated "
                        "annual reports (they are otherwise only 'values as disclosed in the 2016 notice')."),
            "counts": dict(Counter(r["outcome"] for r in rows)), "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    service = ResearchService()
    out = {}
    for policy in ("latest_available", "original_only"):
        coverage = service.literature_coverage("1785", RETRO, version_policy=policy, start_year=2011, end_year=2025)
        (args.out / f"literature_coverage_matrix_{policy}.json").write_text(
            json.dumps(coverage, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
        compared = service.literature_compare("1785", RETRO, start_year=2011, end_year=2025, version_policy=policy)
        run = service.build_run("literature_comparison", "1785", RETRO, start_year=2011, end_year=2025,
                                version_policy=policy)
        out[policy] = {"run_id": run["run_id"], "input_digest": run["input_digest"], "output_digest": run["output_digest"],
                       "coverage": compared["coverage"], "concordance": compared["concordance"],
                       "filing_selection": compared["models"]["filing_selection"],
                       "results": {m: [slim(r) for r in compared["models"]["results"][m]] for m in MODELS},
                       "pairs": [{k: p[k] for k in ("fiscal_year", "comparable", "reasons")}
                                 | {"original_benchmark_side": p.get("original_benchmark_side")} for p in compared["pairs"]],
                       "coverage_summary": Counter(f"{r['model_id']}|{r['readiness']}" for r in coverage["rows"])}
    strict = {}
    for cutoff in ("2016-05-13T00:00:00+08:00", "2016-11-13T21:26:22+08:00", "2016-11-13T21:26:23+08:00"):
        computed = service.literature_compute("1785", build_context("STRICT_AS_OF", cutoff), model_ids=MODELS,
                                              start_year=2011, end_year=2015, version_policy="latest_available")
        strict[cutoff] = {"status": computed["status"], "counts": computed["counts"],
                          "literature_observations_admitted": computed["input_snapshot"]["literature_observation_count"],
                          "scores": sorted({str(r["score"]) for rows in computed["results"].values() for r in rows})}
    out["strict"] = strict
    (args.out / "literature_case_study_1785_results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    (args.out / "notice_pre_vs_original_report_crosscheck.json").write_text(
        json.dumps(notice_crosscheck(service), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    registry = registry_payload()
    ledger = {"registry_version": registry["registry_version"], "approval_status": registry["approval_status"],
              "models": [{"model_id": m["model_id"], "formula_version": m["formula_version"],
                          "score_enabled": m["score_enabled"], "verification_problems": m["verification_problems"],
                          "coefficient_verification": sorted({t["verification"] for t in m["terms"]}),
                          "blocked_by": {"paper": [] if m["score_enabled"] else m["verification_problems"],
                                         "financial_data": "see coverage matrix (per year)",
                                         "software": []},
                          "method_owner_decisions_pending": ["Taiwan input mapping (DRAFT)", "local interpretation",
                                                             "R&D in SG&A", "IFRS 16 depreciation / lease debt",
                                                             "IFRS transition opening balance as t-2"]}
                         for m in registry["models"]],
              "paper_sources": {k: {"doi": v["doi"], "version": v["verified_text"]["version"],
                                    "sha256": v["verified_text"]["sha256"], "redistributed": False}
                                for k, v in registry["paper_sources"].items()}}
    (args.out / "literature_method_status_ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n",
                                                                   encoding="utf-8")
    from app.main import app

    schema = app.openapi()
    research = {"openapi": schema["openapi"], "info": schema["info"],
                "paths": {k: v for k, v in schema["paths"].items() if k.startswith("/api/v1/research")}}
    (args.out / "openapi_research_v2.json").write_text(json.dumps(research, ensure_ascii=False, indent=1) + "\n",
                                                       encoding="utf-8")
    print(json.dumps({p: {"coverage": out[p]["coverage"], "run_id": out[p]["run_id"]} for p in
                      ("latest_available", "original_only")} | {"strict": strict}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
