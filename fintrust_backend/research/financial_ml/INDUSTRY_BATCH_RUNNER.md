# Phase 4A — Repeatable industry candidate acquisition

This research-only command builds on `official_batch.py`. It **does not train a model**,
create reference-normal labels, alter the product database, write Firestore, or
claim historical-as-of original statements. The 2026 industry taxonomy is a
candidate list only; delisted and post-2015 issuers require verification.

## Safety properties

- Default **dry run**. Only `--execute` sends official MOPS requests.
- Only fiscal 2013–2015; 2011–2012 are not silently converted into TIFRS.
- Hard cap 36 company-year selections per invocation; reused official downloader
  caps each chunk to 12 and rate-limits requests.
- `1785` is explicitly excluded from normal-reference acquisition.
- Resume uses `acquisition_results.json` **and validates raw SHA-256** before
  skipping any prior candidate; failed downloads may be retried.
- Uses existing XBRL normalization, archiving and `candidate_facts.csv` outputs.
- The manifest carries `UNREVIEWED` normal labels and no historical PIT certification.

## Recommended run on a separate Git worktree

Your current local worktree is on another branch and has untracked documentation.
Do not forcibly checkout/reset/clean it. From the root of your existing repo:

```powershell
# First run only; source files and original local database are untouched.
git fetch origin "refs/heads/feature/financial-ml-industry-acquisition-20261018:refs/remotes/origin/feature/financial-ml-industry-acquisition-20261018"
git worktree add --detach ..\Financial-Risk-Alert-System-ML origin/feature/financial-ml-industry-acquisition-20261018

# In the new worktree, point to candidate manifest and original archive in the
# EXISTING worktree, to resume from the 9 previously downloaded filings.
cd ..\Financial-Risk-Alert-System-ML\fintrust_backend
$original = "C:\Users\samue\Documents\GitHub\Financial-Risk-Alert-System\fintrust_backend"
python -m research.financial_ml.industry_batch_runner `
  --candidate-csv "$original\data\financial_ml\historical_candidate_coverage\historical_candidate_gap_plan.csv" `
  --output-dir "$original\data\financial_ml\official_batch" `
  --max-company-years 12
```

If the resulting **dry run** plan looks reasonable, repeat the command with
`--execute` to download a bounded group of new candidate years. Each repeat
selects the next group not already recorded with a verified raw artifact.

Run tests separately in the ML worktree:

```powershell
python -m unittest discover -s tests -p "test_financial_ml_industry_batch_runner.py" -v
```

After a completed batch, run existing feature pilot against the original
archive's `candidate_facts.csv` with `--mode retrospective` and inspect its
readiness JSON. **Do not call unlabeled candidate firms normal**, and do not
claim predictive accuracy without historical-original evidence and outcomes.

## Important limits

- Existing official archive has only one captured version per filing URL; it
  does not prove the contents were available at the historical observation date.
- Stock-list membership and subindustry labels are unverified in 2013–2015.
- Executing large-scale downloads should remain bounded and respect MOPS terms
  and rate limits. Stop and review failures before increasing scope.
- Real normal-only model training needs a separate documented normal-reference
  ledger, temporal/company-disjoint splits, and out-of-time evaluation labels.