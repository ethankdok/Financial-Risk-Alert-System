# Single local integrated Phase3 verification. Research-only.
param()

$ErrorActionPreference = "Stop"
function Check-Exit([string]$stage) {
    if ($LASTEXITCODE -ne 0) { throw "$stage failed (exit $LASTEXITCODE)" }
}
$root=(git rev-parse --show-toplevel).Trim()
Check-Exit "git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Only allowed in the dedicated Financial-Risk-Alert-System-ML worktree"
}
Write-Host "Phase3: bridge and original paper model regression tests"
python -m unittest discover -s tests -p "test_financial_ml_phase3_literature_bridge.py" -v
Check-Exit "Phase3 bridge tests"
python -m unittest discover -s tests -p "test_financial_ml_literature_dataset_phase5.py" -v
Check-Exit "Original 15-feature engine regression"
python -m unittest discover -s tests -p "test_literature_models.py" -v
Check-Exit "Published formula regression"
python -m unittest discover -s tests -p "test_literature_data_integrity.py" -v
Check-Exit "Source identity regression"
python -m unittest discover -s tests -p "test_financial_ml_phase12_integrated_gate.py" -v
Check-Exit "Phase2 integrity regression"

$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$out=Join-Path $data "phase3_literature_integrated"
Write-Host "Phase3: 120 issuers, 24 base inputs, 15-paper feasibility and official XBRL"
python -m research.financial_ml.phase3_literature_bridge --data-root $data --output $out --start-year 2013 --end-year 2025
Check-Exit "Phase3 integrated data stage"

$r=Get-Content (Join-Path $out "phase3_integrated_report.json") -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "===== PHASE3 INTEGRATED REPORT ====="
$r | Select-Object status,cohort_company_count,company_years,literature_base_metrics,paper_features,account_evidence_rows,component_feasibility_rows,finmind_training_15_feature_rows_admitted,supervised_training_labels_created,reserve_1785_untouched | Format-List
$r.official_xbrl_feature_report | Select-Object status,company_year_rows,companies,fully_computed_15_rows,full_beneish8_rows,full_dechow7_rows | Format-List
$r.official_crosscheck_review | Format-List
Write-Host "Report: $(Join-Path $out 'phase3_integrated_report.json')"
Write-Host "If tests fail, retain console output; no re-download required."
