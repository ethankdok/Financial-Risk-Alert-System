"""Generate the literature-model evidence set (read-only over the approved archive + the literature sidecar).

    cd fintrust_backend && python ../docs/development/evidence/literature_evidence.py --out <dir>

Writes: coverage matrices (both version policies), the 1785 case-study results (both policies + strict cutoffs),
the 2016-notice 'pre' cross-check against the original FY2011-2012 annual reports, the method status ledger and the
research OpenAPI snapshot. No network, no writes outside ``--out``.

With ``--previous-results`` / ``--previous-coverage-dir`` (the f83aa98 evidence, read from its review ZIP) it also
writes the data-integrity correction evidence: the old-vs-corrected score delta table, the audit of the reviewed
matrix entries (LIT-F01), the TW-GAAP identity diagnostics (LIT-F02), alias-candidate statistics (LIT-F03), every
t-2 cross-filing overlap check (LIT-F04) and the run supersession records.
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


def _rows_by_key(matrix: dict) -> dict:
    return {(r["model_id"], r["variable"], r["fiscal_year"], r["relative_period"], r["formula_component"]): r
            for r in matrix["rows"]}


def correction_evidence(service: ResearchService, out: dict, coverages: dict, previous: dict, previous_dir: Path) -> dict:
    """Old (f83aa98) vs corrected results, reviewed-entry audit and per-finding evidence (read-only)."""
    delta = []
    for policy in ("latest_available", "original_only"):
        for model in MODELS:
            old = {r["fiscal_year"]: r for r in previous[policy]["results"][model]}
            for row in out[policy]["results"][model]:
                before = old.get(row["fiscal_year"], {})
                if before.get("status") == row["status"] and before.get("score") == row["score"]:
                    change = "unchanged"
                elif before.get("score") is not None and row["score"] is None:
                    change = "score_withdrawn"
                elif before.get("score") is None and row["score"] is not None:
                    change = "score_added"
                else:
                    change = "score_changed" if before.get("score") != row["score"] else "status_reason_changed"
                delta.append({"version_policy": policy, "model_id": model, "fiscal_year": row["fiscal_year"],
                              "f83aa98_status": before.get("status"), "f83aa98_score": before.get("score"),
                              "corrected_status": row["status"], "corrected_score": row["score"], "change": change,
                              "corrected_missing_inputs": sorted({f"{m['metric']}:{m['relative_period']}:{m['status']}"
                                                                  for m in row["missing_inputs"]})})
    audit = {}
    for policy in ("latest_available", "original_only"):
        old_matrix = json.loads((previous_dir / f"literature_coverage_matrix_{policy}.json").read_text(encoding="utf-8"))
        new_rows = _rows_by_key(coverages[policy])
        entries: dict = {}
        for key, row in _rows_by_key(old_matrix).items():
            if row["readiness"] == "complete" and not row["sources"]:
                new = new_rows[key]
                entry = entries.setdefault((row["fiscal_year"], row["formula_component"], row["relative_period"]), {
                    "fiscal_year": row["fiscal_year"], "metric": row["formula_component"],
                    "relative_period": row["relative_period"],
                    "f83aa98": {"readiness": "complete", "value_twd": row.get("value_twd"), "sources": 0},
                    "corrected": {"readiness": new["readiness"], "input_status": new["input_status"],
                                  "evidence_type": new["evidence_type"], "value_twd": new.get("value_twd"),
                                  "sources": len(new["sources"]), "missing_reason": new["missing_reason"],
                                  "zero_evidence": new.get("zero_evidence")},
                    "matrix_rows": []})
                entry["matrix_rows"].append(f"{key[0]}|{key[1]}")
        audit[policy] = {"reviewed_entries": len(entries),
                         "matrix_rows": sum(len(e["matrix_rows"]) for e in entries.values()),
                         "corrected_status_counts": dict(Counter(
                             f"{e['corrected']['input_status']}|{e['corrected']['evidence_type']}" for e in entries.values())),
                         "entries": sorted(entries.values(), key=lambda e: (e["fiscal_year"], e["metric"],
                                                                            e["relative_period"]))}
    from app.services.financial_research.literature_extraction import TWGAAP_PDF_EXTRACTOR_VERSION

    identities = [{k: d.get(k) for k in ("fiscal_year", "filing_version_id", "filing_version_type", "raw_sha256",
                                         "statement_pages", "identity_checks", "identity_rule_version",
                                         "arithmetic_checks", "failed_identities", "arithmetic_check_details")}
                  for d in service.literature_store.list_diagnostics("1785")
                  if d.get("extractor_version") == TWGAAP_PDF_EXTRACTOR_VERSION and d.get("arithmetic_checks")]
    aliases: Counter = Counter()
    overlaps = []
    for policy, coverage in coverages.items():
        seen = set()
        for row in coverage["rows"]:
            key = (row["fiscal_year"], row["formula_component"], row["relative_period"])
            if key in seen:
                continue
            seen.add(key)
            candidates = row.get("alias_candidates") or []
            if len(candidates) > 1:
                aliases[f"{policy}|{row['input_status']}|{len(candidates)}_candidates"] += 1
            if row.get("input_status") == "mapping_conflict":
                aliases[f"{policy}|mapping_conflict"] += 1
            if row.get("cross_filing_overlap"):
                overlaps.append({"version_policy": policy, "fiscal_year": row["fiscal_year"],
                                 "input_status": row["input_status"], **row["cross_filing_overlap"]})
    supersession = [{"version_policy": p, "superseded_run_id": previous[p]["run_id"],
                     "superseded_input_digest": previous[p]["input_digest"], "corrected_run_id": out[p]["run_id"],
                     "corrected_input_digest": out[p]["input_digest"],
                     "note": ("f83aa98 literature runs were evidence-only (never persisted); the corrected run records "
                              "supersedes_run_id and has a new run id because the method versions changed.")}
                    for p in ("latest_available", "original_only")]
    return {"delta": {"rows": delta, "counts": dict(Counter(f"{r['version_policy']}|{r['change']}" for r in delta))},
            "lit_f01_reviewed_entries": audit,
            "lit_f02_twgaap_identity_diagnostics": identities,
            "lit_f03_alias_candidates": dict(aliases),
            "lit_f04_cross_filing_overlaps": {"counts": dict(Counter(f"{o['version_policy']}|{o['status']}"
                                                                     for o in overlaps)), "checks": overlaps},
            "zero_evidence_records": {p: c["zero_evidence_records"] for p, c in coverages.items()},
            "run_supersession": supersession}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--previous-results", type=Path)
    parser.add_argument("--previous-coverage-dir", type=Path)
    parser.add_argument("--supersedes-results", type=Path,
                        help="case-study results whose run ids the new runs supersede (no correction evidence)")
    args = parser.parse_args()
    previous = json.loads(args.previous_results.read_text(encoding="utf-8")) if args.previous_results else None
    superseded = previous or (json.loads(args.supersedes_results.read_text(encoding="utf-8"))
                              if args.supersedes_results else None)
    args.out.mkdir(parents=True, exist_ok=True)
    service = ResearchService()
    out, coverages = {}, {}
    for policy in ("latest_available", "original_only"):
        coverage = service.literature_coverage("1785", RETRO, version_policy=policy, start_year=2011, end_year=2025)
        coverages[policy] = coverage
        (args.out / f"literature_coverage_matrix_{policy}.json").write_text(
            json.dumps(coverage, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
        compared = service.literature_compare("1785", RETRO, start_year=2011, end_year=2025, version_policy=policy)
        run = service.build_run("literature_comparison", "1785", RETRO, start_year=2011, end_year=2025,
                                version_policy=policy,
                                supersedes_run_id=superseded[policy]["run_id"] if superseded else None)
        out[policy] = {"run_id": run["run_id"], "input_digest": run["input_digest"], "output_digest": run["output_digest"],
                       "method_version": run["method_version"], "supersedes_run_id": run["supersedes_run_id"],
                       "coverage": compared["coverage"], "concordance": compared["concordance"],
                       "filing_selection": compared["models"]["filing_selection"],
                       "results": {m: [slim(r) for r in compared["models"]["results"][m]] for m in MODELS},
                       "pairs": [{k: p[k] for k in ("fiscal_year", "comparable", "reasons")}
                                 | {"original_benchmark_side": p.get("original_benchmark_side")} for p in compared["pairs"]],
                       "coverage_summary": Counter(f"{r['model_id']}|{r['readiness']}" for r in coverage["rows"]),
                       "input_status_counts": coverage["input_status_counts"]}
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
    if previous is not None:
        correction = correction_evidence(service, out, coverages, previous, args.previous_coverage_dir)
        (args.out / "literature_data_integrity_correction_evidence.json").write_text(
            json.dumps(correction, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
        print(json.dumps({"delta_counts": correction["delta"]["counts"],
                          "reviewed": {p: {k: v for k, v in a.items() if k != "entries"}
                                       for p, a in correction["lit_f01_reviewed_entries"].items()},
                          "overlaps": correction["lit_f04_cross_filing_overlaps"]["counts"],
                          "aliases": correction["lit_f03_alias_candidates"]}, ensure_ascii=False, indent=1))
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
                                                             "IFRS transition opening balance as t-2",
                                                             "zero-evidence rule twgaap_equity_section_exhaustive_enumeration",
                                                             "component-level presentation rule for partial sums",
                                                             "explanation register for cross-filing overlap differences"]}
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
