# Phase 5B — Annual candidate panel and temporal window readiness (2026-10-18)

## User-approved research objective
Preserve the MOPS XBRL archives, Beneish 1999 (8) and Dechow 2011 Model 1 (7) engines,
2,086-current-company FinMind candidate universe, known-event case registry and
branch-isolated ML experiments. Scale the Taiwan company-year panel, audit
FinMind annual semantics and literature input mappings, then compare
**time-series neural architecture families (GRU/LSTM, TCN, Transformer)**
against Isolation Forest/LOF, tabular AEs and later verified-label
RF/XGBoost/CatBoost. Multiround means cross-architecture comparative research
plus tuning and epochs, not just refitting one Isolation Forest 10 times.

## Evidence received — real 12-company provisional annual file

The 2013–2025 `finmind_annual_candidate_lines.csv` has exactly **1,872**
rows = 12 companies × 13 fiscal years × 12 selected *candidate* metrics.
There are **no duplicate (ticker, fiscal year, metric) keys**.

- **1,323** candidate populated metric cells (70.67%).
- **156** empty-provider-response cells, all issuer **2452**.
- **173** missing Dec 31 values and **220** missing complete income-quarter sets.
- **99/156** company-years have all 12 provisional metrics populated.
- **Six** firms have all 13 fiscal years complete: `1558`, `2330`,
  `2506`, `3691`, `4938`, `8421`.
- Other full 12-metric company-years: `6485: 11`, `6588: 6`,
  `4442: 3`, `6931: 1`, `7828/2452: 0`.
- Sliding sequences with **all 12 candidates per year**, requiring complete
  fiscal-year succession:
  - **3 years: 80 candidate-complete windows from 9 distinct firms**
  - **5 years: 63 candidate-complete windows from 8 distinct firms**
- These windows overlap within the same issuer; **80 is not 80 independent
  training companies**. The current data cannot substantiate neural model
  out-of-sample detection accuracy.

Earlier FY2013–2015 numeric crosscheck on ticker 2330 only supported
specific *candidate* family policies: profit/loss Q1–Q4 sums 15/15, CFO
Q4 reported cumulative values 3/3, balance Q4 instant values 17/18.
FY2014 liabilities mismatch (~0.164%) remains unresolved.
No extrapolated Taiwan-wide accounting method is approved on this basis.

## New module and contract
`research/financial_ml/annual_panel_readiness.py` operates **offline** on
`finmind_annual_candidate_lines.csv` from the prior stage; no raw API calls.
It rejects ambiguous/duplicate company-year-metric keys, unsupported statuses,
nonfinite numbers, missing-value substitutions, missing SHA provenance, cross-row
source-hash conflicts, unauthorized training admission, outcome labels and
ticker 1785. It creates:

- `company_year_candidate_panel.csv`: one **provisional** row per issuer
  × FY, 12 candidate amounts and availability count; unknowns kept blank.
- `candidate_sequence_window_index.csv`: every potential consecutive
  3-year / 5-year window, observed-cell count and complete-window flag.
- `candidate_panel_readiness.json`: missingness, per-company coverage,
  complete-window counts, source dataset SHA and gating limitations.

**Every output is `training_admitted=false`; it does not create the 15
Beneish/Dechow variables, labels or a trained ML model.**

## User's local Windows ML worktree recipe
```powershell
$branch = "feature/financial-ml-timeseries-panel-readiness-20261018"
if (@(git status --porcelain).Count -gt 0) { throw "Unsaved ML worktree changes" }
git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
if ($LASTEXITCODE -ne 0) { throw "Git fetch failed" }
git switch --detach "origin/$branch"
if ($LASTEXITCODE -ne 0) { throw "Git switch failed" }
python -m unittest discover -s tests -p "test_financial_ml_annual_panel_readiness.py" -v
if ($LASTEXITCODE -ne 0) { throw "Panel regression failed" }

$mlRoot = (git rev-parse --show-toplevel).Trim()
$mainRoot = Join-Path (Split-Path $mlRoot -Parent) "Financial-Risk-Alert-System"
$data = Join-Path $mainRoot "fintrust_backend\data\financial_ml"
python -m research.financial_ml.annual_panel_readiness `
 --dataset (Join-Path $data "finmind_annual_candidates\finmind_annual_candidate_lines.csv") `
 --output (Join-Path $data "finmind_sequence_readiness")
if ($LASTEXITCODE -ne 0) { throw "Panel audit failed" }
```

## Next high-impact work
1. **Expand candidate acquisition** beyond 12 issuers, after bounded
   cross-industry annual-account comparison and provider quota audit.
   Keep raw source record hashes and distinguish empty responses. Avoid
   claiming all 2,086 issuers have historical data.
2. **Complete source-specific 24-base-input mapping**, including preferred
   capital, long/short-term debt, exact SG&A and issuance evidence, while
   preserving missing value semantics and period t,t−1,t−2.
3. Transform sufficiently verified annual source amounts through the *existing*
   `literature_inputs.py` and `beneish_1999.py` / `dechow_2011.py`
   mapping contract, then construct 15-paper-feature chronological sequences.
4. Compare GRU/LSTM sequence reconstructions, TCN, Transformer encoders and
   tabular baselines under the same temporal + company-disjoint split.
5. Use independent problematic **other company-years** as development-time
   positive controls; hold out **1785** until model/threshold architecture
   freeze, and do not treat post-restatement 1785 values as pre-2016 inputs.

Out of scope: production pipeline, scheduler, website, ongoing learning.
