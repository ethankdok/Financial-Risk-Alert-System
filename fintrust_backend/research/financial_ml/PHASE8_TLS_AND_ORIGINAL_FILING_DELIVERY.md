# Phase 8: Judiciary TLS certificate compatibility and original MOPS filing intake

Date 2026-10-19. Dedicated feature branch feature/financial-ml-phase8-verified-tls-filing-intake-20261019. The user requested once-per-phase development/validation and to incorporate previous phase defects in the next round.

## Actual Phase7 user-side evidence (NOT a claim of successful source recovery)

- 10 Phase7 + 10 Phase6 + 12 Phase1 tests **32/32 passed**.
- Of four official links, **1 (6452 SFIPC investor-protection publication) had been archived with verified document-text identity and SHA; 3 judiciary originals remained unarchived**.
- Exactly all three court pages, one for 3027 and two for 8299, failed urllib HTTPS certificate verification:
  SSL: CERTIFICATE_VERIFY_FAILED: Missing Subject.
- 3 case candidates, 7 affected company-years, 21 target-plus-two-years source *demands*; 0 verified original company financial filings, 0 verified earliest market disclosure timestamps, 0 confirmed positive/negative labels, and reserved final 1785 untouched.
- An archived legal case HTML is legal source evidence, **NOT** the original financial filing or proof it was publicly available when the historically evaluated model ran.

## Repair: SSL RFC 5280 compatibility WITHOUT disabling HTTPS authentication

Changed research/financial_ml/phase6_official_evidence_recovery.py:
- Create a fresh ssl.create_default_context() per retrieval, always checking trusted CA certificates (ssl.CERT_REQUIRED) AND target hostname (check_hostname=True).
- First request retains all Python SSL defaults. A second request is permitted **only for the exact official host judgment.judicial.gov.tw**, and **only if** the first failure is ssl.SSLCertVerificationError describing "Missing Subject", and ssl.VERIFY_X509_STRICT is available.
- Retry clears only VERIFY_X509_STRICT from a newly created context, preserving CA/hostname checks; never sets CERT_NONE, verify=False, global default context, no pinning an unknown certificate. A different SSL error (unknown issuer, wrong host, expired certificate, missing CA chain) FAILS CLOSED.
- Record the retry policy string in archived HTTPS source receipt metadata tls_policy. Existing archived 6452 original bytes are reused without refetching; the three failed judiciary sources are candidates for retry.
- Python's own SSL reference documents VERIFY_X509_STRICT and its compatibility relaxation; it is weaker X.509-format enforcement, **not full TLS bypass**: https://docs.python.org/3.14/library/ssl.html . Security caveat: a newer or properly configured judiciary server certificate is preferable; the compatibility retry is narrowly scoped to these public official-document lookups.

## New actual original-report evidence workflow

research/financial_ml/phase8_original_filing_intake.py:
- Deduplicates Phase7 21 target-year/prior-year demands into **13 unique issuer–fiscal-year original-filing needs**:
  3027 FY2013–2016 (4)
  8299 FY2012–2014 (3)
  6452 FY2015–2020 (6).
- Calls the existing MOPS historical audit acquisition_results.json and SHA-validating RawEvidenceArchive to discover already archived official source bytes *for these exact issuer/year pairs*. This is **retrospective evidence only**; original-publication-year validity is still false unless separately reviewed.
- Outputs original_case_filing_source_intake.csv with prior official archive coverage, the three-historical-year demands, source SHA, and accounting regime. FY2012 is explicitly PRE_TIFRS_GAAP_NEEDS_HISTORICAL_MAPPING.
- Optional manually sourced official MOPS original PDF/XML/HTML/ZIP files plus original market notice text can be ingested through **explicit CSV manifest** path financial_ml/phase8_original_filing_intake.csv with exactly:
  ticker,fiscal_year,local_report_file,claimed_mops_original_publication_at,mops_original_notice_file,original_filing_document_id,review_notes
  Paths require immutable SHA archiving, no symlinks, per-file size and type limits, document identity and time-with-timezone checks. **All claimed dates and original versions remain independently unverified**; there is no automatic outcome label or as-of feature promotion from a handwritten manifest.
- Critical caveat: this intake does not download original financial reports from historical MOPS itself. If no precise original version is locally available, rows remain NO_USER_SUPPLIED_ORIGINAL_VERSION, even if some retrospective archive has a valid hash. To claim early fraud prediction, the original filing needs external/primary evidence retrieval and verified publication timestamp.
- Preserves the existing Phase1 3027/8299/6452 development candidate set, separate unresolved allegations/confirmed judicial findings, and final 1785 test embargo.

research/financial_ml/phase8_integrated_run.py:
- One combined entrypoint reruns bounded Phase7 source recovery, reusing verified previous 6452 evidence, then builds 13-entry original-filing evidence intake.
- Writes phase8_case_original_filing_recovery/phase8_integrated_report.json, phase8_original_filing_readiness.json, original_case_filing_source_intake.csv. Reports both legal-source counts and actual original-PIT publication/labels.
- Offline tests in test_financial_ml_phase8_verified_tls_filing_intake.py cover peer authenticity, host-limited strict fallback, 13 nonduplicate fiscal source needs, immutable import and declared-vs-proven publication times. All tests mock network; **actual Windows real-site outcome remains subject to final local acceptance**.
- verify_phase8.ps1 is one user-side execution: Phase8 + Phase7 + Phase6 + Phase1 regression suites, then three pending court-page retries and original-filing review. No FinMind downloads, no model fitting, no production Firestore/SQL, no frontend changes.

## One local validation (one time, after fetching clean branch)

PowerShell in the dedicated Financial-Risk-Alert-System-ML\fintrust_backend with ml-env active:

powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_phase8.ps1

Expected reporting only, NOT invented site successes:
- Up to 4 official case source URLs examined, with existing 6452 receipt reused.
- Three pending judicial sources may succeed after safe TLS compatibility retry; if a trusted certificate chain/hostname still fails, errors remain visible and no fake archive written.
- Exactly 13 unique issuer years of initial historical original-file needs. If the user has not supplied original report+notice material, zero original versions should be certified.
- Source-specific output is archived with TLS policy metadata; origin/issuer/date/outcome labels remain gated.

Only upload:
financial_ml/phase8_case_original_filing_recovery/phase8_integrated_report.json
and failed-test Terminal trace if needed.

## Remaining research work toward the actual stated goal

This phase is an evidence-collection and as-of audit **not** demonstration that erroneous original 2014 financial numbers were predicted. Formally approved positive/negative Taiwanese issuer/filing labels are still zero; the 120-firm FinMind 15 original variables are unapproved; and original pre-correction historical MOPS documents for 3027/8299/6452 are not automatically available. The final 1785 event pre-2016 must remain held out.

Prioritize exact original publicly released filings, official disclosure events, period-specific judicial findings and independent outcome sign-off. Then run Taiwan real train/validation/test with literature M/F scores, properly calibrated baseline ML and time-series models. US real data or synthetic auxiliary samples only with Taiwan-domain comparability and independent validation.
