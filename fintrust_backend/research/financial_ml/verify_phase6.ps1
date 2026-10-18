# Phase6 single acceptance: official legal-source archival and original-filing review.
# This script issues up to four official HTTPS requests on first run.
param()
$ErrorActionPreference="Stop"
function Ensure-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit $LASTEXITCODE)" }
}
$root=(git rev-parse --show-toplevel).Trim()
Ensure-Exit "Git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Use the separate Financial-Risk-Alert-System-ML worktree"
}
Write-Host "Phase6 official evidence regression"
python -m unittest discover -s tests -p "test_financial_ml_phase6_official_evidence_recovery.py" -v
Ensure-Exit "Phase6 official source tests"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Ensure-Exit "Phase1 source tests"
python -m unittest discover -s tests -p "test_financial_ml_phase5_taiwan_unlabeled_pilot.py" -v
Ensure-Exit "Phase5 finance regression"

$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$output=Join-Path $data "phase6_taiwan_case_official_evidence"
Write-Host "Phase6: retrieve judiciary/investor-protection sources only"
python -m research.financial_ml.phase6_official_evidence_recovery --output $output --retrieve-official --pace-seconds 2
Ensure-Exit "Phase6 official evidence integration"
$report=Get-Content (Join-Path $output "phase6_evidence_readiness.json") -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "==== PHASE6 OFFICIAL EVIDENCE READINESS ===="
$report | Select-Object status,candidate_case_count,case_year_review_rows,official_source_urls_expected,official_source_bytes_archived,original_pre_restatement_filing_count_verified,earliest_public_revelation_times_verified,case_year_positive_labels_approved,reviewed_negative_labels_approved,eligible_supervised_training_rows,holdout_1785_untouched | Format-List
$report.source_collection_statuses | Format-List
Write-Host "Report: $(Join-Path $output 'phase6_evidence_readiness.json')"
Write-Host "Attach source register only when retrieval errors need investigation."
