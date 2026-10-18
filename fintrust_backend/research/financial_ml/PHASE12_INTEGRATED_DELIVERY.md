# Phase 1 closure review + Phase 2 integrated execution (2026-10-19)

## What user requested
One phase-sized development delivery and **one local verification**, rather than running a different script after every small commit. When validation finds defects, repair them **along with** the next planned round. Leave deployment, production database and frontend completely untouched.

The **scientific target** remains: identify material misstatements in previously published Taiwan financial reports, using only original filing data known at a historical prediction cutoff. Core model inputs will later be Beneish (1999) 8 + Dechow et al. (2011) Model 1 7. The current 12 provisional FinMind source amounts are not those features. Final issuer **1785** is held out from every training, feature choice, hyperparameter choice and threshold calibration. A modern retrospective blind test is not the same as proving a model could have been trained as of 2016.

## Phase 1 completion standard and real gap
**Phase 1 case-registry engineering is complete for the current candidate scope; scientific outcome-label admission is not completed.** Uploaded 2026-10-18 local evidence report: 3 candidate cases, 7 potentially affected company-years, 4 reference URL anchors, **zero archived primary-source bytes, zero approved positives and zero approved negatives**. The database therefore has no justified supervised labels. The integrated command regenerates these facts using the updated seeded registry, which now carries five source references (new Supreme Court status).

Official-source review correction:
- **3027 盛達**: Taipei District Court 113 Jin-Su 29 (2025-04-30), initial first-instance conviction, identifies FY2015–2016 materially overstated revenue via principal-versus-agent gross/net recognition, and mentions June 2017 financial corrections. Judicial print source: https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPDM%2C113%2C%E9%87%91%E8%A8%B4%2C29%2C20250430%2C1 . Do **not** assert conviction is finally upheld without confirming appeals, earlier public warning date, and per-filing scope.
- **8299 群聯**: Earlier High Court civil director-removal case 113 Jin-Shang-Geng-Yi 2 (2025-01-15) was **VACATED and REMANDED** by **Supreme Court 114 Tai-Shang 859 (2025-11-19)**. Separate criminal 111 Jin-Shang-Su 11 judgment is described by the Supreme Court as *final*. This distinction is now preserved in the source seed; never use the vacated civil result as final evidence. Supreme print: https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPSV%2C114%2C%E5%8F%B0%E4%B8%8A%2C859%2C20251119%2C1 . Historical affected filings and earliest public announcement still need original evidence.
- **6452 康友-KY**: SFIPC source documents civil claims concerning FY2017Q2–FY2020Q1, **not automatically a court-proven positive for all four fiscal years**. https://www.sfipc.org.tw/News_Content.aspx?n=7458&s=571 .
- **1785 光洋科**: retains independent final-case embargo and pre-restatement input availability caveat from existing case_labels and case_knowledge code.
- Document date and actual public publication time are different; first discovered correction notice time is a *candidate*, not verified earliest disclosure. Do not compute early-warning lead times from a later judgment.

Before formal outcome label admission, phase1 case reports explicitly retain gates: official original source bytes with verifiable SHA, per-document paragraph-level finding versus claim, original company period-specific filings, first public knowledge time, and independent method-owner sign-off. Negative/control labels require a documented discovery/followup window and audited historical search, NOT merely no known case.

## Phase 2 code-level delivery

A new research-only entrypoint, phase12_integrated_gate.py, performs:
1. Re-extract Phase1 candidates, references and source/label blockers.
2. Optionally resume the full **120-company × 3-statement** raw FinMind cohort, using existing 12-company chunks, at most 3 batches per round. Default 5 rounds (>10 batches when quota allows); downloader enforces default 15-second pacing, reuses existing cache, stops on quota/provider errors or corruption. **Network is disabled unless --execute-download.**
3. Audit each cached source's issuer identity, provider identity, requested 2013–2025 period, numerical finiteness, invalid percentage-only responses, conflicting type-date values, SHA. Missing files, empty valid provider responses, valid nonempty, and **quarantined** invalid archives are distinct. Never rewrite archive bytes during audit; exclude quarantined issuers from conversions, preserving a review CSV.
4. Reuse previous annual candidate stage (2013–25, twelve coarse finance account candidates only; income four quarters, cash flow year-to-date Q4, balance Dec31 candidates), with explicit blank unknowns, input SHA and training_admitted=false.
5. Reuse financial panel 3-/5-year-window readiness, publisher source-type alias schema audit, and compare overlap with archived MOPS validated FY2013–15 company-years where locally available (numeric mapping proposals only).
6. Write one phase12_gate_report.json with data counts and **non-approval** flags. Network-free code does not produce true outcome labels, any paper 15-feature model, proven original-vintage financials, or trained ML models.

### Actual source coverage received before this round
- Cohort: 120 current listed nonfinancial candidates, 41 industries, semiconductor 24.
- User confirmed **48 company download batches complete** (first four batches); remaining 72 / six batches. Recent 3 batches added 99 archives, 9 reused and 14 zero-row responses; initial batch 33 new + 3 reused. Do not equate HTTP success with source finance usable.
- Earlier run on those 48 downloaded issuer archives but 120-member candidate CSV produced **18,720 candidate cells, 6,836 nonempty candidate annual values**, **10,296 missing archive-based candidate cells**, 535 complete 12-candidate company-years, 442 complete 3-year / 357 complete 5-year preliminary windows. These are **not** 15 paper-feature observations or supervised sample counts.
- FinMind raw 2013–25 source period dates and apparent matching do NOT independently establish historical original filing versions or publication as-of times.
- Even if all 360 archives are present, certain issuers may return empty archives; these require separate source strategy for historical cases. Never impute financial zero or infer normal label.

### What Phase 2 can/cannot be declared finished
- YES: a single repeatable batch-acquisition + source-integrity + quarantine + annual *candidate* + sequence-readiness + official crosscheck **engineering process** is written on an isolated branch.
- NOT YET: all 120 company statement caches downloaded until local opt-in run succeeds; archived official statement-by-statement numeric reconciliation and *method owner* mapping approval over issuers/years, original PIT filing publication validation, 15 true literature-model features, or fully approved Taiwan outcome label dataset.
- There is **no scientific basis** to mark Phase1 outcome-label evidence complete or Phase2 data approved when their source gates remain red. The report makes these exact omissions visible; do not falsify completion.

## Single local validation; not a list of manual scripts

In the separate ML worktree under fintrust_backend with ml-env active:

1. Fetch/switch only if git status is clean:
    git fetch origin refs/heads/feature/financial-ml-phase1-close-phase2-integrated-20261019:refs/remotes/origin/feature/financial-ml-phase1-close-phase2-integrated-20261019
    git switch --detach origin/feature/financial-ml-phase1-close-phase2-integrated-20261019
2. Run **ONE** PowerShell script, which runs all Phase1/Phase2 regression tests first and then one source/data acceptance pipeline:
    powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase12.ps1 -ExecuteDownloads

Download is explicitly opt-in. Remove -ExecuteDownloads to run without network. Do not launch concurrent FinMind downloads. The script discovers the previously used sibling local data folder (Financial-Risk-Alert-System/fintrust_backend/data/financial_ml) and writes only research files in phase12_integrated_verification.

Send back **ONLY**
- phase12_integrated_verification/phase12_gate_report.json
- phase12_integrated_verification/phase2/phase2_raw_audit.csv **if the report contains quarantines**
- console regression failures, if any
No need to upload hundreds of original provider raw JSON files or API tokens.

## What happens after validation
If tests/errors appear, patch them in the **next development round plus that round's planned feature mapping work**. If quotas block finishing raw downloads, preserve caches and audit results; do not call missing data complete. To formally finish Phase1 outcomes, obtain and independently verify primary source bytes/time/period evidence, then route to method-owner review for positive/negative admission. Phase3 will engineer and evaluate **real** 15 Beneish/Dechow variables with Taiwan-only train/validation/test and as-of splits, optional US/synthetic transfer tested only for domain comparability.
