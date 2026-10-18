# Phase 5B — FinMind annual semantics, MOPS crosscheck and real-source findings
**Date:** 2026-10-18. **Scope:** standalone offline research; no financial predictions, labels, production writes, cloud deployment, re-download or scheduling.

## 12-company results received
- 36/36 HTTP requests completed; 33 statement JSONs non-empty and **3 empty success responses, all for ticker 2452**. A `downloaded` result does not imply there is usable financial data. Total **55,445 source line records** across 11 companies with nonempty financial statements: balance 36,447, cash flow 11,723, profit/loss 7,275.
- 184 distinct `(dataset, type)` combinations: 124 balance-sheet, 36 cashflow, 24 income statement. `finmind_field_catalog.csv` reflects 2013–2025 source coverage across different companies, **not** verified whole-year reporting semantics for each row.
- Of 12 × 24 = 288 issuer × literature base-account alias checks, 160 have at least one exact MOPS-alias `type`; 128 do not. This is **lexical overlap**, not 160 valid annual inputs.
- Both original 64 MOPS issuer-year samples and the 15-feature research output remain separate and intact.
- Important source-proven code divergences to investigate, **not silently approve**:
  - MOPS `CostOfSales/OperatingCosts` vs FinMind `CostOfGoodsSold` (11/11 nonempty issuers).
  - MOPS `Assets` vs FinMind `TotalAssets` (11/11).
  - MOPS `DepreciationExpense/AdjustmentsForDepreciationExpense` vs FinMind `Depreciation` (11/11).
  - MOPS `ProfitLossFromContinuingOperations` vs FinMind `IncomeFromContinuingOperations` (11/11).
  - MOPS `OperatingRevenue/Revenue` vs FinMind `Revenue` (11/11).
  - MOPS `AccountsReceivableDueFromRelatedPartiesNet` vs FinMind `AccountsReceivableDuefromRelatedPartiesNet`; differences are not approved just by spelling.
  - MOPS `NotesReceivableNet` vs FinMind `BillsReceivableNet`; same caveat.
  - Need **separate** selling/administrative expenses, `stock_issued` evidence, and account details used for RSST. FinMind `OperatingExpenses` is **not** a justified replacement for either selling or administrative by itself.
  - Dechow `issue` UNKNOWN must never become 0 without evidence.
  - FinMind `*_per` are ratios/percentages, never TWD line amounts.
- FinMind's documented `date` field is the **financial-period end**, not a verified public release date (see https://github.com/FinMind/FinMind/blob/master/FinMind/data/data_loader.py and https://finmind.github.io/tutor/TaiwanMarket/Fundamental/). Annual Q4 versus year-to-date and quarterly-flow aggregation require independent inspection.

## What was developed this round
`research/financial_ml/finmind_annual_crosscheck.py`:
- Reads only already-staged FinMind JSON and already-validated MOPS annual `acquisition_results.json`. No network, DB, labels, case 1785.
- For 12 conservative candidate field pairings, writes quarterly Q4 original, optional Q1–Q4 sum for flows, and corresponding MOPS official metric on the **same issuer-year**. Balance sheet compares 12/31 instant only, never summed.
- Reports exact values, SHA provenance and normalized relative errors for **both** possible income/cashflow period interpretations. Explicitly marks Q4-only, four-quarter-sum, both, no-match or unavailable. **None are approved automatically**: numerical match is not validation of every future period or original filing/publication timestamp.
- Starts with FY2013–2015 **2330 only**, because those fiscal years are already archived through the original MOPS branch.
- Also fixes `finmind_cross_industry_pilot.audit` to report empty-success provider archives as `raw_empty_response`.
- Adds 7 hermetic tests for reconciliation and 1 for empty-success classification.

## Safe local validation: separate ML Worktree `fintrust_backend`
```powershell
$branch = "feature/financial-ml-finmind-annual-crosscheck-20261018"
if (@(git status --porcelain).Count -gt 0) { throw "Unsaved ML worktree modifications" }
git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
if ($LASTEXITCODE -ne 0) { throw "fetch failed" }
git switch --detach "origin/$branch"
if ($LASTEXITCODE -ne 0) { throw "switch failed" }

python -m unittest discover -s tests -p "test_financial_ml_finmind_annual_crosscheck.py" -v
if ($LASTEXITCODE -ne 0) { throw "crosscheck tests failed" }
python -m unittest discover -s tests -p "test_financial_ml_finmind_cross_industry_pilot.py" -v
if ($LASTEXITCODE -ne 0) { throw "cross-industry tests failed" }

$worktree = (git rev-parse --show-toplevel).Trim()
$main = Join-Path (Split-Path $worktree -Parent) "Financial-Risk-Alert-System"
$data = Join-Path $main "fintrust_backend\data\financial_ml"
$raw = Join-Path $data "finmind_cross_industry_raw"
$mops = Join-Path $data "official_batch\acquisition_results.json"
$out = Join-Path $data "finmind_annual_crosscheck"

python -m research.financial_ml.finmind_annual_crosscheck `
    --provider-root $raw `
    --mops-manifest $mops `
    --output $out `
    --ticker 2330 --start-year 2013 --end-year 2015
if ($LASTEXITCODE -ne 0) { throw "annual numeric reconciliation failed" }
```

Please review and provide:
1. `finmind_annual_crosscheck/finmind_mops_crosscheck_report.json`
2. `finmind_annual_crosscheck/finmind_mops_annual_crosscheck.csv`

No full raw archives or tokens are needed for this first comparison. Optionally rerun `finmind_cross_industry_pilot audit` on cached files to see `raw_empty_response: 3` and `raw_schema_review_only: 33`.

## Decision gate after matching
1. Inspect which MOPS official annual facts match `Q4_ONLY` or `FOUR_QUARTER_SUM` on FY2013–2015 for different income and cashflow accounts; do not extrapolate blindly.
2. Confirm fiscal period semantics, original/reporting scope, source revision and numeric units; freeze provider-specific mapping with evidence.
3. Align calendar/fiscal-year panel, derive literature 8+7 and 3–5-year sequences, assess completeness, then stage large non-financial universe acquisition.
4. On sufficiently large, verified series compare GRU/LSTM-AE, TCN, Transformer against tabular baselines; preserve independent time/company splits. No fraud accuracy without outcome labels.
