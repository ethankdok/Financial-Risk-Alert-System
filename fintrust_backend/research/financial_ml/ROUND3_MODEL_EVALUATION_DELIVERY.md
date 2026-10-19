# FinTrust ML Round 3 — actual numeric and unlabeled evaluation (2026-10-20)

Branch `feature/financial-ml-round3-model-evaluation-20261020`, based on the
user-validated Round2 source-checking bridge, **not** a new XBRL crawler.

## What is developed vs what cannot be claimed

**Round2 user acceptance:** 12/12 focused tests passed, nine frozen source
SHAs verified, four stored legal-case HTML bytes checked against SHA and local
receipts, 163 review candidates preserved, zero network or production DB
writes. The Round2 report explicitly states that **zero original-first-public
historical financial statements** and **zero true positive / reviewed-normal
periods** have been certified. Therefore Round3 cannot infer actual financial
misstatement labels from those sources.

**Round3 developed model runs (real metrics only after running on actual data):**

| Track | Models | Measurable metrics | NOT allowed to claim |
|---|---|---|---|
| FY next-year 12 FinMind amount fields (3-year history) | Last-year persistence; Ridge; Random Forest; MLP; CatBoost (if installed); GRU/LSTM/TCN/Transformer (if PyTorch installed) | Fit/validation/holdout window counts, scaled MSE/MAE/RMSE/R2, signed-log MAE, TWD MAE and sMAPE if numerically finite, per-field errors, validation-selected model | Fraud accuracy, F1, class recall, true early detection |
| Strict issuer **and** target-year disjoint FY numeric proxy | Persistence; Ridge; Random Forest | Exactly the same numeric evaluation on the intersecting joint split, *if* at least 30 fit, 5 validation, 5 untouched test windows; else reason and no fabricated statistics | Supervised case classification or independently certified historical account origins |
| 24 exact-concept/grain source-linked historical MOPS quarter candidates | Isolation Forest; LOF (novelty); One-Class SVM; PCA reconstruction | Fit-set 95th percentile score threshold, validation/test anomaly fraction above fit p95, KS distance, JSD distribution divergence, strict company+quarter-time sample and issuer counts | Precision, fraud recall, false positive rate, fraud probabilities |

True published Beneish (1999) 8 / Dechow et al. (2011) 7 feature values
remain separate; only **11 retrospective official FY source-tiers**
have all 15, with 0 original-as-first-public vintages. It is scientifically
invalid to present that as a 15-feature genuine Taiwanese fraud training set.
The previous original literature engines remain in place, unmodified.

## Methodology / split and data-leakage controls

- Annual temporal numeric regression:
  training target FY2016–2020; validation FY2021–2022; one-time
  holdout FY2023–2025. Models fit on the **same companies** across
  years, so those numbers measure temporal numeric generalization,
  not independent-issuer generalization. A second **separate**
  issuer-disjoint/time-disjoint baseline transparently reports whether
  enough fully observed windows remain.
- Annual 3-year historical x, next FY target y. All 12 target
  financial values required; missing rows are excluded and never
  assumed zero. Scaling uses only training rows, their historical
  windows and training numeric targets. No validation/test fit to scaler.
- Model selection exclusively by FY2021–2022
  `validation_signed_log_mae`, not by 2023–2025 holdout. True
  0/1 fraud label fields remain UNKNOWN throughout.
- Quarterly feature dictionary exactly the accepted Round1 24
  exact-concept + temporal-grain features, selected on fitting data
  only. Preserve explicit observed-mask (financial zero is observed,
  missing is not zero). Fit-only medians/scaler. Only validated
  current-archive XBRL sources admitted into these **unlabeled**
  learning algorithms.
- Quarterly combined `joint_strict_split` must match the existing
  SHA issuer and historical quarter boundaries. A non-fit company
  cannot enter fitting or threshold computation. No case ticker 1785,
  3027, 8299, 6452 allowed in comparison samples.
- Dataset transfer manifest from Round2, nine earlier source hashes
  and release gates are immutable. Fail closed if permissions
  suddenly claim fraud supervised learning is approved.

The actual number of complete strict joint windows may be small:
this is a **scientific limitation**, not a reason to silently relax
the sampling protocol.

## Outputs (no fake numbers)

Under `fintrust_backend/data/financial_ml/round3_real_model_evaluation/`:

1. `round3_real_data_model_report.json` — machine-readable complete
   provenance, sample counts, actual regression metrics, quarterly
   unsupervised comparisons and intentionally null fraud labels/metrics.
2. `annual_numeric_prediction_model_metrics.csv` — nine requested
   architectures, status and observed numeric errors (optional packages
   absent = unavailable, not zero or fabricated).
3. `annual_numeric_prediction_per_financial_field.csv` — 12 distinct
   financial targets × each fitted model × validation/test.
4. `annual_strict_joint_split_numeric_baseline.csv` — generated **only
   if** the strict joint issuer+time count criteria pass.
5. `quarter_unlabeled_model_comparison.csv` — four anomaly/novelty
   methods, numeric fit/validation/test drift and threshold proportions.
6. `quarter_unlabeled_validation_test_scores.csv` — individual
   held-out quarter proxy score/flag, still UNKNOWN fraud label.
7. `annual_checkpoints/` — training-only scaler, and algorithm-specific
   model artifacts; no production deployment.

**No model's MSE can be relabeled as misstatement  accuracy.** Fraud
Precision/Recall/F1/PR-AUC/ROC-AUC/confusion matrix fields are JSON `null`
rather than 0. A zero would incorrectly imply measured performance.

## One real-data verification

While located in the existing independent
`Financial-Risk-Alert-System-ML\fintrust_backend` worktree, with
the existing `ml-env` active and clean tracked files:

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-round3-model-evaluation-20261020
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round3_real_models.ps1
```

If the local branch already exists, use `git switch feature/financial-ml-round3-model-evaluation-20261020`.
Do not `cd fintrust_backend` again if you are already there.
Do not rerun Round1/Round2, rewrite first-source archives,
delete/recompute the accepted prior reports, or unlock 1785.

On missing optional ML libraries, the model is explicitly marked as
`OPTIONAL_DEPENDENCY_UNAVAILABLE` or `DEPENDENCY_NOT_INSTALLED`.
To run all nine families in your env, make sure `catboost` and
`torch` are installed. Sklearn/numpy/joblib are needed. No external
network calls are made by the experiment itself.

The command prints model scores directly and writes JSON/CSVs, leaving
real-data validation as the **only remaining software acceptance step**.
Upload just:
`round3_real_model_evaluation/round3_real_data_model_report.json`
and the terminal exception if any, then compare actual model scores,
validate sample-size and source-level interpretation before Round4.

Research blocker *after software QA*:
A genuine Taiwanese fraud classifier and its real
F1/PR-AUC require independently reviewed positive/negative company
report-period labels, original first-filing versions and publication
timestamps, explicit label-availability dates, well-sized unaffected
company test sets and the original-15 published feature coverage.
No software-only workaround can certify those facts.

## CI verification

The synthetic CI fixture reconstructs the accepted topology of 535
complete provisional annual rows and 399 complete 3-year-plus-target
windows, plus 144 quarter positions and exactly 2,232 observed source
cells across 24 candidate features. It exercises real sklearn fitting,
frozen hash manifests, zero-valued observed account facts, time splits
and UNKNOWN fraud outputs. It uses artificial numbers solely for
**software tests**, never reports them as real Taiwan model performance.

GitHub Actions: https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39294234789 .

## Final synthetic CI / debug checkpoint

The final targeted
[GitHub Actions Round3 run](https://github.com/ethankdok/Financial-Risk-Alert-System/actions/runs/39295169950)
reported **9/9 PASS** on synthetic topology. Earlier defects found and
repaired during CI: optional `httpx` leaked from the MOPS downloader
module import into numeric-only evaluation; synthetic test dictionary
omitted the real `candidate_source_tier`; full selected-feature
missingness needed to match the accepted 2,232 observed facts; the
already-frozen 2019Q3 quarter timing was confirmed and retained.
All those changes are committed to the same feature branch.

This result verifies executable model output formatting and intended
safety/partition checks. **It is not actual Taiwan model performance**.
Only the one real-data Windows command above produces those scores.

## 2019Q3 real-run bug and safe rerun

The user's real run passed nine tests but stopped when checking the quarterly time split. Round1 assigns 2019Q3 to validation (inclusive) and 2019Q4 to test. Round3 had used the exclusive 2019Q3 cutoff. The code now uses the original inclusive cutoff and a targeted boundary regression; it keeps the source SHA and group/period leakage checks unchanged. The PowerShell runner preserves any partial annual artifacts left by the failing run and chooses an unused retry folder, rather than deleting or overwriting them. Fetch the latest commit and run the existing verify_round3_real_models.ps1 command again, then upload the JSON report from the printed retry folder. The supervised-fraud metrics remain unavailable without verified labels.
