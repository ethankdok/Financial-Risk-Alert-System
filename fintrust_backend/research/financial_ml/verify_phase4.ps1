# Phase4 once-per-phase integrated offline validation. No FinMind, no model fitting.
param()

$ErrorActionPreference = "Stop"
function Check([string]$stage) {
    if ($LASTEXITCODE -ne 0) { throw "$stage failed (exit $LASTEXITCODE)" }
}
$root=(git rev-parse --show-toplevel).Trim()
Check "Git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Only the separate Financial-Risk-Alert-System-ML research worktree is allowed"
}
Write-Host "Phase4: Taiwan issuer/time/label/as-of split tests"
python -m unittest discover -s tests -p "test_financial_ml_phase4_taiwan_dataset_gate.py" -v
Check "Phase4 split tests"
Write-Host "Phase4: Phase3 paper-feature source regression"
python -m unittest discover -s tests -p "test_financial_ml_phase3_literature_bridge.py" -v
Check "Phase3 bridge regressions"
python -m unittest discover -s tests -p "test_financial_ml_literature_dataset_phase5.py" -v
Check "Existing paper feature tests"
Write-Host "Phase4: Phase1 case and Phase2 source integrity"
python -m unittest discover -s tests -p "test_financial_ml_phase1_*.py" -v
Check "Phase1 case regression"
python -m unittest discover -s tests -p "test_financial_ml_phase12_integrated_gate.py" -v
Check "Phase2 integrity regression"

$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$output=Join-Path $data "phase4_taiwan_research_dataset"
Write-Host "Phase4: build Taiwan-only feature provenance + joint issuer/time split + evidence mismatch diagnostics"
python -m research.financial_ml.phase4_taiwan_dataset_gate --data-root $data --output $output --seed 20261019
Check "Phase4 integrated dataset construction"

$report=Get-Content (Join-Path $output "phase4_dataset_integrated_report.json") -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host "==== PHASE4 RESEARCH DATASET READINESS ===="
$report | Select-Object status,Taiwan_issuer_count,evidence_rows,official_retrospective_rows,
    finmind_candidate_rows,official_paper_15_full_row_count,labels_approved_positive,
    labels_approved_negative,train_val_test_supervised_admitted_rows,
    eligible_for_supervised_financial_fraud_training,
    cross_source_overlap_company_years | Format-List
$report.mops_source_disputes | Format-List
Write-Host "Sequence windows:"
$report.sequence_window_counts | Format-List
Write-Host "Blocked true supervised learning is EXPECTED until labeled historical original reports are verified."
Write-Host "Attach report $(Join-Path $output 'phase4_dataset_integrated_report.json') and discrepancy CSV for unresolved rows."
