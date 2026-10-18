# FinMind TaiwanStockInfo market-history reconciliation

FinMind `TaiwanStockInfo` can contain **multiple dated rows for one stock_id**:
a historical emerging-market row and a newer TWSE/TPEx row. Official guidance says
the **latest dated row per stock_id** determines the current market (see
https://finmind.github.io/tutor/TaiwanMarket/Technical/).
A repeated stock ID is therefore not necessarily a source data error.

## Corrected process (2026-10-18)

1. Preserve the immutable `TaiwanStockInfo_snapshot.json` fetched earlier.
2. Group four-digit stock IDs. Exclude the reserved case `1785`.
3. Require a valid ISO `date` for each candidate record. If any row for an
   ID is undated, quarantine the entire ID (cannot prove which record is latest).
4. Choose the **greatest date** per stock ID before testing current market/type,
   current non-financial industry, and instrument eligibility.
5. Several identical latest-date entries are harmless; if latest-date market,
   stock name or industry differs, quarantine **that ID only** and continue.
   Do not choose arbitrarily or fabricate a historical classification.
6. Preserve a readable quarantine CSV and counts/examples in the coverage JSON.
   The output company CSV schema is unchanged for `finmind_bulk_stage.py`.
7. Do not infer historical 2013–2025 listing membership, normality or company
   financial-data correctness from a 2026 current-company snapshot.

## Resume without re-fetching (separate ML worktree)

```powershell
$branch = "feature/financial-ml-iterative-literature-benchmark-20261018"
git fetch origin "refs/heads/${branch}:refs/remotes/origin/${branch}"
git switch --detach "origin/$branch"
$mlRoot = (git rev-parse --show-toplevel).Trim()
$mainRoot = Join-Path (Split-Path $mlRoot -Parent) "Financial-Risk-Alert-System"
$out = Join-Path $mainRoot "fintrust_backend\data\financial_ml\finmind_universe"
python -m research.financial_ml.finmind_universe --source-json (Join-Path $out "TaiwanStockInfo_snapshot.json") --output $out
```

No `--fetch` is needed again. Inspect
`taiwan_nonfinancial_universe_report.json`,
`taiwan_nonfinancial_current_candidates.csv`, and
`taiwan_stock_info_quarantined.csv`.

Run offline tests:
`python -m unittest discover -s tests -p "test_financial_ml_finmind_phase5.py" -v`.

If a ticker remains quarantined, compare the differing dated records in
the quarantine CSV against the original snapshot or official listing sources
before resolving. Do not silently override a same-date discrepancy.
