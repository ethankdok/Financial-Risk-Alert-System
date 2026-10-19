# Phase 11: Quarter-accurate Taiwan case intake and actual paper-feature root-cause audit
Date: 2026-10-19. Research-only branch: feature/financial-ml-phase11-quarterly-case-gap-analysis-20261019.

## Verified Phase 10 handoff
34 of 34 regressions passed. Phase10 calculated 133 of 195 15-paper-variable company-year cells from 11 validated official historic XBRL sources for 3 Taiwan case issuers. One year had all 15 components, 3 had Beneish8 complete, 1 had Dechow7 complete, zero complete 3-year 15-feature windows. Two annual source gaps: 6452 FY2020 not found and 8299 FY2012 TW-GAAP. The total 62 missing feature cells are exactly 32 absent within the 11 downloaded annual reports and 30 from the two unavailable annual source years. Leading formula gaps: Dechow RSST 10, Beneish TATA 7, Beneish LVGI 6, Dechow Issue 4, Soft Assets 3. Zero approved positives, negatives, historical original vintages, filing public times or supervised train rows. 1785 held out.

## Scientific correction in this phase
The Phase1 case seed, grounded in the archived 2023 official SFIPC statement, concerns *alleged* Kangyou 6452 consolidated reports **from FY2017 Q2 through FY2020 Q1**, NOT FY2020 full-year annual statement wrongdoing. Missing FY2020 annual data must therefore NEVER be used to conclude FY2020 Q1 did not exist or that FY2020 is a validated fraudulent annual financial filing. A court or investor-protection allegation does not confer automatic confirmed period labels.

The period audit makes 12 separate 6452 quarterly research candidates (2017Q2-2020Q1), plus two 3027 and one 8299 annual candidate with exact quarter scope pending. All 15 candidates remain UNKNOWN outcomes with original-filing and disclosure proof false. No aliases, periods or labels are invented.

## New implementation
- phase11_case_quarterly_gap_analysis.py:
  - Enforce frozen case issuer set and explicit 6452 2020 Q1 granularity.
  - Read Phase10 literature_missing_reasons.jsonl, compare all 15 variable-specific source missing counts against the observed published formula engine results, and fail closed if mismatched. Write paper_feature_missing_reason_priority.csv. Missing financial data never means 0.
  - Write case_precise_reporting_period_candidates.csv; never uses final 1785 or converts allegations to confirmed outcomes.
  - Perform no more than **one** extra official MOPS quarterly 2020Q1 request for 6452 via the original official source URL template with season=1. Existing trusted OfficialSourceFetcher handles HTTPS, bounds, and classification. RawEvidenceArchive stores content under 6452/2020Q1/content-hash, preserving bytes and SHA. Verify parsed XBRL has a 2020-03-31 nondimensional period context and consolidated statement scope before claiming a matching **retrospective quarterly source**. Source vintage and first public release remain UNVERIFIED.
  - Never pass the quarterly document to an annual normalizer or compute annual Beneish or Dechow scores from one quarter. An unavailable quarterly request is reported, not filled from FY2020.
  - Emit phase11_integrated_report.json with both official quarterly source metadata and missing component reasoning, including 62 = 32 + 30.
- test_financial_ml_phase11_case_quarterly_gap_analysis.py: 8 hermetic regression tests for precise 6452 2017Q2-2020Q1 scope, case label holdout, genuine formula missing reasons, fixed quarter URL, immutable source archive and no falsely annual scores.
- verify_phase11.ps1: single PowerShell acceptance, Phase11+Phase10+Phase9+paper formula regression, then one bounded 6452 quarterly request and report. No FinMind download, no rerun of the 11 MOPS annual sources, no ML training and no production DB writes.

## One acceptance
In a clean separate Financial-Risk-Alert-System-ML/fintrust_backend worktree, fetch and checkout feature/financial-ml-phase11-quarterly-case-gap-analysis-20261019, then execute only:
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase11.ps1

Send phase11_case_quarterly_and_paper_gaps/phase11_integrated_report.json and, only if a test fails, the relevant traceback. This new branch has been authored remotely; its tests on the user's actual 6452 quarterly source have not yet been run.

## Remaining science requirements
Archived legal case evidence and a quarter-correct source do not constitute verified original filing vintage, public filing time, earliest market revelation, or confirmed misstatement labels. No retrospectively computed paper feature may be used to claim true early detection. 8299 2012 original TW-GAAP PDF and remaining 24-account mappings still need primary original-source evidence and review. Actual Taiwan real-event outcomes and an independent negative/unknown control design are prerequisites for supervised train/validation/test. Preserve 1785 as an untouched pre-2016 final historical replay.
