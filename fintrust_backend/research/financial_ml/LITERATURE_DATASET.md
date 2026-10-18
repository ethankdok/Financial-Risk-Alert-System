# Phase 5A — real Beneish 8 + Dechow 7 literature features from official raw XBRL

This module **does not calculate** the old `pilot.py` 15 generic accounting ratios.
It calls the existing `beneish_1999.evaluate` and `dechow_2011.evaluate`
engines with their exact-source method registry, XBRL line extractor, Taiwan
COMPUSTAT mapping and t/t-1/t-2 panels.

From the separate ML worktree's `fintrust_backend` directory:

```powershell
$mlRoot = (git rev-parse --show-toplevel).Trim()
$mainRoot = Join-Path (Split-Path $mlRoot -Parent) "Financial-Risk-Alert-System"
$data = Join-Path $mainRoot "fintrust_backend\data\financial_ml"
python -m research.financial_ml.literature_dataset `
  --acquisition-results (Join-Path $data "official_batch\acquisition_results.json") `
  --output (Join-Path $data "literature_phase5a")
```

Outputs:

- `literature_15_features.csv`: 8 `b_*` + 7 `d_*` columns; blank fields represent a variable that is **not computable**, not zero.
- `literature_missing_reasons.jsonl`: reason codes for unavailable variables and corrupt archive items.
- `literature_coverage.json`: number of computed variables and 8/7/15 complete model observations.

**Constraints:** only validated, consolidated, TIFRS, SHA-256-verified official archive inputs; case 1785 excluded. No network requests, API keys, labels, model fitting or database writes. No assertion of original-filing vintage or point-in-time prediction. Source Taiwan-mapping semantics remain pending research-method owner approval. FinMind's quarterly tables must not be fed into this calculator as annual MOPS filings without mapping and period reconciliation.

Run after fetching this branch. Do not reset/clean the original worktree.

The research scope is locked in `docs/research/FINANCIAL_ML_PHASE5_REQUIREMENTS_2026-10-18.md`. The next stage is all-market nonfinancial source collection, annual statement reconciliation and <10 prespecified ML training experiments.
