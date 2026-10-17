# Phase 3B: current taxonomy → historical candidate coverage plan

This is a **candidate acquisition planning tool**, not an ML training dataset. It fixes the Phase 3A blocker `blocked_no_local_semiconductor_master` by **reusing the 96-company 2026 coverage report that already exists in this repository**, *without* claiming those companies were listed in 2011–2015 or calling them normal.

From `fintrust_backend/`, on the isolated research branch:

```powershell
python -m research.financial_ml.taxonomy_gap_plan `
  --start-year 2011 --end-year 2015 `
  --output-dir data/financial_ml/historical_candidate_coverage
```

The program reads `../docs/database/semiconductor-expansion-coverage-2026-09-21.json` and, if available, `data/financial_pipeline.sqlite3`, producing:

- `historical_candidate_gap_plan.csv`: one candidate-company × fiscal-year planning row, no financial values.
- `historical_candidate_summary.json`: counts, warnings and provenance.

**Every row has `historical_listing_status=UNVERIFIED`, `historical_industry_status=UNVERIFIED`, `normal_label_status=UNREVIEWED`.** This is deliberate. Avoid historical survivorship bias: 2026 current-listed universe does not represent 2011–2015 listed issuers, including delisted companies and firms newly listed after 2015. Actual official filing availability, original filing version and public availability timestamp must be proven before as-of ML claims. Cloud Firestore/Cloud SQL have not been queried. Existing local and historical databases are not modified.

Reference testing (from `fintrust_backend/` with `PYTHONPATH` set appropriately):

```powershell
python -m unittest discover -s tests -p "test_financial_ml_taxonomy_gap_plan.py" -v
```

## Next implementation stage

1. Retrieve the **historical** 2011–2015 issuer universe from official records, including listings/delistings and industry codes at each point in time. Use this candidate table only as a head start, not the authoritative historical universe.
2. Read existing Firestore/Cloud SQL metadata **with explicitly read-only and permission-reviewed access**; do not assume absent local data are absent remotely.
3. Batch-acquire missing original filings with bounded requests/rate limits and archived evidence, maintaining per-observation available-at timestamps and IFRS-transition policy.
4. Build train/validation/test from verified-normal *reference cohorts*, not automatically all current companies. Keep 1785 out of fitting, preprocessing and threshold calibration. Treat its restated statement values as retrospective, not prospective detection evidence.