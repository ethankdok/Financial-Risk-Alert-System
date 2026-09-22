# Round 3 Official Event Production Automation

This runbook deploys the reviewed Round 3 official-event ingestion code and provisions the production Cloud Scheduler jobs for material events and investor conferences.

## Canonical source

Use only:

- repository: `ethankdok/Financial-Risk-Alert-System`
- branch: `feature/release-delivery`

Do not deploy from the stale legacy repository or from a Windows checkout that has not been synchronized with `origin/feature/release-delivery`.

A fresh Cloud Shell clone is preferred for production work because it removes ambiguity about whether the local workstation is current.

## Production targets

- project: `fintrust-alert-ccu`
- region: `asia-east1`
- Cloud Run service: `fintrust-api`
- existing Scheduler service account: `fintrust-scheduler@fintrust-alert-ccu.iam.gserviceaccount.com`
- existing ingestion secret: `fintrust-ingestion-token`

The existing financial Scheduler `fintrust-financial-refresh-semiconductor-eligible` must not be changed.

## Scheduler lifecycle

| Source | Job | Schedule | Time zone |
| --- | --- | --- | --- |
| Financial statements | `fintrust-financial-refresh-semiconductor-eligible` | `15 7 * * 1-5` | `Asia/Taipei` |
| Material events | `fintrust-material-events-semiconductor` | `5 * * * *` | `Asia/Taipei` |
| Investor conferences | `fintrust-investor-conferences-semiconductor` | `15 19 * * 1-5` | `Asia/Taipei` |

Material-event polling uses the shared TWSE OpenAPI mode, so the upstream feed is fetched once per batch and then filtered across the classified company universe.

Investor-conference scheduled polling keeps `extract_documents=false`; full PDF/transcript extraction remains on demand.

## Security rules

Never print, paste, commit, or screenshot the ingestion-token value.

The helper script:

- reads the existing secret only into temporary permission-restricted files;
- disables shell tracing before secret operations;
- excludes Scheduler HTTP headers from safe verification output;
- requires an explicit `ROUND3_PRODUCTION_APPROVED=YES` guard before any production mutation;
- deploys a tagged Cloud Run candidate with 0% production traffic before promotion.

If a secret value is ever exposed in visible output, stop the deployment and rotate the secret before continuing.

## Step 1 — fresh Cloud Shell checkout

Use a new Cloud Shell working directory instead of the possibly stale Windows checkout:

```bash
rm -rf ~/fintrust-round3-deploy
git clone --branch feature/release-delivery --single-branch \
  https://github.com/ethankdok/Financial-Risk-Alert-System.git \
  ~/fintrust-round3-deploy
cd ~/fintrust-round3-deploy

git fetch origin feature/release-delivery
git status --short
git rev-parse HEAD
git rev-parse origin/feature/release-delivery
```

The last two SHAs must match and `git status --short` must be empty.

## Step 2 — read-only preflight

Run:

```bash
bash deploy/round3_cloudshell.sh preflight
```

This step is read-only. It records safe metadata under `/tmp/fintrust-round3/` and does not display Scheduler headers.

Review these items before deployment:

- current Cloud Run revision and traffic;
- service account, timeout, image, resource settings;
- environment-variable names and Secret Manager reference names;
- Cloud Run IAM bindings;
- enabled/disabled secret version metadata;
- the existing financial Scheduler configuration;
- whether the two Round 3 Scheduler names already exist.

Do not proceed if the service configuration is unexpected.

## Step 3 — deploy a 0%-traffic candidate

After preflight approval:

```bash
export ROUND3_PRODUCTION_APPROVED=YES
bash deploy/round3_cloudshell.sh deploy-candidate
```

The helper derives the existing Artifact Registry image repository from the current Cloud Run service, builds the current Git HEAD, and deploys it as a tagged revision with `--no-traffic`.

Production traffic is unchanged at this stage.

## Step 4 — candidate smoke

Run:

```bash
bash deploy/round3_cloudshell.sh candidate-smoke
```

The candidate is checked for:

- `/health`;
- OpenAPI presence of `/api/v1/financial/admin/official-events/refresh-all`;
- explicit material-event batch for `2330`, `2454`, `6770`;
- explicit investor-conference batch for `2330`, `2454`, `6770`;
- zero technical company failures.

`BLOCKED_BY_SOURCE` or other expected conference-source limitations may produce a partial batch without failing the smoke.

## Step 5 — promote tested candidate

Only after candidate smoke passes:

```bash
bash deploy/round3_cloudshell.sh promote
```

This shifts 100% of Cloud Run traffic to the tested candidate revision.

The previous revision remains available for rollback; do not delete it during Round 3 close-out.

## Step 6 — full production manual validation

Run one full classified batch for each new source:

```bash
bash deploy/round3_cloudshell.sh manual-validate
```

The expected company scope is 96 classified semiconductor companies.

The script requires:

- `requested_companies = 96`;
- `failed_companies = 0` for the material-event batch;
- `failed_companies = 0` for the conference batch.

Conference partial results caused by external source blocking are acceptable.

The script also queries Cloud Run logs for the material batch's `official_events_material_feed` marker. The expected count is exactly one, confirming the shared TWSE OpenAPI fetch behavior at runtime.

Safe batch summaries are stored in:

- `/tmp/fintrust-round3/material-manual.json`
- `/tmp/fintrust-round3/conference-manual.json`

Do not publish the complete result files if they contain more operational detail than needed; use filtered `jq` summaries for reports/screenshots.

## Step 7 — create Scheduler jobs

After both full manual batches have zero technical failures:

```bash
bash deploy/round3_cloudshell.sh create-schedulers
```

The helper creates or updates:

- `fintrust-material-events-semiconductor`
- `fintrust-investor-conferences-semiconductor`

It computes each HTTP attempt deadline from the observed full production runtime, with a bounded safety margin and a maximum of 30 minutes.

The OIDC audience is the Cloud Run service URL without query parameters, while the target URI includes the required route query parameters.

The existing financial Scheduler is not modified.

## Step 8 — force-run and verify both new Schedulers

Run:

```bash
bash deploy/round3_cloudshell.sh trigger-verify
```

The helper force-runs each new job, then watches safe Cloud Run log messages for:

- `trigger=scheduler`;
- `scope=classified`;
- material/conference source mode;
- the generated batch ID;
- the batch-completion summary.

It does not print Scheduler HTTP headers.

## Step 9 — final safe verification

Run:

```bash
bash deploy/round3_cloudshell.sh verify
```

Final expected state:

1. `fintrust-api` serves the tested Round 3 revision at 100% traffic.
2. Existing financial Scheduler remains enabled and unchanged.
3. Material-event Scheduler is enabled at `5 * * * *`, `Asia/Taipei`.
4. Investor-conference Scheduler is enabled at `15 19 * * 1-5`, `Asia/Taipei`.
5. Secret version metadata shows no unintended secret rotation or disablement.
6. Git working tree remains clean and matches `origin/feature/release-delivery`.

## Safe evidence for the presentation

For screenshots, prefer the following and avoid showing token-bearing command history:

- Cloud Scheduler console rows for the three jobs: name, status, schedule, timezone.
- `/tmp/fintrust-round3/material-scheduler-triggered.safe.json`.
- `/tmp/fintrust-round3/conference-scheduler-triggered.safe.json`.
- the filtered batch completion text generated by `trigger-verify`.
- Cloud Run revision/traffic information from `verify`.

Never use an unfiltered Scheduler `describe` screenshot because stored HTTP headers are sensitive.

## Rollback principle

Round 3 does not delete the previous Cloud Run revision. If a production regression appears after promotion, route traffic back to the previously verified revision before debugging. Do not roll back or delete Firestore data as part of a Cloud Run revision rollback.
