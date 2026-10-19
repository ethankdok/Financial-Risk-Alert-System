# Phase13 — Twelve-quarter Taiwan financial candidate features, strict period and taxonomy

Date: 2026-10-19. Branch: feature/financial-ml-phase13-quarterly-temporal-features-20261019.
Scope: local, read-only official XBRL feature candidates for issuer 6452. NOT supervised false financial statement classification.

## Observed Phase12 validation accepted from user

- 49/49 relevant regressions passed: Phase12 11, Phase11 8, Phase10 8, Phase9 10, Phase1 12.
- 12/12 actual MOPS official 6452 2017Q2–2020Q1 documents passed quarter-period and consolidated-scope audits.
- The latest execution had cached_reused_prior_phase12=11, reused_verified_2020Q1_from_phase11=true, and new_network_requests=0. Eleven original sources were already locally cached. DO NOT describe the latest execution as eleven new downloads.
- Source XBRL fact diagnostics: quarterly_numeric_current_period_facts=3296, quarterly_exact_duration_facts=890 and quarterly_ytd_duration_facts=1105. These numbers are facts within filings, NOT independent companies or real training samples.
- Original first-public filing versions verified=0, first-publication time proofs=0, approved true false-statement outcome labels=0 and supervised training admissions=0. Final 光洋科 1785 is completely excluded. Official SFIPC alleged 2017Q2–2020Q1 is NOT twelve legally confirmed quarterly positive labels.

## Actual Phase13 implementation

New phase13_quarterly_temporal_features.py:
1. Read Phase12 complete-12-quarter status and no-promoted-outcome gates before raw evidence is used.
2. Reverify each of the 11 Phase12 content-addressed XBRL SHA digests and the distinct Phase11 2020Q1 archive. Disagreeing source paths and hashes fail closed.
3. Reuse ParsedXbrlDocument. Only accept entity 6452, consolidated entry-point, non-dimensional primary-statement numeric XBRL contexts, original TWD currency unit and actual target quarter-end dates. Reject prior-year comparative facts as current facts.
4. Keep four mutually exclusive fact measurement categories: fiscal-quarter-end stock values (instant), real three-month quarter flows (quarter_duration), Jan1-to-quarter-end cumulative flows (ytd_duration), and other nonstandard durations. Q1 same-date quarter and YTD overlap is deduplicated, not made into two model features.
5. For every exact namespace URI, original local taxonomy concept, quarter, same measurement grain and currency, repeated values must agree or be quarantined. No presumed 0 for missing financial statement facts.
6. Compute *candidate* changes ONLY from matching original taxonomy URI, exact concept, TWD unit and measurement period category:
   - QoQ on instant and true three-month duration;
   - YoY on instant, true three-month duration, or YTD cumulative within the same quarter number;
   - NEVER subtract quarter-to-quarter YTD amounts and call it a true three-month comparative quarterly performance.
   - Signed absolute delta=current-prior; relative change=delta/abs(prior). Zero denominator gives blank percentage. Taxonomy URI changes are not silently collapsed across years.
7. Write phase13_kangyou_quarterly_temporal_features/quarterly_twd_source_observations.csv, quarterly_same_grain_change_candidates.csv, quarterly_concept_coverage.csv, quarter_source_quality.csv and phase13_integrated_report.json. Every observation and signal has raw source hash and financial outcome label UNKNOWN, original-vintage approval false, training admission false.
8. No new MOPS/FinMind HTTP requests, no production DB/Flask/FastAPI/frontend writes, no model training and no 1785 leakage. This is only one issuer with 12 linked quarterly reports, not a statistically independent multi-company classifier cohort.

New test_financial_ml_phase13_quarterly_temporal_features.py has NINE hermetic tests: original XML parsing and source unit, excluding comparative dates, Q1 YTD vs true quarter dedupe, duplicate conflicts, QoQ/YoY grain, strict source taxonomy identity, signed negatives and zero denominators, label gate and offline synthetic 12-quarter integration.
verify_phase13_quarterly_features.ps1 is a single local PowerShell entrypoint for Phase13 new tests and Phase12, Phase11, Phase1 regressions, then actual extraction from SHA archived source files. Expected regressions: 9+11+8+12=40. This development was committed remotely; user local acceptance has NOT yet happened.

## One user-side acceptance

From a clean dedicated Financial-Risk-Alert-System-ML/fintrust_backend Windows worktree with ml-env active, fetch/checkout the Phase13 feature branch and execute only this once:

    powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase13_quarterly_features.ps1

The integrated offline program reads already cached quarterly XBRL source files and writes one summary. Upload only:
Financial-Risk-Alert-System/fintrust_backend/data/financial_ml/phase13_kangyou_quarterly_temporal_features/phase13_integrated_report.json

If it fails, add the precise test traceback or quarter_source_quality.csv as relevant. Do not upload the entire private provider archive or any API keys.

## Next scientific work

One 6452 quarterly sequence alone cannot support actual supervised Taiwan false financial statement detection claims. Future phases should align strict fiscal-quarter source semantics for a multi-company Taiwan cohort, validate original-as-first-published pre-restatement source vintages and independent market disclosure times, adjudicate affected quarterly outcomes versus mere allegations, distinguish audited negatives from unknown, and compare genuine published Beneish8/Dechow7 against supervised/disjoint and time-series models. Only after this, the final untouched 1785 pre-2016 historical case can assess true advance warning. This cannot be honestly assigned a fixed number of remaining coding phases while primary-source evidence is incomplete.
