# Phase 9 — official MOPS case-year financial statement candidate retrieval

Date: October 19, 2026. Branch: feature/financial-ml-phase9-case-mops-xbrl-recovery-20261019.

## Verified Phase8 handoff
- 42/42 regression tests passed.
- Official legal source archives: 4/4, with content identity checks; not automatically labeled financial misstatement positives.
- Original, as-first-published, pre-correction report versions: 0/13 issuer-years independently verified.
- Original financial report release times: 0; confirmed first-public-event timestamps: 0.
- Approved Taiwan positive issuer-year labels: 0/7 potential periods; reviewed negative controls: 0.
- 1785 strictly held out.
- 13 unique original report issuer-year demands: 3027 2013–2016 (4), 8299 2012–2014 (3), 6452 2015–2020 (6). There were 21 overlapping target/prior-year window demands.

## What this Phase9 implementation really does
It reuses existing historical_audit.sources.OfficialSourceFetcher and the already-developed financial_ml.official_batch.acquire, whose bounded work and immutable SHA storage have previously been tested on other Taiwanese public companies.

- Validate frozen 13 issuer-year source requirements and current Phase8 outcome/PIT rejection flags.
- Reconstruct twelve safe, exact, official MOPS annual XBRL URLs for fiscal years 2013–2020, at most twelve requests per run. Reuse existing archive by SHA on retry.
- Reserve the one legacy 8299 FY2012 as PRE_TIFRS_GAAP, not a presumed TIFRS document. It needs a separately located contemporaneous official PDF and appropriate old-accounting-standard treatment.
- Attempt bounded HTTP retrieval with original OfficialSourceFetcher 2s spacing / 2 attempts, retaining source status and content digest. Documents that parse as consolidated TIFRS financials yield candidate normalized accounting fact rows and account scope/revision diagnostics.
- Write phase9_case_mops_xbrl_candidates/phase9_integrated_report.json, phase9_case_mops_version_review.csv and the original research immutable content-addressed MOPS source archive + acquisition manifest.
- Refuse 1785, unknown issuers, duplicate/missing 13 source needs, unapproved 0/1 label promotion and hash mismatch. No production database, Flask/FastAPI or model state writes. Not a normal/negative-label sample creator.

All 12 modern MOPS documents remain explicitly UNVERIFIED AS HISTORICAL ORIGINAL even if retrieved and parsed. Downloading a fiscal 2014 report today cannot establish which filing version investors saw in 2015. SHA-256 shows bytes are preserved from TODAY onward; it does not prove original-publication timestamp or that the bytes predate later restatements. No source from this phase alone enters real fraud supervised training. Later 2025 judicial findings must not be assumed known in FY2015.

## Remaining work toward true ex-ante financial misstatement prediction
A. Original first-published public financial report vintages, exact release and first-disclosure times for case years and a broader comparable Taiwanese company cohort.
B. Accounting item mapping across 24 paper base accounts and complete Beneish 8 + Dechow 7, plus independently reviewed affected issuer-year labels and audited negative/unknown sample distinction.
C. Proper Taiwan-only chronological and issuer-disjoint supervised training/validation/untouched test, literature M/F-score comparison and calibrated model ablations.
D. Final untouched historical 1785 replay using actually retrievable pre-2016 financial evidence and a historically available training-knowledge cutoff.

These FOUR are outstanding research workstreams, not a promise that exactly four more scripts will make the scientific evidence appear. If original first-published MOPS files cannot be recovered, retrospective risk analysis may still be possible but authentic prior-to-public-disclosure performance cannot be scientifically claimed.

## One local user acceptance
In a clean Windows Financial-Risk-Alert-System-ML/fintrust_backend ML worktree, fetch and switch to the Phase9 feature branch, then run once:

    powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase9.ps1

The script runs Phase9 new ten tests, existing official-batch regression, Phase8 and Phase1 tests, then attempts the twelve official case annual XBRL source retrievals. The 2012 source remains an explicit separate manual-path item. It does not rerun 120-firm FinMind API calls, run another ML training sweep or touch production DB.

Return only phase9_case_mops_xbrl_candidates/phase9_integrated_report.json and test traceback if any. If MOPS source errors need attention, also return phase9_case_mops_version_review.csv. Investigate failures alongside next phase source vintage evidence work, not separate micro-retests.
