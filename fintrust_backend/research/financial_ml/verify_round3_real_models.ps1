# Round3 one real-source numerical-model run. No refetch, no production, no 1785.
param(
    [int]$Epochs = 40,
    [switch]$SklearnOnly
)
$ErrorActionPreference = "Stop"
function Require-Good([string]$where) {
    if ($LASTEXITCODE -ne 0) { throw "$where failed (exit $LASTEXITCODE)" }
}

$root = (git rev-parse --show-toplevel).Trim()
Require-Good "git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Use the dedicated Financial-Risk-Alert-System-ML worktree"
}
$branch = (git branch --show-current).Trim()
Require-Good "git branch"
if ($branch -ne "feature/financial-ml-round3-model-evaluation-20261020") {
    throw "Round3 requires its isolated feature branch; preserve local work"
}
$main = Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data = Join-Path $main "fintrust_backend\data\financial_ml"
$bridge = Join-Path $data "round2_closure_round3_preflight"
$out = Join-Path $data "round3_real_model_evaluation"
if (-not (Test-Path -LiteralPath (Join-Path $bridge "round3_release_gates.json"))) {
    throw "Round2 accepted release gates missing"
}
if (Test-Path -LiteralPath $out) {
    $prior = Join-Path $out "round3_real_data_model_report.json"
    if (Test-Path -LiteralPath $prior) {
        throw "Previous Round3 report already exists: $prior. Review results; do NOT overwrite."
    }
    # Round3 failures can leave annual checkpoints before quarterly checks.
    # Retain ALL artifacts from previous attempts and choose a clean retry.
    $baseOut = $out
    $found = $false
    for ($index = 1; $index -le 30; $index++) {
        $candidate = "{0}_retry_{1:D2}" -f $baseOut, $index
        if (-not (Test-Path -LiteralPath $candidate)) {
            $out = $candidate
            $found = $true
            break
        }
    }
    if (-not $found) {
        throw "No unused Round3 retry output folder available; preserve existing research artifacts."
    }
    Write-Host "Previous Round3 partial result kept intact. Writing only to: $out"
}

Push-Location (Join-Path $root "fintrust_backend")
try {
    Write-Host "Round3: source/leakage/fraud-label hermetic regressions"
    python -m unittest discover -s tests -p "test_financial_ml_round3_research_models.py" -v
    Require-Good "Round3 hermetic tests"

    $runArgs = @(
        "-m", "research.financial_ml.round3_research_models",
        "--data-root", $data,
        "--round2-bridge-root", $bridge,
        "--output", $out,
        "--epochs", $Epochs
    )
    if ($SklearnOnly) {
        $runArgs += @("--models", "persistence", "ridge", "random_forest", "mlp")
        Write-Host "Round3: sklearn-only profile selected; no GRU/LSTM/TCN/Transformer/CatBoost"
    }
    else {
        Write-Host "Round3: full architecture list; optional unavailable libraries reported, NOT faked"
    }
    python @runArgs
    Require-Good "Round3 real multi-model evaluation"

    $path = Join-Path $out "round3_real_data_model_report.json"
    $r = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host ""
    Write-Host "===== ROUND3 NUMERICAL AMOUNT PREDICTION (NOT FRAUD) ====="
    $r.annual_numeric_study.comparisons |
        Select-Object model,status,validation_signed_log_mae,holdout_signed_log_mae,
            validation_scaled_rmse,holdout_scaled_rmse,holdout_scaled_r2 |
        Format-Table -AutoSize
    Write-Host ""
    Write-Host "===== ROUND3 UNLABELED QUARTERLY NOVELTY (NOT FRAUD) ====="
    $r.quarter_unlabeled_study.models |
        Select-Object model,fit_quarters,validation_quarters,test_quarters,
            validation_anomaly_fraction_above_fit_p95,
            test_anomaly_fraction_above_fit_p95,
            test_score_jsd_from_fit |
        Format-Table -AutoSize
    Write-Host "Verified fraud F1/Recall/PR-AUC remain unavailable; positive=0 negative=0."
    Write-Host "Upload real results (only): $path"
    Write-Host "Per-model CSVs remain under: $out"
}
finally {
    Pop-Location
}
