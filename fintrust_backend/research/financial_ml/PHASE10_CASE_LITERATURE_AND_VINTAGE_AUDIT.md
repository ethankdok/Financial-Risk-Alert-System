# Phase 10 — Actual Beneish/Dechow 15-paper-feature extraction on known Taiwanese case financial reports

Date: October 19, 2026. Dedicated branch feature/financial-ml-phase10-case-literature-vintage-audit-20261019.

## User-verified Phase9 result
- 37/37 regressions passed (Phase9 10, previous official batch 5, Phase8 10, Phase1 12).
- Of 13 unique development-case issuer/fiscal-year requirements: **11 official MOPS historical annual XBRL candidates fetched, SHA-verified and validated**, one official consolidated filing returned filing_not_found, one FY2012 8299 was explicitly rejected as pre-TIFRS legacy requiring its original financial PDF.
- Historical original-first-published financial versions certified: **0/13**. Original public-time proof: 0; first market misstatement revelation time: 0; confirmed positive/negative issuer-year training labels: 0; supervised admission: 0.
- 1785 still reserved exclusively for a final pre-2016 blind historical replay, and absolutely not included in this research training/feature selection branch.
- The Phase9 summary did not disclose the exact identity of the 1 missing regular MOPS filing, so Phase10 will read the actual per-year CSV instead of guessing.

## What Phase10 adds (not merely another "plan")

**phase10_case_literature_vintage_audit.py**:
1. Verify the frozen 13 case issuer-year registry derived independently from Phase7, and reject any promoted historical-original status, approved label, source SHA mismatch or 1785 contamination in Phase9.
2. Call the ORIGINAL research/financial_ml/literature_dataset.produce(...) engine to parse the **11 actual Phase9 MOPS XBRL byte archives** and compute the exact original Beneish 1999 8 features, Dechow et al. 2011 Model1 7 features wherever their real account evidence allows. Uses the unchanged original TIFRS mapping, missing-reason registry and original formula engines; no unapproved FinMind alias injections or manual financial-zero imputations.
3. Write phase10_case_official_paper_audit/official_case_literature/literature_15_features.csv and literature_missing_reasons.jsonl, plus:
   - phase10_case_official_paper_features.csv: every one of 13 issuer-years, exact 15 component vector, Beneish/Dechow available retrospective scores, normalized input original SHA, source version identity, source-family and every vintage/label/training field marked unapproved.
   - phase10_case_missing_features.csv: missing feature *per year and per original paper variable*, distinct FY2012 pre-TIFRS vs missing official downloaded XBRL vs incomplete paper component inputs. Missing is NEVER financial zero.
   - phase10_case_three_year_windows.csv: 7 candidate affected target years; each requires t, t−1 and t−2, with 45 possible source feature cells and exact gaps. A computed retrospective window is NOT a safe train/test input without earliest historical publication time and original first-filing version.
   - phase10_integrated_report.json: source status breakdown and exact company/year for the previously unidentified filing_not_found, actual original-paper feature counts, full 15 versus partial 8/7 coverage, missingness, 3-year readiness, source manifest SHA, 0 approved positive/negative and 0 certified original period evidence.
4. All processing offline using already-downloaded files: no network, no production DB writes, no future model retraining or resplitting (Phase4 frozen split remains intact).
5. Hermetic tests include spoofed approved label and false-original flag rejection, SHA mismatch, missing FY2012 source, seven backward-only 3-year windows and no holdout leakage. Built-in literature dataset tests and Phase9/Phase8 regressions rerun in same acceptance.

## Important evidence distinction
A period-matched retrospective numeric Beneish M-Score may be calculable on the post-correction 2026 MOPS archive and still provide **zero** evidence that someone running in 2015 could flag the original 2015 financial filing. Historical version and first-publication proof remain separate, mandatory gates.

The long-term workstreams are still original PIT first-filing and event notices; 24 component mapping and confirmed positive/negative Taiwan issuer-years; chronological/company-isolated supervised and literature baseline evaluation on real Taiwan data; final untouched 1785 blind historical replay. There is no honest fixed percentage-complete or predetermined exact remaining count of script phases, because primary-source original 2012/2013 reports and public-time proof can be a fundamental availability blocker.

## Single Windows execution (one command)

In clean Financial-Risk-Alert-System-ML/fintrust_backend with ml-env active, after checking out this branch:

    powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase10.ps1

This runs new and existing tests and then reuses all Phase9 MOPS archived case XBRLs, computes true original literature formula outputs and produces one report. No MOPS or FinMind download, no software deployment. Return only:
- financial_ml/phase10_case_official_paper_audit/phase10_integrated_report.json
- if the Phase9 missing source needs precise review, phase10_case_official_paper_audit/phase10_case_official_paper_features.csv or the terminal exception excerpt.

Unmet vintage/label gates should not trigger repeated micro-commands. If a failure is found, repair it in the next phase alongside source-publication evidence and real-label research.
