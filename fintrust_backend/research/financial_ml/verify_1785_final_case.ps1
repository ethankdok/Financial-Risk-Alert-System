# 1785 final independent case replay; frozen source, no model fitting.
$ErrorActionPreference="Stop"
function Require-Success([string]$name) {
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}
$git=(git rev-parse --show-toplevel).Trim();Require-Success "git status"
if (-not $git.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Use dedicated Financial-Risk-Alert-System-ML worktree"
}
$branch=(git branch --show-current).Trim();Require-Success "git branch"
if ($branch -ne "feature/financial-ml-1785-final-case-inference-20261020") {
    throw "Wrong feature branch; leave the main checkout unchanged."
}
$main=Join-Path (Split-Path $git -Parent) "Financial-Risk-Alert-System"
$base=Join-Path $main "fintrust_backend\data"
$ml=Join-Path $base "financial_ml"
$package=Join-Path $base "historical_audit\packages\fintrust_1785_asof_2016-11-14.zip"
$round3=Join-Path $ml "round3_real_model_evaluation_retry_01"
$round4=Join-Path $ml "round4_explainability_handoff\round4_research_handoff_report.json"
$bridge=Join-Path $ml "round2_closure_round3_preflight"
$output=Join-Path $ml "final_1785_case_replay"

foreach ($file in @(
    $package,
    $round4,
    (Join-Path $round3 "round3_real_data_model_report.json"),
    (Join-Path $bridge "round3_release_gates.json")
)) {
    if (-not (Test-Path -LiteralPath $file)) {
        throw "Required frozen evidence missing: $file"
    }
}
if (Test-Path -LiteralPath $output) {
    throw "Previous 1785 final-case output exists; inspect it, do not overwrite."
}
Push-Location (Join-Path $git "fintrust_backend")
try {
    Write-Host "1785: isolated case-source/inference validation"
    python -m unittest discover -s tests -p "test_financial_ml_final_1785_case_replay.py" -v
    Require-Success "1785 case regression"

    Write-Host "1785: verify actual archived strict ZIP, frozen models, full literature scores"
    python -m research.financial_ml.final_1785_case_replay `
        --data-root $ml `
        --round2-bridge-root $bridge `
        --round3-root $round3 `
        --round4-report $round4 `
        --strict-zip $package `
        --output $output
    Require-Success "1785 source pinned final case execution"

    $report=Join-Path $output "1785_case_final_report.json"
    $data=Get-Content -Raw -Encoding UTF8 -LiteralPath $report | ConvertFrom-Json
    Write-Host "===== FINAL 1785 REAL CASE RESULT ====="
    $data | Select-Object status,strict_package_financial_fact_count,
      frozen_round3_training_test_1785_excluded | Format-List
    $data.historical_score_rows | Format-Table fiscal_year,version,beneish_m_score,dechow_f_score -AutoSize
    $data.frozen_round3_case_numeric_inference | Format-List
    Write-Host "Report: $report"
    Write-Host "Slide-ready CSV: $(Join-Path $output '1785_historical_model_scores.csv')"
}
finally { Pop-Location }
