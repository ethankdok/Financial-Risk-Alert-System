# Phase 4B: unreviewed-source exploratory anomaly model diagnostic

This is explicitly a **pipeline smoke test**, not a real normal-only anomaly detector, a fraud classifier, or an ex-ante backtest. It fits an Isolation Forest on **2013 exploratory/unreviewed observations** and produces **2014 diagnostic** and **2015 untouched ranking** reports. It does not create normal labels, calibrated cutoffs, predicted fraud flags, or evaluation accuracy/F1.

## Purpose and limitations

- Company-year = observation. 2013: 11 observations (fit), 2014: 10 (diagnostic), 2015: 11 (untouched scoring). **Only 11 companies; time windows share issuer identities.**
- Choose seven fully populated contemporaneous financial ratios. Do not use seven prior-year-growth features because all 2013 values are missing. Exclude `cogs_sales_ratio` because it is algebraically redundant with `gross_margin`.
- If an input includes 1785, out-of-scope years, duplicate company-years, missing/invalid model features or labels, fail hard.
- Use RobustScaler fitted only to 2013 rows; train IsolationForest over 12 seeds. Report mean and standard deviation of score/rank and mean pairwise Spearman across seeds.
- **Do not claim the ranked issuers are anomalous/fraudulent**. Stable ranks demonstrate deterministic robustness in this small configuration, not validity. With 11 fit rows and no reviewed normals, the model has no usable false positive rate or threshold.
- Does not modify production database, official archives, cloud stores, or Git working tree.
- Existing `dataset_readiness_gate.json` correctly says **`blocked_not_training_ready`** and is not overridden by this experiment.

## Run inside the independent ML Git worktree

```powershell
python -m research.financial_ml.exploratory_temporal `
  --dataset "C:\Users\samue\Documents\GitHub\Financial-Risk-Alert-System\fintrust_backend\data\financial_ml\industry_pilot_v2\financial_ml_pilot.csv" `
  --output "C:\Users\samue\Documents\GitHub\Financial-Risk-Alert-System\fintrust_backend\data\financial_ml\exploratory_phase4b"
```

Offline tests: `python -m unittest discover -s tests -p "test_exploratory_temporal.py" -v`.

## Before a publishable model

1. Increase historical company-year cohort to include true historical constituents and delisted entities; validate original filing date, revisions and as-of availability.
2. Create normal-reference review ledger from independently verifiable regulatory evidence with adequate follow-up (absence of recorded scandal != proven normal).
3. Train through independent company-/time-based splits and calibrate the cutoff only on reviewed validation normals.
4. Reserve 1785 in a separate holdout dataset, never used for preprocessing/hyperparameters or threshold.
5. For model evaluation, build independently labeled positive/negative test cases and compare against statistical/Beneish/Dechow baselines.