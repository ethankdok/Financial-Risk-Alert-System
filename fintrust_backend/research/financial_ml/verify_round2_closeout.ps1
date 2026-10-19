# Round2 engineering closeout + Round3 conditional preflight (one offline execution).
# Retains the user's accepted Round2 packet; never rewrites reviewer files.
param()
$ErrorActionPreference = "Stop"
function Require-Exit([string]$what) {
    if ($LASTEXITCODE -ne 0) {
        throw "$what failed with exit $LASTEXITCODE"
    }
}
$root = (git rev-parse --show-toplevel).Trim()
Require-Exit "git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Use independent Financial-Risk-Alert-System-ML worktree"
}
$branch = (git branch --show-current).Trim()
Require-Exit "git branch"
if ($branch -ne "feature/financial-ml-round2-closeout-round3-handoff-20261020") {
    throw "Wrong feature branch; protect other research worktrees"
}
$main = Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$source = Join-Path $main "fintrust_backend\data\financial_ml"
$round2 = Join-Path $source "round2_evidence_review"
$output = Join-Path $source "round2_closure_round3_preflight"
$acceptedReport = Join-Path $round2 "round2_evidence_review_report.json"
if (-not (Test-Path -LiteralPath $acceptedReport)) {
    throw "Accepted Round2 report missing; do not regenerate Stage1/Stage2 inputs"
}

Push-Location (Join-Path $root "fintrust_backend")
try {
    Write-Host "Round2 closeout: focused synthetic archive + split/holdout regressions"
    python -m unittest discover -s tests -p "test_financial_ml_round2_closeout_round3_bridge.py" -v
    Require-Exit "Round2 closeout focused regressions"

    # This hash was taken directly from the user's uploaded accepted JSON.
    # A mismatch is a stop, not an invitation to rewrite the old report.
    $acceptedSha = "f8d4a6606c44976ad50d2f26dce2a9291b838bcafb8741486f4be337e837b8c2"
    $localSha = (Get-FileHash -LiteralPath $acceptedReport -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($localSha -ne $acceptedSha) {
        throw "User-accepted Round2 report SHA mismatch: $localSha"
    }
    Write-Host "Round2: verify 9 frozen sources and official archived bytes; produce Round3 gated manifest"
    python -m research.financial_ml.round2_closeout_round3_bridge `
        --data-root $source `
        --round2-review-root $round2 `
        --output $output `
        --expected-round2-sha256 $acceptedSha
    Require-Exit "Round2 real-source archive integrity and Round3 gated preflight"

    $path = Join-Path $output "round2_closure_and_round3_preflight.json"
    $r = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host ""
    Write-Host "===== ROUND2 ENGINEERING CLOSEOUT ====="
    $r | Select-Object status, round2_source_sha256_verified,
        official_legal_sources_hashed_against_archived_bytes,
        original_first_filed_versions_independently_certified,
        adjudicated_case_periods, independently_followed_up_normal_periods,
        reviewed_positive_labels, reviewed_negative_labels,
        supervised_fraud_training_admitted,
        round2_engineering_gates_passed,
        round2_research_label_acceptance_passed,
        holdout_1785_untouched | Format-List
    $q = Get-Content -LiteralPath (Join-Path $output "round3_release_gates.json") -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host "===== ROUND3 RELEASE GATE ====="
    $q | Select-Object status,dataset_stage_ready,
        quarter_fit_only_features,supervised_fraud_train_allowed,
        unlabeled_anomaly_diagnostics_allowed,
        amount_forecasting_research_only_allowed,
        final_1785_holdout_restricted | Format-List
    Write-Host "Return two JSONs from: $output"
}
finally {
    Pop-Location
}
