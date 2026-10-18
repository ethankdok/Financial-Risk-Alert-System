# One-shot Phase7 acceptance: verify and retry only four source-locked official URLs.
# Optional saved-official-HTML import manifest may exist in the data root.
param()
$ErrorActionPreference="Stop"
function Check-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit $LASTEXITCODE)" }
}
$root=(git rev-parse --show-toplevel).Trim()
Check-Exit "Git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Dedicated ML worktree required"
}
Write-Host "Phase7: charset/company aliases, docket check, original filing-asof gap tests"
python -m unittest discover -s tests -p "test_financial_ml_phase7_evidence_asof_audit.py" -v
Check-Exit "Phase7 tests"
python -m unittest discover -s tests -p "test_financial_ml_phase6_official_evidence_recovery.py" -v
Check-Exit "Phase6 regression tests"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Check-Exit "Phase1 case evidence regression"

$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$output=Join-Path $data "phase7_official_case_asof_recovery"
$params=@("-m","research.financial_ml.phase7_evidence_asof_audit",
          "--data-root",$data,"--output",$output,
          "--retrieve-official","--pace-seconds","2")
$manualManifest=Join-Path $data "phase7_official_manual_imports.csv"
if (Test-Path $manualManifest) {
    Write-Host "Explicit local evidence import manifest detected and will be reviewed"
    $params+=@("--manual-import-manifest",$manualManifest)
}
Write-Host "Phase7: official-only evidence retry and period-specific as-of gap inventory"
python @params
Check-Exit "Phase7 official evidence and historical filing readiness"

$report=Get-Content (Join-Path $output "phase7_evidence_asof_report.json") -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "===== PHASE7 CASE-SOURCE AND ORIGINAL-ASOF REPORT ====="
$report | Select-Object status,case_count,affected_company_year_candidates,
    primary_source_count,archived_primary_sources_with_docket_and_company,
    original_filing_requirements,verified_original_financial_reports,
    first_public_disclosure_times_verified,approved_taiwan_misstatement_labels,
    supervised_ex_ante_ml_admitted_rows,holdout_1785_untouched | Format-List
$report.content_identity_diagnostic_counts | Format-List
$report.source_failures | Format-Table -AutoSize
Write-Host "Final JSON: $(Join-Path $output 'phase7_evidence_asof_report.json')"
Write-Host "Source review: $(Join-Path $output 'phase7_official_source_review.csv')"
Write-Host "No case outcomes or source publication times are automatically admitted."
