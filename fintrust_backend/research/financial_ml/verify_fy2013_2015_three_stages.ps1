# FinTrust FY2013-2015 ONLY — three stages, one stable branch.
# Existing FY2016-2025 annual numeric research is READ only as Round1 source,
# then FILTERED to FY2013-2015 BEFORE feature/label/model outputs.
param([ValidateSet("Prepare","Approve","Train")][string]$Stage="Prepare")
$ErrorActionPreference="Stop"
function Check([string]$context){if($LASTEXITCODE -ne 0){throw "$context failed ($LASTEXITCODE)"}}
$root=(git rev-parse --show-toplevel).Trim();Check "Git worktree"
if(-not $root.EndsWith("Financial-Risk-Alert-System-ML")){
    throw "Run in independent Financial-Risk-Alert-System-ML worktree."
}
$branch=(git branch --show-current).Trim();Check "git branch"
if($branch -ne "feature/financial-ml-fy2013-2015-three-stage-20261020"){
    throw "Wrong branch. Only FY2013-2015 features are supported here."
}
$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$ml=Join-Path $main "fintrust_backend\data\financial_ml"
$index=Join-Path $ml "final_round1_integrated_ml_dataset\annual_12_amount_candidate_index.csv"
$work=Join-Path $ml "fy2013_2015_three_stage_research"
$first=Join-Path $work "stage1_data"
$second=Join-Path $work "stage2_review"
$approved=Join-Path $work "stage2_approved"
$third=Join-Path $work "stage3_model"
$source=Join-Path $first "fy2013_2015_exact_360_financial_source_audit.csv"
# The original review queue is immutable for reproducibility. When reviewing,
# write a NEW file, do not modify the generated blank template.
$filled=Join-Path $second "fy2013_15_360_manual_0_1_review_FILLED.csv"
$evidence=Join-Path $work "original_official_evidence"
$approvedcsv=Join-Path $approved "fy2013_15_approved_original_0_1.csv"
$gate=Join-Path $approved "fy2013_15_stage2_label_gate.json"
Push-Location (Join-Path $root "fintrust_backend")
try{
    Write-Host "Strict FY2013-15 model source, label and holdout regression."
    python -m unittest discover -s tests -p test_financial_ml_fy2013_2015_three_stages.py -v
    Check "Three stage research regression"
    if($Stage -eq "Prepare"){
        if(-not(Test-Path -LiteralPath $index)){throw "Missing original cleaned Round1 index: $index"}
        if(Test-Path -LiteralPath $first){throw "Stage1 already exists: do not overwrite."}
        python -m research.financial_ml.fy2013_2015_stage1_freeze `
            --round1-annual-index $index --out $first
        Check "FY2013-15 clean cohort 360"
        python -m research.financial_ml.fy2013_2015_stage2_labels prepare `
            --stage1-csv $source --out $second
        Check "FY2013-15 review queue creation"
        Write-Host "REVIEW THIS: $(Join-Path $second 'fy2013_15_360_manual_0_1_review_QUEUE.csv')"
        Write-Host "All numeric provisional sources are research-only, not original-verified inputs."
    }elseif($Stage -eq "Approve"){
        if(-not(Test-Path -LiteralPath $filled)){
            throw "No independently reviewed 360-row FY2013-15 CSV: $filled"
        }
        if(-not(Test-Path -LiteralPath $evidence)){
            throw "No official archived PDF, original notice, correction/search evidence folder: $evidence"
        }
        python -m research.financial_ml.fy2013_2015_stage2_labels approve `
            --review-queue $filled `
            --official-evidence-root $evidence --out $approved
        Check "Double-review and official evidence hashes"
        Write-Host "Approved label gate: $gate"
    }else{
        if(-not(Test-Path -LiteralPath $approvedcsv) -or
           -not(Test-Path -LiteralPath $gate)){
            throw "No dual-approved official original FY2013-15 0/1 rows. Cannot truthfully train."
        }
        python -m research.financial_ml.fy2013_2015_stage3_supervised `
            --approved-csv $approvedcsv `
            --label-gate $gate --out $third
        Check "Company-heldout FY2013-15 classifier"
        $report=Join-Path $third "fy2013_15_supervised_study_report.json"
        $result=Get-Content -Raw -Encoding UTF8 -LiteralPath $report|ConvertFrom-Json
        $result | Select-Object status,approved_0,approved_1,test_precision,
            test_recall,test_f1,test_pr_auc | Format-List
        if($result.status -ne "FY1315_APPROVED_0_1_SUPERVISED_MODEL_EVALUATED"){
            Write-Host "No real supervised F1. Review source/evidence counts; NEVER fill synthetic values."
        }
    }
}
finally{Pop-Location}
