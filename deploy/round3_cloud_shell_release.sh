#!/usr/bin/env bash
set -euo pipefail

# Round 3 production automation helper for Google Cloud Shell.
# This script intentionally never prints the ingestion-token value or Scheduler headers.
# Run from a fresh clone of feature/release-delivery so the user's local Windows repo
# does not need to be synchronized first.

PROJECT="${PROJECT:-fintrust-alert-ccu}"
REGION="${REGION:-asia-east1}"
SERVICE="${SERVICE:-fintrust-api}"
BRANCH="${BRANCH:-feature/release-delivery}"
ROUND3_REVIEW_SHA="81b868db6da0e8c0ff12e2be9588d5b660e77e24"
SCHEDULER_SA="${SCHEDULER_SA:-fintrust-scheduler@fintrust-alert-ccu.iam.gserviceaccount.com}"
INGESTION_SECRET="${INGESTION_SECRET:-fintrust-ingestion-token}"
FINANCIAL_JOB="fintrust-financial-refresh-semiconductor-eligible"
MATERIAL_JOB="fintrust-material-events-semiconductor"
CONFERENCE_JOB="fintrust-investor-conferences-semiconductor"
TEST_VENV="${ROUND3_TEST_VENV:-/tmp/fintrust-round3-test-venv}"

MODE="${1:-preflight}"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

safe_scheduler_show() {
  local job="$1"
  gcloud scheduler jobs describe "$job" \
    --project="$PROJECT" \
    --location="$REGION" \
    --format='yaml(name,state,schedule,timeZone,httpTarget.uri,httpTarget.httpMethod,httpTarget.oidcToken.serviceAccountEmail,retryConfig,attemptDeadline,status,lastAttemptTime)'
}

service_url() {
  gcloud run services describe "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --format='value(status.url)'
}

current_image() {
  local image
  image="$(gcloud run services describe "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --format='value(spec.template.spec.containers[0].image)' 2>/dev/null || true)"
  if [[ -z "$image" ]]; then
    image="$(gcloud run services describe "$SERVICE" \
      --project="$PROJECT" \
      --region="$REGION" \
      --format='value(template.containers[0].image)' 2>/dev/null || true)"
  fi
  [[ -n "$image" ]] || fail "Could not determine current Cloud Run image."
  printf '%s\n' "$image"
}

image_repository() {
  local image="$1" without_digest last_segment
  without_digest="${image%@*}"
  last_segment="${without_digest##*/}"
  if [[ "$last_segment" == *:* ]]; then
    without_digest="${without_digest%:*}"
  fi
  printf '%s\n' "$without_digest"
}

verify_git() {
  require_cmd git
  git fetch origin "$BRANCH" --quiet
  local remote_head local_head
  remote_head="$(git rev-parse "origin/$BRANCH")"
  local_head="$(git rev-parse HEAD)"
  printf 'remote_head=%s\n' "$remote_head"
  printf 'local_head=%s\n' "$local_head"
  git merge-base --is-ancestor "$ROUND3_REVIEW_SHA" "$remote_head" \
    || fail "Remote branch does not contain the reviewed Round 3 commit $ROUND3_REVIEW_SHA"
  [[ "$local_head" == "$remote_head" ]] \
    || fail "Current checkout is not synchronized with origin/$BRANCH. Use a fresh clone or fast-forward first."
  [[ -z "$(git status --porcelain)" ]] || fail "Working tree is not clean."
}

preflight() {
  require_cmd gcloud
  require_cmd git
  require_cmd curl
  verify_git

  local configured_project url image revision traffic timeout_value
  configured_project="$(gcloud config get-value project 2>/dev/null || true)"
  printf 'configured_project=%s\n' "$configured_project"
  [[ "$configured_project" == "$PROJECT" ]] \
    || fail "Active gcloud project is not $PROJECT"

  url="$(service_url)"
  [[ -n "$url" ]] || fail "Cloud Run service URL is empty."
  image="$(current_image)"
  revision="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.latestReadyRevisionName)')"
  traffic="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.traffic[0].percent)')"
  timeout_value="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(spec.template.spec.timeoutSeconds)' 2>/dev/null || true)"

  printf 'cloud_run_url=%s\n' "$url"
  printf 'current_revision=%s\n' "$revision"
  printf 'current_traffic_percent=%s\n' "$traffic"
  printf 'current_image=%s\n' "$image"
  printf 'current_timeout_seconds=%s\n' "${timeout_value:-unknown}"

  printf '%s\n' 'existing_financial_scheduler:'
  safe_scheduler_show "$FINANCIAL_JOB"

  printf '%s\n' 'secret_metadata:'
  gcloud secrets versions list "$INGESTION_SECRET" \
    --project="$PROJECT" \
    --filter='state=ENABLED' \
    --format='table(name,state,createTime)' \
    --limit=5

  printf '%s\n' 'health_check:'
  curl -fsS "$url/health"
  printf '\nPRECHECK_OK\n'
}

ensure_test_env() {
  require_cmd python3
  if [[ ! -x "$TEST_VENV/bin/python" ]]; then
    printf 'Creating isolated test virtualenv at %s...\n' "$TEST_VENV"
    python3 -m venv "$TEST_VENV"
  fi

  local py="$TEST_VENV/bin/python"
  printf '%s\n' 'Installing repository requirements into isolated test virtualenv...'
  "$py" -m pip install --disable-pip-version-check --quiet \
    -r requirements.txt \
    -r fintrust_backend/requirements.txt

  "$py" - <<'PY'
import fastapi
import httpx
import pydantic
from google.cloud import firestore
print(
    "test_environment_ok "
    f"fastapi={fastapi.__version__} "
    f"httpx={httpx.__version__} "
    f"pydantic={pydantic.__version__} "
    f"firestore_module={firestore.__name__}"
)
PY
}

run_tests() {
  ensure_test_env
  local py="$TEST_VENV/bin/python"
  printf '%s\n' 'Running backend tests in isolated project virtualenv...'
  (cd fintrust_backend && "$py" -m unittest discover -s tests)
  printf '%s\n' 'Running root tests in isolated project virtualenv...'
  "$py" -m unittest discover -s tests
}

deploy_round3() {
  verify_git
  run_tests

  local image base_image sha short_sha new_image suffix url
  image="$(current_image)"
  base_image="$(image_repository "$image")"

  sha="$(git rev-parse HEAD)"
  short_sha="$(git rev-parse --short=12 HEAD)"
  new_image="${base_image}:round3-${short_sha}"
  suffix="release-${short_sha}"

  printf 'building_sha=%s\n' "$sha"
  printf 'new_image=%s\n' "$new_image"

  gcloud builds submit . \
    --project="$PROJECT" \
    --config=deploy/cloudbuild-fastapi.yaml \
    --substitutions="_IMAGE=${new_image}"

  # Existing service settings (environment variables, secrets, service account,
  # ingress and IAM policy) are intentionally not replaced here.
  gcloud run deploy "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --image="$new_image" \
    --revision-suffix="$suffix" \
    --quiet

  url="$(service_url)"
  printf 'deployed_url=%s\n' "$url"
  gcloud run services describe "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --format='yaml(status.latestReadyRevisionName,status.traffic,spec.template.spec.serviceAccountName,spec.template.spec.timeoutSeconds)'

  curl -fsS "$url/health"
  printf '\n'
  curl -fsS "$url/openapi.json" | python3 -c 'import json,sys; d=json.load(sys.stdin); p="/api/v1/financial/admin/official-events/refresh-all"; assert p in d.get("paths",{}), p; print("official_event_route=present")'
  printf 'DEPLOY_OK\n'
}

upsert_scheduler_job() {
  local job="$1" schedule="$2" uri="$3" deadline="$4" description="$5" token="$6"
  if gcloud scheduler jobs describe "$job" --project="$PROJECT" --location="$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs update http "$job" \
      --project="$PROJECT" \
      --location="$REGION" \
      --schedule="$schedule" \
      --time-zone='Asia/Taipei' \
      --uri="$uri" \
      --http-method=POST \
      --oidc-service-account-email="$SCHEDULER_SA" \
      --oidc-token-audience="$(service_url)" \
      --update-headers="X-Ingestion-Token=${token}" \
      --attempt-deadline="$deadline" \
      --max-retry-attempts=2 \
      --max-retry-duration=600s \
      --min-backoff=30s \
      --max-backoff=120s \
      --max-doublings=2 \
      --description="$description" \
      --quiet >/dev/null
  else
    gcloud scheduler jobs create http "$job" \
      --project="$PROJECT" \
      --location="$REGION" \
      --schedule="$schedule" \
      --time-zone='Asia/Taipei' \
      --uri="$uri" \
      --http-method=POST \
      --oidc-service-account-email="$SCHEDULER_SA" \
      --oidc-token-audience="$(service_url)" \
      --headers="X-Ingestion-Token=${token}" \
      --attempt-deadline="$deadline" \
      --max-retry-attempts=2 \
      --max-retry-duration=600s \
      --min-backoff=30s \
      --max-backoff=120s \
      --max-doublings=2 \
      --description="$description" \
      --quiet >/dev/null
  fi
}

create_schedulers() {
  local url material_uri conference_uri token
  url="$(service_url)"
  material_uri="${url}/api/v1/financial/admin/official-events/refresh-all?include_conferences=false&include_material_events=true&material_openapi_only=true&trigger=scheduler&batch_scope=classified"
  conference_uri="${url}/api/v1/financial/admin/official-events/refresh-all?include_conferences=true&include_material_events=false&extract_documents=false&trigger=scheduler&batch_scope=classified"

  # Security critical: never enable xtrace around secret access or gcloud commands
  # that contain the header value. The variable only exists inside this script process.
  set +x
  token="$(gcloud secrets versions access latest --secret="$INGESTION_SECRET" --project="$PROJECT")"
  [[ -n "$token" ]] || fail "Ingestion token could not be loaded."

  upsert_scheduler_job \
    "$MATERIAL_JOB" \
    '5 * * * *' \
    "$material_uri" \
    '600s' \
    'Poll TWSE official material-event disclosures for the classified semiconductor universe' \
    "$token"

  upsert_scheduler_job \
    "$CONFERENCE_JOB" \
    '15 19 * * 1-5' \
    "$conference_uri" \
    '600s' \
    'Refresh official investor-conference metadata for the classified semiconductor universe' \
    "$token"

  unset token

  printf '%s\n' 'material_scheduler:'
  safe_scheduler_show "$MATERIAL_JOB"
  printf '%s\n' 'conference_scheduler:'
  safe_scheduler_show "$CONFERENCE_JOB"
  printf 'SCHEDULERS_OK\n'
}

verify_safe() {
  local url
  url="$(service_url)"
  printf '%s\n' 'cloud_run:'
  gcloud run services describe "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --format='yaml(status.url,status.latestReadyRevisionName,status.traffic,spec.template.spec.timeoutSeconds)'
  printf '%s\n' 'financial_scheduler_unchanged_check:'
  safe_scheduler_show "$FINANCIAL_JOB"
  printf '%s\n' 'material_scheduler:'
  safe_scheduler_show "$MATERIAL_JOB"
  printf '%s\n' 'conference_scheduler:'
  safe_scheduler_show "$CONFERENCE_JOB"
  printf '%s\n' 'health:'
  curl -fsS "$url/health"
  printf '\nVERIFY_OK\n'
}

case "$MODE" in
  preflight)
    preflight
    ;;
  test)
    verify_git
    run_tests
    ;;
  deploy)
    preflight
    deploy_round3
    ;;
  schedulers)
    preflight
    create_schedulers
    ;;
  verify)
    verify_safe
    ;;
  all)
    preflight
    deploy_round3
    create_schedulers
    verify_safe
    ;;
  *)
    fail "Usage: $0 {preflight|test|deploy|schedulers|verify|all}"
    ;;
esac
