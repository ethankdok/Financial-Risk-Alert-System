# Phase 3–5 integration progress (resumable)

Branch `feature/phase3-5-research-integration` from `506b64cb62f9a31353d87444f0080fa6540cf759` (ancestry verified).
Untracked user inputs preserved and never committed: `docs/development/phase3_5_handoff/`,
`docs/development/FinTrust_Phase3-5_Claude_Implementation_Handoff_2026-10-11.zip`.

## Baseline (read-only, before any change)

- `python -m scripts.research_baseline --out data/phase3_5/baseline_before.json` (from `fintrust_backend/`):
  16 tables (facts 234, versions 44, comparisons 158, events 919, disclosed 60, availability 79, summaries 210,
  sources 102); 12 package files, all hashes equal to the expected Phase 1C–2C values; raw archive 274 files;
  conference archive 4,735 files.
- Tests: backend `564 passed, 3 skipped`; root (Flask/frontend) `142 passed`.

## Milestones

| # | Milestone | Status | Commit |
|---|---|---|---|
| 0 | Inventory, baseline, design lock (`PHASE3_5_DESIGN_LOCK.md`) | done | aa9004c |
| 1 | `financial_research` domain layer (modes, Decimal, snapshot, bridge, features, literature gates, reconciliation + PDF p.8, text bridge) | done | aa9004c |
| 2 | Append-only result store (SQLite + Firestore), run verification, CLI + review fixture | done | 3398361, 68db626 |
| 3 | FastAPI router `/api/v1/research` + OpenAPI snapshot | done | aa9004c, 821bb6a |
| 4 | Flask proxy, six-view research page, UI chain test, real-process smoke + headless Chrome screenshots | done | 68db626 |
| 4b | Pre-existing Flask catch-all file exposure fixed (separate commit, review requested) | done | 0427418 |
| 5 | Result export (lock/journal/batches/retries), emulator tier (Firestore emulator 3 passed), preflight, runbooks | done | 5e27573, 821bb6a |
| 6 | Full regression, non-mutation check, review bundle, final report | in progress | — |

## Key decisions

- No React/Vite exists: the UI follows the real vanilla HTML/JS + Flask static pattern.
- Derived results live in a separate `research_results.sqlite3`; the approved DB is opened `mode=ro` only.
- Strict reads use the reader with `as_of = cutoff − 1 µs` (reader treats datetimes inclusively) and re-check `< cutoff`.
- TPEx summaries are `not_comparable` (scope inferred from XBRL revenue — circular).
- No literature-model coefficients shipped; methods are `DRAFT_PENDING_METHOD_OWNER_REVIEW`.

## Next action

Collect full regression logs, compare the data baseline, build the review bundle and write the final report.
