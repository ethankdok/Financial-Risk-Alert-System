# Phase 5C diagnostic — repeated paper-feature anomaly models

This is a bounded research experiment, **not** a production pipeline, continuous online learning, a new fraud label, a calibrated Taiwan probability or proof that multiple fits improve accuracy. Latest user requirement clarifies that "10+ rounds" means **enough repeatable optimization/comparisons**, not 10 as a fixed cap; tree count, neural-network epoch, repeated randomized fits and new data volume are distinct.

## Data contract
- Input: `literature_15_features.csv` from `literature_dataset.py`: 8 Beneish (1999) and 7 Dechow et al. (2011) Model 1 components, never the 15 generic pilot ratios.
- At present only FY2013–2015 TIFRS consolidated source candidates; label must remain `UNREVIEWED`; archived filings are retrospective and vintage not verified.
- No `1785` in model fitting, tuning, calibration, or data selection.
- Training-only: feature selection (missing/constant), median imputation, RobustScaler. Unknown issuance is never converted to a *factually observed zero* (any imputation is model-internal, unverified; near-constant issue is excluded at current coverage).
- Always inspect current `literature_coverage.json`, especially `b_TATA`, `d_rsst_acc`, `d_issue`, `b_LVGI`. No model can fix absent fact evidence.

## Run
From a clean separate ML worktree containing this branch (`fintrust_backend`, `ml-env`):

```powershell
$original = "C:\Users\samue\Documents\GitHub\Financial-Risk-Alert-System\fintrust_backend"
$data = Join-Path $original "data\financial_ml\literature_phase5a\literature_15_features.csv"
python -m unittest discover -s tests -p "test_financial_ml_iterative_literature_benchmark.py" -v
python -m research.financial_ml.iterative_literature_benchmark --dataset $data --output (Join-Path $original "data\financial_ml\iterative_phase5_temporal") --rounds 10 --split temporal
python -m research.financial_ml.iterative_literature_benchmark --dataset $data --output (Join-Path $original "data\financial_ml\iterative_phase5_disjoint") --rounds 10 --split company_disjoint
```

This repeats four prespecified models under random subsampling/seeds: Isolation Forest 200 and 400 trees, novelty LOF and an MLP reconstruction model. The ensemble averages **validation-anchored score percentiles**, not raw incomparable scores. In addition, run company-disjoint diagnostics. All holdout scores are descriptive only and are not tuned against an anomaly outcome.

Artifacts: `experiment_report.json`, `model_round_comparison.csv`, `holdout_model_scores.csv`, `literature_feature_sensitivity.csv`, seed-0 model files in `models/`. Other model fits contribute reproducible seed-based score records; these are not successive incremental training checkpoints.

## Model selection research plan
1. Unlabeled (now): Isolation Forest / LOF / AE; evaluate multi-seed robustness, temporal and firm-disjoint instability, convergence, feature sensitivity. No ranking as "best fraud detector".
2. Optional large-sample **unsupervised** tabular reconstruction (once hundreds/thousands of firm-years exist): Random Forest or gradient-boosted model predicts each paper component from the others; out-of-fold reconstruction residual is anomaly score. This is not supervised fraud classification.
3. **Independently labeled outcomes**: RF / XGBoost / CatBoost are important tabular supervised controls; compare PR-AUC, ROC-AUC, recall at a fixed alert budget, time/firm split and calibrated probabilities. A negative must be evidence-backed, not merely the absence of an enforcement notice.
4. Transformer: test only after sufficient multi-year sequences or external tabular pretraining and out-of-time baselines; investigate capacity vs sample.
5. GNN: require verified supplier/customer/ownership/transaction edges and temporal graph construction; no fabricated edges from similarity alone.
6. Compare feature influence correctly: current column-permutation score delta is **model sensitivity to perturbation**, not fraud prediction importance; with independent labels evaluate SHAP, out-of-sample permutation importance and correlated-feature groups.
7. Combine models only after checking scales, dependence, false positive stability and ideally labeled outcomes. Keep 1785 entirely untouched until frozen model assessment.

## Current state
2026-10-18 received 64 firm-years/22 firms, only 11 complete 15-feature rows. This script is a bounded training demonstration, **not** an answer to insufficient sample size. Primary next-stage effort remains scaling nonfinancial TWSE/TPEx financial statements, fixing financial variable evidence and historical panel semantics, then retraining and evaluating on expanded data. Existing MOPS SHA-256 archive, extraction, literature calculators and FinMind staging should be reused, not replaced.

Documentation also in `docs/research/FINANCIAL_ML_PHASE5_REQUIREMENTS_2026-10-18.md`.
