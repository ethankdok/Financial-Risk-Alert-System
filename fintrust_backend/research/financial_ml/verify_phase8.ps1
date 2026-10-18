# Phase8 one-command acceptance. Only 3 pending official judicial HTTPS sources
# should require new requests; SFIPC byte archive is reused if unchanged.
param()
$ErrorActionPreference="Stop"
function Check([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit $LASTEXITCODE)" }
}
$root=(git rev-parse --show-toplevel).Trim()
Check "git"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Use the dedicated research ML worktree"
}
Write-Host "Phase8: verified TLS compatibility and original-MOPS evidence/label tests"
python -m unittest discover -s tests -p "test_financial_ml_phase8_verified_tls_filing_intake.py" -v
Check "Phase8 tests"
python -m unittest discover -s tests -p "test_financial_ml_phase7_evidence_asof_audit.py" -v
Check "Phase7 identity tests"
python -m unittest discover -s tests -p "test_financial_ml_phase6_official_evidence_recovery.py" -v
Check "Phase6 evidence regression"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Check "Case candidate/holdout regression"

$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"

# Explicit bounded research retrieval. No API keys or production writes.
python -m research.financial_ml.phase8_integrated_run --data-root $data
Check "Phase8 integrated official-source and original-filing audit"

$path=Join-Path $data "phase8_case_original_filing_recovery\phase8_integrated_report.json"
$report=Get-Content $path -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "===== PHASE8 EVIDENCE AND ORIGINAL FILING GATES ====="
$report | Select-Object status,official_case_sources_expected,official_case_content_identity_passed,
    original_filing_company_years_needed,historical_year_window_slot_requirements,
    verified_original_filing_versions,first_disclosure_time_verified,
    positive_labels_admitted,negative_labels_admitted,
    supervised_model_training_admitted,holdout_1785_never_used | Format-List
$report.official_case_source_failures | Format-Table -AutoSize
Write-Host "One report to upload: $path"
Write-Host "If errors persist, the report contains the source IDs/reasons. Do not retry individually."
