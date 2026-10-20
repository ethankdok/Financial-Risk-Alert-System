# Round10: 120 confirmed issuers + disclosed financial statement correction leads.
# Never infers fraud label 1 or audited-clean label 0 from a search result.
$ErrorActionPreference="Stop"
function Require-Success($message){
    if($LASTEXITCODE -ne 0){throw "$message failed: $LASTEXITCODE"}
}
$repo=(git rev-parse --show-toplevel).Trim()
Require-Success "git root"
if(-not $repo.EndsWith("Financial-Risk-Alert-System-ML")){
    throw "Run from dedicated Financial-Risk-Alert-System-ML worktree."
}
$branch=(git branch --show-current).Trim()
if($branch -ne "feature/financial-ml-round10-120-period-disclosure-audit-20261020"){
    throw "Wrong research branch: $branch"
}
$main=Join-Path (Split-Path $repo -Parent) "Financial-Risk-Alert-System"
$ml=Join-Path $main "fintrust_backend\data\financial_ml"
$annual=Join-Path $ml "final_round1_integrated_ml_dataset\annual_12_amount_candidate_index.csv"
$output=Join-Path $ml "round10_120_company_disclosure_evidence"
if(-not (Test-Path -LiteralPath $annual)){
    throw "No frozen original Round1 annual input. Do not regenerate a different cohort."
}
if(Test-Path -LiteralPath $output){
    throw "Existing Round10 output must not be overwritten; preserve manual review changes."
}
Push-Location (Join-Path $repo "fintrust_backend")
try{
    python -m unittest discover -s tests -p test_financial_ml_round10_120_period_audit.py -v
    Require-Success "Round10 synthetic full cohort test"
    python -m research.financial_ml.round10_disclosure_event_label_gate `
        --annual-index $annual `
        --out $output
    Require-Success "Real frozen 120 issuer disclosure evidence source reconciliation"
    $report=Join-Path $output "round10_label_gate_report.json"
    $v=Get-Content -Raw -Encoding UTF8 -LiteralPath $report|ConvertFrom-Json
    $v | Select-Object status,companies,annual_periods,quarterly_periods,
        notice_leads,unique_notice_companies,
        fraud_positive_labels_approved,negative_controls_approved,
        supervised_classifier_fit_allowed | Format-List
    Write-Host "Manual annual queue: $(Join-Path $output 'round10_1560_annual_manual_review.csv')"
    Write-Host "Manual quarter queue: $(Join-Path $output 'round10_6240_quarter_manual_review.csv')"
    Write-Host "Approved 0/1 controls not present: DO NOT TRAIN FRAUD CLASSIFIER"
}
finally{Pop-Location}
