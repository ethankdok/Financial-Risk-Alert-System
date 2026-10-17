# Phase 3C — safe MOPS XBRL pilot (research only)

Uses the existing MOPS OfficialSourceFetcher, SHA-256 RawEvidenceArchive, annual parse_xbrl_document and normalize_annual_filing, and revision classifier. No production SQLite, Firestore, Cloud SQL, scheduler or UI writes.

## What the earlier report actually established

The user's 2026 semiconductor inventory contains 96 candidate companies and 480 candidate company-years (2011–2015) absent from the local financial DB. This does not establish historical listed status, official filing availability, or normal-company labels. Historical eligibility and survival bias remain to be audited.

## Run from fintrust_backend/ on this research branch

```powershell
# Dry run first: no official requests.
python -m research.financial_ml.official_batch --ticker 2303 --ticker 2330 --year 2013 --year 2014

# Opt in only after reviewing the four official URLs.
python -m research.financial_ml.official_batch --ticker 2303 --ticker 2330 --year 2013 --year 2014 --execute

# Mock-network regression checks.
python -m unittest discover -s tests -p "test_financial_ml_official_batch.py" -v
```

The candidate input CSV is data/financial_ml/historical_candidate_coverage/historical_candidate_gap_plan.csv. Default is DRY RUN. At most 12 explicit company-year requests can be made in a single invocation, 2013–2015 only. The reserved 1785 case is not accepted in the normal candidate acquisition.

All generated files are under ignored data/financial_ml/official_batch/: request_plan.json, raw/ SHA-256 archives, acquisition_results.json, candidate_facts.csv, and acquisition_summary.json. Completed validated files can be reused after hash verification. Failed/ambiguous sources are recorded, not silently substituted.

## Research limitations

Output facts are retrospective exploratory inputs ONLY; this stage creates no machine-learning labels. MOPS archive content may be revised/restated, even for an old fiscal year. The tool never treats retrieval time as historical public availability, never marks a downloaded filing original without evidence, and always sets point_in_time_eligible=false. The 2011–2012 years need separate original PDF/financial-statement methodology; they are not assumed downloadable as XBRL. The full 480-row plan has not been fetched.

Next gates: historical listed/delisted issuer population, as-of filing evidence, Taiwan industry and feature compatibility, candidate normal reference review, followed by train/validation/test split and protected 1785 holdout. An actual MOPS request must be verified in the user's network environment; Python 3.14 ARM64 may require dependency checks.
