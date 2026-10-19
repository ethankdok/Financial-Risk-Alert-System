# Round4: explainability, robustness, final 1785 gate, research/presentation handoff.
param([int]$Permutations=5)
$ErrorActionPreference = "Stop"
function Check-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit $LASTEXITCODE)" }
}
$root=(git rev-parse --show-toplevel).Trim()
Check-Exit "git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Run from dedicated Financial-Risk-Alert-System-ML worktree"
}
$branch=(git branch --show-current).Trim()
Check-Exit "git branch"
if ($branch -ne "feature/financial-ml-round4-explainability-handoff-20261020") {
    throw "Wrong branch; preserve team work"
}
$source=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System\fintrust_backend\data\financial_ml"
$bridge=Join-Path $source "round2_closure_round3_preflight"
$round3=Join-Path $source "round3_real_model_evaluation_retry_01"
$report=Join-Path $round3 "round3_real_data_model_report.json"
$out=Join-Path $source "round4_explainability_handoff"
if (-not (Test-Path -LiteralPath $report)) {
    throw "Accepted real Round3 report missing; do not rerun prior phases"
}
# Pin the original exact user-uploaded bytes to prevent silent source substitution.
$accepted="766fa54e83763c39634605e983a3928e0fd8055e7fa06b72fc767bfa037ce380"
$hash=(Get-FileHash -LiteralPath $report -Algorithm SHA256).Hash.ToLowerInvariant()
if ($hash -ne $accepted) {
    throw "Accepted Round3 report SHA changed. Stop, review data. Found: $hash"
}
if (Test-Path -LiteralPath $out) {
    throw "Round4 output directory exists. Preserve previous findings; never overwrite"
}
Push-Location (Join-Path $root "fintrust_backend")
try {
    Write-Host "Round4: offline synthetic source/label/permutation regression"
    python -m unittest discover -s tests -p "test_financial_ml_round4_research_handoff.py" -v
    Check-Exit "Round4 synthetic tests"
    Write-Host "Round4: source-pinned REAL validation-only permutation and quarter model agreement"
    python -m research.financial_ml.round4_research_handoff `
        --data-root $source `
        --round2-bridge-root $bridge `
        --round3-root $round3 `
        --output $out `
        --round3-sha256 $accepted `
        --repeats $Permutations
    Check-Exit "Round4 real-data evaluation"
    $final = Join-Path $out "round4_research_handoff_report.json"
    $result=Get-Content -LiteralPath $final -Encoding UTF8 -Raw | ConvertFrom-Json
    Write-Host "===== ROUND4 REAL-DATA INTERPRETABILITY QA ====="
    $result | Select-Object status,annual_numeric_models_with_metrics,
       validation_chosen_numeric_model,diagnostic_permutation_features_per_model,
       unlabeled_quarter_scores_compared,strict_joint_test_company_count,
       original_asof_1785_replay_status,reserved_1785_excluded | Format-List
    Write-Host "Return: $final"
    Write-Host "Details: $out"
}
finally { Pop-Location }
