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

| # | Milestone | Status |
|---|---|---|
| 0 | Inventory, baseline, design lock (`PHASE3_5_DESIGN_LOCK.md`) | done |
| 1 | `financial_research` domain layer (modes, Decimal, snapshot, bridge, features, literature gates, reconciliation, text bridge) | in progress |
| 2 | Append-only result store (SQLite + Firestore) and CLI | pending |
| 3 | FastAPI router + OpenAPI snapshot | pending |
| 4 | Flask proxy + research UI + browser evidence | pending |
| 5 | Cloud readiness: preflight, runbooks, emulator attempt | pending |
| 6 | Full regression, non-mutation check, review bundle, final report | pending |

## Next action

Implement milestone 1 under `fintrust_backend/app/services/financial_research/`.
