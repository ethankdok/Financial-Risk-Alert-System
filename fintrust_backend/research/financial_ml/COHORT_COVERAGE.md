# Phase 3A: offline financial-ML company-year gap analysis

This extends the normal-only ML research module. It **does not train** any model, download XBRL, access Google Cloud, read statement amounts, treat records as confirmed original, or modify existing SQLite databases.

## Purpose

The previous `source_inventory` enumerated only four fact/filing tables. The current company's master data live in `companies` (local SQLite or Firestore); therefore the old inventory's 2 issuers must **not** be interpreted as the project's complete semiconductor company list.

This planner reads the existing local `companies` master (if present), defaults to TWSE `industry_code=24` but supports repeatable `--market` and `--industry-code` filters, excludes held-out `1785`, respects observed listing dates, and compares each company/year with existing `financial_filings` and annual `normalized_financial_facts` **counts only**. Earlier historical snapshots and incident/backup DBs are intentionally not merged. The output is an acquisition-gap **planning artifact only**, not an ML dataset.

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

## Critical peer-group design caveat

1785 is classified as **TPEX / other electronics** in a TWSE 2022 published list, while the TPEX value-chain profile puts it in semiconductor chemicals, among other fields. The 2013–2015 historical taxonomy must be separately verified. A TWSE/semiconductor-only trained model may flag business-model differences rather than misstatements. Compare a broad reference and genuinely comparable materials/electronics peers, with documented matching criteria. Official reference: https://ic.tpex.org.tw/company_chain.php?stk_code=1785

An optional expanded local-master experiment can specify repeated arguments (only when the corresponding official codes have been verified):

    python -m research.financial_ml.cohort_coverage --market TWSE --market TPEX --industry-code 24 --industry-code 31 --output-dir data/financial_ml/industry_coverage_multiindustry

Industry code 31 is illustrative of an other-electronics grouping and must be verified against the cohort's official taxonomy. No source is downloaded and no company is labeled normal by this tool.
