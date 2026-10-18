# Phase5: single offline acceptance for Taiwan paper-feature unsupervised proxy.
param()
$ErrorActionPreference="Stop"
function Confirm-Exit([string]$stage) {
    if ($LASTEXITCODE -ne 0) { throw "$stage failed (exit $LASTEXITCODE)" }
}
$here=(git rev-parse --show-toplevel).Trim()
Confirm-Exit "Git root"
if (-not $here.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Dedicated Financial-Risk-Alert-System-ML worktree required"
}
Write-Host "Phase5: Taiwan paper-feature/finance provenance regression tests"
python -m unittest discover -s tests -p "test_financial_ml_phase5_taiwan_unlabeled_pilot.py" -v
Confirm-Exit "Phase5 model tests"
python -m unittest discover -s tests -p "test_financial_ml_phase4_taiwan_dataset_gate.py" -v
Confirm-Exit "Phase4 split tests"
python -m unittest discover -s tests -p "test_financial_ml_phase3_literature_bridge.py" -v
Confirm-Exit "Phase3 paper formula tests"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Confirm-Exit "Phase1 evidence tests"

$main=Join-Path (Split-Path $here -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$old=Join-Path $data "phase4_taiwan_research_dataset"
$output=Join-Path $data "phase5_taiwan_unlabeled_pilot"
$register=Join-Path $old "taiwan_research_split_register.csv"
$report=Join-Path $old "phase4_dataset_integrated_report.json"
if (-not (Test-Path $register)) { throw "Missing Phase4 register: $register" }
if (-not (Test-Path $report)) { throw "Missing Phase4 audit report: $report" }

Write-Host "Phase5: four separate unlabeled paper-feature model families on Taiwan cohort"
python -m research.financial_ml.phase5_taiwan_unlabeled_pilot --register $register --phase4-report $report --output $output --experimental-allow-unverified-data
Confirm-Exit "Phase5 exploratory machine learning"

$summary=Get-Content (Join-Path $output "phase5_exploratory_report.json") -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "===== PHASE5 PROVISIONAL MODEL REPORT ====="
$summary | Select-Object status,study,model_families,labels_approved,accuracy_recall_pr_auc_f1_reported,uses_frozen_1785,network_requests,production_db_writes | Format-List
$summary.audit | Select-Object status,rows_by_split,issuer_counts,excluded | Format-List
Write-Host "Report: $(Join-Path $output 'phase5_exploratory_report.json')"
if ($summary.status -ne "PROXY_MODEL_FAMILIES_FIT_NOT_FINANCIAL_MISSTATEMENT_DETECTION") {
    Write-Host "Scientific model fitting was blocked by insufficient coverage; this is an EXPECTED data gate, not necessarily a code fault."
}
Write-Host "Never report these unlabeled proxy score flags as validated financial misstatements."
