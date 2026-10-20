# FinTrust Round9 full 120-company human source review queue.
# SAFE: reads existing Round1 original research index; writes only a new
# immutable company-review directory, never sets supervised 0/1 labels.
$ErrorActionPreference="Stop"
function AssertSuccess([string]$context){
    if($LASTEXITCODE -ne 0){throw "$context failed (code $LASTEXITCODE)"}
}
$git=(git rev-parse --show-toplevel).Trim()
AssertSuccess "git root"
if(-not $git.EndsWith("Financial-Risk-Alert-System-ML")){
    throw "Run from your dedicated Financial-Risk-Alert-System-ML repository."
}
$branch=(git branch --show-current).Trim()
if($branch -ne "feature/financial-ml-round9-company-evidence-audit-20261020"){
    throw "Switch to Round9 company evidence branch."
}
$main=Join-Path (Split-Path $git -Parent) "Financial-Risk-Alert-System"
$root=Join-Path $main "fintrust_backend\data\financial_ml"
$index=Join-Path $root "final_round1_integrated_ml_dataset\annual_12_amount_candidate_index.csv"
$output=Join-Path $root "round9_every_company_evidence_review"
$leads=Join-Path $git "fintrust_backend\research\financial_ml\round9_official_case_source_leads.json"
if(-not(Test-Path $index)){
    throw "Round1 original exact 120-company annual index not found: $index"
}
if(Test-Path $output){
    throw "Round9 company review output already exists. Do not overwrite reviewer research."
}
Push-Location (Join-Path $git "fintrust_backend")
try {
    python -m unittest discover -s tests -p test_financial_ml_round9_every_company_audit.py -v
    AssertSuccess "Round9 120 company evidence tests"
    python -m research.financial_ml.round9_every_company_official_review `
        --annual-index $index `
        --official-leads $leads `
        --out $output
    AssertSuccess "Round9 exact issuer-year research queue"
    Write-Host ""
    Write-Host "UPLOAD THIS FILE: $(Join-Path $output 'round9_each_company_research_queue.csv')"
    Write-Host "YEAR LEVEL: $(Join-Path $output 'round9_each_issuer_year_research_queue.csv')"
    Write-Host "REPORT: $(Join-Path $output 'round9_company_audit_report.json')"
    Write-Host "Do not treat missing search hits as clean or trained label=0."
}
finally{Pop-Location}
