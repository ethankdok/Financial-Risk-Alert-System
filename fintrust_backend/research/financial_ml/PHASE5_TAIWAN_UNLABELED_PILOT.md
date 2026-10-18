# Phase 5 — Taiwan-only provisional literature-feature anomaly research pilot

Date: 2026-10-19. Scope: offline research only. Phase4 acceptance provided by user: all 48 regression tests passed; data report successfully generated. The user requests one complete phase of development followed by ONE local verification, with defects repaired alongside next phase.

## Actual source-backed Phase4 handoff
- 120 Taiwan FinMind candidate companies × FY2013–2025, 1,560 issuer-years; plus 64 retrospective official MOPS issuer-years from 22 companies, including overlaps: 138 distinct Taiwanese issuers, 1,624 independent source-tier rows.
- Complete fifteen literature features: FinMind 0 / 1,560; MOPS 11 / 64. Only one potentially 15-complete three-year window exists across the source tiers; zero five-year windows.
- MOPS study years limited to 2013–2015. Consequently zero official cases in the initially suggested 2021–2022 validation and 2023–2025 held-out future fiscal-year periods.
- Labels: 0 approved positive, 0 approved negative. No supervised fraud-detection test set is valid. Company 1785 excluded from all development.
- Dispute A: TSMC ticker 2330 FY2014 FinMind Liabilities 448720754000 versus MOPS 449458098000 TWD; difference -737344000 (0.16405%). Vendor 2014 Q4 TotalAssets 1495049086000, Liabilities 448720754000 and Equity 1046328332000 satisfy A=L+E exactly. This internal identity DOES NOT prove accounting vintage/filing-scope consistency with official annual XBRL.
- Dispute B: ticker 2458 FY2013 FinMind operating cash flow 1661734000 versus MOPS 1670146000 TWD; difference -8412000 (0.50367%). Both vendor operating cashflow/net-inflow aliases show 1661734000 and vendor cash-received-through-operations 1784601000 is not an equivalent net amount. Both discrepancies stay UNRESOLVED; 0.1% threshold unchanged. Do NOT convert these differences into financial-fraud labels.

## Phase5 new code

Module research/financial_ml/phase5_taiwan_unlabeled_pilot.py reads the existing Phase4 Taiwan feature/split register. It does NOT use Phase4's unknown labels as normal examples. It validates frozen study conditions, excludes the reserved 1785 case and known 3027, 6452, 8299 candidate case issuers, and refuses any prematurely approved source flags.

Only FinMind provisional source-tier evidence is used for exploratory learning. Retrospective official MOPS source-tier records remain separate and never merged with vendor figures. Original 15 published Beneish/Dechow feature names are preserved; unverified d_issue is always blank, and fewer than four observed components per record causes that record to be excluded.

Two-axis strict split: issuer-disjoint SHA cohort AND fiscal year must agree. Training through FY2020, validation FY2021–22, untouched test FY2023–25. Validation/test companies never occur in training; no use of 1785 or candidate cases. Reproducible frozen seed 20261019.

Training-only preprocessing selects features with sufficient coverage, then applies median input imputation together with a binary missingness mask; signed log1p and RobustScaler are fitted to training data ONLY. Imputed model inputs are not fabricated financial zeros or retroactive financial source records. A missing Dechow Issue is never automatically set to zero.

Four distinct technical anomaly proxies fitted on the same source and split:
1. Isolation Forest with 250 trees.
2. Local Outlier Factor with novelty score.
3. RBF One-Class SVM.
4. PCA reconstruction residual.

Threshold for comparing score distributions is training-only 95th percentile, not validated fraud probability. Validation/holdout output reports only fraction scoring above this threshold and unknown-label proxy scores. No fraud AUROC, PR-AUC, Recall@K, F1 or precision may be claimed.

Hard coverage check: at least 30 fit rows spanning at least 8 companies, 5 validation and 5 held-out rows, at least 3 fit-supported genuine paper components. If unmet, the program outputs a BLOCKED report without training a model. This avoids forcing full fifteen-variable sequences where zero exist.

Output in phase5_taiwan_unlabeled_pilot directory:
- phase5_exploratory_report.json
- unlabeled_method_comparison.csv when fitting is permitted
- unknown_label_holdout_proxy_scores.csv when fitting is permitted

No network requests. No changes to production SQL, Cloud Run, Flask or FastAPI. The 2023–2025 holdout scores are purely exploratory, and must NOT be used for parameter selection.

## One terminal command

From clean dedicated Windows ML worktree after checking out feature/financial-ml-phase5-unlabeled-literature-pilot-20261019:

powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase5.ps1

It executes the 10 new Phase5 unit tests and Phase4/3/1 regression tests and then tries the offline four-architecture research pilot on the already acquired Phase4 data. If source coverage is insufficient, the resulting report explicitly explains the scientific block. The program has not been run on the user's actual CSV in this GitHub development environment: local acceptance is still required.

Return only the phase5_exploratory_report.json, plus terminal failures if any.

## What still blocks the true research target

This is not yet an ex-ante Taiwan financial misstatement model. Needed:
1. Original official statements with publisher timestamps and revised/original filing-vintage traceability.
2. Accurate verified mapping of all 24 base accounts and Dechow Issue.
3. More official paper-feature issuer-years through modern holdout periods.
4. Independently validated material misstatement positives and audited Taiwan comparison/unknown-case periods.
5. Literature M-Score/F-Score baselines, supervised CatBoost/XGBoost/RF/Logistic, and suitable GRU/LSTM/TCN/Transformer only after labeled, original-asof train/validation/test are viable.
6. Frozen final 1785 historical replay with 2016-earlier model knowledge, especially original pre-restatement FY2013–15.
US real SEC data or synthetic auxiliary features may be used for pretraining only after GAAP/TIFRS feature comparability and independent Taiwan validation/test ablations.
