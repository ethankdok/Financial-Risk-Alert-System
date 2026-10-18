# Research-only experimental ML learning on the partially acquired 120-issuer cohort

**Status 2026-10-18:** User has completed four 12-issuer raw acquisition batches (48/120 issuer download sets). Six batches remain. In the last 3 batches, 99 new financial statement JSONs were downloaded and 9 caches reused. Fourteen reports had no records, despite HTTP success. Do not count those as training companies. The full 120-issuer cohort contains 24 semiconductor candidates and 41 current industry types.

## Two distinct research goals — do not conflate

1. **Now (technical engineering smoke):** verify that multiple different architectures can train on actual multi-year input, use a training-only scaler, use a later-year validation period for choosing a model, save checkpoints and score the held-out future years. The twelve FinMind annual candidate amounts still have unapproved quarterly-to-annual semantics and MOPS mappings; they are **NOT** Beneish (1999) eight / Dechow (2011) seven published paper features and are **NOT** point-in-time original filings. The run can show only next-year numeric-prediction errors, *not* financial-misstatement accuracy or early detection.
2. **Actual study after data gates:** finish raw download and broader official reconciliation; map the correct 24 Compustat/TIFRS source accounts to the original literature feature engines; generate a source-versioned 15-feature panel. Then compare GRU/LSTM, TCN, Transformer and tabular baselines under issuer-disjoint plus out-of-time validation; freeze the models before applying to **1785**. Independent other-known-problem issuer-year case evidence is used for development controls; known outcomes do not enter feature engineering.

## New module

\`research/financial_ml/provisional_sequence_experiment.py\` implements **seven different model families** on a comparable next-year regression proxy:

- Ridge regression (simple linear baseline)
- Random Forest regression (nonlinear tree baseline)
- MLP (feed-forward neural network)
- GRU
- LSTM
- Small temporal convolutional network (TCN)
- Small attention/Transformer encoder

Prediction: from **three observed consecutive fiscal years × twelve provisional amounts**, predict the following year's twelve amounts. Optional five-year history. Signed \`log1p\` followed by \`RobustScaler\` fit **only using training financial data**. Missing or empty annual values **reject that window**; no zero imputation. Time split by **target year**, train 2016–2020, validation 2021–2022, holdout 2023–2025. Outputs normalized next-year MSE and future-year prediction residuals; do not call these fraud labels or probabilities. The same issuer may occur across time slices; an independent issuer-disjoint experiment is not yet implemented.

Training preflight: minimum 15 fit windows, 5 validation windows, 5 holdout windows, and 8 distinct fit issuers. On the **previous actual 12-company panel**, only 7 issuers yielded complete fitting-period windows, so the model **properly refused to fit**. Do not remove that gate. Rebuild using the user's newer 48-issuer raw cache first.

Safety: explicit \`--experimental-allow-unverified-data\` flag required; refuses ticker 1785, duplicate company-years, invalid finites, unexpected flags; network and production DB untouched. All artifacts marked \`candidate_data_only\`. Do not use these as the final project's evaluated fraud models.

## Copy-and-run (Windows PowerShell, current ML worktree)

\`\`\`powershell
$branch="feature/financial-ml-multimodel-temporal-smoke-20261018"
if (@(git status --porcelain).Count -gt 0) { throw "Unsaved ML worktree changes" }
git fetch origin "refs/heads/\${branch}:refs/remotes/origin/\${branch}"
if ($LASTEXITCODE -ne 0) { throw "Git fetch failed" }
git switch --detach "origin/$branch"
if ($LASTEXITCODE -ne 0) { throw "Git switch failed" }

python -m unittest discover -s tests -p "test_financial_ml_provisional_sequence_experiment.py" -v
if ($LASTEXITCODE -ne 0) { throw "Experimental model unit tests failed" }

$mlRoot=(git rev-parse --show-toplevel).Trim()
$mainRoot=Join-Path (Split-Path $mlRoot -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $mainRoot "fintrust_backend\data\financial_ml"
$cohort=Join-Path $data "finmind_scaled_120\finmind_scaled_cohort.csv"
$raw=Join-Path $data "finmind_cross_industry_raw"
$annual=Join-Path $data "finmind_scaled_annual_candidates"
$panel=Join-Path $data "finmind_scaled_sequence_readiness"
$result=Join-Path $data "finmind_temporal_technical_smoke"

python -m research.financial_ml.finmind_annual_candidate_stage \`
  --candidate-csv $cohort --raw-root $raw --output $annual
if ($LASTEXITCODE -ne 0) { throw "Annual-candidate staging failed" }

python -m research.financial_ml.annual_panel_readiness \`
  --dataset (Join-Path $annual "finmind_annual_candidate_lines.csv") --output $panel
if ($LASTEXITCODE -ne 0) { throw "Temporal panel preflight failed" }

# Probe installed CPU PyTorch. If unavailable, sklearn controls can still run:
python -c "import torch; print(torch.__version__)"
if ($LASTEXITCODE -ne 0) {
  Write-Host "PyTorch unavailable; run sklearn baselines only until compatible PyTorch is installed."
  $models = @("ridge", "random_forest", "mlp")
} else {
  $models = @("ridge", "random_forest", "mlp", "gru", "lstm", "tcn", "transformer")
}

python -m research.financial_ml.provisional_sequence_experiment \`
  --dataset (Join-Path $panel "company_year_candidate_panel.csv") \`
  --output $result --history 3 --epochs 40 \`
  --models $models --experimental-allow-unverified-data
if ($LASTEXITCODE -ne 0) { throw "Temporal pilot refused unsafe or insufficient data, or fitting failed" }

Get-Content (Join-Path $result "experiment_report.json") -Raw
\`\`\`

If **the sample count gate fails**, the fix is not to reduce the threshold: acquire more issuers from the remaining six batches, rerun the same annual staging/panel commands, and retry training. This is precisely why expanding issuer count matters. If PyTorch fails to import on the user's Windows environment, do not blindly install incompatible wheels or use the production Python interpreter; retain sklearn-only results and investigate the appropriate environment separately.

Outputs:
- \`experiment_report.json\` — split sizes, method comparison, best validation *proxy* model, source SHA, methodological limitations
- \`architecture_comparison_experimental.csv\` — normalized future-year financial prediction errors by model
- \`holdout_proxy_residual_scores.csv\` — descriptive residual rankings with \`known_financial_misstatement_label=UNKNOWN\`
- Saved model checkpoints (\`*.joblib\`, \`*.pt\`) and a train-only \`candidate_scaler.joblib\`

Training output does not establish actual financial fraud detection. Need externally documented case positives, verified negatives or appropriately scoped positive recall, leakage-safe original historical financial data, and later held-out case testing.
