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