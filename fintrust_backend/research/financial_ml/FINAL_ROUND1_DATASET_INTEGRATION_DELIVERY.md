# FinTrust ML finalization, Round 1: training-data source integration

Date: 2026-10-19. Branch: feature/financial-ml-finalization-round1-dataset-integration-20261019.

## Prior factual baseline

Phase14 passed 41/41 tests. Twelve comparison companies in ten industries supplied 132/144 official quarter-source reports, with nine not found and three invalid content. The 22,055 TWD original quarterly financial observations and 13,819 QoQ/YoY changes are individual accounting facts and linked features, NOT independent company-quarter cases.

Phase12 retrieved all twelve 6452 development-case quarter reports from 2017Q2 to 2020Q1, kept separate from present-market selection. Phase4 120 current issuers across FY2013-2025 supplied 1,560 provisional FinMind paper-feature company-years and 64 overlapping-retrospective official MOPS tier rows. Phase5 four anomaly engines fitted 392/28/30 company-year rows using only six adequately covered actual paper candidates, labels all unknown. Seven further financial next-year regression models fitted 192/82/125 overlapping-company yearly windows using twelve different provisional FinMind AMOUNTS, not the 15 original published ratios. Their MSEs are NOT percentage classification accuracy. The true supervised fraud-positive and reviewed-normal counts remain ZERO. Final light 1785 is untouched.

Phase10 three-case annual paper-feature evidence had 13 required fiscal year sources: 11 XBRL retrieved, one 6452 full FY2020 annual not found (separate 2020Q1 report successfully archived) and one 8299 FY2012 different-accounting-GAAP historical legacy. 133/195 paper feature cells computed, one full 15 case fiscal year, no original filing first-public version or known-period outcome approved.

## New functionality this branch

Module fintrust_backend/research/financial_ml/final_round1_dataset_integration.py is a strict, network-free, read-only evidence registry. DO NOT simply vertically concatenate differing financial data definitions.

DATA LAYER A: Annual twelve FinMind financial amounts (FY2013-2025).
- Require original frozen 120 current-listed company cohort, company-year uniqueness and 12 metric names from original annual_panel_readiness.METRICS.
- Recompare ALL 18,720 staged annual source cells from finmind_scaled_annual_candidates/finmind_annual_candidate_lines.csv with original derived company_year_candidate_panel.csv. No fabricated missing amounts or zero imputation; no source/file replacement.
- Derive a canonical 120x13 issuer/year candidate feature inventory. Freeze existing Phase4 hash-based company split and time split by target year. Compute realistic three- and five-year history plus target completeness windows, separating incomplete sources from genuine numeric zeros.
- Output annual_12_amount_candidate_index.csv and annual_12_amount_sequence_windows.csv. These are AMOUNT regression-proxy sources, NOT Beneish/Dechow 15.

DATA LAYER B: Original Beneish 8 + Dechow 7 source-tier separated annual features.
- Re-evaluate Phase4 complete company/year/tier register. Verify each of the 1,624 existing feature vectors against the original Phase3 exact source CSV values AND frozen SHA-256 for MOPS official retrospective and FinMind provisional data independently.
- Any disputed vintage, source alias or duplicate remains separate; the same company/year in both MOPS and FinMind is NOT a new independent company sample. No unreviewed company is a healthy negative.
- Compute per-paper-variable fit-period source coverage, NOT feature importance, using company-disjoint and temporal-fit intersection only.
- Output annual_original_15_paper_candidate_index.csv and paper_feature_fit_coverage.csv.

DATA LAYER C: Official 3027/8299/6452 known litigation candidate separate annual case sources.
- Read exactly Phase10 thirteen original fiscal-year required case records. Verify eleven official retrospective filing SHA identifiers against the Phase9 original source acquisition manifest. FY2012 8299 remains distinct pre-TIFRS GAAP; absent FY2020 annual is not evidence of absent 2020Q1.
- Do NOT automatically transform later official legal allegations into labels 1, or compare with unreviewed normal labels 0. Never put development cases into reference healthy training cohort.
- Output case_official_15_paper_candidate_separate.csv.

DATA LAYER D: Official quarter comparison cohort and separate 6452 development-case quarters.
- Verify 144 selected present-day issuers/quarter source index positions for twelve issuers, against the original acquisition manifest and each locally preserved raw-file SHA, including quarantined documents.
- Validate twelve source quarters from 6452, sourcing the final 2020Q1 from the distinct Phase11 immutable archive and earlier 11 quarters from Phase12 archives, all SHA-256 rechecked.
- Read 22k+ sources of TWD-only quarterly observations and group exactly by original issuer, full taxonomy URI and concept name and accounting measurement grain. Do NOT mix annual/year, end-of-quarter stock, quarter-flow and Jan-to-date accumulated flow. Quarterly dense-feature coverage is per issuer across independent quarter positions, not per XBRL fact.
- Output quarterly_issuer_period_source_index.csv and quarterly_feature_coverage_by_issuer.csv.

ACTUAL INTEGRATION REPORT: final_round1_integrated_ml_dataset/round1_dataset_readiness_report.json. This gives actual annual full amount vectors, source-separated original paper 15-feature coverage, strict time+issuer-disjoint 3yr/5yr candidate windows, 156 issuer/quarter positions separated by comparison/case, yearly label/history holdout gate, source-status errors and original input SHA manifests. All source labels remain UNKNOWN and training_admitted false. No HTTP, no external model fitting, no production SQL/Firestore/API writes and no 1785 final holdout access.

## 2026-10-19 consolidated closeout Stage1 hardening

This branch incorporates the distinctive **fit-only sparse quarterly model-input view**
from the parallel Stage1 readiness work without duplicating its 600-line annual,
paper, and official-quarter ingestion procedures. Original Round1 remains the
single source-of-truth verifier for original paper feature CSV hashes, the 13
known development-case annual records, and the separate 6452 quarterly archive.

- Fixed an integration error: distinct `other_duration` facts with different
  duration starts are legitimate XBRL observations but cannot be collapsed
  to a unique quarter feature. They are excluded **before** duplicate-concept
  checks; distinct standard-grain duplicates still fail closed.
- Reuse the existing quarterly source-index and SHA verification, and reuse
  the same quarterly candidate read pass. Select up to 24 distinct
  exact-QName + accounting-grain features on **fit issuers and fit
  2017Q2-2018Q4 periods only**, with at least 3 fit issuers per feature.
  No taxonomy-name guessing, mixed year/quarter measurement, imputation,
  legal outcome labels, or model fitting.
- New files from the existing consolidated execution:
  `quarterly_fit_selected_feature_dictionary.csv` and
  `quarterly_sparse_feature_matrix.csv`. The matrix has 144 planned
  comparison company-quarter positions, not 22,055 independent labels.
  Each feature has an explicit `_observed` mask; actual numeric zero stays
  an observed zero while missing values stay blank. The 6452 case and
  3027/8299/1785 are excluded from the comparison matrix.
- Added four focused hermetic regression scenarios to the existing Round1
  test module: nonstandard-duration repeats, test-only taxonomy exclusion,
  observed zero, and exact QName identity disagreement.
- The prior Stage1 alternate branch is kept untouched for audit, not
  merged as another parallel duplicate production path.

**Acceptance status:** code committed to the remote research feature branch.
The new regressions and user-local source integration have **not been executed**
in this ChatGPT session. Do not report this as real-data PASS until the
Windows verification command below returns success and the JSON report is
reviewed. No production, release, or teammate branch was modified.

## One execution on user's actual environment

In clean Financial-Risk-Alert-System-ML/fintrust_backend using existing ml-env, fetch/check out this branch and run:
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_final_round1_dataset.ps1

Default: the script executes seventeen hermetic Round1 tests (the prior thirteen plus four focused regressions) and ONE real-data offline integration run. This avoids needlessly repeating earlier accepted Phase4/13/14/model suites. To rerun all those previous regression suites as well, pass -FullRegression. It fails closed if any previously derived source SHA or register disagrees with original records.

Send one report:
Financial-Risk-Alert-System/fintrust_backend/data/financial_ml/final_round1_integrated_ml_dataset/round1_dataset_readiness_report.json
If a test fails, add its error and traceback, not all original raw archives. The branch is remotely authored, not yet user-local tested.

## Fixed next rounds and release gates

Round2: reviewed true positive/negative/UNKNOWN affected periods, original-as-first-public filing and first-disclosure time, and credible original Beneish/Dechow source mapping for RSST, TATA, LVGI, Issue.
Round3: Genuine supervised fraud classification ONLY if independent labels plus historically available source versions support valid splits; compare published Beneish/Dechow baseline with Logistic, RF, CatBoost and conditional temporal neural models. Output Precision/Recall/F1/PR-AUC and confusion matrix only when ground truth exists. Otherwise retain explicitly unlabeled novelty warning evidence, never false 99% accuracy.
Round4: SHAP/permutation feature contributions, frozen pre-2016 final 1785 case as-of replay if documents and label evidence support it, technical handoff and faithful presentation.

This code is the FIRST agreed dataset finalization workstream, not another endlessly proliferating Phase.
