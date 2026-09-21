# Semiconductor Expansion Core

## Scope model

The rule engine reports rule coverage independently from filing, fact, metric,
and final analysis coverage.

| Coverage | Meaning |
| --- | --- |
| `full` | Common rules and a business-model-specific monitorable/historical overlay are available. |
| `partial` | A reviewed historical overlay exists, but one analysis layer still uses common semiconductor rules. |
| `common_only` | Only broadly applicable revenue, profitability, cash-flow, and capital-structure rules are enabled. |
| `unsupported` | The company is unclassified or outside the reviewed semiconductor taxonomy. |

Current `full` groups are IC Design, Memory Manufacturing, Semiconductor
Equipment, and Memory Module / Storage. Foundry and Packaging / Testing remain
`partial` because their existing historical overlays are preserved while their
monitorable layer is not being redesigned in this round. Power, Materials, and
Optoelectronics remain explicitly `common_only`.

The configured numeric thresholds are MVP heuristics or company-history
thresholds. They are not represented as literature-validated industry
standards. Peer median / MAD calibration remains future work.

## New overlays

- Memory Manufacturing combines inventory growth relative to revenue, revenue
  decline, gross-margin deterioration, and (for higher pressure) CapEx above
  company history plus negative free cash flow. High CapEx alone is neutral.
- Semiconductor Equipment combines demand deterioration with inventory or
  receivable-days pressure and gross-margin deterioration. The supplier's own
  CapEx is not treated as downstream semiconductor demand. R&D is informational.
- Memory Module / Storage combines inventory growth relative to revenue,
  gross-margin deterioration, and cash-conversion weakness. It does not inherit
  foundry or memory-manufacturer capital-intensity logic.

## Batch and coverage audit

`FinancialIngestionPipeline` accepts only tickers in the existing curated
semiconductor taxonomy. Its default refresh list remains `2330,2454`; expanding
the default or scheduling the full universe is a separate operational decision.
Document identities and repository upserts are unchanged, so reruns retain the
existing idempotency contract.

The following command performs a read-only pilot or full-universe audit. It
fetches the current TWSE universe and MOPS filings, but does not construct a
writable datastore repository.

```powershell
$env:MOPS_XBRL_PARSER_MODE='lightweight'
python -m scripts.audit_semiconductor_expansion --scope pilot --years 3 --output coverage.json
python -m scripts.audit_semiconductor_expansion --scope all --years 3 --output coverage.json
```

Each company row separately reports filing coverage, canonical fact coverage,
metric coverage, rule coverage, missing concepts/metrics, and final
`PASS`/`PARTIAL`/`FAIL`. A successful data fetch therefore cannot be mistaken
for a complete subindustry model.

The latest checked-in read-only run is
[`semiconductor-expansion-coverage-2026-09-21.json`](semiconductor-expansion-coverage-2026-09-21.json).

The 2026-09-21 audit intersected all 96 curated tickers with the live TWSE
universe. The nine-company pilot produced 4 `PASS`, 5 `PARTIAL`, and 0 `FAIL`;
all nine had complete three-year data coverage, while the five `PARTIAL` rows
accurately reflected `partial` or `common_only` rule coverage. The final full
run produced 49 `PASS`, 38 `PARTIAL`, and 9 `FAIL`.

The shared parser gap found by the pilot was the official
`GrossProfit`/`GrossProfitLossFromOperations` concept naming; both are now
canonical aliases for `gross_profit`. The nine full-run failures returned
invalid consolidated-report content for all five attempted candidate years.
The audit keeps those rows as `FAIL` and does not silently substitute an
individual-company statement with a different accounting scope. Intermittent
HTTP 502 responses are retained in `filing_diagnostics`; companies with three
other usable years can still receive valid data coverage.

Both audits were read-only. No analysis repository, Firestore repository, or
ingestion-run writer is constructed by the audit command.
