# Round 3 Production Automation Runbook

This runbook deploys the reviewed Round 3 official-event batch code and provisions two Cloud Scheduler jobs without depending on the developer's Windows working copy.

## Canonical source

- Repository: `ethankdok/Financial-Risk-Alert-System`
- Branch: `feature/release-delivery`
- Reviewed Round 3 application checkpoint: `81b868db6da0e8c0ff12e2be9588d5b660e77e24`

The Cloud Shell helper verifies that the current remote branch still contains that reviewed checkpoint and refuses to continue if the checkout is not synchronized with `origin/feature/release-delivery`.

## Why use a fresh Cloud Shell clone

The local Windows repository can be stale without affecting this release. For production work, create a fresh Cloud Shell clone from the canonical GitHub branch. Do not copy files from the old `UnaLu027/fintrust-alert` repository or the stale `feature/financial-statement-ai-mvp` branch.

## Production target

- Project: `fintrust-alert-ccu`
- Region: `asia-east1`
- Cloud Run service: `fintrust-api`
- Existing financial Scheduler: `fintrust-financial-refresh-semiconductor-eligible`
- Scheduler service account: `fintrust-scheduler@fintrust-alert-ccu.iam.gserviceaccount.com`
- Existing ingestion secret: `fintrust-ingestion-token`

The helper does not print the ingestion secret or Scheduler HTTP headers.

## Safe staged workflow

Run each stage separately instead of using `all` during the first production rollout.

### 1. Fresh clone

```bash
rm -rf /tmp/fintrust-round3-release
git clone --branch feature/release-delivery \
  https://github.com/ethankdok/Financial-Risk-Alert-System.git \
  /tmp/fintrust-round3-release
cd /tmp/fintrust-round3-release
chmod +x deploy/round3_cloud_shell_release.sh
```

### 2. Read-only preflight

```bash
./deploy/round3_cloud_shell_release.sh preflight
```

This checks:

- Git branch synchronization and clean worktree
- active GCP project
- current Cloud Run URL / revision / traffic / image
- existing financial Scheduler, using a filtered output that excludes headers
- enabled Secret Manager version metadata only
- `/health`

Do not continue unless the script ends with `PRECHECK_OK`.

### 3. Deploy Round 3

```bash
./deploy/round3_cloud_shell_release.sh deploy
```

The helper reruns backend and root test suites, builds the FastAPI image using the repository Cloud Build config, deploys a new Cloud Run revision, checks `/health`, and verifies that OpenAPI contains:

`/api/v1/financial/admin/official-events/refresh-all`

The existing service configuration is not intentionally replaced by the helper.

Do not continue unless the script ends with `DEPLOY_OK`.

### 4. Production manual batch validation

Before creating recurring jobs, invoke the secured endpoint manually for a small explicit/default scope and then for classified scope. Use the existing ingestion token from Secret Manager with shell tracing disabled. Never print the token or request headers.

Validate both modes:

- Material events: `include_conferences=false`, `include_material_events=true`, `material_openapi_only=true`
- Investor conferences: `include_conferences=true`, `include_material_events=false`, `extract_documents=false`

Expected classified scope is 96 companies. External source blocking can produce `partial`; it should not abort the batch.

### 5. Create/update the two Scheduler jobs

```bash
./deploy/round3_cloud_shell_release.sh schedulers
```

This creates or updates:

- `fintrust-material-events-semiconductor`
  - `5 * * * *`
  - `Asia/Taipei`
  - hourly material-event polling
- `fintrust-investor-conferences-semiconductor`
  - `15 19 * * 1-5`
  - `Asia/Taipei`
  - weekday 19:15 conference metadata refresh

Both jobs use OIDC with the existing Scheduler service account and the existing `X-Ingestion-Token` secret value. The OIDC audience is the Cloud Run service URL without query parameters.

### 6. Safe verification

```bash
./deploy/round3_cloud_shell_release.sh verify
```

The output deliberately excludes Scheduler headers.

### 7. Controlled force-run validation

Force-run each new Scheduler job once, wait for completion, and verify the corresponding batch result in application logs / batch history.

```bash
gcloud scheduler jobs run fintrust-material-events-semiconductor \
  --project=fintrust-alert-ccu \
  --location=asia-east1

gcloud scheduler jobs run fintrust-investor-conferences-semiconductor \
  --project=fintrust-alert-ccu \
  --location=asia-east1
```

Expected behavior:

- `trigger = scheduler`
- `scope = classified`
- 96 company results
- no batch abort
- conference source blocking may be represented as `partial`

## Security constraints

- Never run `set -x` while reading or using `fintrust-ingestion-token`.
- Never `echo` the token.
- Never paste the token into GitHub, `.env`, YAML, screenshots, or chat output.
- Do not use an unrestricted Scheduler describe command in screenshots; HTTP headers may contain the ingestion token.
- Do not rotate the secret unless an actual exposure occurs.
- Do not rerun Firestore migration.
- Do not delete legacy Firestore documents.
- Do not modify the existing financial Scheduler as part of Round 3.

## Rollout gates

Production automation is complete only after all of the following are true:

1. reviewed Round 3 code is deployed to `fintrust-api`;
2. `/health` and the official-event route pass production smoke;
3. one manual material-event classified batch completes;
4. one manual investor-conference classified batch completes;
5. both new Scheduler jobs exist with the reviewed schedules;
6. each Scheduler job has been force-run successfully once;
7. the original financial Scheduler remains enabled and unchanged;
8. no secret value was exposed.
