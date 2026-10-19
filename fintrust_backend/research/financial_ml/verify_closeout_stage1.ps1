# One offline acceptance for financial ML closeout Stage1.
# Never downloads, trains, deploys or alters production data.
param()
$ErrorActionPreference="Stop"
function Assert-Good([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit=$LASTEXITCODE)" }
}
$repo=(git rev-parse --show-toplevel).Trim()
Assert-Good "Git worktree"
if (-not $repo.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Dedicated Financial-Risk-Alert-System-ML research worktree required"
}
Write-Host "Closeout S1: annual, paper and quarterly source QA regression"
python -m unittest discover -s tests -p "test_financial_ml_closeout_stage1_dataset_readiness.py" -v
Assert-Good "Stage1 14 new QA regressions"
python -m unittest discover -s tests -p "test_financial_ml_phase14_multiissuer_quarterly_cohort.py" -v
Assert-Good "Phase14 multi-company regression"
python -m unittest discover -s tests -p "test_financial_ml_phase13_quarterly_temporal_features.py" -v
Assert-Good "Phase13 period comparability regression"
python -m unittest discover -s tests -p "test_financial_ml_phase4_taiwan_dataset_gate.py" -v
Assert-Good "Phase4 source tier and split regression"
python -m unittest discover -s tests -p "test_financial_ml_provisional_sequence_experiment.py" -v
Assert-Good "Temporal sequence regression"

$main=Join-Path (Split-Path $repo -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$out=Join-Path $data "closeout_stage1_dataset_readiness"
Write-Host "Closeout S1: build three unmerged source-backed datasets (OFFLINE)"
python -m research.financial_ml.closeout_stage1_dataset_readiness --data-root $data --output $out --max-quarter-features 24
Assert-Good "Stage1 actual data audit"

$reportPath=Join-Path $out "closeout_stage1_integrated_report.json"
$r=Get-Content $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "===== FINANCIAL ML CLOSEOUT STAGE1 DATA READINESS ====="
$r | Select-Object status,frozen_cohort_issuer_count,annual_provisional_company_years,annual_12_metric_complete_company_years,paper_feature_source_tier_rows,paper_full_15_candidate_company_year_rows_by_tier,historical_original_versions_approved,model_ready_supervised_positive_labels,model_ready_supervised_negative_labels,model_ready_supervised_training_rows,frozen_1785_holdout_preserved,network_requests,production_db_writes | Format-List
Write-Host "Actual numerical 3-year forecast windows by strict issuer+time split:"
$r.three_year_history_numeric_forecast_opportunities | Format-List
Write-Host "Actual numerical 5-year forecast windows by strict issuer+time split:"
$r.five_year_history_numeric_forecast_opportunities | Format-List
Write-Host "Quarter data and fit-only feature coverage:"
$r.quarterly | Format-List
Write-Host "Single report to upload: $reportPath"
Write-Host "No unknown class has been assigned a normal/fraud label."
