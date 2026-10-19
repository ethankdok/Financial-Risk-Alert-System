# Phase10 one offline integration: existing Beneish8+Dechow7 genuine formulas on
# locally SHA archived Phase9 official MOPS. No network, no database writes.
param()
$ErrorActionPreference="Stop"
function Require-Exit([string]$stage) {
  if ($LASTEXITCODE -ne 0) { throw "$stage failed (exit $LASTEXITCODE)" }
}
$here=(git rev-parse --show-toplevel).Trim()
Require-Exit "git root"
if (-not $here.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Dedicated Financial-Risk-Alert-System-ML worktree required"
}
Write-Host "Phase10: literature variables, prior-year sequence and official vintage"
python -m unittest discover -s tests -p "test_financial_ml_phase10_case_literature_vintage_audit.py" -v
Require-Exit "Phase10 tests"
python -m unittest discover -s tests -p "test_financial_ml_literature_dataset_phase5.py" -v
Require-Exit "Original literature engine tests"
python -m unittest discover -s tests -p "test_financial_ml_phase9_case_mops_xbrl_recovery.py" -v
Require-Exit "Phase9 acquisition regression"
python -m unittest discover -s tests -p "test_financial_ml_phase8_verified_tls_filing_intake.py" -v
Require-Exit "Phase8 vintage regression"

$base=Join-Path (Split-Path $here -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $base "fintrust_backend\data\financial_ml"
$out=Join-Path $data "phase10_case_official_paper_audit"
Write-Host "Phase10: calculate and audit 15 original financial paper formulas on cached case XBRL"
python -m research.financial_ml.phase10_case_literature_vintage_audit --data-root $data --output $out
Require-Exit "Phase10 actual financial literature features"

$path=Join-Path $out "phase10_integrated_report.json"
$r=Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "===== PHASE10 OFFICIAL CASE LITERATURE FEATURES ====="
$r | Select-Object status,source_issuer_year_rows,official_archived_xbrl_years,actual_paper_feature_years,fully_computed_15_feature_years,beneish8_complete_years,dechow7_complete_years,missing_literature_feature_cells,candidate_event_three_year_windows,complete_three_year_paper_windows,original_pre_correction_versions_verified,verified_positive_labels,historical_asof_training_rows_admitted | Format-List
$r.missing_official_years | Format-Table -AutoSize
Write-Host "Upload report: $path"
Write-Host "All computed components are retrospective; this is not a fraud-detection performance score."
