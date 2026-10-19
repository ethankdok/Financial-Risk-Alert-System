# Phase11: ONE local verification. Reuse Phase10 real 15-paper features;
# perform at most one additional official MOPS quarterly lookup (6452 FY2020 Q1).
param()
$ErrorActionPreference="Stop"
function Check([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit $LASTEXITCODE)" }
}
$ml=(git rev-parse --show-toplevel).Trim()
Check "git root"
if (-not $ml.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Only the dedicated Financial-Risk-Alert-System-ML worktree is allowed"
}
Write-Host "Phase11: quarter-level allegations, official raw Q1 evidence, source SHA"
python -m unittest discover -s tests -p "test_financial_ml_phase11_case_quarterly_gap_analysis.py" -v
Check "Phase11 tests"
python -m unittest discover -s tests -p "test_financial_ml_phase10_case_literature_vintage_audit.py" -v
Check "Phase10 literature case regression"
python -m unittest discover -s tests -p "test_financial_ml_phase9_case_mops_xbrl_recovery.py" -v
Check "Phase9 MOPS archive regression"
python -m unittest discover -s tests -p "test_financial_ml_literature_dataset_phase5.py" -v
Check "Published formula adapter regression"

$main=Join-Path (Split-Path $ml -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
Write-Host "Phase11: analyze 15-variable genuine MOPS reasons + one targeted 6452 2020Q1 request"
python -m research.financial_ml.phase11_case_quarterly_gap_analysis --data-root $data --execute
Check "Phase11 quarter and feature gap audit"

$path=Join-Path $data "phase11_case_quarterly_and_paper_gaps\phase11_integrated_report.json"
$r=Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "==== PHASE11 HISTORICAL QUARTER AND MISSING-FEATURE AUDIT ===="
$r | Select-Object status,case_reporting_period_candidates,6452_alleged_quarterly_periods,
 phase10_total_15_feature_cells_missing,phase10_missing_from_11_parsed_xbrl_years,
 phase10_missing_from_two_unavailable_annual_source_years,
 network_requests,original_company_report_vintages_verified,
 confirmed_positive_labels,supervised_early_warning_samples,holdout_1785_excluded | Format-List
$r.quarterly_source_status | Select-Object acquisition_status,raw_sha256,
  network_requests_this_run,cached_reused,verified_historical_original | Format-List
Write-Host "One report to upload: $path"
Write-Host "If quarter lookup fails, report it without repeating individual requests."
