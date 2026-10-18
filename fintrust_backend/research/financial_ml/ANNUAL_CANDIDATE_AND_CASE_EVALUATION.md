# Phase 5B+5D research bridge: annual staging + known-problem controls

The research objective remains **large Taiwan listed/nonfinancial annual panel → the
original Beneish (1999) eight and Dechow (2011) Model-1 seven variables → multiple
ML architectures (GRU/LSTM, TCN, Transformer, IF/LOF/AE, conditional
XGBoost/CatBoost/RF) → independent known-outcome case assessment**. Do not
prioritize production orchestration.

## Current evidence and status (2026-10-18)
- FinMind `TaiwanStockInfo`: 2,086 current nonfinancial issuer **candidates**,
  not downloaded annual records, normals, or verified historical listings.
- 12-company cross-industry pilot: 36/36 HTTP successful, **33 actual
  nonempty statement responses** for 11 issuers, 3 empty responses for 2452.
- 2330 FY2013–15 against archived MOPS annual: 15/15 candidate income
  amount fields favor Q1–Q4 addition; 3/3 operating cash-flow entries match
  reported Q4 (cumulative YTD); 17/18 balance-sheet candidates match
  Dec 31 position. FY2014 total liabilities mismatched by 737,344,000 TWD
  (~0.164%). These facts establish **candidate period policies**, not a
  globally approved source mapping.
- Literature engine already computes 15 variables from audited MOPS XBRL,
  but only 11/64 original pilot company-years had all 15 available.
- No large multi-thousand-company-year FinMind annual table or time-series
  neural model has yet been trained. Do not describe this as complete.

## New `finmind_annual_candidate_stage.py`
- Offline only. Reads **cached** `finmind_cross_industry_raw/<ticker>/...`
  JSON (full three statements), validates ticker, provider origin,
  finite numeric values, unique amount by (type, period). No API requests.
- Produces `finmind_annual_candidate_lines.csv` for the **12 narrowly
  investigated candidate fields only**. Applies the source-family proposal
  `income: sum four quarters`, `cashflow: Q4 value`, `balance: Dec 31
  instant` (not annual sum); records method version, source SHA-256,
  missing-quarter status and `empty_provider_response` separately.
- Every row has `training_admitted=false`, `publication_asof_verified=false`,
  `label_status=UNREVIEWED`; unknown/absent values remain blank, not zero.
  Even exact matching names or source totals do not approve comparability.
- Can process any list of staged company JSONs, but today's available pilot
  is 12 issuers. This **starts scalable cleaning**; actual 2,086-issuer download,
  mapping approval, paper-variable feature engineering and training are
  separate next steps.

## Known problematic issuers for evaluation
- **Use known-positive issuer-year examples to test anomaly detection**:
  independent official restatement/misstatement/enforcement evidence,
  affected financial statement period, event type, first-public disclosure
  date and raw cited evidence. Positive means a specific proven event type,
  not all cases are criminal fraud.
- Existing `app/services/financial_research/case_labels.py` provides
  retrospective outcome labels for 1785 with official 2016 disclosure
  provenance. `case_knowledge.py` and
  `docs/research/LITERATURE_COMPARATIVE_CASE_STUDY_1785.md` hold contextual
  evidence and critical vintage caveats.
- **1785 stays final untouched holdout** until trained parameters, missing
  policy, thresholds, weights and architecture choice are frozen. Choose
  *other* independently documented issue cases for development-time positive
  controls. Do not infer a control label from missing data (2452) or a
  source disagreement (2330 FY2014).
- Important: 1785's currently machine-readable FY2013–15 filings are
  **post-restatement**. A retrospective anomaly ranking from them is
  not a pre-2016 early-warning prediction. Early-warning evaluation needs
  true original filings available at the model's prediction cutoff.
- Initially report ranking position and recall@K of **independently documented
  positives**. Precision, F1, PR-AUC and specificity require reasonably
  complete verified negatives/outcome collection, not automatic
  negative = no known disclosure.

## Local validation from separate ML Git Worktree `fintrust_backend`
```powershell
$branch="feature/financial-ml-annual-candidate-and-case-eval-20261018"
if (@(git status --porcelain).Count -gt 0) { throw "Uncommitted ML worktree; stop" }
git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
if ($LASTEXITCODE -ne 0) { throw "Fetch failed" }
git switch --detach "origin/$branch"
if ($LASTEXITCODE -ne 0) { throw "Switch failed" }
python -m unittest discover -s tests -p "test_financial_ml_finmind_annual_candidate_stage.py" -v
if ($LASTEXITCODE -ne 0) { throw "Unit tests failed" }

$root=(git rev-parse --show-toplevel).Trim()
$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
python -m research.financial_ml.finmind_annual_candidate_stage `
  --candidate-csv (Join-Path $data "finmind_cross_industry_pilot\finmind_pilot_candidates.csv") `
  --raw-root (Join-Path $data "finmind_cross_industry_raw") `
  --output (Join-Path $data "finmind_annual_candidates") `
  --start-year 2013 --end-year 2025
if ($LASTEXITCODE -ne 0) { throw "Annual candidate staging failed" }
```

Review `finmind_annual_candidates/finmind_annual_candidate_report.json` and
`finmind_annual_candidates/finmind_annual_candidate_lines.csv`.

**Next development**: audited vendor-to-MOPS account mapping at company-year
grain, seasonal/annual alignment on more companies, then scale cached
downloads with quota-aware chunks; build literature-15 and multi-year
windows only after that. Separately build an external event-labeled case
registry for *other* cases; keep 1785 completely held out.
