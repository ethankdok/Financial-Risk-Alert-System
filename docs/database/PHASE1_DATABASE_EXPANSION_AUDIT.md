# Phase 1 — Database Expansion Audit

## Confirmed scope

- Market: Taiwan Stock Exchange (TWSE)
- Industry: listed semiconductor companies (`industry_code=24`)
- Official company source: TWSE OpenAPI `t187ap03_L`
- Historical financial horizon: 3–5 years per company
- Production persistence: Firestore; SQLite remains the local/test fallback

## Current state

The v4 pipeline already separates financial filings, normalized facts, calculated
metrics, rule results, latest snapshots, and official events. It also supports
idempotent document identifiers for most analytical records.

The main scaling blockers found in the audit were:

1. The analyzable company registry was hard-coded to four companies.
2. There was no persisted company master sourced from the official market list.
3. There is not yet a first-class ingestion-run ledger with found/inserted/updated/failed counts.
4. News/social evidence is not yet represented in the persistence contract.
5. Bulk execution is sequential and has no retry/checkpoint policy.

## Phase 1 implementation

This phase adds a `companies` master for SQLite and Firestore, plus an official
TWSE sync service. Re-running the sync upserts the same ticker instead of creating
duplicates. Known demo companies retain their reviewed subindustry; newly found
companies are marked `待分類` so no unsupported peer-group rule is inferred.

Run locally from `fintrust_backend`:

```bash
python -m scripts.sync_company_universe
```

The command writes only company metadata. It does not trigger financial ingestion,
LLM calls, or overwrite financial facts.

## Next implementation order

1. Add ingestion-run ledger and per-company status/error counts.
2. Expose persisted company universe through the API while preserving the four-company demo contract.
3. Classify/approve semiconductor subindustries.
4. Run a 2330/2454 controlled backfill and data-quality report.
5. Add bounded concurrency, retry, and checkpointing for full-universe backfill.
6. Connect incremental schedules to source lifecycle rules.

## Phase 2 implementation and verification (2026-09-20)

Implemented:

- `ingestion_runs` for SQLite and Firestore with run/batch identity, company,
  trigger, source mode, requested history, timing, status, persistence counts,
  written-record count, and error details.
- Protected API access for company-universe sync and ingestion-run inspection.
- Versioned subindustry mapping for all 96 TWSE-listed semiconductor companies.
- Configurable lightweight iXBRL parsing for restricted runtimes where Arelle
  cannot resolve external taxonomy resources.
- Reproducible small-backfill and data-quality audit command.

Official 5-year backfill results:

| Ticker | Periods | Facts | Metrics per run | Duplicate fact keys | Blank sources | Demo facts | Insufficient rules |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2330 | 2021FY–2025FY (5/5) | 91 | 112 | 0 | 0 | 0 | 20% |
| 2454 | 2021FY–2025FY (5/5) | 91 | 112 | 0 | 0 | 0 | 15% |

The same backfill was executed twice. Filing and normalized-fact grains remained
stable (`5` filings and `91` facts per company); metrics and rule results retained
both runs by design because `run_id` is part of their analytical-history grain.
No critical, high, medium, or low QA finding was produced by the current gate.

The detailed subindustry taxonomy is project metadata, not an official TWSE
field. Four existing demo companies are marked `reviewed`; the remaining
classifications are `medium` confidence and should be reviewed before enabling
subindustry-specific rules for the full 96-company universe.
