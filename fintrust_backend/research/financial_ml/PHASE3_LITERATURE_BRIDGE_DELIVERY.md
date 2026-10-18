# Phase 3 | Taiwan paper-variable source coverage and formula bridge (2026-10-19)

## Empirical Phase 1+2 handoff (validated on Windows)
- All 36 integrated regressions passed.
- 120/120 issuer trios saved: 360 archives, of which 340 nonempty and 20 empty provider responses; 0 quarantined corrupted archives, 113 issuers with all three nonempty statements.
- 1,560 issuer-years, 18,720 source candidate account cells, 14,392 populated values, 1,080 full twelve-account issuer-years.
- 863 complete three-year windows (93 issuers) and 685 complete five-year windows (83 issuers), all based on UNAPPROVED source candidate amounts.
- Existing MOPS comparison on 4 issuers × 3 years: 144 candidates, 60 sum-of-four quarters, 71 December 31 instant, 11 Q4 cumulative, 2 NO_MATCH.
- Phase1: 3 candidates, 7 issuer-year candidates, 5 source references, zero approved positive/negative outcome labels and no verified public first revelation time.
- 1785 strictly remains an untouched final historical event holdout.

## Phase3 development: phase3_literature_bridge.py

Reuses the original published Beneish (1999) eight-variable and Dechow et al. (2011) Model 1 seven-variable formula engines; the 24 COMPUSTAT-to-TIFRS underlying mappings and the existing official-XBRL literature_dataset.py. New code does NOT replace the original arithmetic with guessed proxies.

One locally runnable entrypoint checks all cached 120-company FinMind archives, period/type/number contracts and annual data constraints, then outputs:
1. finmind_24_account_candidate_coverage.csv: 24 per-year literature base-account candidate evidence rows with SHA, names, missingness. Only one_of single-source items are provisionally converted to candidate annual amounts. Sum/difference rules remain pending, missing is not 0. FinMind aliases such as TotalAssets, CostOfGoodsSold and Depreciation are unapproved candidates, not certified accounting equivalences.
2. finmind_15_feature_feasibility.csv: paper-dependency-aware t,t-1,t-2 input availability for all 15 variables, including blocked Issue (absence of issuance is NOT proof of zero).
3. finmind_provisional_paper_component_values.csv: original shared literature component arithmetic produces available descriptive candidate values when supported by the provisional input lines. Every record states candidate-only / no training admission / UNKNOWN labels, and preserves reasons for missing components. No claimed M-Score or F-Score from unapproved FinMind source; no 15 approved training features fabricated.
4. mops_official_15_features/ : actual source-locked official archived XBRL -> Beneish/Dechow 15 component calculations from existing literature_dataset.produce() along with missing reasons and score readiness. Historical filing original versions and public timestamps remain unverified, so retrospective outputs are not automatically allowed in 2016-asof research.
5. mops_reconciliation_review_queue.csv: reports the two unsupported or ambiguous vendor-vs-official fiscal comparisons rather than inventing a preferred value.
6. phase3_integrated_report.json: comprehensive feature source and official source status, missingness, component counts, and the audit gates that remain blocked.

Input policy: provider year-end dates are not official-publication timestamps; quarter-to-annual semantics are source/account/year candidates. FinMind ratio *_per fields not monetary. No unchecked receivables aggregation, debt financing, preferred-stock zero, SG&A conflation or emission of false issuance=0. Data never enter training and neither Taiwan negatives nor final 1785 case are inferred.

## Remaining evidence work after running program
- Official MOPS source and TIFRS/GAAP method-owner review for multi-source or period-varying literature input definitions; separate selling and administrative costs, debt, preferred share evidence and Issue.
- Resolve the two cross-source numeric NO_MATCH instances using their original filings, fiscal scopes, periods and version dates. Expand official MOPS numeric checks beyond current 4 companies and 12 company-years.
- Phase1 judicial and corporate announcement original evidence bytes, case affected periods, first public exposure timestamps, human signoff and auditable Taiwan control cohort. Zero approved real labels => zero supported supervised fraud metrics.
- Original-filing historical asof evaluation and Taiwan-only fitting/validation/test cohort before Phase4 training; US/synthetic only auxiliary and Taiwan-domain gated.

## ONE user-side verification command
Execute from Financial-Risk-Alert-System-ML/fintrust_backend after fetching/switching to this branch:

powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase3.ps1

The script first runs Phase3 + original literature formula + Phase2 regression tests, then processes the 120 already-cached company sources and official XBRL evidence. No network request, no DB write and no model fitting.

Return only phase3_literature_integrated/phase3_integrated_report.json and, if any, mops_reconciliation_review_queue.csv; include failures if tests stop. Review any gaps in the next round alongside Phase4 work, as requested; do not ask for repetitive intermediate shell executions.
