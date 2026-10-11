# Phase 5 — Historical research: cloud compatibility, staging preflight, deployment and rollback runbooks

**Status: deployment-ready local source and configuration. Nothing was deployed, no cloud resource was created or
modified, no production write, IAM, Secret Manager, DNS or scheduler change was made.** Production promotion and any
staging-account change need a separate explicit approval after independent review.

## 1. Audited current architecture (from the repository, not queried live)

| Item | Repository evidence |
|---|---|
| Project / region | `fintrust-alert-ccu`, `asia-east1` (`deploy/round3_cloud_shell_release.sh`, `docs/cloud/PHASE7_CLOUD_RUN_PRODUCTION.md`) |
| Services | Cloud Run `fintrust-api` (FastAPI, `Dockerfile.fastapi`), `financial-risk-web` (Flask, `Dockerfile.flask`) |
| Datastores | Firestore (production `DATASTORE_BACKEND=firestore`, `FLASK_DATASTORE_BACKEND=firestore`); SQLite only locally |
| Objects | GCS conference-PDF archive bucket(s) (`CONFERENCE_PDF_ARCHIVE_GCS_BUCKET`, `OFFICIAL_IR_PDF_GCS_BUCKET`) |
| Secrets | Secret Manager: `SECRET_KEY`, `INGESTION_API_TOKEN`/`FINTRUST_INGESTION_TOKEN` (`fintrust-ingestion-token`), `GEMINI_API_KEY` |
| Schedulers | Cloud Scheduler examples with OIDC service accounts (`deploy/cloud-scheduler-*.example.yaml`) |
| Historical research cloud | `historical_audit/cloud_config.py`: disabled by default; `emulator` / `isolated-test` only; production refused without `HISTORICAL_CLOUD_PRODUCTION_APPROVAL` + `--allow-production` |

Live state (current revisions, IAM bindings, budgets) was **not** queried: it needs credentials and is outside this
phase. The staging preflight below lists what must be confirmed by the owner.

## 2. One authoritative owner per data category

| Category | Authoritative store | Cloud representation | Writer |
|---|---|---|---|
| Immutable raw bytes (PDF, notice HTML, XBRL, listings, conference PDFs, research ZIPs) | local content-addressed archive `fintrust_backend/data/historical_audit/raw`, `data/historical-conference-pdfs` (approved baseline 506b64c) | optional GCS mirror via `cloud_sync` (create-only, SHA-verified); research ZIPs are **not** uploaded by default (220 MB) | historical ingestion CLI only |
| Metadata and official facts | local `historical_audit.sqlite3` (read-only for Phase 3–5) | `historical_research_*` Firestore collections (create-only mirror) | historical ingestion / `cloud_sync` only |
| Literature-model line inputs (extension) | local append-only `data/literature_models/literature_inputs.sqlite3` (rebuildable from the raw archive by `scripts/ingest_literature_inputs.py`) | **not mirrored** in this pass; a Cloud Run image without it reports `literature_inputs_available=false` and every literature year `source_unavailable` | ingestion CLI only |
| Derived research results | local append-only `research_results.sqlite3` | `<collection_prefix>_results_*` Firestore collections derived from the isolated config (default `historical_research_results_*`; create-only mirror via `result_sync`) | research CLI / authorized `persist=true` |

The research layer never writes official tables; derived results never overwrite (SQLite triggers forbid UPDATE/DELETE;
Firestore writes are `create()` only; a different output for the same run id is an integrity error).

## 3. Runtime behaviour per environment

| Environment | Research data source | Expected research API state |
|---|---|---|
| Local dev | local SQLite (read-only `mode=ro`) + archives | `ready` |
| Cloud Run image as built today | **no research data in the image** (by design) | `GET /api/v1/research/health` → `degraded`; data endpoints → `503 research_dataset_unavailable`; production endpoints unaffected |
| Future staging (after approval) | either a read-only volume with the approved archive, or `FirestoreResearchBackend` over the `historical_research_*` mirror (parity tested) | `ready` |

Choosing the staging data source is an explicit decision for the owner (§7). The code supports both; no default switch
to Firestore was made.

## 4. Security and operations posture (implemented)

- **Auth**: research GET routes are public read-only like the existing financial GETs; computation is bounded (≤15 years,
  registered tickers only) and dry-run; `persist=true` reuses `require_ingestion_token` (503 in production without a
  token). The browser proxy can never persist.
- **CORS**: unchanged (`CORS_ALLOW_ORIGINS`, default localhost). The browser talks to Flask; FastAPI need not be exposed to
  browsers.
- **Input validation**: mode/cutoff/version policy/year range/ticker/run-id patterns; Flask whitelists query parameters.
- **Output hygiene**: no filesystem paths, raw bytes or non-official URLs.
- **Flask static exposure fixed** (pre-existing defect found during this phase): the catch-all route served any repository
  file (`/financial_risk.db`, `/app.py`, local SQLite archives). It now serves only html/css/js/image/font assets at the
  root, `static/` or `templates/` (commit `fix(flask): restrict the catch-all static route…`). Review requested.
- **Health vs readiness**: `/health` (liveness, unchanged) vs `/api/v1/research/health` (dataset readiness).
- **Export safety** (`result_sync`): dry-run plan by default, exclusive lock file, `batch_limit` (1–500), bounded retries
  with ×4 backoff, JSON-lines journal, collision report (never overwritten), idempotent re-run, non-production targets only
  (`emulator` / `isolated-test`); the result namespace is `<config collection_prefix>_results`, so independently configured
  environments never share result collections (debug pass P2-F04).
- **Logging/monitoring signals**: research endpoints use structured HTTP status codes (`503 research_dataset_unavailable`,
  `409`, `422`); the export journal records `start/written/retry/integrity_failure/end`. Proposed alerts (not created):
  5xx rate on `/api/v1/research/*`, `research_health.status=degraded` after deploy, any `integrity_failure` journal entry.
- **Secrets**: none in code, images or docs; the preflight prints only set/unset.
- **Cost**: no new always-on resource; computation is per request and bounded (<2 s locally for the full case); export
  writes ≈ (runs × (1 + chunks + projections)) documents — today 4 runs ≈ 260 documents.

## 5. Verification tiers (do not conflate)

| Tier | What ran | Result |
|---|---|---|
| Unit / fixture | research layer, API, Flask proxy, UI renderer | pass (see test log) |
| MOCK cloud | in-memory Firestore/GCS fakes: mirror parity, result-store parity, export dry-run/batches/collisions/failure injection/lock | pass |
| **Firestore emulator** | `firebase-tools 13.35.1` → `cloud-firestore-emulator v1.19.8`, project `demo-fintrust`: existing historical emulator test + result-store parity + research-output parity SQLite vs emulator mirror | **3 passed** (log: `cloud_evidence/firestore_emulator_run.log`) |
| GCS emulator | not available locally (no Docker / fake-gcs-server) | object identity/hash checks only at MOCK tier |
| Live cloud / staging | **not run, not authorized** | — |

Reproduce the emulator tier (no credentials, demo project):

```bash
mkdir -p /tmp/emu && cd /tmp/emu
echo '{"emulators":{"firestore":{"host":"127.0.0.1","port":8085},"ui":{"enabled":false}}}' > firebase.json
npx -y firebase-tools@13 emulators:exec --only firestore --project demo-fintrust \
  "cd <repo>/fintrust_backend && ../.venv/Scripts/python.exe -m pytest -v tests/test_historical_cloud_emulator.py tests/test_financial_research_cloud.py"
```

## 6. Staging preflight runbook (read-only; run before any approval request)

1. `cd fintrust_backend && python -m scripts.research_baseline --out before.json` — approved dataset digests + package hashes.
2. `python -m scripts.research_cloud_preflight --out preflight.json` — must report `"ok": true`, `"writes_performed": "none"`.
3. Full regression (see test log commands) + `python -m scripts.research_ui_smoke --out ui/` (real local processes).
4. Owner confirms (read-only, with their own credentials, outside this task): current Cloud Run revisions and traffic,
   service accounts and their roles, Secret Manager versions in use, Firestore location, budget alerts.
5. Owner decides the staging research data source (§3) and the staging project/bucket names (must contain
   `test|dev|sandbox|staging`, must differ from production per `cloud_config`).

## 7. Deployment runbook (requires explicit approval — NOT executed)

1. Approval record: change reference, staging project, data source choice, rollback owner.
2. Build images from the reviewed commit (`deploy/cloudbuild-fastapi.yaml`, `deploy/cloudbuild-flask.yaml`); record digests.
3. Staging only: deploy both services with **no traffic** (`--no-traffic`), same env/secrets as today; nothing new is secret.
4. If Firestore-backed research is chosen: `HISTORICAL_CLOUD_SYNC_ENABLED=true HISTORICAL_CLOUD_ENVIRONMENT=isolated-test …`
   then `cloud_sync` dry-run → review collision report → execute in bounded batches; then `result_sync` dry-run → execute.
5. Smoke on the tagged revision URL: `/health`, `/api/v1/research/health`, the six research views, existing 2330/2454 pages.
6. Shift staging traffic; observe 24 h. Production promotion is a **separate** approval.

## 8. Rollback runbook (rehearsed locally without cloud writes)

- **Code**: route traffic back to the previous Cloud Run revision (`gcloud run services update-traffic … --to-revisions=<prev>=100`);
  the research router is additive, so removing it changes no existing route.
- **Derived results**: never deleted in place; a bad run is superseded by a new run (`supersedes_run_id`). Firestore result
  collections are namespaced (`historical_research_results_*`) and can be abandoned by switching the prefix.
- **Mirror data**: create-only; a faulty mirror is discarded by prefix, never patched.
- **Local rehearsal performed**: interrupted export (failure injection) leaves no committed run; retry completes
  idempotently; collision leaves the existing document unchanged; lock prevents concurrent exports
  (`tests/test_financial_research_cloud.py`).

## 9. Missing permissions / approvals (explicit)

- Live read of Cloud Run/IAM/Secret Manager/budget state (owner credentials).
- Creation of a staging/isolated-test project or bucket, and any Firestore writes outside the emulator.
- Decision on the staging research data source; any production promotion.

## 10. Literature-model pass (2026-10-12)

- New read-only endpoints under `/api/v1/research/literature/*` and `/cases/{ticker}/literature/coverage`; persistence
  reuses `persist=true` + ingestion token and the existing append-only result store (new result kinds
  `literature_models` / `literature_comparison`, additive projection table / collection `research_literature_scores`
  / `<collection_prefix>_results_literature_scores`, created on first open — an additive migration; existing rows unchanged).
- The literature-input sidecar is a local research artifact; no Firestore/GCS mirror was created and none is required
  for the API to degrade safely. Any mirror needs the same separate approval as §7.
- No deployment, cloud write, IAM, Secret Manager or scheduler change was made.

