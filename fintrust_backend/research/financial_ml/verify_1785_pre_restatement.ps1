# FinTrust: 1785 final PRE-restatement annual numeric model application.
# Run in your independent ML worktree, no API keys, network, retraining or production DB.
$ErrorActionPreference = "Stop"
function Require-Success([string]$context) {
    if ($LASTEXITCODE -ne 0) { throw "$context failed (exit $LASTEXITCODE)" }
}
$root=(git rev-parse --show-toplevel).Trim()
Require-Success "git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Open the dedicated Financial-Risk-Alert-System-ML worktree."
}
$branch=(git branch --show-current).Trim()
Require-Success "git branch"
if ($branch -ne "feature/financial-ml-1785-prerestatement-replay-20261020") {
    throw "Wrong branch; preserve existing work and switch to 1785 PRE replay."
}
$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$base=Join-Path $main "fintrust_backend\data"
$ml=Join-Path $base "financial_ml"
$archive=Join-Path $base "historical_audit\packages\fintrust_1785_asof_2016-11-14.zip"
$bridge=Join-Path $ml "round2_closure_round3_preflight"
$round3=Join-Path $ml "round3_real_model_evaluation_retry_01"
$destination=Join-Path $ml "final_1785_pre_restatement_replay"
foreach($path in @($archive,
    (Join-Path $round3 "round3_real_data_model_report.json"),
    (Join-Path $round3 "annual_checkpoints\fit_only_preprocessor.joblib"),
    (Join-Path $bridge "round3_release_gates.json"))) {
    if (-not (Test-Path -LiteralPath $path)) {
        throw "Required frozen source is missing: $path"
    }
}
if (Test-Path -LiteralPath $destination) {
    throw "Final PRE-result directory already exists. Preserve it; do not overwrite."
}
Push-Location (Join-Path $root "fintrust_backend")
try {
    Write-Host "1785: hermetic PRE-versus-POST source and frozen model regression tests"
    python -m unittest discover -s tests -p "test_financial_ml_round5_1785_pre_restatement.py" -v
    Require-Success "1785 pre-restatement model tests"

    Write-Host "1785: official pre-restatement MOPS notice -> frozen Persistence amount forecast"
    python -m research.financial_ml.round5_1785_pre_restatement_replay `
        --strict-zip $archive `
        --data-root $ml `
        --round2-bridge-root $bridge `
        --round3-root $round3 `
        --output $destination
    Require-Success "1785 real pre-restatement replay"

    $p=Join-Path $destination "1785_pre_restatement_replay_report.json"
    $r=Get-Content -Raw -Encoding UTF8 -LiteralPath $p | ConvertFrom-Json
    Write-Host ""
    Write-Host "===== FROZEN 1785 PRE-RESTATEMENT NUMERICAL FORECAST ====="
    $r | Select-Object status,official_pre_post_metric_pairs,
        2015_numeric_forecast_count,2016_three_year_same_feature_numeric_forecast_count,
        2016_full_twelve_metric_vector_available,
        post_restatement_not_used_as_feature | Format-List
    Write-Host ""
    $pred=Import-Csv -LiteralPath (
        Join-Path $destination "1785_frozen_persistence_pre_only_predictions.csv")
    $pred | Where-Object { $_.forecast_year -eq "2016" } |
        Select-Object metric,forecast_twd | Format-Table -AutoSize
    $pred | Where-Object { $_.forecast_year -eq "2015" } |
        Select-Object metric,forecast_twd,observed_pre_twd,observed_post_twd,
            error_vs_pre_twd,restatement_adjustment_twd | Format-Table -AutoSize
    Write-Host "Upload these two files to complete the PPT 1785 case slide:"
    Write-Host $p
    Write-Host (Join-Path $destination "1785_frozen_persistence_pre_only_predictions.csv")
}
finally {
    Pop-Location
}
