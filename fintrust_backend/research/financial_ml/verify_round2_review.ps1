# Round2: one offline evidence/adjudication review packet; no refetching.
param()
$ErrorActionPreference = "Stop"

function Require-Good([string]$step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$step failed (exit $LASTEXITCODE)"
    }
}

$repo = (git rev-parse --show-toplevel).Trim()
Require-Good "git root"
if (-not $repo.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Run inside the dedicated Financial-Risk-Alert-System-ML worktree only."
}
$current = (git branch --show-current).Trim()
Require-Good "git branch"
if ($current -ne "feature/financial-ml-round2-review-gate-20261020") {
    throw "Wrong branch: $current. Do not overwrite existing or other team branches."
}
$backend = Join-Path $repo "fintrust_backend"
if (-not (Test-Path (Join-Path $backend "research\financial_ml\round2_evidence_review.py"))) {
    throw "Wrong backend/research path."
}
Push-Location $backend
try {
    Write-Host "Round2: ONLY new hermetic provenance and label tests"
    python -m unittest discover -s tests -p "test_financial_ml_round2_evidence_review.py" -v
    Require-Good "Round2 focused tests"

    $main = Join-Path (Split-Path $repo -Parent) "Financial-Risk-Alert-System"
    $source = Join-Path $main "fintrust_backend\data\financial_ml"
    $target = Join-Path $source "round2_evidence_review"
    if (-not (Test-Path (Join-Path $source "final_round1_integrated_ml_dataset\round1_dataset_readiness_report.json"))) {
        throw "Round1 real-data report missing; do not regenerate or silently substitute inputs."
    }
    Write-Host "Round2: ONE offline integration of already archived evidence (no HTTP, no model fitting)"
    python -m research.financial_ml.round2_evidence_review --data-root $source --output $target
    Require-Good "Round2 actual-source packet"

    $path = Join-Path $target "round2_evidence_review_report.json"
    $r = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "===== ROUND2 EVIDENCE REVIEW / HUMAN ADJUDICATION GATES ====="
    $r | Select-Object status, candidate_case_company_years,
        separate_alleged_case_quarters, unreviewed_comparison_issuer_quarters,
        case_annual_complete_retrospective_15, case_legal_sources_with_content_identity,
        reviewed_fraud_positives, reviewed_healthy_negatives,
        original_filing_vintages_certified, supervised_fraud_training_admitted,
        holdout_1785_excluded, zero_network_requests, zero_production_writes |
        Format-List
    Write-Host "Upload ONLY report: $path"
    Write-Host "Round2 remains blocked for supervised ML until primary and reviewer evidence is approved."
}
finally {
    Pop-Location
}
