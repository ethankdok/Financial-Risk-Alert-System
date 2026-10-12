# Phase 2–6 原始碼整合紀錄（待集中驗證）

## Branch

- Base: cb1ea1a3d80227d4733a860b6babff3b07ff63a4 (Phase 1.1 accepted source)
- Branch: feature/fintrust-phase23-integrate-phase11
- No merge to main or v4-integration; no deployment, protected database writes, cloud writes, or JSD algorithm edits.
- Original financial-integrity.html and financial-integrity.js are unchanged relative to Phase 1.1. 新增頁面完全獨立。

## Implemented source components

### Phase 2–3
- Read-only financial/nonfinancial growth comparator: app/services/financial_nonfinancial_alignment.py
- Strict F4 Workbench bridge and source time/version validation: app/services/integrity/nfm_evidence_bridge.py
- Byte-integrity preflight for archived PDF documents, with official identity intentionally not asserted: official_archive_integrity.py
- Frozen-panel multi-company adapter using unchanged Beneish/Dechow research engines: multi_company_models.py
- Existing Workbench readiness and assessment invoke strict F4, which remains unavailable for non-archived verified inputs.

### Phase 4
- Source-family corroboration engine: cross_evidence.py
- JSD compatibility/calibration state remains a separate signal; source-family counts are not fraud confidence measures.
- Does not change teammate JSD algorithm.

### Phase 5
- PIT strict holdout evaluation: research_evaluation.py
- Read-only local JSON CLI: scripts/evaluate_pit_holdout.py
- Rejects future information, unknown outcome, incomplete negative-control followup, duplicate company-cutoff and training-company leakage.
- No real benchmark dataset, independently verified event labels, holdout calibration results or proven predictive skill are supplied.

### Phase 6
- B2B issuer/counterparty diligence composer: b2b_dossier.py
- Additive FastAPI endpoint POST /api/v1/b2b/dossiers/preview
- Additive Flask endpoint POST /api/b2b/dossiers/preview
- Standalone URL /b2b-due-diligence.html, with b2b-due-diligence.js.
- Cooperation type is user-declared, not externally verified. No stored watchlists, false supply links, scores, default probabilities or disruption predictions.
- Existing financial-integrity original page/tab layout is unchanged.

## Limits preventing actual-source completion

1. Current archived pipeline financial facts are URL-identified but missing raw official filing SHA-256, byte and original public availability verification.
2. No officially source-verified, scope-consistent two-year NFM series exists for the production F4 comparator. Fake data must never turn this green.
3. Company-level frozen research Panel release must be validated with real source observations; the adapted model runner is an internal retrospective tool, not an exposed current-company scorer.
4. Research sample/labels/negative controls and holdout experiment are not supplied; metrics cannot be claimed as validated.
5. The draft Taiwan accounting mappings and research methodology still need the method owner's review.

## Tests added (not yet executed as full integration suite)

- test_financial_nonfinancial_alignment.py
- test_integrity_phase23_nfm_bridge.py
- test_integrity_phase23_archive.py
- test_integrity_phase23_multi_company_models.py
- test_integrity_phase456_dossier_evaluation.py
- test_integrity_phase6_b2b_api.py

Run via a new worktree after all planned code edits are done, using Python 3.13+ and the existing pinned project dependencies. Check in this order:

1. Protected SQLite hash and test-sandbox preflight.
2. Newly added unit/contract tests.
3. Existing Phase 1 and Phase 1.1 tests and 1785 baseline.
4. FastAPI => Flask => headless browser E2E for original and standalone B2B pages.
5. Actual official source integration, F4 provenance and model readiness with explicit unavailable when evidence is missing.
6. Current Git diff secret/path scan, true Ruff/Bandit exit codes, full root/backend regression, before/after protected SHA.

**Do not interpret absence of test failures as validation if tests have not been executed.**
All unknown/missing evidence must remain unavailable; no scores are substituted from 1785 retrospective work into current 2330/2454 views.
