# Phase 5B — Scaled multi-industry source acquisition (2026-10-18)

## Why this was built
The current source-based panel from 12 pilot issuers produced 1,872
issuer–year–candidate-metric rows, including 1,323 provisional values,
99 complete 12-candidate issuer-years, **80 complete 3-year** and **63
complete 5-year** sequences. Five local user regression tests passed.
This is too few distinct issuers to compare GRU/LSTM, TCN, Transformer and
other model families reliably, and these 12 source amounts are **not** the
Beneish 8 + Dechow 7 paper features.

**Priority now: increase the real multi-year financial panel**, not more
small-sample refits. Continue preserving MOPS official archives, literature
engines, case-outcome holdout rules, and data-quality evidence.

## Implementation
`research/financial_ml/finmind_scaled_cohort.py`:

- `plan`: deterministic, industry-spread cohort, **120 companies and 24
  semiconductor issuers by default**, configurable up to 500. Anchors 2330
  when present, balances semiconductor boards, then rotates through remaining
  current nonfinancial industries. Does not call FinMind.
- `batch`: safely reuses `finmind_bulk_stage.run()`, its existing period
  contracts, original raw provider JSON, quota handling and 15-second pacing.
  Every run processes at most **one 12-issuer batch by default**, 36 financial
  requests, and saves a separate per-batch report. Batches with complete
  cached source archives are skipped on later runs.
- API calls are **opt-in** via `--execute`; the default is a network-free
  preview. `--max-batches` capped at 3 and `--batch-size` capped at 40.
  When a quota/access failure or bad existing source is encountered, stop
  without overwriting existing provider evidence.
- No database changes, no provider tokens written to logs, no normal labels
  inferred, ticker 1785 excluded from both phases, no frozen test-case scores.
- Empty-response provider archives are reused but **counted explicitly**;
  HTTP success does not establish financial record availability.
- Source cohorts are based on **current listed stocks**, not all historical
  companies, and not a representative training set or unbiased validation
  sample. The stratified 120 are deliberately industry-balanced research
  acquisition candidates.
- Individual issuer grouping is deterministic and sorted for stable
  `--resume` batch indexing.

## Windows PowerShell: run once to plan and fetch the first batch

Work in a clean `Financial-Risk-Alert-System-ML\fintrust_backend`
worktree with `(ml-env)` activated.

```powershell
$branch = "feature/financial-ml-scaled-acquisition-20261018"
if (@(git status --porcelain).Count -gt 0) { throw "Unsaved ML worktree changes" }
git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
if ($LASTEXITCODE -ne 0) { throw "Git fetch failed" }
git switch --detach "origin/$branch"
if ($LASTEXITCODE -ne 0) { throw "Git switch failed" }

python -m unittest discover -s tests -p "test_financial_ml_finmind_scaled_cohort.py" -v
if ($LASTEXITCODE -ne 0) { throw "Scaled cohort tests failed" }

$mlRoot = (git rev-parse --show-toplevel).Trim()
$mainRoot = Join-Path (Split-Path $mlRoot -Parent) "Financial-Risk-Alert-System"
$data = Join-Path $mainRoot "fintrust_backend\data\financial_ml"
$universe = Join-Path $data "finmind_universe\taiwan_nonfinancial_current_candidates.csv"
$cohort = Join-Path $data "finmind_scaled_120"
$raw = Join-Path $data "finmind_cross_industry_raw"
$reports = Join-Path $data "finmind_scaled_batch_reports"

python -m research.financial_ml.finmind_scaled_cohort plan `
  --candidate-csv $universe --output $cohort --size 120 --semiconductors 24
if ($LASTEXITCODE -ne 0) { throw "Cohort planning failed" }

$selection = Join-Path $cohort "finmind_scaled_cohort.csv"
python -m research.financial_ml.finmind_scaled_cohort batch `
  --cohort-csv $selection --raw-root $raw --reports-root $reports `
  --batch-size 12 --max-batches 1
if ($LASTEXITCODE -ne 0) { throw "Dry-run failed" }

# Only after inspecting the network request budget:
python -m research.financial_ml.finmind_scaled_cohort batch `
  --cohort-csv $selection --raw-root $raw --reports-root $reports `
  --batch-size 12 --max-batches 1 --execute
if ($LASTEXITCODE -ne 0) { throw "First scaled batch failed" }

Get-Content (Join-Path $reports "finmind_scaled_run_summary.json") -Raw
```

To continue, rerun **only the last `batch --execute` invocation**; the
driver automatically skips fully cached earlier batches. Avoid concurrent
copies of the command. Do not decrease the 15-second pacing to evade provider
limits.

## Inspect and build annual candidates after enough batches
When the 120-issuer cohort has been downloaded, reuse existing code:

```powershell
python -m research.financial_ml.finmind_cross_industry_pilot audit `
  --pilot-csv $selection --raw-root $raw `
  --output (Join-Path $data "finmind_scaled_schema_audit")
python -m research.financial_ml.finmind_annual_candidate_stage `
  --candidate-csv $selection --raw-root $raw `
  --output (Join-Path $data "finmind_scaled_annual_candidates")
python -m research.financial_ml.annual_panel_readiness `
  --dataset (Join-Path $data "finmind_scaled_annual_candidates\finmind_annual_candidate_lines.csv") `
  --output (Join-Path $data "finmind_scaled_sequence_readiness")
```

Note that these annual line values remain **unapproved provisional amounts**:
only 12 simple finance fields and candidate reporting-frequency mappings.
They do not yet generate the original 15 literature variables. Prior to
training: cross-industry MOPS reconciliation, 24 base-item field mapping
and source/fiscal-period approval, and true outcome labels for independently
documented problem-company years. The reserved 1785 case stays the final
blind assessment and **post-restatement inputs cannot represent ex-ante
pre-2016 prediction**.

## Evidence and validation
- Six self-contained module tests: deterministic diverse cohort, source
  integrity, cache replay, quota fail-stop, corrupt-file protection, and
  no spurious normal labels. Executable through the above unittest command.
- Offline local test using an older uploaded 1,482-company candidate frame
  produced a 120-company, 24-semiconductor, 40-industry cohort with 360
  total requests planned; the new 2,086-company user frame has **not yet
  been executed by this assistant** and its selected composition may differ.
- No network calls were made by the new script in the local validation.
