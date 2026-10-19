# Phase14 — Taiwan cross-industry official quarterly feature replication (2026-10-19)

Dedicated feature branch: feature/financial-ml-phase14-multiissuer-quarterly-cohort-20261019.

## Verified Phase13 handoff

User-provided Windows record and JSON: 40/40 tests passed (Phase13 9, Phase12 11, Phase11 8, Phase1 12). Actual cached official issuer 6452 2017Q2–2020Q1 iXBRL yielded 1889 TWD primary-statement period facts after unit/filter selection, 1872 unique concept-and-grain observations, 645 exact-concept-grain coverage groups, 1150 matched temporal change candidates (653 QoQ, 497 YoY), zero conflicting same-quarter values. The quarterly change candidates are NOT 1150 independent training cases. Independent issuer count=1, real positive/negative labels=0, original pre-revision filing vintages=0, earliest-publication timestamps=0, fraud-supervised training admitted=0, final holdout 1785 excluded.

The next necessary task is not more isolated 6452 feature engineering. Replicate the source-to-feature pipeline across multiple Taiwanese businesses before attempting model training.

## New engineering in Phase14

Research module phase14_multiissuer_quarterly_cohort.py:
- Input is EXACT frozen 120-issuer current-listing cohort at financial_ml/finmind_scaled_120/finmind_scaled_cohort.csv. Verify the 120-row schema, review gate of all issuers and no duplicate ticker. Deterministically choose 12 firms via hashed seed: three semiconductor companies (including the earlier crosscheck anchor 2330 if present in the frozen 120) and nine non-semiconductor companies from nine distinct industries: 10 current-listed industries total. Explicitly exclude development case issuers 3027, 6452, 8299 and untouched final 1785.
- Freeze selection with full source CSV SHA256, selected issuer industry/market and exactly the same twelve quarters as the observed 6452 case, 2017Q2–2020Q1. These are present-day listed issuers; this is a convenience source-recovery sample with historic listing/survivorship-bias warnings, NOT a valid historically representative negative cohort.
- At most 12 * 12 = 144 approved official MOPS annual-form endpoint requests using report_id=C and season=1,2,3,4, bounded rate/retries from OfficialSourceFetcher. A live run is explicitly opted into with --execute. Keep RAW evidence with SHA under issuer/quarter, each source result in quarterly_acquisition_results.json, immediate atomic save after every request, immutable cohort plan and safe resumability. Previously saved files are SHA-verified and never redownloaded or overwritten; wrong-issuer or wrong-period documents are quarantined with reason rather than considered normal. Stop on repeated source_unavailable or invalid responses.
- BACKWARDS COMPATIBLE minor refactor of phase13_quarterly_temporal_features.py adds keyword-only ticker parameter to extract_source and derive_signals. Existing default still 6452, so prior Phase13 works unchanged. Cross-company row mixing is explicitly rejected. The actual parser retains exact original QName namespace, unit TWD, consolidated scope, un-dimensioned context and period-end instant/quarter/YTD categories. Do not replace missing data with zeros, infer old filing timestamps or map differing taxonomy namespaces without evidence.
- Each selected issuer is separately processed into genuine quarter source observations and strict same-grain quarterly/YoY candidate signals. Never calculate annual Beneish8/Dechow7 from a single quarter, and never treat these candidate changes as a verified fraud probability.
- Research outputs in phase14_multiissuer_quarterly_comparison/: frozen_phase14_plan.json, quarterly_acquisition_results.json, raw/ SHA archives, multiissuer_official_quarter_sources.csv, multiissuer_quarter_twd_observations.csv, multiissuer_quarter_same_grain_changes.csv, multiissuer_source_coverage.csv, phase14_integrated_report.json.
- Outcome labels ALWAYS UNKNOWN; true negatives=0, true positives=0, supervised trained rows=0, original market-available report versions=0; no production DB/Flask/FastAPI/frontend writes, no deployment and no 1785.
- Nine hermetic tests cover deterministic ten-industry selection, allowlisted official quarter URLs, zero-network planning, 144 fake source documents with issuer-isolated signals and cache replay, partial pre-listing historical gaps, wrong entity XBRL quarantine/replay, immutable cohort-plan identity, forged known-normal label fail-closed. Test synthetic financial XML never becomes real research data.

## One Windows acceptance

Use clean separate Financial-Risk-Alert-System-ML/fintrust_backend worktree and Python ml-env; fetch/switch to feature/financial-ml-phase14-multiissuer-quarterly-cohort-20261019.

One command: powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase14_multiissuer_quarterly.ps1

The verifier runs Phase14 tests, then automatically executes the bounded actual MOPS source acquisition. If the original 120-company selection CSV is missing, the stage FAILS rather than silently inventing a new cohort. Existing Phase13 6452 source files are retained separate and never cross-labeled as safe controls. At most 144 new requests on the first run, with resumable content-addressed artifacts.

Upload one file:
Financial-Risk-Alert-System/fintrust_backend/data/financial_ml/phase14_multiissuer_quarterly_comparison/phase14_integrated_report.json
If a unit test or source schema fails, also provide the relevant traceback or source index; no need to upload whole raw XBRL archives. Results from actual Windows MOPS requests are UNVERIFIED until user runs this once.

## What remains for meaningful ex-ante false-financial-statement detection

The external evidence problem persists: source version retrieved today is not proof it was first published in the past, and court allegations are not confirmed individual affected fiscal-quarter labels. Real outcome-approved Taiwanese positives, independently reviewed negatives, original market-available financials and release times, complete paper 8+7 financial ratios, sampling including no-survivorship bias, and issuer/time-isolated train/validation/test are still required. A successful source-extraction Phase14 does not make existing unlabeled 4-architecture experiments into true fraud models. Final 光洋科 1785 pre-2016 original-filing blind replay remains separate and untouched until these gates pass.
