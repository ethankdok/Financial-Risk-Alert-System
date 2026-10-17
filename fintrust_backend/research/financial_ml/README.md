# Financial ML: safe offline pilot (research only)

This first-stage pilot **does not invent labels, compute Beneish/Dechow from proxy inputs, fit a Transformer, change production databases, or claim pre-event predictive accuracy**. It converts an existing `historical_audit_case export` CSV to a version-audited company–fiscal-year dataset with 11 registry-compatible descriptive features and 4 exploratory ones. It can optionally train a **supervised Logistic Regression baseline** only after verified labels, sufficient samples, and chronological train/test partitions are supplied.

## Run from `fintrust_backend/` in VS Code

Export an already registered historical case from your existing isolated SQLite research archive (database must exist and contain data):

```powershell
python -m scripts.historical_audit_case export --ticker 1785 --start-year 2013 --end-year 2015 --version-policy all --format csv --output data/1785_research_export.csv
```

Build a **retrospective** pilot (cannot be interpreted as ex-ante warning):

```powershell
python -m research.financial_ml.pilot --csv data/1785_research_export.csv --mode retrospective --output data/financial_ml/pilot
```

For multiple researched companies, repeat `--csv` with previously exported datasets. The historical case exporter itself requires a reviewed case registration: it is **not** an unrestricted all-industry downloader.

For a strict point-in-time pilot, supply a reviewed cutoff ledger with columns `ticker,fiscal_year,cutoff_at`, with e.g. an ISO-8601 instant including `+08:00`, and run `--mode strict --cutoffs ...`. The builder admits only **original filings** whose individually verifiable availability precedes the cutoff. In the currently documented 1785 archive this may yield **zero eligible rows**, which is a valid blocker rather than a reason to backfill future filings.

Optional **independently established labels** must use this CSV schema:

```csv
ticker,fiscal_year,label,label_source,outcome_known_at
```

Labels must be `0` or `1`, source evidence must be nonempty, and outcome-known timestamps must include timezone. **No sample labels are supplied.** Control-company absence of an enforcement notice is not sufficient to call it confirmed normal; the label protocol must explicitly define controls, observation horizon and censoring.

When enough defensible labeled data exist:

```powershell
python -m research.financial_ml.train_baseline --dataset data/financial_ml/pilot/financial_ml_pilot.csv --output data/financial_ml/pilot/baseline --train-through 2014 --test-from 2015 --label-known-by 2016-01-01T00:00:00+08:00 --exclude-ticker 1785
```

Baseline dependencies: `scikit-learn` (plus its standard numerical dependencies). Training refuses insufficient samples, single-class folds, or train/test time overlap. `label-known-by` applies only to training labels; research protocols should also verify exposure dates and outcome censoring on both partitions. Hyperparameters and threshold are fixed in this first version; no test-set tuning.

## Dataset guarantees & current limitations

- 1 row per **unambiguous** company × fiscal year × consolidated annual filing version. If multiple filing versions exist, the entire company-year is withheld for manual review; versions are never silently mixed.
- Sources with mismatched accounting framework, scope, currency, invalid decimal values, test fixtures, or invalid source validation are rejected and counted in `financial_ml_readiness.json`.
- Cross-year ratios use prior-year data **only if it is independently selected and from the same accounting framework**; no TW-GAAP/TIFRS mixing.
- Strict mode requires explicit per-company/year cutoffs, original version, and proven row availability. Retrospective mode is distinctly flagged and is for engineering/forensics only.
- The 11 features matching the descriptive `financial_research/feature_registry.py` are calculated directly from canonical facts, not substituted for the **different** Beneish/Dechow literature variables. Additional exploratory features: `revenue_yoy`, `inventory_yoy`, `receivables_yoy`, `cashflow_assets_ratio`.
- For original source facts, the historical export must be fully populated; this pilot does not download documents or authenticate external events. Training results on any retrospective/revised sources are not evidence of historical prediction.
- The baseline is deliberately only a pipeline smoke test. It does not yet implement grouped time-series validation, confidence intervals, feature selection, PR-AUC-first hyperparameter search, neural networks, LSTM, Transformer, or paper-specific variable enrichment.
- **Do not commit real research datasets, labels containing sensitive evidence, downloaded financial documents, or trained checkpoints without an explicit data publication review.** Put outputs under ignored local `data/` directories.

## Phase 2 — Normal-only anomaly research (2026-10-17)

**Research hypothesis:** establish a robust normal-company financial-behavior reference distribution from audited/curated company-year observations; detect outliers including a completely held-out case (`1785`). The core training design is **one-class/unsupervised**, not supervised fraud-vs-nonfraud classification. All companies' XBRL may enter the **candidate pool**, but only explicitly reviewed reference-normal company-years enter normal model fitting. This review is *not* an assertion that no undetected irregularity ever occurred.

### What has been implemented

* Offline CLI `research.financial_ml.source_inventory` checks aggregate table counts, firm counts and year ranges in *existing* local research/production SQLite files using `mode=ro`; does not query Cloud SQL or Firestore or export financial values. Missing local files are not proof that cloud data do not exist.
* Offline CLI `research.financial_ml.anomaly` provides `audit`, `scaffold-ledger`, `train`.
* `scaffold-ledger` emits **`unreviewed`** for all rows; absence of official restatement is never automatically mapped to `reviewed_normal`.
* Reviewed-normal evidence CSV is explicitly provided by the research team after checking the source and observation horizon; fields: `ticker,fiscal_year,review_status,review_source,reviewed_at,followup_through`. Accepted `review_status` values: `reviewed_normal`, `excluded`, `unreviewed`, `suspected`. Training uses *only* `reviewed_normal`, with `followup_through >= Dec 31 of fiscal_year + 2` (configurable). `reviewed_by` prevents use of reviews unknown by an intended historical reconstruction date. The code checks metadata but cannot certify the truth of external evidence.
* Two independent baselines: scikit-learn `IsolationForest` (tree-based) and `MLPRegressor` used as a reconstruction-error neural autoencoder proxy; **neither is a PyTorch Transformer**. Fits median imputation, robust normalization and models on *train normal only*, with validation normal data exclusively setting the threshold (default 95th percentile). Does not use labels or cases in training, preprocessing or threshold calibration.
* Strict chronological train year / normal validation year / future test years, and optional `company_disjoint` hash-group split for firm-level robustness. Independent reserved-case set (`1785`) never fitted or threshold-tuned. Reporting includes cutoff parameters, sample/group counts, selected feature list, case/test score CSVs, false-positive reference threshold and retrospective warnings.
* Accuracy, positive-class F1, PR-AUC are reported only for test data carrying **independent** labels for both classes; no outcome label is invented to make the score look good. F1 targets ≥ 0.95 are aspirational and cannot be evaluated until external labels are verified.
* All data and research outputs remain under ignored `fintrust_backend/data/` and are never automatically pushed to GitHub. Production FastAPI / Flask / Firestore / Cloud SQL / website unchanged.

### Run now (from `fintrust_backend/`; no change of Git branch is needed for read-only inspection)

```powershell
# Requires only Python standard library. Safe on current Python 3.14 / ml-env.
python -m research.financial_ml.source_inventory --output data/financial_ml/local_source_inventory.json
```

If a multi-company `historical_audit_case export` CSV is available, generate a feature pilot first:

```powershell
python -m research.financial_ml.pilot --csv data/1785_research_export.csv --mode retrospective --output data/financial_ml/pilot
python -m research.financial_ml.anomaly audit --dataset data/financial_ml/pilot/financial_ml_pilot.csv --output data/financial_ml/audit
python -m research.financial_ml.anomaly scaffold-ledger --dataset data/financial_ml/pilot/financial_ml_pilot.csv --output data/financial_ml/normal_review_candidates.csv
```

**Do not mark rows normal just to make training run.** `normal_review_candidates.csv` is a review template, not model training labels. Once a multi-firm feature dataset and defensible `reviewed_normal` ledger exist, training is:

```powershell
# Example year windows; alter to match the *actual* multi-company year coverage.
python -m research.financial_ml.anomaly train `
 --dataset data/financial_ml/pilot/financial_ml_pilot.csv `
 --normal-ledger data/financial_ml/reviewed_normal_ledger.csv `
 --train-through 2013 --val-from 2014 --val-through 2014 --test-from 2015 `
 --model isolation_forest --split-policy temporal `
 --reserve-ticker 1785 --output data/financial_ml/experiments/iforest

# Neural reconstruction baseline: add --model mlp_autoencoder and change --output.
# Separately run --split-policy company_disjoint for firm-disjoint robustness.
# For strict as-of evaluation, use `pilot --mode strict --cutoffs ...` and supply
# `anomaly train --reviewed-by <historical ISO timestamp>` with legally reviewable
# normal evidence available by that date; otherwise report is retrospective.
```

Failure to obtain minimum normal training/validation coverage intentionally raises `NORMAL_REFERENCE_INSUFFICIENT`; current `1785`-only database must fail this gate. The first real cohort needs many independent companies and years. `train_through` and `test_from` should be selected *before* test labels or case outcomes are inspected.

### Optional external pretraining — evidence-led plan, **not implemented/trained**

**Best official candidate:** U.S. SEC [Financial Statement Data Sets](https://www.sec.gov/dera/data/financial-statement-data-sets.html) publish as-filed XBRL financial statement numbers from 2009 onward with SIC sector identifiers. They are not ready-made fraud/normal labels and they follow US GAAP, unlike Taiwan TIFRS. Never concatenate raw USD financial values and TWD figures; the adapted features must be currency-invariant ratios with identical accounting definitions.

Before claiming transfer learning: (1) download bounded SEC periods with saved source metadata, and inspect terms/availability; (2) harmonize to documented shared ratios with per-field mapping and fiscal-period semantics; (3) split U.S. **and** Taiwan entities/years before any fit; (4) pretrain a sufficiently regularized neural autoencoder/sequence encoder only on a defensible reference cohort; (5) fine-tune using Taiwan normal training data; (6) compare **Taiwan-only**, **US-only zero-shot** and **US-pretrained + Taiwan fine-tuned** using the same untouched Taiwan validation and test sets, and a separately held-out 1785; (7) ablate each feature group and report domain shift/negative transfer. Isolation Forest is **not** a neural model to fine-tune across domains. No public dataset of normal-only, Taiwan-specific, period-correct financial reports with verified controls has been validated in this stage.

### Implementation limits and review gates

1. Existing `pilot.py` uses **15 exploratory/descriptive** tabular features, NOT the eight authoritative Beneish plus seven Dechow literature variables. The next integration must call the existing source-locked literature engines, preserve `not_computable`, and avoid aliases/proxies masquerading as paper variables.
2. Current local audited historical SQLite reported by user has only 1 company (1785), FY2011–2025; this is *not* enough to train an industry normal distribution. Cloud/other local sources still need to be inventoried.
3. Annual time series of only three years per company do not justify a large sequence Transformer. A future GRU/TCN/Transformer experiment requires sufficient companies, sequence length and leakage-safe holdouts; compare with nonsequence tree and reconstruction baselines.
4. Missing or restated original 1785 statements preclude claiming pre-disclosure prediction. Case scores on post-restatement values have a retrospective-forensics label only.
5. Threshold estimated from a normal validation quantile targets the *empirical* normal false-positive reference rate; it does not guarantee precision, recall, or 95% accuracy. External confirmed anomalies belong to evaluation, never the normal-model fit.