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
5. Several identical latest-date entries are harmless. If latest-date
   market or name differs, quarantine that ID. Multiple industry tags can be
   hierarchical: remove only the three known parent/segment categories and
   require exactly one remaining specific industry. Preserve every original
   tag in the industry-memberships sidecar. If several incomparable specific
   industries remain, quarantine rather than choosing arbitrarily.
6. Preserve a readable quarantine CSV, a source-tag membership CSV, and
   counts/examples in the coverage JSON. The candidate CSV schema remains
   compatible with `finmind_bulk_stage.py`.
7. Do not infer historical 2013–2025 listing membership, normality or company
   financial-data correctness from a 2026 current-company snapshot.

## Resume without re-fetching (separate ML worktree)

```powershell
$branch = "feature/financial-ml-finmind-taxonomy-reconciliation-20261018"
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

## Empirical correction from the 2026-10-18 uploaded outputs

The earlier deduplicator quarantined 605 stock IDs / 1,227 same-date rows.
Inspection of the actual quarantine CSV found:
- 604 IDs: **identical latest date, company name and market**, but two or
  three industry tags. All 604 have precisely one specific tag after removing
  the three explicit broad/segment tags: `電子工業`, `化學生技醫療`, `創新板股票`.
- One ID (`8908`): the same latest date / name / industry appears with
  different market values (TWSE and TPEx), so it stays quarantined.
- Most common multiple taxonomies: 電子工業 + 電子零組件業 (105),
  電子工業 + 半導體業 (103), 電子工業 + 光電業 (78), and
  電子工業 + 電腦及週邊設備業 (70).

The revised program records every source tag in
`taiwan_stock_info_industry_memberships.csv`, selects the unique **specific**
industry, and excludes only genuinely unresolved ID/market/name or
incomparable-industry conflicts. Given the reported earlier 1,482 valid
candidate IDs plus 604 industry-tag-reconciled IDs, the **expected** count is
2,086 non-financial candidates before further real-world listing validation.

Source rows and raw snapshot remain unchanged. Same-day market differences,
including ticker 8908, are **not** auto-corrected. Review using a dated
authoritative listing source before making historical membership claims.

For a rerun use the original cached `TaiwanStockInfo_snapshot.json` and
`--source-json`, not `--fetch`; inspect the report and memberships sidecar.
