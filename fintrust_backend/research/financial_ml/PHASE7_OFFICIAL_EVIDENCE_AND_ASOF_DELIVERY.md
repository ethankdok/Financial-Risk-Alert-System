# Phase 7 | Official case evidence retry, exact docket identity and original-MOPS filing-asof gaps

**Development 2026-10-19**. Dedicated branch: feature/financial-ml-phase7-official-evidence-diagnostics-20261019.

## Phase 6 actual user-side validation (not an inferred success)
- 10 Phase6 + 12 Phase1 + 11 Phase5 tests **33/33 passed**.
- Four official links requested; **none archived**: three RETRIEVAL_FAILED_NO_LABEL, one DOCUMENT_IDENTITY_UNVERIFIED_NOT_SAVED. One secondary media link intentionally excluded. Official labels positive=0, negative=0, first disclosure=0, original pre-revision financials=0.
- The previous Phase6 JSON summarizes statuses but did **not** contain per-source error diagnosis; cannot determine which three requests failed (TLS/HTTP/block/redirect) from aggregate alone. New report includes source_id and bounded error reason.
- Public investigation (no changes to target labels): official judiciary court pages for 3027 and 8299 are indexed as live results. SFIPC official 2023-05-12 announcement uses **康友公司**, not **康友-KY**. Exact full company display name alone was too restrictive. 8299 Jan 2025 civil judgment was vacated/remanded by Supreme Nov 2025, while a separate 2022 criminal judgment is described as final. NEVER mix them.
- Source case observations are retrospective candidates only. A 2025 court ruling cannot be treated as known to the 2015 prediction model.

## Repairs merged from previous Phase (no repeat micro-runs)
Changed phase6_official_evidence_recovery.py:
- Allow specifically curated issuer text identities: 3027 盛達電業/盛達公司, 8299 群聯電子/群聯公司, 6452 康友公司/康友-KY/康友製藥; no unbounded fuzzy search.
- Decode judiciary pages using declared HTML charset and fallback utf-8, UTF-8 BOM or CP950/Big5. Raw byte hashes are invariant; no source data rewrite or dropped invalid document.
- Include **per_source_diagnostics** in Phase6 JSON so HTTP failures vs body identity rejections can be diagnosed without requesting the user upload additional CSV by default.
- All labels still UNKNOWN and no production DB writes.

## Phase7 development artifacts

**phase7_evidence_asof_audit.py**:
1. Optionally reattempt at most the **four pre-reviewed official URLs** using existing phase6 bounded downloader, with 2s pacing on actual Windows run. Does NOT crawl arbitrary sites, bypass login/captcha, or fabricate an official archive if a site blocks retrieval.
2. Inspect previously saved source bytes (or Phase6 new ones) with explicit **court docket numbers** (3027 113 金訴 29, 8299 113 金上更一 2, 8299 114 台上 859) or **SFIPC 2023 康友 announcement title**, plus issuer aliases and judgment/news context. Report whether document *content* supports the intended identity; matching text alone is NOT cryptographic website provenance.
3. If an official site blocks automation and user already saved the exact court HTML through their browser, support an **optional** local CSV import manifest containing exactly source_id,local_file. Strict one-to-one trusted source_id, .html/.htm/.txt, size, company alias + exact docket/title. SHA-256 immutable copy with receipt provenance **MANUAL_IMPORTED_BROWSER_SAVE_ORIGIN_UNVERIFIED**. No automatic evidence qualification or labels; if source or docket missing, reject without overwrite.
4. Generate **phase7_original_filing_asof_gap_queue.csv**: for 3 cases/7 target issuer years, require each target FY plus its two preceding FYs (21 targeted source needs, repetitions allowed). Lists missing original-as-first-published MOPS filing, original bytes/digest, original publication time and independent first market disclosure. **2012 and earlier** periods must be appropriately mapped to their historical GAAP regime, never assumed TIFRS.
5. Preserve **1785** completely outside development and source lists. Do not turn court findings or lawsuits into approved positives; never infer unreviewed Taiwan companies are true negatives.
6. Output **phase7_official_source_review.csv**, **phase7_original_filing_asof_gap_queue.csv**, **phase7_evidence_asof_report.json** (source-specific errors, identity confirmations and explicit zero verified as-of/positive labels). Also updates Phase6 report in this Phase7 output directory.

**test_financial_ml_phase7_evidence_asof_audit.py**: ten hermetic regression tests (no real network), including 6452 issuer aliases, Big5 court decoding, exact docket checks, source content authenticity limits, safe manual import, immutable original bytes, 21 PIT needs, 1785 holdout, no label promotion.

**verify_phase7.ps1**: one Windows command for 10 Phase7 + 10 previous Phase6 + 12 Phase1 regression tests, then run the official-only retry and full original filing gap inventory, no ML retraining or production database writes.

### Scientific gates still open
- Official judicial document retrieval and original financial filing are separate. Even if 4/4 court/protection-center sources become SHA archived, every target year still needs original pre-correction MOPS annual/quarterly statement version and demonstrably public filing timestamp.
- Earliest revelation of financial misstatement is not a court judgment document date or a later correction notice automatically; must find original announcement and confirm earlier absence.
- Specific dates and legal finality require legal source cross-review; SFIPC 6452 2017Q2–2020Q1 report allegation must not be labeled as four confirmed positives.
- Explicitly distinguish present-time model trained retrospectively with verified later outcomes from a **strict original-as-of historical model** that could have been trained and deployed before 2016.
- Taiwan real approved positive and audited negative cases still 0. No supervised accuracy/PR-AUC/Recall@K claims permitted; Phase5 four-model results remain anonymous unlabeled outlier score proxies, not fraud detection.
- Important next input: original source of **8299 111年度金上訴字第11號 2022 criminal ruling** is referenced by judicial decisions. Researchable court PDF URL is a case lead, not yet admitted into Phase1 registry or hashed local source; prefer official content with documented stable legal identity.
- US/synthetic data only can be a domain-validated auxiliary baseline, not a replacement for actual Taiwan outcomes.

## ONE user-side verification

In a clean separate Windows ML worktree at Financial-Risk-Alert-System-ML/fintrust_backend, check out feature/financial-ml-phase7-official-evidence-diagnostics-20261019 and execute once:

powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase7.ps1

The script sends up to four source-locked HTTPS GET requests, and otherwise operates on your local cached data. If site restrictions persist, the report will say NO_ARCHIVED_OFFICIAL_BYTES, not pretend the phase's scientific case source evidence is solved.

**Return only:**
- Financial-Risk-Alert-System/fintrust_backend/data/financial_ml/phase7_official_case_asof_recovery/phase7_evidence_asof_report.json
- If any source remains blocked, phase7_official_source_review.csv (or just the errors in JSON if adequate)
- Console traceback only for failed tests.

Do not send API passwords, cookies, verification tokens or unrelated court judgment bulk archives. If official court authentication is needed, use the official public/browser method and explicit saved-file import, not arbitrary bypass. Future phase should deal with these remaining obstacles **together with** original-MOPS filing time and label methodology, as the user has requested.
