# Phase 6 — Taiwan official case evidence collection and ex-ante review gate

**Development date:** 2026-10-19. **Branch:** feature/financial-ml-phase6-case-evidence-recovery-20261019. **End goal:** A reproducible model of the risk that an originally filed Taiwan corporate financial statement materially misstated financial facts, allowing a truly out-of-sample pre-2016 historical replay of 1785 when evidence becomes available.

## Phase 5 verified handoff (from user-provided terminal and JSON)

All Phase5 45 regressions (11+13+9+12) passed. Actual unsupervised technical pilot fitted **4 different algorithms** on real Taiwan but UNAPPROVED literature-input candidates:
- training **392 company-years / 60 distinct issuers**
- validation **28 / 15**
- independent holdout **30 / 10**.
Only **6 of 15** original Beneish/Dechow features were fit-supported: b_GMI, b_AQI, b_SGI, b_DEPI, d_ch_inv and d_ch_roa. d_issue and eight other variables were excluded for absence/coverage.
- IForest: validation fraction above fit P95 0.0000, holdout 0.0000
- LOF: validation 0.035714, holdout 0.066667
- One-Class SVM: validation 0.071429, holdout 0.133333
- PCA reconstruction: validation 0.035714, holdout 0.066667

**These are scores above a training-only proxy cutoff, not correct detection rates, classification accuracy, evidence of wrongdoing or model discrimination.** All 30 holdout issuer-year labels remain UNKNOWN. Do not pick the highest flag-rate algorithm as best. Notably the 4 model scores are not calibrated fraud probabilities, and current finance-source as-of evidence is absent.

## Why Phase6 prioritizes cases/source evidence over another proxy model

Phase1 outcomes still: three candidate cases / seven candidate issuer-years / **0 approved material-misstatement positive labels** / **0 audited true negatives**, so no scientifically grounded target to optimize. The 120-company annual feature data are FinMind candidates with incomplete historical original-vintage proof. The official MOPS fifteen-feature engine covers FY2013–15 only, and just 11 complete issuer-years. Original pre-restatement 1785 FY2013–15 must stay reserved.

This phase builds the first **independent official-source collection and review pipeline**, so legal decisions, originally published investor notices and pre-correction original financial filings can eventually be connected.

### Deliverables

- phase6_official_evidence_recovery.py: legally sourced registry review and optional HTTPS retrieval of only known specific official sources in phase1_case_sources_seed.json, strictly allowlisting two hostnames (judgment.judicial.gov.tw, www.sfipc.org.tw), validating redirects/size/content type and company presence, SHA hashing and immutable on-disk caching. Secondary news is excluded by policy. No general crawling or arbitrary URLs.
- official_case_bytes/[case_id]/[source_id].html: raw-source bytes if available by HTTPS, SHA immutable and no replacement on corruption.
- official_case_bytes/[case_id]/[source_id].json: collection UTC time, source URL, SHA, content type, source publication UNKNOWN, period-specific label not approved.
- official_case_source_register.csv: per source download/cached/error state, digest, whether displayed company appears, and explicit no-fraud-label flags.
- taiwan_misstatement_review_queue.csv: 3027 2015–16, 8299 2014, 6452 2017–20, all UNKNOWN. Specifies each fiscal year's missing original MOPS filing, original publication time, **earliest public market disclosure**, court material finding versus allegation, and independent methodology review. No newly dated announcement invented.
- phase6_evidence_readiness.json: local archive successes / failures / outstanding review issues / 0 approved labels.
- test_financial_ml_phase6_official_evidence_recovery.py: ten hermetic no-network tests including idempotent byte archive, corruption without overwrite, official-vs-news, URL/redirect safety, holdout and never fabricating training outcome labels.
- verify_phase6.ps1: one Windows command executes Phase6+Phase1+Phase5 regression and the optional small real official-HTTPS batch. No FinMind downloading, no training, no production database writes.

**Source links verified publicly as official navigation anchors:**
1. 3027 Taipei District Court 113 Jin-Su 29 judgment 2025-04-30: https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPDM%2C113%2C%E9%87%91%E8%A8%B4%2C29%2C20250430%2C1
2. 8299 High Court 113 Jin-Shang-Geng-Yi 2 2025-01-15: https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPHV%2C113%2C%E9%87%91%E4%B8%8A%E6%9B%B4%E4%B8%80%2C2%2C20250115%2C1
3. 8299 Supreme Court 114 Tai-Shang 859 judgment 2025-11-19, **vacated and remanded civil matter**. Separate criminal fraud/misstatement judgment mentioned as final, but original criminal judgment still must be independently archived: https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPSV%2C114%2C%E5%8F%B0%E4%B8%8A%2C859%2C20251119%2C1
4. 6452 official SFIPC litigation statement (civil claim, NOT final judicial verification of every FY2017–20 positive): https://www.sfipc.org.tw/News_Content.aspx?n=7458&s=571
5. 8299 news.pts.org.tw (secondary context only, not archived by this official collector).

MOPS official research query portal for historical major disclosures and revised filings: https://mops.twse.com.tw/mops/web/t120sb02_q10 . **Do not confuse a current revised MOPS financial statement with the exact version originally filed years earlier**. Finding an official court URL, or archiving a 2025 court judgment, does not prove an input or positive label was knowable before the company's first public disclosure. It also does not mean model trained as-of historical time knew the ultimate court outcome.

### IMPORTANT completion boundaries

**Phase6 engineering** can be tested and source references archived on the user's Windows machine; no one can responsibly label the 7 issuer-year candidate rows as confirmed without reviewing the actual archived paragraphs, appendices and corresponding original fiscal filings.
**Phase6 scientific outcome labels remain pending** until the following are actually resolved:
- independently verified legal source text with relevant precise affected periods and distinction between party claims and judicial holdings
- original MOPS quarterly/yearly report originally available and identifiable by bytes/hash/version, not the later corrected filing
- market notice timestamp and earliest relevant public disclosure, evidenced by original announcement
- distinct training-outcome known-at timestamp (not judgment document date or event fiscal-year end)
- independently reviewed control/unknown periods and split/followup logic
- 1785 kept completely unexamined for model selection and only used for later blind external case test.

US SEC real data, or synthetic data with explicitly synthetic outcomes, may be used only as supporting pretrained models if GAAP/TIFRS features and Taiwan business behavior are validated and held-out Taiwan real-label performance substantiates transfer.

## ONE final user-side verification

Use the clean separate Windows ML worktree Financial-Risk-Alert-System-ML/fintrust_backend and fetch/switch this branch, then:

powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase6.ps1

The script uses standard-library HTTPS to attempt only the four official source pages on its first run. If TLS/network site restrictions make a source inaccessible, the report will say RETRIEVAL_FAILED_NO_LABEL, not pretend archived. All cached raw bytes are protected; reruns reuse their hashes, but according to user workflow don't rerun without first inspecting report.

Return only:
- financial_ml/phase6_taiwan_case_official_evidence/phase6_evidence_readiness.json
- financial_ml/phase6_taiwan_case_official_evidence/official_case_source_register.csv IF any source failed/was unverified
- terminal test failure excerpt, if any.

No need to upload all judicial-source raw HTML files, and absolutely no need to upload provider API keys or user credentials. If a source refuses automated access, use existing phase1_archive_evidence.py to archive a manually downloaded copy in a later evidence review workflow. Do not attempt unsafe bypass of access protections.

## Next phase sequencing

Review any Phase6 failed source evidence alongside the next development round's **original-MOPS-filing-asof extraction and human-audited outcome-label approval gateway**, not another round of unlabeled model leaderboard optimization. Only once Taiwan real case outcome labels and actual original-vintage features are available should use of supervised XGBoost/CatBoost, Logistic and GRU/TCN/LSTM be called validated fraud prediction. Gradual partial progress can still be reported without overstating readiness.
