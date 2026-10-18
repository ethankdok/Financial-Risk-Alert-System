# Phase 5 — large Taiwan historical finance cohort: research tools

**Scope:** user-approved model-first research; not a scheduled ingestion / continuous retraining system. See [research requirements](../../../docs/research/FINANCIAL_ML_PHASE5_REQUIREMENTS_2026-10-18.md).

## 1. Reuse official archive to calculate actual literature variables NOW

Run from `fintrust_backend`, with `app.services.financial_research` installed in this worktree:

```powershell
$root = Join-Path (Split-Path (git rev-parse --show-toplevel).Trim() -Parent) "Financial-Risk-Alert-System"
$fm = Join-Path $root "fintrust_backend\data\financial_ml"
python -m research.financial_ml.literature_dataset `
 --acquisition-results (Join-Path $fm "official_batch\acquisition_results.json") `
 --output (Join-Path $fm "literature_phase5a")
```

Inspect `literature_coverage.json`: how many **actual** Beneish/Dechow variables, both complete models, and all 15 components are available? Do **not** infer `fully_computed_15_rows == input manifest rows`.

## 2. Create current TWSE/TPEx nonfinancial reference candidate universe

The explicit `--fetch` retrieves **one** FinMind `TaiwanStockInfo` JSON response and stores an archive; source is provider data, not official issuer listing verification.

```powershell
python -m research.financial_ml.finmind_universe `
 --fetch --output "data/financial_ml/finmind_market"
```

Or use `--source-json <previously_saved_TaiwanStockInfo_snapshot.json>` to avoid a request.

Output `data/financial_ml/finmind_market/taiwan_nonfinancial_current_candidates.csv`. This is an up-to-date **candidate-only** market universe; current listing excludes some delisted companies and cannot establish whether each company traded in historical fiscal years. Keep `1785` excluded.

## 3. Fetch raw 3-statement records over many years (NO annual feature assumptions)

Preview, **no network**:

```powershell
python -m research.financial_ml.finmind_bulk_stage `
 --candidate-csv "data/financial_ml/finmind_market/taiwan_nonfinancial_current_candidates.csv" `
 --output "data/financial_ml/finmind_raw" `
 --start-date 2013-01-01 --end-date 2025-12-31 --offset 0 --max-tickers 8
```

Add `--execute` only if API quota/license and preview are acceptable; max 40 tickers per invocation (three statement queries each). Increment `--offset` for later chunks; verified local JSON is reused. Set optional `FINMIND_API_TOKEN` **only in the environment**, never paste it into chat or commit it.

**Not done yet:** FinMind row-level data is quarterly (often accumulated income/cash-flow or single-quarter depending on dataset/type); `*_per` percentage rows and `EPS` units are not annual TWD amounts. Must validate each type's period, annual transformation and Taiwan XBRL mapping against official MOPS first. **FinMind JSON must NOT be fed directly to the MOPS 15-literature-feature converter.** Source and mapping coverage report precede full-model training.

## Research checkpoints

- Current official research archive: user reported 64 validated company-years / 22 companies, FY2013–15. This is a historical SMOKE dataset, not the target large-data train frame.
- The new converter reuses authentic Beneish8 and Dechow7 engines and per-component reasons; it has not yet been run against user's private raw XBRL bytes from this assistant environment.
- Once full fifteen-variable coverage across broader years is known, freeze up-to-10 training configurations with company+time separation and preserve artifacts; 1785 only after freeze.

No cloud writes, production/frontend changes, fraud/normal labels or model training in these Phase 5A/5B staging tools.
