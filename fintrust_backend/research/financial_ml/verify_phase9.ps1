# Phase9 single Windows acceptance. Bounded up to 12 official MOPS annual XBRL requests;
# SHA archives stay only in ignored research data, not production databases.
param()
$ErrorActionPreference = "Stop"
function Assert-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit=$LASTEXITCODE)" }
}
$mlRoot=(git rev-parse --show-toplevel).Trim()
Assert-Exit "Git root"
if (-not $mlRoot.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Refusing to run outside dedicated Financial-Risk-Alert-System-ML worktree"
}
Write-Host "Phase9: official case-year XBRL and historical-vintage admission regression"
python -m unittest discover -s tests -p "test_financial_ml_phase9_case_mops_xbrl_recovery.py" -v
Assert-Exit "Phase9 case MOPS acquisition tests"
python -m unittest discover -s tests -p "test_financial_ml_official_batch.py" -v
Assert-Exit "Official batch archive regressions"
python -m unittest discover -s tests -p "test_financial_ml_phase8_verified_tls_filing_intake.py" -v
Assert-Exit "Phase8 original filing/holdout regressions"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Assert-Exit "Phase1 event evidence regressions"

$base=Join-Path (Split-Path $mlRoot -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $base "fintrust_backend\data\financial_ml"
Write-Host "Phase9: bounded 12 historical official annual XBRL sources; FY2012 legacy separated"
python -m research.financial_ml.phase9_case_mops_xbrl_recovery --data-root $data --execute
Assert-Exit "Phase9 official case XBRL acquisition"

$reportPath=Join-Path $data "phase9_case_mops_xbrl_candidates\phase9_integrated_report.json"
$r=Get-Content $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "==== PHASE9 FINAL CASE FILING SOURCE STATUS ===="
$r | Select-Object status,required_company_years,unique_tifrs_xbrl_requests,
  legacy_gaap_years_not_automatically_fetched,network_requests,
  xbrl_archived_with_sha_verified,xbrl_parsed_validated,
  original_company_years_still_unverified,
  pre_restated_original_filing_versions_approved,
  original_source_publication_times_verified,
  material_misstatement_positive_labels_approved,
  approved_supervised_model_rows,holdout_1785_excluded | Format-List
$r.source_acquisition_counts | Format-List
Write-Host "One report to send: $reportPath"
Write-Host "If MOPS blocks some requests, do not repeat individually; this manifest is resumable."
