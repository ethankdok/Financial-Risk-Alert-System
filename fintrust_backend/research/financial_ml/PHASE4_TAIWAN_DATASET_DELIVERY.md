# Phase4 — Taiwan-only research split + first-source dispute triage (2026-10-19)

## Purpose and scientific acceptance criteria

The target is **early risk prediction for materially misstated Taiwan company financial reports**. The prediction as of a historical day must use original statements and publication times available by then, plus a model/label knowledge base available by that same day. **Company 1785 remains a final, never-tuned case holdout.** Published Beneish (1999) 8 + Dechow et al. (2011) Model 1 7 features and their original M/F-Score baselines must be preserved.

User requested: develop a **complete phase at a time**, then give one local validation command. Repair defects found in one phase during the next phase's development, rather than asking for many individual test runs. No production API, website, Firestore or deployment.

### True Phase3 handoff validated by user (not assumed)
- 68 passed / 10 skipped (missing approved original 1785 archive fixture in the dedicated ML test location) / 0 failed.
- 120 TWSE/TPEx issuers, FY2013–2025: 37,440 source-account slot checks, 23,400 paper-component availability checks, 1,560 issuer-year rows; 6,315 provisional component values (UNAPPROVED).
- 64 archived MOPS retrospective official issuer-years from **22 issuers**, **all FY2013–2015**; 11 full-15 component years, 17 full Beneish8 and 17 full Dechow7. Original versions and public timestamps unverified. Therefore **zero** available official examples in the proposed 2021–22 validation or 2023–25 untouched test time periods.
- The previous MOPS-vs-FinMind 144 issuer/year/account comparisons had exactly **two NO_MATCH**: (a) ticker 2330 FY2014 consolidated liabilities, FinMind Dec31 448,720,754,000 vs MOPS 449,458,098,000 TWD; delta -737,344,000 TWD, 0.1641% > 0.1% tolerance. In the same year total assets, current assets and current liabilities also had smaller nonzero differences; inspect version/scope before declaring root cause. (b) ticker 2458 FY2013 operating cash flow, Q4 provider 0.5037% below MOPS annual 1,670,146,000 TWD (approx 8,412,000 TWD); four-quarter sum grossly diverges, so it cannot be substituted automatically. Both are **UNRESOLVED**, NOT evidence that companies falsified reports. Do not relax the 0.1% tolerance to make them pass.
- Phase1 remains 3 source-backed case candidates / 7 issuer-years; **zero approved real positives and zero audited negatives**. Absence of reported cases never means confirmed normality.

## New implementation

New: research/financial_ml/phase4_taiwan_dataset_gate.py, test_financial_ml_phase4_taiwan_dataset_gate.py (13 hermetic tests), verify_phase4.ps1 (single offline acceptance run).

The Phase4 gate consumes **existing local Phase3 outputs** (all the raw files stay private on the user's Windows machine):

1. finmind_provisional_paper_component_values.csv — 120 issuers, candidate only, component source string, all 15 component columns, missingness. Requires Dechow Issue be **blank** for this source cohort (never fabricated zero) and all training-admitted/outcome flags remain unapproved.
2. mops_official_15_features/literature_15_features.csv — from official SHA-preserved XBRL, *retrospective* method with 15 formula components, no certified earliest source-publication date or original filing vintage.
3. phase1_case_sources_seed.json — development-case issuer IDs 3027, 6452, 8299. Each sample is flagged as a known candidate *for independent review*, not a known negative. No judicial outcomes are leaked into numeric feature vectors.
4. phase12_integrated_verification/phase2/official/finmind_mops_annual_crosscheck.csv — both unresolved 2330/2458 source account discrepancies for numeric triage and archive hashes.

The program writes:

- **taiwan_research_split_register.csv** — 15 component input values as structured JSON per issuer/FY/source tier; strict unique key by (source tier, issuer, year); source-file SHA; full-15 availability; first-public-time = false; original-vintage-verified = false; unknown outcomes; no supervised admission. Official vs provider rows stay in different tiers even for the same issuer/year (NOT coalesced).
- **taiwan_sequence_window_admission.csv** — genuine chronological 3- and 5-fiscal-year paper feature windows, observed/missing cells, no filling zero for missing feature inputs, t only follows prior years (never future values); no model fit allowed until as-of/time/label gates pass.
- **cross_source_paper_feature_review.csv** — compare provider-conditional source candidate components and official retrospective component values only where issuer, FY and variable name match; **comparison is advisory** because original revisions and vendor mapping may differ.
- **mops_source_discrepancy_diagnostics.csv** — each NO_MATCH and BOTH_AGREE_AMBIGUOUS official annual comparison, Q4 and 4Q sums, official value, signed/absolute deltas, relative difference, same-year balance peer comparison, existing SHA hashes, the source's own FY-end Assets = Liabilities + Equity residual (where all three vendor concepts exist), alternate FY-end operating-cashflow provider types (not automatically substituted), plausible causes to review, and unresolved status. Source SHA mismatch fails closed.
- **phase4_dataset_integrated_report.json** — deterministic issuer-group and time splits, source tiers, full15 counts, the overlapping-source conflicts, no fake approved labels, original/public time gates, historical holdout and open scientific blockers.

### Two separate partition experiments, both from Taiwan data
- **Temporal-only generalization:** target fiscal year fit = 2013–2020, validation = 2021–2022, untouched test = 2023–2025. This is a DATA PLAN only; fiscal end date is **not** publication/as-of date. The same issuer can occur over time; useful for chronological future evaluation once actual filing-times and labels exist.
- **Issuer-disjoint split:** issuer seeded stable SHA grouping, 70% fit / 15% validation / 15% test *approximately*. The same issuer remains in the same group across years and source tiers. This is NOT industry-stratified or outcome-stratified; final study must check industry/year/positive case counts, survivorship bias and cohort shift.
- **Joint conservative test:** only issuer-fit AND time-fit rows enter strict fit, likewise issuer-validation/time-validation and issuer-test/time-test; other combinations marked outside_joint_evaluation. This is a *predefined study design*, not permission to use unreviewed 15 features, unknown labels or post-restatement data.

The initial SHA split seed is 20261019. It must be **frozen before using held-out labels**; adjustments to group sizes later need a new documented split version, not iterative test-peeking. Robust cross-validation and calibration are later-phase requirements.

### Critical phase-entry gates remain RED

Nothing here creates fake supervised 0/1 labels or proves an early warning model:
- No approved source-vintage-as-of feature input (both vendor provisional and official retrospective).
- No approved period-specific Taiwan event labels / audited negative controls.
- No MOPS official validation/test-year data for 2021–2025.
- 11 full official 15-feature issuer-years insufficient for credible generalization; no forced random row split.
- Previously discovered 2 MOPS vendor/official mismatches unresolved, not waived.
- No model, scaling, probabilities or trained deployment files written. US SEC or synthetic proxy auxiliary inputs later allowed **only** with Taiwan behavior compatibility and independent Taiwan test verification.

## ONE Windows ML worktree acceptance

From Financial-Risk-Alert-System-ML/fintrust_backend with ml-env active, after switching to feature/financial-ml-phase4-research-dataset-20261019 run:

powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase4.ps1

The script runs 5 regression suites and constructs all Phase4 audit outputs without any network requests. The only necessary response is:
1. phase4_taiwan_research_dataset/phase4_dataset_integrated_report.json
2. phase4_taiwan_research_dataset/mops_source_discrepancy_diagnostics.csv (2 disputes)
3. Any failing console trace

### Next phase
Fix findings from the Phase4 user acceptance along with the planned **as-of and case-label-aware supervised-data gate, baseline methods and Taiwan-only model experimentation**. Prioritize obtaining independently verified post-2020 original company filings and period-specific confirmed-positive controls before claiming real fraud-detection performance. A technical self-supervised proxy may be explored in isolation if clearly unapproved, but does not substitute for this goal.
