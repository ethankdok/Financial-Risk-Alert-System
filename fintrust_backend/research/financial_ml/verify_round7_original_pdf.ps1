# 1785 original FY2013–15 scanned PDFs from existing archived FULL ZIP.
# Run in dedicated Financial-Risk-Alert-System-ML worktree with ml-env active.
param([switch]$Finalize)
$ErrorActionPreference="Stop"
function AssertExit($context){if($LASTEXITCODE -ne 0){throw "$context failed (exit $LASTEXITCODE)"}}
$root=(git rev-parse --show-toplevel).Trim();AssertExit "git root"
if(-not $root.EndsWith("Financial-Risk-Alert-System-ML")){throw "Use dedicated ML worktree."}
$branch=(git branch --show-current).Trim()
if($branch -notin @(
    "feature/financial-ml-round7-original-pdf-ingestion-20261020",
    "feature/financial-ml-round8-human-supervised-20261020"
)){throw "Wrong branch for original PDF review"}
$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data"
$full=Join-Path $data "historical_audit\packages\fintrust_1785_2011_2016_full.zip"
$strict=Join-Path $data "historical_audit\packages\fintrust_1785_asof_2016-11-14.zip"
$review=Join-Path $data "financial_ml\round7_original_1785_pdf_review"
$verified=Join-Path $data "financial_ml\round7_original_1785_verified_db"
foreach($f in @($full,$strict)){if(-not (Test-Path -LiteralPath $f)){throw "Archived real PDF ZIP missing: $f"}}
Push-Location (Join-Path $root "fintrust_backend")
try{
    python -m unittest discover -s tests -p test_financial_ml_round7_original_pdf_review.py -v
    AssertExit "Round7 unit test"
    if($Finalize){
        if(-not (Test-Path -LiteralPath (Join-Path $review "original_review_A.csv"))){
            throw "Round7 prepare and manual A/B review required first"
        }
        python -m research.financial_ml.round7_original_pdf_review finalize `
          --review-dir $review --strict-zip $strict --out $verified
        AssertExit "Real original PDF double-review SQLite ingestion"
        Write-Host "Verified research database: $(Join-Path $verified 'original_1785_research.sqlite3')"
        Write-Host "Read audit: $(Join-Path $verified 'original_1785_ingestion_report.json')"
    }else{
        python -m research.financial_ml.round7_original_pdf_review prepare `
          --full-zip $full --out $review
        AssertExit "Real archived original 1785 AI1 PDF verification/render"
        Write-Host "Images: $(Join-Path $review 'pages')"
        Write-Host "Reviewer A: $(Join-Path $review 'original_review_A.csv')"
        Write-Host "Reviewer B: $(Join-Path $review 'original_review_B.csv')"
        Write-Host "Complete 36 field entries from the ORIGINAL rendered PDF; leave uncertain amounts blank."
        Write-Host "Then rerun this same script with -Finalize after independent reviews."
    }
}
finally{Pop-Location}
