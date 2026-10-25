"""One entrypoint for already-owned FinTrust X and TEJ calendar proxy Y2.

It first reuses a locally created TEJ Y2 cohort; otherwise regenerates it
from an existing yearly TEJ table; otherwise uses the user's ORIGINAL
20261025034613DataExport.xlsx through the ALREADY IMPLEMENTED parser.
All licensed data and outputs remain under the user's ignored data root.
No download, TT2, FinLab tokens or production writes.

Example (inside Financial-Risk-Alert-System-ML-Binary/fintrust_backend):
  py -3.12 -m research.financial_ml.run_existing_binary --data-root "C:\\...\\fintrust_backend\\data\\financial_ml"

If TEJ input is elsewhere, use --tej-xlsx "C:\\...\\20261025034613DataExport.xlsx".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .finlab_finmind_binary import build
from .round2_label_cohorts import build as build_proxy
from .round2_tej_transparency import build as build_yearly

X_FILENAME = "finmind_annual_candidate_lines.csv"
MOPS_FILENAME = "all_market_public_annual_financial_features_2013_2021.csv"
TEJ_XLSX_NAME = "20261025034613DataExport.xlsx"
PROXY_NAME = "tej_calendar_proxy_cohort_private.csv"
YEAR_NAME = "tej_calendar_year_evidence_private.csv"


class MissingInput(RuntimeError):
    pass


def unique_existing(paths):
    found = {}
    for x in paths:
        p = Path(x)
        if p.is_file():
            found[str(p.resolve()).lower()] = p
    return sorted(found.values(), key=lambda p: str(p).lower())


def pick_provenance(paths, preferred_fragment):
    """Reject genuinely divergent automatic matches; never guess which Y is correct."""
    hits = unique_existing(paths)
    if not hits:
        return None
    if len(hits) == 1:
        return hits[0]
    preferred = [p for p in hits if preferred_fragment in str(p).lower()]
    # Matching identical SHA across copies is safe; different bytes are not.
    sources = preferred if preferred else hits
    digests = {hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    if len(digests) > 1:
        raise MissingInput("MULTIPLE_DIFFERENT_TEJ_EXPORTS: please specify --tej-xlsx "
                           "or resolve the correct existing Y2 cohort manually.")
    return sources[0]


def run(data_root, out=None, *, tej_xlsx=None, allow_no_x=False):
    root = Path(data_root).expanduser().resolve()
    if not root.is_dir():
        raise MissingInput("DATA_ROOT_NOT_FOUND: " + str(root))
    folder = Path(out).expanduser().resolve() if out else root / "binary_existing_real_run_20261026"
    if not folder.is_relative_to(root):
        raise MissingInput("OUTPUT_MUST_STAY_INSIDE_PRIVATE_DATA_ROOT")
    folder.mkdir(parents=True, exist_ok=True)
    # Prefer original immutable/reviewed Y2 if present. Avoid remake and double handling.
    proxy = pick_provenance(root.rglob(PROXY_NAME), "round2_label_cohorts")
    y_step = "reused_y2"
    raw_original = None
    if proxy is None:
        yearly = pick_provenance(root.rglob(YEAR_NAME), "round2_tej_transparency")
        if yearly is None:
            if tej_xlsx is not None:
                raw_original = Path(tej_xlsx).expanduser().resolve()
                if not raw_original.is_file():
                    raise MissingInput("EXPLICIT_TEJ_XLSX_NOT_FOUND: " + str(raw_original))
            else:
                raw_original = pick_provenance(root.rglob(TEJ_XLSX_NAME),
                                               TEJ_XLSX_NAME.lower())
            if raw_original is None:
                raise MissingInput(
                    "TEJ_Y2_SOURCE_NOT_ON_THIS_COMPUTER_PATH. "
                    "No TEJ cohort, yearly CSV or original 20261025034613DataExport.xlsx "
                    "was found under " + str(root) + ". "
                    "Locate the ORIGINAL XLSX in Downloads/older folder and rerun "
                    "with --tej-xlsx <full_path>. Do not download TT2.")
            yearly = folder / "tej_yearly_from_existing_xlsx" / YEAR_NAME
            if not yearly.exists():
                build_yearly(raw_original, yearly.parent)
            y_step = "recovered_from_original_xlsx"
        else:
            y_step = "recovered_from_existing_yearly_csv"
        proxy = folder / "tej_y2_from_existing_yearly" / PROXY_NAME
        if not proxy.exists():
            build_proxy(yearly, proxy.parent)
    if not proxy.is_file():
        raise MissingInput("Y2_MATERIALIZATION_FAILED")

    annual = unique_existing(root.rglob(X_FILENAME))
    mops = pick_provenance(root.rglob(MOPS_FILENAME), "public_mops")
    if not annual and mops is None and not allow_no_x:
        raise MissingInput("EXISTING_FINANCIAL_X_NOT_FOUND: expected FinMind annual CSV "
                           "or public MOPS annual CSV.")
    result = build(annual if annual else None, proxy, "tej_proxy",
                   folder / "classification",
                   mops_annual=mops, train=True)
    # Only print aggregations. Private issuer rows stay inside data root.
    report = {
        "status": result["training"]["status"],
        "y2_recovery": y_step,
        "y2_source_sha256": result["source_sha256"]["labels"],
        "finmind_files": len(annual),
        "mops_file_found": bool(mops),
        "eligible_y2": result["valid_label_rows"],
        "matched_company_years": result["matched_feature_rows"],
        "matched_class_counts": result["matched_class_counts"],
        "by_split": result["by_split"],
        "unmatched_reasons": result["unmatched_reasons"],
        "models": [
            {"model": x["model"], "status": x["status"],
             "validation": x.get("validation"), "test": x.get("test")}
            for x in result["training"].get("models", [])
        ],
        "training_blocker": result["training"].get("reason")
            or result["training"].get("selection_blocker"),
        "private_report_path": str(folder / "classification" /
                                   "finlab_finmind_binary_report.json"),
        "interpretation": ("EXPLORATORY_TEJ_CALENDAR_YEAR_PROXY_ONLY_NOT_CONFIRMED_"
                           "MATERIAL_MISSTATEMENT_OR_PROSPECTIVE_PIT")
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-root", required=True,
                   help="Existing original fintrust_backend/data/financial_ml")
    p.add_argument("--tej-xlsx", help="Optional explicit path to user's already exported Excel")
    p.add_argument("--out", help="Optional new private output folder below data root")
    a = p.parse_args(argv)
    try:
        run(a.data_root, a.out, tej_xlsx=a.tej_xlsx)
    except (MissingInput, FileNotFoundError, FileExistsError, ValueError) as exc:
        print("FINTRUST_BINARY_STOPPED: " + str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
