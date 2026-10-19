# Phase12 Kangyou quarter-panel one-pass acceptance.
# Up to 11 new official MOPS quarter requests, reuse Phase11 2020Q1.
# Deliberately separate from legacy verify_phase12.ps1 (Phase 1+2 script).
param()
$ErrorActionPreference="Stop"
function Check([string]$stage) {
    if ($LASTEXITCODE -ne 0) { throw "$stage failed (exit $LASTEXITCODE)" }
}
$repo=(git rev-parse --show-toplevel).Trim()
Check "Git worktree"
if (-not $repo.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Requires the dedicated Financial-Risk-Alert-System-ML worktree"
}
Write-Host "Phase12 Kangyou: official quarter XBRL + case outcome gates"
python -m unittest discover -s tests -p "test_financial_ml_phase12_kangyou_quarterly_panel.py" -v
Check "Phase12 new unit tests"
python -m unittest discover -s tests -p "test_financial_ml_phase11_case_quarterly_gap_analysis.py" -v
Check "Phase11 source scope regression"
python -m unittest discover -s tests -p "test_financial_ml_phase10_case_literature_vintage_audit.py" -v
Check "Phase10 genuine published formula regression"
python -m unittest discover -s tests -p "test_financial_ml_phase9_case_mops_xbrl_recovery.py" -v
Check "Phase9 MOPS immutable source archive regression"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Check "Phase1 case/holdout regression"

$main=Join-Path (Split-Path $repo -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$out=Join-Path $data "phase12_kangyou_quarterly_panel"
Write-Host "Phase12: acquire at most 11 new 6452 official quarter source reports"
python -m research.financial_ml.phase12_kangyou_quarterly_panel --data-root $data --output $out --execute
Check "Phase12 actual MOPS quarterly source and period-context audit"

$path=Join-Path $out "phase12_integrated_report.json"
$r=Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "===== PHASE12 OFFICIAL KANGYOU QUARTER PANEL ====="
$r | Select-Object status,candidate_quarters,new_quarters_planned,
  official_quarters_context_scope_validated,reused_verified_2020Q1_from_phase11,
  cached_reused_prior_phase12,new_network_requests,
  quarterly_numeric_current_period_facts,quarterly_exact_duration_facts,
  quarterly_ytd_duration_facts,historical_original_filing_vintages_verified,
  confirmed_period_outcome_labels,financial_misstatement_supervised_training_rows,
  final_holdout_1785_excluded | Format-List
$r.source_status_counts | Format-List
$r.unavailable_or_quarantined_quarters | Format-Table -AutoSize
Write-Host "One report to upload: $path"
Write-Host "Missing official source != financial zero or approved outcome label"
