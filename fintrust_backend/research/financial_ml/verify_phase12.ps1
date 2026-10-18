# Phase 1+2 one-shot local acceptance: no intermediate manual commands.
# Run only from fintrust_backend of the separate Financial-Risk-Alert-System-ML worktree.
param([switch]$ExecuteDownloads)

$ErrorActionPreference = "Stop"

function Verify-Exit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit=$LASTEXITCODE)" }
}

Write-Host "Phase 1+2 integrated research regression suite"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Verify-Exit "Phase 1 tests"
python -m unittest discover -s tests -p "test_financial_ml_phase12_integrated_gate.py" -v
Verify-Exit "Integrated gate tests"
python -m unittest discover -s tests -p "test_financial_ml_finmind_scaled_cohort.py" -v
Verify-Exit "FinMind download regression"
python -m unittest discover -s tests -p "test_financial_ml_finmind_annual_candidate_stage.py" -v
Verify-Exit "Annual source staging regression"
python -m unittest discover -s tests -p "test_financial_ml_annual_panel_readiness.py" -v
Verify-Exit "Panel readiness regression"

$mlRoot = (git rev-parse --show-toplevel).Trim()
Verify-Exit "git root"
if (-not $mlRoot.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Refusing to run outside the dedicated ML worktree"
}
$mainRoot = Join-Path (Split-Path $mlRoot -Parent) "Financial-Risk-Alert-System"
$dataRoot = Join-Path $mainRoot "fintrust_backend\data\financial_ml"
$cohort = Join-Path $dataRoot "finmind_scaled_120\finmind_scaled_cohort.csv"
if (-not (Test-Path $cohort)) { throw "120-issuer cohort file is missing: $cohort" }
$out = Join-Path $dataRoot "phase12_integrated_verification"

Write-Host "Running Phase 1 evidence gate and Phase 2 source integrity/annual panel"
$arguments = @(
    "-m", "research.financial_ml.phase12_integrated_gate",
    "--data-root", $dataRoot,
    "--output", $out
)
if ($ExecuteDownloads) { $arguments += "--execute-download" }
python @arguments
Verify-Exit "Integrated phase execution"

$report = Get-Content (Join-Path $out "phase12_gate_report.json") -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "==== FINAL Phase 1+2 acceptance report ===="
$report | Select-Object status,phase1_case_candidates,phase1_candidate_company_years,
    phase1_approved_positive_labels,phase1_approved_negative_labels,
    phase1_evidence_complete,phase2_annual_candidate_rows,
    phase2_annual_candidate_amounts,phase2_all_requested_sources_present,
    phase2_original_filing_pit_verified,phase2_vendor_mapping_certified,
    phase2_complete_for_trusted_15_features | Format-List
$report.phase2_raw | Select-Object cohort_companies,fully_cached_issuers,
    fully_nonempty_issuers,missing_archives,provider_empty_responses,
    quarantined_issuers | Format-List
Write-Host "FULL REPORT: $(Join-Path $out 'phase12_gate_report.json')"
Write-Host "Attach only report JSON plus selected error CSV rows for review; do not upload API tokens."
