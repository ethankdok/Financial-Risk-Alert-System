# Phase 3A: offline financial-ML company-year gap analysis

This extends the normal-only ML research module. It **does not train** any model, download XBRL, access Google Cloud, read statement amounts, treat records as confirmed original, or modify existing SQLite databases.

## Purpose

The previous `source_inventory` enumerated only four fact/filing tables. The current company's master data live in `companies` (local SQLite or Firestore); therefore the old inventory's 2 issuers must **not** be interpreted as the project's complete semiconductor company list.

This planner reads the existing local `companies` master (if present), limits the pilot cohort to TWSE `industry_code=24`, excludes held-out `1785`, respects observed listing dates, and compares each company/year with existing `financial_filings` and annual `normalized_financial_facts` **counts only**. Earlier historical snapshots and incident/backup DBs are intentionally not merged. The output is an acquisition-gap **planning artifact only**, not an ML dataset.

From `fintrust_backend/`:

```powershell
python -m research.financial_ml.cohort_coverage --start-year 2011 --end-year 2015 --output-dir data/financial_ml/industry_coverage
```

Outputs:

- `data/financial_ml/industry_coverage/coverage_summary.json`
- `data/financial_ml/industry_coverage/company_year_gap_plan.csv`

**If the local company master is missing/empty**, the tool refuses to fabricate a 96-company universe, exits with status 2 and reports `blocked_no_local_semiconductor_master`. The current production company master may be in Firestore; that must be inventoried separately with explicitly authorized read-only access, and joined only using verified issuer IDs and research-scope approval. No cloud credentials or service account keys should be uploaded to chat or committed.

`recorded_but_unverified` means only that local filing and annual fact *rows exist*, not that they were original, coherent or public at the target timestamp. Prior-year TIFRS comparability, duplicate versions, and audited normal reference membership still need separate checks.

**Historical bias caveat:** today's TWSE/listed master may exclude since-delisted companies and issuers that left or entered the cohort in earlier years. Do not claim that this is the complete 2013 historical semiconductor universe; reconstruct historical membership from dated official listings before publication.

Run tests (standard library only):

```powershell
python -m unittest discover -s tests -p "test_financial_ml_cohort_coverage.py" -v
```