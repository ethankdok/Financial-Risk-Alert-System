# FinTrust Round11: same fiscal year, original-as-of 24-month supervised label audit.
# No invented zeros or positive fraud claims. Reads only immutable source cohorts.
param([switch]$Train)
$ErrorActionPreference="Stop"
function Check-Exit([string]$ctx){
    if($LASTEXITCODE -ne 0){ throw "$ctx failed: $LASTEXITCODE" }
}
$root=(git rev-parse --show-toplevel).Trim()
Check-Exit "git root"
if(-not $root.EndsWith("Financial-Risk-Alert-System-ML")){
    throw "Use dedicated Financial-Risk-Alert-System-ML worktree."
}
$branch=(git branch --show-current).Trim()
if($branch -ne "feature/financial-ml-round11-yearmatched-label-evidence-20261020"){
    throw "Wrong research branch."
}
$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$ml=Join-Path $main "fintrust_backend\data\financial_ml"
$review=Join-Path $ml "round11_same_fy_24m_review"
$approved=Join-Path $review "round11_approved_year_matched_labels.csv"
$evidence=Join-Path $ml "round11_primary_source_archive"
$trained=Join-Path $ml "round11_approved_fy_matched_classifier"

Push-Location (Join-Path $root "fintrust_backend")
try{
    python -m unittest discover -s tests -p test_financial_ml_round11_same_year_evidence.py -v
    Check-Exit "Round11 evidence regression tests"

    if($Train){
        if(-not(Test-Path -LiteralPath $approved)){
            throw "No approved double-reviewed 0/1 panel. Use prepare mode, obtain official primary documents, then have two reviewers certify them before running Train."
        }
        if(Test-Path -LiteralPath $trained){
            throw "Previous frozen same-year experiment exists; do not overwrite."
        }
        python -m research.financial_ml.round11_year_matched_evidence_gate train `
            --approved-panel $approved `
            --evidence-root $evidence `
            --out $trained
        Check-Exit "Round11 source-audited same-year classification"
        Write-Host "Evidence/fit report: $(Join-Path $trained 'round11_evidence_matched_training_report.json')"
    }else{
        if(Test-Path -LiteralPath $review){throw "Original review directory exists; do not overwrite any human work."}
        python -m research.financial_ml.round11_year_matched_evidence_gate prepare `
            --out $review
        Check-Exit "Prepare exact-year double-review packet"
        Write-Host "FY2022 + FY2023 240 issuer-year records:"
        Write-Host (Join-Path $review "round11_same_fy_human_annotation_queue.csv")
        Write-Host "Approved 0/1 template (empty by design):"
        Write-Host (Join-Path $review "round11_approved_year_matched_label_TEMPLATE.csv")
    }
}
finally{Pop-Location}
