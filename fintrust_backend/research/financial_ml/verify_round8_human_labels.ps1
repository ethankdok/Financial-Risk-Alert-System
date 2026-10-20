# FinTrust Round8: create candidate human-label review queue or evaluate genuinely
# approved original-filing issuer-years. Leaves all older model studies unchanged.
param([switch]$Train,[switch]$ScoreCase)
$ErrorActionPreference="Stop"
function Require-Success([string]$context){
  if($LASTEXITCODE -ne 0){throw "$context failed (exit $LASTEXITCODE)"}
}
$root=(git rev-parse --show-toplevel).Trim();Require-Success "git root"
if(-not $root.EndsWith("Financial-Risk-Alert-System-ML")){throw "Run from dedicated ML worktree"}
$branch=(git branch --show-current).Trim()
if($branch -ne "feature/financial-ml-round8-human-supervised-20261020"){
    throw "Use Round8 branch; do not mix model branches."
}
$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$ml=Join-Path $main "fintrust_backend\data\financial_ml"
$input=Join-Path $ml "final_round1_integrated_ml_dataset\annual_12_amount_candidate_index.csv"
$labels=Join-Path $ml "round8_human_review_packet"
$evidence=Join-Path $ml "round8_independent_evidence"
$panel=Join-Path $labels "round8_approved_original_supervised_panel.csv"
if(-not $Train -and -not $ScoreCase -and -not(Test-Path -LiteralPath $input)){
  throw "Existing frozen Round1 annual index missing. Do not invent samples."
}
Push-Location (Join-Path $root "fintrust_backend")
try{
  python -m unittest discover -s tests -p "test_financial_ml_round8_human_supervised.py" -v
  Require-Success "Round8 human-label classifier synthetic acceptance"
  if($ScoreCase){
      $modelDir=Join-Path $ml "round8_supervised_eval"
      $originalDb=Join-Path $ml "round7_original_1785_verified_db\\original_1785_research.sqlite3"
      $resultDir=Join-Path $ml "round8_blind_1785_original_case"
      if(-not (Test-Path -LiteralPath $originalDb)){
        throw "Original FY2013-15 1785 PDF amounts must first be independently double-reviewed."
      }
      python -m research.financial_ml.round8_human_supervised_classifier score-case `
          --original-review-db $originalDb `
          --approved-model-dir $modelDir `
          --out $resultDir
      Require-Success "Frozen approved classifier independently scores 1785 original amounts"
      Write-Host "Case scores: $(Join-Path $resultDir 'round8_1785_original_blind_case_scores.json')"
  }elseif($Train){
      $dest=Join-Path $ml "round8_supervised_eval"
      if(Test-Path -LiteralPath $dest){
          throw "Existing evaluation is immutable. Archive review it before any new approved-label round."
      }
      python -m research.financial_ml.round8_human_supervised_classifier train `
          --approved-panel $panel `
          --evidence-root $evidence `
          --out $dest
      Require-Success "Round8 approved original supervised train-or-research-gate"
      $report=Join-Path $dest "round8_supervised_classification_report.json"
      Write-Host "Model / label evidence report: $report"
      $json=Get-Content -Raw -Encoding UTF8 -LiteralPath $report | ConvertFrom-Json
      $json | Select-Object status,selected_model,real_supervised_accuracy,
        real_supervised_precision,real_supervised_recall,real_supervised_f1,
        real_supervised_pr_auc | Format-List
  }else{
      if(Test-Path -LiteralPath $labels){
          throw "Existing human label review packet is immutable. Preserve reviewer work."
      }
      python -m research.financial_ml.round8_human_supervised_classifier prepare `
          --annual-index $input `
          --out $labels
      Require-Success "Round8 human-review queue"
      Write-Host "Proposed UNKNOWN review queue: $(Join-Path $labels 'round8_human_label_review_queue.csv')"
      Write-Host "Separate APPROVED first-original supervised template: $(Join-Path $labels 'round8_approved_original_supervised_panel_TEMPLATE.csv')"
      Write-Host "Only after independent evidence review create:"
      Write-Host "  $panel"
      Write-Host "Evidence bytes root:"
      Write-Host "  $evidence"
      Write-Host "Then rerun with -Train (unapproved or too-sparse labels must not claim F1)."
  }
}
finally{Pop-Location}
