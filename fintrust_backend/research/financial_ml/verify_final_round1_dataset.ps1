# Finalization Round1: ONE offline Windows verification.
# Use frozen local data from Phases 4/10/12/13/14, no HTTP, no ML fit,
# no production database writes, and no 1785 final-holdout access.
param([switch]$FullRegression)
$ErrorActionPreference="Stop"

function Assert-LastExit([string]$step) {
    if ($LASTEXITCODE -ne 0) { throw "$step failed (exit code: $LASTEXITCODE)" }
}

$root=(git rev-parse --show-toplevel).Trim()
Assert-LastExit "Git root"
if (-not $root.EndsWith("Financial-Risk-Alert-System-ML")) {
    throw "Run only from the separate Financial-Risk-Alert-System-ML worktree."
}

Write-Host "Round1: focused source-linked dataset integration regression (add -FullRegression for previously passed suites)"
python -m unittest discover -s tests -p "test_financial_ml_final_round1_dataset_integration.py" -v
Assert-LastExit "Round1 seventeen evidence integration tests"

if ($FullRegression) {
Write-Host "Round1: Phase4 company/time & original paper feature provenance"
python -m unittest discover -s tests -p "test_financial_ml_phase4_taiwan_dataset_gate.py" -v
Assert-LastExit "Phase4 issuer/time leakage regression"

Write-Host "Round1: Phase13/14 quarterly source and same-grain regressions"
python -m unittest discover -s tests -p "test_financial_ml_phase13_quarterly_temporal_features.py" -v
Assert-LastExit "Phase13 quarter feature regression"
python -m unittest discover -s tests -p "test_financial_ml_phase14_multiissuer_quarterly_cohort.py" -v
Assert-LastExit "Phase14 12-company source regression"

Write-Host "Round1: original finance candidate sequence and literature regression"
python -m unittest discover -s tests -p "test_financial_ml_provisional_sequence_experiment.py" -v
Assert-LastExit "Annual financial sequence regression"
python -m unittest discover -s tests -p "test_financial_ml_literature_dataset_phase5.py" -v
Assert-LastExit "Beneish/Dechow paper feature formula regression"

}

$main=Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data=Join-Path $main "fintrust_backend\data\financial_ml"
$out=Join-Path $data "final_round1_integrated_ml_dataset"

$expected=@(
    "finmind_scaled_120\finmind_scaled_cohort.csv",
    "finmind_scaled_annual_candidates\finmind_annual_candidate_lines.csv",
    "finmind_scaled_sequence_readiness\company_year_candidate_panel.csv",
    "phase4_taiwan_research_dataset\taiwan_research_split_register.csv",
    "phase14_multiissuer_quarterly_comparison\multiissuer_official_quarter_sources.csv",
    "phase12_kangyou_quarterly_panel\quarterly_case_official_source_index.csv",
    "phase10_case_official_paper_audit\phase10_case_official_paper_features.csv",
    "phase9_case_mops_xbrl_candidates\acquisition_results.json",
    "phase13_kangyou_quarterly_temporal_features\quarterly_twd_source_observations.csv"
)
foreach ($relative in $expected) {
    $found=Join-Path $data $relative
    if (-not (Test-Path -LiteralPath $found -PathType Leaf)) {
        throw "Missing real previously-generated source: $found"
    }
}

Write-Host "Round1: verify 120x13 annual candidates, 15 paper columns and all cached quarterly raw SHAs"
python -m research.financial_ml.final_round1_dataset_integration --data-root $data --output $out
Assert-LastExit "Round1 actual source-linked financial panel construction"

$reportPath=Join-Path $out "round1_dataset_readiness_report.json"
$r=Get-Content $reportPath -Raw -Encoding UTF8 | ConvertFrom-Json
Write-Host ""
Write-Host "===== FINALIZATION ROUND1 REAL DATA QA ====="
$r | Select-Object status,
    cohort_120_current_listed_issuers,
    annual_12_amount_candidate_company_years,
    annual_12_amount_full_12_company_years,
    annual_paper_15_source_tier_rows,
    development_case_annual_source_years_separate_from_noncase_fit,
    development_case_annual_official_XBRL_source_years,
    three_year_history_complete_12_amount_windows,
    three_year_history_fit_issuer_and_time_disjoint_complete_candidates,
    quarter_issuer_period_source_rows,
    quarter_research_issuer_count,
    quarter_comparison_source_period_validated,
    quarter_known_case_source_period_validated,
    quarter_sparse_comparison_company_quarters,
    quarter_fit_only_selected_exact_concept_grain_features,
    quarter_sparse_observed_selected_feature_cells,
    approved_positive_labels,approved_negative_labels,
    fraud_supervised_training_rows_admitted,
    last_event_holdout_1785_excluded,network_requests,production_db_writes | Format-List
Write-Host "Annual strict company+target-year split:"
$r.annual_12_amount_strict_issuer_and_target_year_split | Format-List
Write-Host "15 original Beneish/Dechow paper candidates by evidence source:"
$r.annual_paper_15_source_tiers | Format-List
Write-Host "Validated/missing official company-quarter statuses:"
$r.quarter_sources_by_role_and_status | Format-List
Write-Host "New outputs: quarterly_sparse_feature_matrix.csv and quarterly_fit_selected_feature_dictionary.csv"
Write-Host "Report to share: $reportPath"
Write-Host "Do not report account/quarter fact counts as independent training sample counts."
