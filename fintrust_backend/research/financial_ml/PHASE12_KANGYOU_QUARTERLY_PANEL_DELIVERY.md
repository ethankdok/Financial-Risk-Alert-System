# Phase 12: Kangyou official quarterly filing case panel (2026-10-19)

Branch: feature/financial-ml-phase12-kangyou-quarterly-panel-20261019.

## Observed actual Phase11 acceptance (user-uploaded Oct 19, 2026)
- Tests: 32/32 passed (Phase11 8, Phase10 8, Phase9 10, original literature module 6).
- A real consolidated official MOPS iXBRL document for 6452 2020Q1 was SHA archived: 708,880 bytes, 326 XBRL contexts, 1209 numeric facts, 2 nondimensional 2020-03-31 quarter-end contexts. Status QUARTERLY_XBRL_CONTEXT_FOUND_VINTAGE_UNKNOWN.
- 2020Q1 actual SHA observed: 1d0491f3ab9ec591ddc435e74dab3b8a20acb9095aae851589ceeb38b5e56913. DO NOT pin that value in code; trust only locally reverified SHA from Phase11 report and content-addressed archive.
- Historical original filing versions / first filing/public market disclosure timestamps = 0. Confirmed positive/negative labels = 0; true supervised training samples = 0. 1785 remains final untouched case.
- Phase10 missing original paper features: 62/195 case-year cells, split 32 within 11 parsed annual MOPS years and 30 due absent 6452 FY2020 annual and 8299 FY2012 legacy annual. Phase11 corrected the category error: alleged Kangyou affected fiscal reporting periods are 2017Q2 through 2020Q1, **not** 2020 full fiscal year.

## Phase12 implementation and actual work

New phase12_kangyou_quarterly_panel.py:
1. Freeze official SFIPC 6452 claim's twelve potential quarterly reporting periods 2017Q2–2020Q1 from the existing Phase1 registry and Phase11 precise reporting-period logic. Each remains legally unapproved, outcome UNKNOWN.
2. Read the already archived 2020Q1 source from the Phase11 report, re-parse its bytes after SHA-256 validation and cross-check immutable content-addressed file/path. **No re-fetch of 2020Q1**.
3. Issue at most **11 new official MOPS HTTPS XBRL requests** for 2017Q2–2019Q4, using the existing bounded OfficialSourceFetcher and allowed MOPS server endpoint. For every returned XBRL: store raw bytes under their SHA, parse XBRL, check consolidated statement entry point and the actual quarter-end non-dimensional context. A source that fails year/quarter/scope checks stays QUARANTINED.
4. For each document, count **instant** (period-end assets/liabilities-style stocks), **true 3-month quarter-duration** facts, **Jan1-to-quarter-end YTD** facts separately; also report other period-duration facts and their counts. No mixing yearly and quarterly measurements and **no annual Beneish/Dechow scores computed from 1-quarter numbers**.
5. Reuse earlier Phase12 successful SHA archives without refetching; verify both SHA and original parsing diagnostics on every reuse. Corrupt bytes, forged approved outcomes, unexpected case identities, or an inconsistent Phase11 source stop the job instead of auto-correcting anything.
6. Emit phase12_kangyou_quarterly_panel/quarterly_acquisition_results.json and quarterly_case_official_source_index.csv (twelve rows), phase12_integrated_report.json (validated quarterly count and explicit misses + zero certified historical-vintage/real outcomes).
7. No test/demo synthetic source data is admitted into real runs. No 1785 anywhere. No official 2020 FY annual assumption, no merging into production Firestore, API or online prediction state, no FinMind rerun and no ML fitting.

Tests: eleven hermetic tests in test_financial_ml_phase12_kangyou_quarterly_panel.py, covering actual structured synthetic XBRL instant-vs-duration-vs-YTD parser, frozen 12/11 period inventory, 11 mocked source requests, 2020Q1 Phase11 hash reuse, safe replay with zero network, source mismatch quarantine, missing remains unknown, source corruption fails closed, forged label blocked and dry-run behavior.

**Name collision guarded:** The existing verify_phase12.ps1 is from a previous Phase1+Phase2 development effort and is NOT overwritten. The new uniquely named single-entry test-and-fetch is verify_phase12_kangyou_panel.ps1.

## ONE acceptance on actual Windows ML worktree
After verifying a clean working tree and checking out feature/financial-ml-phase12-kangyou-quarterly-panel-20261019, from Financial-Risk-Alert-System-ML/fintrust_backend execute:

    powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase12_kangyou_panel.ps1

It runs 11 new tests plus Phase11 8, Phase10 8, Phase9 10, Phase1 12 regressions, then **up to 11** new official MOPS quarterly queries on local Windows, automatically preserving and reusing the Phase11 2020Q1 raw file. No need to run separate dozen commands.

Only send:
Financial-Risk-Alert-System/fintrust_backend/data/financial_ml/phase12_kangyou_quarterly_panel/phase12_integrated_report.json
Plus the exception section of the terminal if a unit test or real source parser fails.

## What remains scientifically unsettled
The archive documents are current accessible historical filings, possibly corrected later, and their SHA records only guarantee post-download byte integrity. Archive count cannot establish what investors could read at the historical cutoff. The SFIPC claim is not 12 verified fraudulent reporting outcomes. Before publishing a Taiwan false-financial-statement classifier claim, obtain original-as-published source versions and original market publication/first-misstatement disclosure timestamps, review precise issuer/fiscal-quarter legal outcomes, complete paper input mappings and independent Taiwan negative/unknown comparators, then run chronological/issuer-isolated supervised benchmarks and final frozen 1785 blind retrospective ex-ante replay. US/synthetic data may assist only if Taiwan-domain transfer has independent evidence.
