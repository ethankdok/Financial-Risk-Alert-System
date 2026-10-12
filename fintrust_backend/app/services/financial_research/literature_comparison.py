"""Literature-model orchestration: input freezing, per-year model runs, paired comparison and coverage matrix.

Unit of observation: ``(ticker, fiscal_year, statement_scope, accounting_framework, filing_version_side,
as_of_cutoff, model_version)``. Both models are evaluated on the *same* frozen snapshot, version policy, mode and
cutoff. A pair is ``comparable`` only when both published scores are computed for the same observation; otherwise
each side keeps its explicit status. Nothing is ranked across incomparable years, and missing output is never zero.

Version series (explicit ``version_policy``, no hidden fallback):

- ``latest_available``: for each fiscal year the latest filing version type present in the archive
  (``restated`` > ``unknown_revision`` > ``original``); if that version's statements are not machine-readable the
  year is ``source_unavailable`` (it does not fall back to an older version).
- ``original_only``: only filing versions typed ``original``.
- ``earliest_available`` is refused for literature models (it would mix series across years).

Modes: RETROSPECTIVE_FORENSIC (hindsight=true); STRICT_AS_OF admits only literature observations accepted by the
strict source contract (currently none, so every year is ``insufficient_point_in_time_evidence``);
CURRENT_EVIDENCE_RECONCILIATION is unsupported (literature scores have no approved meaning there).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.services.financial_research import beneish_1999, dechow_2011
from app.services.financial_research.case_knowledge import accounting_regime
from app.services.financial_research.input_snapshot import InputSnapshot, latest_time, safe_official_url
from app.services.financial_research.literature_extraction import EXTRACTOR_VERSION, is_current_observation
from app.services.financial_research.literature_inputs import (
    MAPPING_INDEX,
    MAPPING_VERSION,
    PANEL_VERSION,
    SOURCE_GATE_VERSION,
    ZERO_POLICY_VERSION,
    FilingLines,
    Panel,
    lease_flags,
    period_key,
    zero_evidence_records,
)
from app.services.financial_research.literature_method_registry import (
    APPROVAL_STATUS,
    BENEISH_MODEL_ID,
    COMPARISON_ID,
    DECHOW_MODEL_ID,
    REGISTRY_VERSION,
)
from app.services.financial_research.modes import AnalysisMode, AnalysisRequestError, ModeNotSupportedError
from app.services.financial_research.version_selection import SELECTION_POLICY_VERSION

METHOD_VERSION = COMPARISON_ID
ENGINES = {BENEISH_MODEL_ID: beneish_1999, DECHOW_MODEL_ID: dechow_2011}
LITERATURE_VERSION_POLICIES = ("latest_available", "original_only")
TYPE_RANK = {"restated": 3, "unknown_revision": 2, "original": 1}
LIMITATIONS = (
    "Published US-sample models (Beneish 1999; Dechow et al. 2011) reproduced arithmetically; coefficients, cutoffs and "
    "base rates are not calibrated for Taiwan and the outputs are not fraud probabilities, findings or trading signals.",
    "The Taiwan statement-line mapping of COMPUSTAT items is a DRAFT pending the method owner (Yu-Jing).",
    "Single-firm case study: no AUC, precision, sensitivity, specificity, confidence interval or significance can be "
    "derived; agreement between the two models is not validation of either.",
    "The 2016 notice 'pre' values are values as disclosed in that notice, not proven first-filed observations; the "
    "original-filing series here comes only from the archived original annual reports.",
    "Outputs never feed the production risk score, alerts, the 2330/2454 universe or any label.",
)


def _filing_view(version: dict[str, Any]) -> dict[str, Any]:
    return {"filing_version_id": version["filing_version_id"], "fiscal_year": version["fiscal_year"],
            "statement_scope": version["statement_scope"], "filing_version_type": version["filing_version_type"],
            "source_kind": version["source_kind"], "content_hash": version["content_hash"],
            "available_at": version.get("available_at"), "availability_status": version.get("availability_status"),
            "source_url": safe_official_url(version.get("source_url"))}


def check_request(context: Any, version_policy: str) -> None:
    if context.mode is AnalysisMode.CURRENT_EVIDENCE_RECONCILIATION:
        raise ModeNotSupportedError(
            "literature_scores_not_supported_in_reconciliation_mode",
            "Literature scores have no approved meaning in CURRENT_EVIDENCE_RECONCILIATION and are never used to "
            "classify source discrepancies.")
    if version_policy not in LITERATURE_VERSION_POLICIES:
        raise AnalysisRequestError(
            "version_policy_not_supported_for_literature",
            f"version_policy must be one of {', '.join(LITERATURE_VERSION_POLICIES)} for literature models.")


def select_filings(versions: list[dict[str, Any]], observed_ids: set[str], years: range, policy: str,
                   ticker: str) -> list[dict[str, Any]]:
    """Per fiscal year: the selected consolidated filing artifact, or an explicit problem (pure, order-independent)."""
    selections = []
    for year in years:
        candidates = sorted((v for v in versions if v["fiscal_year"] == year and v["statement_scope"] == "consolidated"),
                            key=lambda v: v["filing_version_id"])
        record: dict[str, Any] = {"fiscal_year": year, "accounting_framework": accounting_regime(ticker, year) or "unknown",
                                  "version_policy": policy, "filing": None, "problem": None,
                                  "candidates": [_filing_view(v) for v in candidates]}
        if policy == "original_only":
            eligible = [v for v in candidates if v["filing_version_type"] == "original"]
            if not eligible:
                record["problem"] = "no_filing_version_typed_original"
        else:
            top = max((TYPE_RANK.get(v["filing_version_type"], 0) for v in candidates), default=0)
            eligible = [v for v in candidates if TYPE_RANK.get(v["filing_version_type"], 0) == top and top > 0]
            if not eligible:
                record["problem"] = "no_consolidated_filing_version"
        if eligible and not record["problem"]:
            readable = [v for v in eligible if v["filing_version_id"] in observed_ids]
            if len(readable) == 1:
                record["filing"] = {**_filing_view(readable[0]), "accounting_framework": record["accounting_framework"]}
            elif not readable:
                record["problem"] = "source_unavailable:selected_version_statements_not_machine_readable"
            else:
                record["problem"] = "ambiguous_version:several_machine_readable_artifacts_for_selected_version"
        selections.append(record)
    return selections


def freeze_literature_inputs(snapshot: InputSnapshot, versions: list[dict[str, Any]], store: Any) -> InputSnapshot:
    """Freeze the filing selection and every line observation the models may read into the snapshot digest."""
    check_request(snapshot.context, snapshot.version_policy)
    years = range(snapshot.start_year - 2, snapshot.end_year + 1)
    observations = store.list_observations(snapshot.ticker) if store is not None else []
    # Only the extractor versions this method reads (older records stay in the append-only store, unread).
    observations = [o for o in observations if is_current_observation(o)]
    strict = snapshot.context.mode is AnalysisMode.STRICT_AS_OF
    if strict:  # only observations admitted by the strict source contract and public before the cutoff
        observations = [o for o in observations if o.get("pit_admitted")
                        and snapshot.context.admits(_instant(o.get("artifact_available_at")))]
    observed = {o["filing_version_id"] for o in observations}
    selections = select_filings(versions, observed, years, snapshot.version_policy, snapshot.ticker)
    if store is None:
        for record in selections:
            record.update(filing=None, problem="source_unavailable:literature_input_store_not_available")
    elif strict:
        for record in selections:
            if record["filing"] is None:
                record["problem"] = "insufficient_point_in_time_evidence"
    selected = {r["filing"]["filing_version_id"] for r in selections if r["filing"]}
    snapshot.literature_filings = selections
    snapshot.literature_observations = sorted((o for o in observations if o["filing_version_id"] in selected),
                                              key=lambda o: o["observation_id"])
    zero_evidence = []
    for record in selections:
        filing = record["filing"]
        if filing:
            lines = FilingLines([o for o in snapshot.literature_observations
                                 if o["filing_version_id"] == filing["filing_version_id"]])
            zero_evidence += zero_evidence_records(lines, filing["accounting_framework"])
    snapshot.literature_zero_evidence = sorted(zero_evidence, key=lambda z: (z["filing_version_id"], z["metric"],
                                                                            z["period"]))
    snapshot.literature_versions = {"method_registry": REGISTRY_VERSION, "input_mapping": MAPPING_VERSION,
                                    "period_panel": PANEL_VERSION, "line_extractor": EXTRACTOR_VERSION,
                                    "zero_evidence_policy": ZERO_POLICY_VERSION, "source_gate": SOURCE_GATE_VERSION,
                                    "fact_selection": SELECTION_POLICY_VERSION, "comparison": COMPARISON_ID}
    snapshot.literature_frozen = True
    return snapshot


def _instant(value: Any):
    from app.services.historical_audit.models import parse_timestamp

    return parse_timestamp(value)


def _panel(snapshot: InputSnapshot, year: int) -> tuple[Panel | None, dict[str, Any]]:
    selection = {r["fiscal_year"]: r for r in snapshot.literature_filings}
    record = selection.get(year)
    filings = {y: (r["filing"] if r else None) for y, r in selection.items()}
    problems = {y: r["problem"] for y, r in selection.items() if r.get("problem")}
    if record is None or record["filing"] is None:
        return None, {"fiscal_year": year, "problem": problems.get(year, "no_filing")}
    lines = {}
    for filing in (filings.get(year), filings.get(year - 1)):
        if filing:
            fid = filing["filing_version_id"]
            lines[fid] = FilingLines([o for o in snapshot.literature_observations if o["filing_version_id"] == fid],
                                     [z for z in snapshot.literature_zero_evidence if z["filing_version_id"] == fid])
    frameworks = {y: r["accounting_framework"] for y, r in selection.items()}
    return Panel(year, record["filing"]["accounting_framework"], filings, lines, problems, frameworks), record


def observation_identity(snapshot: InputSnapshot, year: int, model_id: str, framework: str | None,
                         filing: dict[str, Any] | None) -> dict[str, Any]:
    return {"ticker": snapshot.ticker, "fiscal_year": year, "statement_scope": "consolidated",
            "accounting_framework": framework, "version_policy": snapshot.version_policy,
            "filing_version_id": filing["filing_version_id"] if filing else None,
            "filing_version_type": filing["filing_version_type"] if filing else None,
            "as_of_cutoff": snapshot.context.cutoff_at.isoformat() if snapshot.context.cutoff_at else None,
            "model_version": model_id}


def run_model_year(snapshot: InputSnapshot, model_id: str, year: int) -> dict[str, Any]:
    engine = ENGINES[model_id]
    panel, record = _panel(snapshot, year)
    base = {"hindsight": snapshot.context.hindsight, "analysis_mode": snapshot.context.mode.value,
            "approval_status": APPROVAL_STATUS, "input_snapshot_digest": snapshot.input_digest}
    if panel is None:
        problem = record.get("problem") or "no_filing"
        status = ("insufficient_point_in_time_evidence" if problem == "insufficient_point_in_time_evidence"
                  else "source_unavailable" if problem.startswith("source_unavailable") or problem.startswith("no_")
                  else "ambiguous_version" if problem.startswith("ambiguous") else "not_computable")
        return {**base, "model_id": model_id, "observation": observation_identity(snapshot, year, model_id,
                                                                                  record.get("accounting_framework")
                                                                                  if isinstance(record, dict) else None,
                                                                                  None),
                "fiscal_year": year, "status": status, "score": None, "components": [], "missing_inputs": [],
                "reasons": [problem], "limitations": list(LIMITATIONS)}
    result = engine.evaluate(panel)
    filing = record["filing"]
    used = [u for u in panel.used if u.status == "computed"]
    observation_ids = sorted({obs["observation_id"] for u in used for obs in u.observations})
    filings_used = sorted({u.filing_version_id for u in used if u.filing_version_id})
    warnings = sorted({w for u in used for w in u.warnings})
    current_lines = panel.lines.get(filing["filing_version_id"])
    if current_lines is not None:
        warnings += lease_flags(current_lines, period_key("instant", year))
    if year >= 2019 and panel.framework == "TIFRS":
        warnings.append("ifrs16_depreciation_may_include_right_of_use_assets")
    if len({f for f in filings_used}) > 1:
        warnings.append("t-2_values_from_prior_year_filing_of_the_same_version_series")
    evidence_types = sorted({u.evidence_type for u in used if u.evidence_type})
    descriptor = {f["filing_version_id"]: f for f in (r["filing"] for r in snapshot.literature_filings) if f}
    return {**base, **result, "fiscal_year": year,
            "observation": observation_identity(snapshot, year, model_id, panel.framework, filing),
            "input_filing_versions": [descriptor[f] for f in filings_used if f in descriptor],
            "source_observation_ids": observation_ids, "validation_warnings": sorted(set(warnings)),
            "input_evidence_types": evidence_types,
            "zero_evidence_used": sorted({u.zero_evidence["evidence_fingerprint"] for u in used if u.zero_evidence}),
            "available_at": latest_time([descriptor[f].get("available_at") for f in filings_used if f in descriptor])
            if snapshot.context.mode is AnalysisMode.STRICT_AS_OF else None,
            "limitations": list(LIMITATIONS)}


def compute_models(snapshot: InputSnapshot, model_ids: list[str]) -> dict[str, Any]:
    check_request(snapshot.context, snapshot.version_policy)
    unknown = [m for m in model_ids if m not in ENGINES]
    if not model_ids or unknown:
        raise AnalysisRequestError("model_id_invalid", f"model_ids must be a non-empty subset of {sorted(ENGINES)}.")
    years = range(snapshot.start_year, snapshot.end_year + 1)
    results = {model_id: [run_model_year(snapshot, model_id, year) for year in years] for model_id in sorted(set(model_ids))}
    counts = {model_id: _counts(rows) for model_id, rows in results.items()}
    strict = snapshot.context.mode is AnalysisMode.STRICT_AS_OF
    return {"method_version": METHOD_VERSION, "approval_status": APPROVAL_STATUS, **snapshot.context.as_dict(),
            "ticker": snapshot.ticker, "statement_scope": "consolidated", "version_policy": snapshot.version_policy,
            "input_snapshot": snapshot.describe(),
            "filing_selection": [{k: v for k, v in r.items() if k != "candidates"} for r in snapshot.literature_filings],
            "results": results, "counts": counts,
            "status": ("insufficient_point_in_time_evidence" if strict and not snapshot.literature_observations
                       else "computed" if any(c["computed"] for c in counts.values()) else "not_computable"),
            "strict_note": ("No literature input observation is admitted before this cutoff under the verified strict "
                            "source contract; both published scores are null (this is not a low-risk result).")
            if strict else None,
            "usage_policy": ("Informational research only; never a fraud finding, risk score, label or trading signal; "
                             "never routed to the production risk model."),
            "limitations": list(LIMITATIONS)}


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {"computed": 0}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def compare(computed: dict[str, Any]) -> dict[str, Any]:
    """Side-by-side pairs for the same observation; concordance only over genuinely comparable pairs."""
    beneish = {r["fiscal_year"]: r for r in computed["results"].get(BENEISH_MODEL_ID, [])}
    dechow = {r["fiscal_year"]: r for r in computed["results"].get(DECHOW_MODEL_ID, [])}
    pairs = []
    for year in sorted(set(beneish) | set(dechow)):
        b, d = beneish.get(year), dechow.get(year)
        same_observation = bool(b and d and {k: v for k, v in b["observation"].items() if k != "model_version"}
                                == {k: v for k, v in d["observation"].items() if k != "model_version"})
        comparable = bool(b and d and b["status"] == "computed" and d["status"] == "computed" and same_observation)
        pair = {"fiscal_year": year, "comparable": comparable, "same_observation_identity": same_observation,
                "observation": {k: v for k, v in (b or d)["observation"].items() if k != "model_version"},
                "beneish": _side(b), "dechow": _side(d),
                "reasons": [] if comparable else _pair_reasons(b, d, same_observation)}
        if comparable:
            b_above = Decimal(b["score"]) > Decimal(b["scaling_provenance"]["benchmark"]["score_cutoff"])
            d_above = Decimal(d["score"]) > Decimal(1)
            pair["original_benchmark_side"] = {
                "beneish_above_original_us_cutoff_-1.78": b_above, "dechow_above_unconditional_expectation_1.00": d_above,
                "same_side": b_above == d_above,
                "note": "Original US-sample reference points only; descriptive, never a label or Taiwan threshold."}
        pairs.append(pair)
    comparable_pairs = [p for p in pairs if p["comparable"]]
    return {"comparison_id": COMPARISON_ID, "approval_status": APPROVAL_STATUS,
            "analysis_mode": computed["analysis_mode"], "hindsight": computed["hindsight"],
            "cutoff_at": computed["cutoff_at"], "version_policy": computed["version_policy"],
            "unit_of_observation": ["ticker", "fiscal_year", "statement_scope", "accounting_framework",
                                    "filing_version_side", "as_of_cutoff", "model_version"],
            "coverage": {"years_requested": len(pairs), "comparable_pairs": len(comparable_pairs),
                         "beneish_computed": computed["counts"].get(BENEISH_MODEL_ID, {}).get("computed", 0),
                         "dechow_computed": computed["counts"].get(DECHOW_MODEL_ID, {}).get("computed", 0)},
            "concordance": {"denominator": len(comparable_pairs),
                            "same_side_of_original_benchmarks": sum(1 for p in comparable_pairs
                                                                    if p["original_benchmark_side"]["same_side"]),
                            "note": ("Descriptive agreement on original US reference points over comparable pairs "
                                     "only; not validation, not predictive performance.")},
            "pairs": pairs, "performance_metrics": None,
            "performance_metrics_reason": ("No labelled, time-aligned multi-company cohort is supplied; AUC, precision, "
                                           "sensitivity, specificity and significance are not computed."),
            "limitations": computed["limitations"]}


def _side(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {"status": row["status"], "score": row.get("score"),
            "probability": row.get("probability_original_model") or row.get("probit_probability_original_sample"),
            "component_coverage": row.get("component_coverage"),
            "missing": [{k: m.get(k) for k in ("component", "metric", "relative_period", "fiscal_year", "status")}
                        for m in row.get("missing_inputs", [])],
            "reasons": row.get("reasons", [])}


def _pair_reasons(b, d, same_observation) -> list[str]:
    reasons = []
    for name, row in (("beneish", b), ("dechow", d)):
        if row is None:
            reasons.append(f"{name}:not_requested")
        elif row["status"] != "computed":
            reasons.append(f"{name}:{row['status']}")
    if b and d and not same_observation:
        reasons.append("different_observation_identity")
    return reasons


# ------------------------------------------------------------------------------------------- coverage matrix
def coverage_matrix(snapshot: InputSnapshot, diagnostics: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per model / variable / fiscal year / relative period: input readiness with provenance (no scores)."""
    rows = []
    years = range(snapshot.start_year, snapshot.end_year + 1)
    for model_id, engine in ENGINES.items():
        requirements = {name: requires for name, (requires, _) in engine.COMPONENTS.items()}
        if model_id == DECHOW_MODEL_ID:
            requirements["issue"] = [("long_term_debt_issued", "t"), ("stock_issued", "t")]
        for year in years:
            panel, record = _panel(snapshot, year)
            for variable, requires in requirements.items():
                for metric, relative in requires:
                    base = {"model_id": model_id, "variable": variable, "formula_component": metric,
                            "canonical_or_new_metric": "new_literature_metric", "ticker": snapshot.ticker,
                            "fiscal_year": year, "relative_period": relative, "statement_scope": "consolidated",
                            "compustat_item": MAPPING_INDEX[metric].compustat, "version_policy": snapshot.version_policy}
                    if panel is None:
                        rows.append({**base, "accounting_framework": record.get("accounting_framework")
                                     if isinstance(record, dict) else None, "readiness": "missing",
                                     "input_status": "no_selected_filing", "evidence_type": None,
                                     "missing_reason": record.get("problem") if isinstance(record, dict) else "no_filing",
                                     "filing_version_id": None, "side": None, "sources": []})
                        continue
                    item = panel.value(metric, relative)
                    rows.append({**base, "accounting_framework": panel.framework,
                                 "readiness": "complete" if item.status == "computed" else "missing",
                                 "input_status": item.status, "evidence_type": item.evidence_type,
                                 "zero_evidence": item.zero_evidence, "cross_filing_overlap": item.cross_filing_overlap,
                                 "alias_candidates": item.candidates,
                                 "missing_reason": None if item.status == "computed" else
                                 ";".join([item.status, *item.reasons]),
                                 "filing_version_id": item.filing_version_id,
                                 "side": next((r["filing"]["filing_version_type"] for r in snapshot.literature_filings
                                               if r["filing"] and r["filing"]["filing_version_id"] == item.filing_version_id),
                                              None),
                                 "period": item.period, "value_twd": item.provenance()["value_twd"],
                                 "lines_not_presented": item.lines_not_presented, "warnings": item.warnings,
                                 "sources": [{k: o.get(k) for k in ("observation_id", "source_concept", "raw_sha256",
                                                                    "locator", "published_unit", "extraction_method",
                                                                    "artifact_available_at", "pit_admitted")}
                                             for o in item.observations]})
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        key = f"{row['model_id']}|{row['fiscal_year']}"
        bucket = summary.setdefault(key, {"complete": 0, "missing": 0})
        bucket[row["readiness"]] += 1
    status_counts: dict[str, int] = {}
    for row in rows:
        key = f"{row['input_status']}|{row['evidence_type']}"
        status_counts[key] = status_counts.get(key, 0) + 1
    return {"matrix_version": "literature_input_coverage_v2", "input_status_counts": dict(sorted(status_counts.items())),
            "zero_evidence_records": snapshot.literature_zero_evidence, "approval_status": APPROVAL_STATUS,
            **snapshot.context.as_dict(), "ticker": snapshot.ticker, "version_policy": snapshot.version_policy,
            "filing_selection": snapshot.literature_filings, "rows": rows, "summary": summary,
            "artifact_diagnostics": diagnostics or [], "input_snapshot": snapshot.describe()}
