# Phase13: one command. Offline source-SHA-audited quarterly feature catalog.
# No API request, no machine learning model fitting and no production writes.
param()
$ErrorActionPreference="Stop"
function Check([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed, exit $LASTEXITCODE" }
}
$repo=(git rev-parse --show-toplevel).Trim()
Check "Git root"
if (-not $repo.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Please execute in dedicated Financial-Risk-Alert-System-ML worktree"
}
Write-Host "Phase13: 12-quarter primary statement TWD source and period-grain tests"
python -m unittest discover -s tests -p "test_financial_ml_phase13_quarterly_temporal_features.py" -v
Check "Phase13 tests"
python -m unittest discover -s tests -p "test_financial_ml_phase12_kangyou_quarterly_panel.py" -v
Check "Phase12 raw source and SHA regression"
python -m unittest discover -s tests -p "test_financial_ml_phase11_case_quarterly_gap_analysis.py" -v
Check "Phase11 period/case-grain regression"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Check "Phase1 outcome and final holdout regression"

$main=Join-Path (Split-Path $repo -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$out=Join-Path $data "phase13_kangyou_quarterly_temporal_features"
Write-Host "Phase13: derive same-concept, same-period-grain candidate quarterly signals (NO NETWORK)"
python -m research.financial_ml.phase13_quarterly_temporal_features --data-root $data --output $out
Check "Phase13 real Taiwan financial feature extraction"

$path=Join-Path $out "phase13_integrated_report.json"
$r=Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "====== PHASE13 KANGYOU TWELVE-QUARTER RESEARCH FEATURES ======"
$r | Select-Object status,official_source_quarters_read,
  total_primary_statement_TWD_period_observations,
  unique_concept_grain_quarter_candidates,
  conflicting_concept_grain_quarters_quarantined,
  candidate_concepts_with_observations,same_grain_change_candidates,
  independent_issuer_count,independent_true_misstatement_labels,
  genuine_historical_original_filing_versions_verified,
  model_training_rows_admitted,is_this_a_valid_multi_company_ml_dataset,
  network_requests,production_db_writes | Format-List
$r.same_grain_change_types | Format-List
Write-Host "Upload report: $path"
Write-Host "Candidate changes are neither an approved Beneish/Dechow mapping nor verified fraud outcomes."
