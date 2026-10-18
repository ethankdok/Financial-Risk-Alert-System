# Phase 4C — One-shot financial ML baselines

This is intentionally a **single research run**, not a scheduler, continuous-learning architecture, normal-labeling workflow, or production deployment.

## Run from the ML worktree fintrust_backend
```powershell
$mainRoot = Join-Path (Split-Path (git rev-parse --show-toplevel).Trim() -Parent) "Financial-Risk-Alert-System"
$dataset = Join-Path $mainRoot "fintrust_backend\data\financial_ml\industry_pilot_v3\financial_ml_pilot.csv"
$output = Join-Path $mainRoot "fintrust_backend\data\financial_ml\one_shot_64"
python -m research.financial_ml.one_shot_train --dataset $dataset --output $output
```

**Eight fixed experiments**: three Isolation Forest configurations, two LOF novelty detectors, two MLP reconstruction configurations and an independent-company Isolation Forest robustness diagnostic. The seven directly comparable configurations use 2013 fit / 2014 diagnostic validation / 2015 one-time scoring, with seven available financial ratios. The eighth separates companies between its own training/validation/score groups. Produces eight joblib model artifacts, per-model comparison and 2015 score CSVs.

**Critical limitations:** raw candidate observations are UNREVIEWED, not certified normal; 2013–15 filings are retrospective with unknown original publication vintage; same issuers recur in time split; model test labels are absent, so score/rank differences must never be advertised as abnormality detection accuracy or evidence of fraud. Deep model convergence is recorded per configuration. The reserved 1785 case is excluded entirely.

To expand training, collect 2013–2025 issuer-financial records and align annual fiscal periods, units, taxonomy and historical company membership. FinMind provides income/balance/cash-flow datasets as an optional non-commercial research data source, but their raw records **are not** automatically interchangeable with MOPS XBRL and require independent source reconciliation.

Tests: `python -m unittest discover -s tests -p 'test_financial_ml_one_shot_train.py' -v`.
