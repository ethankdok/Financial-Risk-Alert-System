# Phase 15 Release Readiness

Status: `PHASE15 LOCAL/STAGING PREPARATION`

This document is a release gate checklist for the existing architecture:

Browser -> Flask Cloud Run (`financial-risk-web`) -> `FinTrustClient` -> FastAPI Cloud Run (`fintrust-api`) -> Firestore, MOPS/TWSE/company IR, and Gemini when enabled.

## Release Audit

| Area | Status | Notes |
| --- | --- | --- |
| Flask repository abstraction | READY | Production uses `FLASK_DATASTORE_BACKEND=firestore`; SQLite remains local/test only. |
| FastAPI repository abstraction | READY | Production uses `DATASTORE_BACKEND=firestore`; official events use one `official_events` collection with event type discrimination. |
| Admin sessions/admin pages | READY | Existing admin auth, keywords, risk features, audit logs, and financial evidence console remain the product path. |
| Member auth | NEEDS_RELEASE_CONFIG | Code supports Firebase/Identity Platform ID token login; production requires `FIREBASE_PROJECT_ID`/`GOOGLE_CLOUD_PROJECT` and Firebase frontend configuration. Local password auth remains disabled in production. |
| Notifications | NEEDS_RELEASE_CONFIG | Console dry-run remains default. SMTP provider is env-driven and safe-error-only. Real email send requires secret-backed SMTP env vars and staged smoke tests. |
| Cloud Scheduler | NEEDS_RELEASE_CONFIG | Example Scheduler config is provided. Production creation requires explicit release approval, Cloud Run invoker IAM, and token/secret setup. |
| Gemini semiconductor scope | READY_WITH_LIMITATION | Gemini orchestration is no longer hard-gated to `IC 設計`. Non-IC semiconductor companies use common + semiconductor deterministic rule layers; subindustry-specific AI overlays remain calibration pending. |
| Fourth financial statement | EXTERNAL_BLOCKER | Statement of changes in equity is still not ingested as a full traditional fourth statement. Ending equity is represented via balance-sheet facts only. |
| STRUX | EXTERNAL_BLOCKER | Exact `train-00000-of-00001.parquet` artifact remains unavailable. Taiwan official evidence and Text Intelligence can run without STRUX. |
| Large document storage | READY_WITH_LIMITATION | Current bounded official text payloads remain acceptable in Firestore. Raw PDFs, large full text, and model artifacts should move to Cloud Storage if size grows. |
| Risk Feature v2 migration | READY_GATED | Migration remains dry-run by default. Production `--execute` requires explicit release approval. |

## Environment Matrix

### Flask

- `APP_ENV=production`
- `SECRET_KEY` from Secret Manager
- `FLASK_DATASTORE_BACKEND=firestore`
- `GOOGLE_CLOUD_PROJECT`
- `FINTRUST_API_BASE_URL`
- `FINTRUST_INGESTION_TOKEN` if protected FastAPI refresh routes are used
- `DATA_SHIFT_PARQUET` only when the STRUX parquet is present at a readable local path
- `MEMBER_ALLOW_LOCAL_PASSWORD_AUTH=false`
- `FIREBASE_PROJECT_ID` for managed member auth
- `NOTIFICATION_JOB_TOKEN` for protected Scheduler execution
- `EMAIL_PROVIDER=console` for dry-run staging, `smtp` only after provider smoke tests

### FastAPI

- `APP_ENV=production`
- `DATASTORE_BACKEND=firestore`
- `GOOGLE_CLOUD_PROJECT`
- `INGESTION_API_TOKEN`
- `GEMINI_API_KEY` only when Gemini is enabled
- `FINANCIAL_LLM_PROVIDER=gemini`
- `FINANCIAL_AI_AUTO_LLM_ENABLED=true` only after staging validation
- `CORS_ALLOW_ORIGINS` restricted to Flask service origin

## Staging Validation Plan

1. Build new FastAPI and Flask revisions.
2. Keep production traffic unchanged.
3. Validate new Flask -> new FastAPI -> Firestore at zero production traffic or staging URL.
4. Smoke test `/health`, admin login, member Firebase login, financial evidence, official events, Text Intelligence, Gemini, notification dry-run, run history, and source links.
5. Confirm no STRUX endpoint is required for core Taiwan official evidence flow.
6. Run Risk Feature v2 migration in dry-run only and compare before/after fingerprints.

## Rollback Plan

- Keep old Cloud Run revisions available.
- Do not delete old revisions during cutover.
- Do not run production Firestore migrations until source and staging smoke tests pass.
- If a new revision fails, route traffic back to the previous known-good revision.
- If a Firestore migration is approved later, capture before/after inventory and keep a rollback export.

## Production Gate

Do not proceed without explicit approval for each action:

- Production traffic cutover.
- Production Firestore mutation.
- Risk Feature v2 `--execute`.
- Cloud Scheduler creation.
- Real email provider enablement.
- Old revision deletion.
