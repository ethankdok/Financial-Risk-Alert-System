#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT="${PROJECT:-fintrust-alert-ccu}"
REGION="${REGION:-asia-east1}"
SERVICE="${SERVICE:-fintrust-api}"
BRANCH="${BRANCH:-feature/release-delivery}"
SCHEDULER_SA="${SCHEDULER_SA:-fintrust-scheduler@fintrust-alert-ccu.iam.gserviceaccount.com}"
INGESTION_SECRET="${INGESTION_SECRET:-fintrust-ingestion-token}"
FINANCIAL_JOB="${FINANCIAL_JOB:-fintrust-financial-refresh-semiconductor-eligible}"
MATERIAL_JOB="${MATERIAL_JOB:-fintrust-material-events-semiconductor}"
CONFERENCE_JOB="${CONFERENCE_JOB:-fintrust-investor-conferences-semiconductor}"
EXPECTED_COMPANIES="${EXPECTED_COMPANIES:-96}"
ARTIFACT_DIR="${ARTIFACT_DIR:-/tmp/fintrust-round3}"

mkdir -p "$ARTIFACT_DIR"
umask 077

log() { printf '[round3] %s\n' "$*"; }
die() { printf '[round3] ERROR: %s\n' "$*" >&2; exit 1; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

require_tools() {
  require_cmd gcloud
  require_cmd git
  require_cmd jq
  require_cmd curl
  require_cmd python3
}

assert_repo_state() {
  git rev-parse --is-inside-work-tree >/dev/null 2>&1 || die "Run this script from the canonical repository checkout."
  local branch local_head remote_head dirty
  branch="$(git branch --show-current)"
  [[ "$branch" == "$BRANCH" ]] || die "Expected branch $BRANCH, got ${branch:-DETACHED}."
  dirty="$(git status --porcelain)"
  [[ -z "$dirty" ]] || die "Working tree is not clean. Do not deploy from a dirty checkout."
  git fetch origin "$BRANCH" --quiet
  local_head="$(git rev-parse HEAD)"
  remote_head="$(git rev-parse "origin/$BRANCH")"
  [[ "$local_head" == "$remote_head" ]] || die "Local HEAD $local_head is not origin/$BRANCH $remote_head. Sync first."
  log "Repository guard passed: $BRANCH @ $local_head"
}

safe_service_json() {
  gcloud run services describe "$SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --format=json \
  | jq '{
      name: .metadata.name,
      url: .status.url,
      latestReadyRevision: .status.latestReadyRevisionName,
      ingress: .metadata.annotations["run.googleapis.com/ingress"],
      traffic: [.status.traffic[]? | {revisionName, percent, tag, url}],
      serviceAccountName: .spec.template.spec.serviceAccountName,
      timeoutSeconds: .spec.template.spec.timeoutSeconds,
      container: {
        image: .spec.template.spec.containers[0].image,
        resources: .spec.template.spec.containers[0].resources,
        envNames: [.spec.template.spec.containers[0].env[]?.name],
        secretRefs: [.spec.template.spec.containers[0].env[]? | select(.valueFrom.secretKeyRef.name? != null) | {env: .name, secret: .valueFrom.secretKeyRef.name, key: .valueFrom.secretKeyRef.key}]
      }
    }'
}

safe_service_iam() {
  gcloud run services get-iam-policy "$SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --format=json \
  | jq '{bindings: [.bindings[]? | {role, members}]}'
}

safe_scheduler_row() {
  local job="$1"
  if gcloud scheduler jobs describe "$job" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    gcloud scheduler jobs describe "$job" \
      --project "$PROJECT" \
      --location "$REGION" \
      --format=json \
    | jq '{
        name,
        state,
        schedule,
        timeZone,
        attemptDeadline,
        status,
        lastAttemptTime,
        retryConfig,
        httpTarget: {
          uri: .httpTarget.uri,
          httpMethod: .httpTarget.httpMethod,
          oidcServiceAccountEmail: .httpTarget.oidcToken.serviceAccountEmail,
          oidcAudience: .httpTarget.oidcToken.audience
        }
      }'
  else
    jq -n --arg name "$job" '{name: $name, state: "NOT_FOUND"}'
  fi
}

preflight() {
  require_tools
  assert_repo_state
  log "Active gcloud account (safe metadata):"
  gcloud auth list --filter='status:ACTIVE' --format='value(account)' || true

  log "Cloud Run safe preflight:"
  safe_service_json | tee "$ARTIFACT_DIR/cloud-run-preflight.safe.json"

  log "Cloud Run IAM policy (safe metadata):"
  safe_service_iam | tee "$ARTIFACT_DIR/cloud-run-iam.safe.json"

  log "Ingestion secret version metadata only:"
  gcloud secrets versions list "$INGESTION_SECRET" \
    --project "$PROJECT" \
    --format='table(name,state,createTime)' \
    | tee "$ARTIFACT_DIR/ingestion-secret-versions.safe.txt"

  log "Existing financial scheduler (must remain unchanged):"
  safe_scheduler_row "$FINANCIAL_JOB" | tee "$ARTIFACT_DIR/financial-scheduler.safe.json"

  log "Round 3 scheduler existence check:"
  safe_scheduler_row "$MATERIAL_JOB" | tee "$ARTIFACT_DIR/material-scheduler-before.safe.json"
  safe_scheduler_row "$CONFERENCE_JOB" | tee "$ARTIFACT_DIR/conference-scheduler-before.safe.json"

  log "Preflight complete. No production mutation was performed."
}

production_guard() {
  [[ "${ROUND3_PRODUCTION_APPROVED:-}" == "YES" ]] || die "Set ROUND3_PRODUCTION_APPROVED=YES for production-mutating modes."
  assert_repo_state
}

image_repo_from_current_service() {
  local current repo base
  current="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(spec.template.spec.containers[0].image)')"
  [[ -n "$current" ]] || die "Could not read current Cloud Run image."
  repo="${current%@*}"
  base="${repo##*/}"
  if [[ "$base" == *:* ]]; then
    repo="${repo%:*}"
  fi
  printf '%s\n' "$repo"
}

deploy_candidate() {
  require_tools
  production_guard
  local sha short_sha image_repo image tag rev_suffix candidate_url revision
  sha="$(git rev-parse HEAD)"
  short_sha="${sha:0:8}"
  image_repo="$(image_repo_from_current_service)"
  image="${image_repo}:round3-${short_sha}"
  tag="r3-${short_sha}"
  rev_suffix="r3-${short_sha}-$(date -u +%m%d%H%M%S)"

  log "Building immutable image for $sha"
  gcloud builds submit . \
    --project "$PROJECT" \
    --config deploy/cloudbuild-fastapi.yaml \
    --substitutions="_IMAGE=${image}" \
    --quiet

  log "Deploying candidate revision with 0% production traffic and tag $tag"
  gcloud run deploy "$SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --image "$image" \
    --revision-suffix "$rev_suffix" \
    --no-traffic \
    --tag "$tag" \
    --quiet

  candidate_url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format=json | jq -r --arg tag "$tag" '.status.traffic[]? | select(.tag == $tag) | .url' | head -n1)"
  if [[ -z "$candidate_url" || "$candidate_url" == "null" ]]; then
    local service_url
    service_url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
    candidate_url="${service_url/https:\/\//https:\/\/${tag}---}"
  fi
  revision="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format=json | jq -r --arg tag "$tag" '.status.traffic[]? | select(.tag == $tag) | .revisionName' | head -n1)"
  [[ -n "$revision" && "$revision" != "null" ]] || die "Could not resolve candidate revision."

  jq -n --arg sha "$sha" --arg image "$image" --arg tag "$tag" --arg revision "$revision" --arg candidate_url "$candidate_url" \
    '{sha:$sha,image:$image,tag:$tag,revision:$revision,candidate_url:$candidate_url}' \
    | tee "$ARTIFACT_DIR/candidate.safe.json"
  log "Candidate deployed with 0% production traffic."
}

make_curl_config() {
  local cfg="$1" id_file="$2" secret_file="$3"
  set +x
  {
    printf 'silent\nshow-error\nfail-with-body\n'
    printf 'header = "Authorization: Bearer %s"\n' "$(tr -d '\r\n' < "$id_file")"
    printf 'header = "X-Ingestion-Token: %s"\n' "$(tr -d '\r\n' < "$secret_file")"
    printf 'header = "Accept: application/json"\n'
  } > "$cfg"
  chmod 600 "$cfg"
}

with_auth_files() {
  local callback="$1"; shift
  local secret_file id_file cfg
  secret_file="$(mktemp "$ARTIFACT_DIR/ingestion.XXXXXX")"
  id_file="$(mktemp "$ARTIFACT_DIR/idtoken.XXXXXX")"
  cfg="$(mktemp "$ARTIFACT_DIR/curl.XXXXXX")"
  chmod 600 "$secret_file" "$id_file" "$cfg"
  set +x
  gcloud secrets versions access latest --secret "$INGESTION_SECRET" --project "$PROJECT" > "$secret_file"
  gcloud auth print-identity-token > "$id_file"
  make_curl_config "$cfg" "$id_file" "$secret_file"
  "$callback" "$cfg" "$@"
  rm -f "$cfg" "$id_file" "$secret_file"
}

candidate_smoke_callback() {
  local cfg="$1" candidate_url="$2"
  log "Candidate /health"
  curl --config "$cfg" "${candidate_url}/health" | jq '{status,service,persistence_backend}'

  log "Candidate OpenAPI route check"
  curl --config "$cfg" "${candidate_url}/openapi.json" \
    | jq -e '.paths["/api/v1/financial/admin/official-events/refresh-all"] != null' >/dev/null \
    || die "Official-event batch route missing from candidate OpenAPI."

  local base material_url conference_url
  base="${candidate_url}/api/v1/financial/admin/official-events/refresh-all"
  material_url="${base}?include_conferences=false&include_material_events=true&material_openapi_only=true&trigger=manual&batch_scope=explicit&tickers=2330&tickers=2454&tickers=6770"
  conference_url="${base}?include_conferences=true&include_material_events=false&extract_documents=false&trigger=manual&batch_scope=explicit&tickers=2330&tickers=2454&tickers=6770"

  log "Candidate material-event explicit smoke: 2330 / 2454 / 6770"
  curl --config "$cfg" -X POST "$material_url" > "$ARTIFACT_DIR/candidate-material.json"
  jq '{batch_id,trigger,scope,status,requested_companies,completed_companies,partial_companies,failed_companies,elapsed_seconds}' "$ARTIFACT_DIR/candidate-material.json"
  [[ "$(jq -r '.requested_companies' "$ARTIFACT_DIR/candidate-material.json")" == "3" ]] || die "Candidate material smoke did not return 3 companies."
  [[ "$(jq -r '.failed_companies' "$ARTIFACT_DIR/candidate-material.json")" == "0" ]] || die "Candidate material smoke has technical failures."

  log "Candidate investor-conference explicit smoke: 2330 / 2454 / 6770"
  curl --config "$cfg" -X POST "$conference_url" > "$ARTIFACT_DIR/candidate-conference.json"
  jq '{batch_id,trigger,scope,status,requested_companies,completed_companies,partial_companies,failed_companies,elapsed_seconds}' "$ARTIFACT_DIR/candidate-conference.json"
  [[ "$(jq -r '.requested_companies' "$ARTIFACT_DIR/candidate-conference.json")" == "3" ]] || die "Candidate conference smoke did not return 3 companies."
  [[ "$(jq -r '.failed_companies' "$ARTIFACT_DIR/candidate-conference.json")" == "0" ]] || die "Candidate conference smoke has technical failures."
}

candidate_smoke() {
  require_tools
  production_guard
  [[ -f "$ARTIFACT_DIR/candidate.safe.json" ]] || die "Run deploy-candidate first."
  local candidate_url
  candidate_url="$(jq -r '.candidate_url' "$ARTIFACT_DIR/candidate.safe.json")"
  with_auth_files candidate_smoke_callback "$candidate_url"
  log "Candidate smoke passed. Production traffic is still unchanged."
}

promote_candidate() {
  require_tools
  production_guard
  [[ -f "$ARTIFACT_DIR/candidate.safe.json" ]] || die "Run deploy-candidate first."
  [[ -f "$ARTIFACT_DIR/candidate-material.json" && -f "$ARTIFACT_DIR/candidate-conference.json" ]] || die "Run candidate-smoke first."
  local revision
  revision="$(jq -r '.revision' "$ARTIFACT_DIR/candidate.safe.json")"
  log "Promoting $revision to 100% production traffic"
  gcloud run services update-traffic "$SERVICE" \
    --project "$PROJECT" \
    --region "$REGION" \
    --to-revisions="${revision}=100" \
    --quiet
  safe_service_json | tee "$ARTIFACT_DIR/cloud-run-after-promote.safe.json"
}

manual_validate_callback() {
  local cfg="$1" service_url="$2"
  local base material_url conference_url
  base="${service_url}/api/v1/financial/admin/official-events/refresh-all"
  material_url="${base}?include_conferences=false&include_material_events=true&material_openapi_only=true&trigger=manual&batch_scope=classified"
  conference_url="${base}?include_conferences=true&include_material_events=false&extract_documents=false&trigger=manual&batch_scope=classified"

  log "Running full material-event classified batch"
  curl --config "$cfg" -X POST "$material_url" > "$ARTIFACT_DIR/material-manual.json"
  jq '{batch_id,trigger,scope,status,requested_companies,completed_companies,partial_companies,failed_companies,elapsed_seconds}' "$ARTIFACT_DIR/material-manual.json"
  [[ "$(jq -r '.requested_companies' "$ARTIFACT_DIR/material-manual.json")" == "$EXPECTED_COMPANIES" ]] || die "Material batch scope is not ${EXPECTED_COMPANIES}."
  [[ "$(jq -r '.failed_companies' "$ARTIFACT_DIR/material-manual.json")" == "0" ]] || die "Material classified batch has technical failures."

  log "Running full investor-conference classified batch"
  curl --config "$cfg" -X POST "$conference_url" > "$ARTIFACT_DIR/conference-manual.json"
  jq '{batch_id,trigger,scope,status,requested_companies,completed_companies,partial_companies,failed_companies,elapsed_seconds}' "$ARTIFACT_DIR/conference-manual.json"
  [[ "$(jq -r '.requested_companies' "$ARTIFACT_DIR/conference-manual.json")" == "$EXPECTED_COMPANIES" ]] || die "Conference batch scope is not ${EXPECTED_COMPANIES}."
  [[ "$(jq -r '.failed_companies' "$ARTIFACT_DIR/conference-manual.json")" == "0" ]] || die "Conference classified batch has technical failures."
}

manual_validate() {
  require_tools
  production_guard
  local service_url
  service_url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"
  with_auth_files manual_validate_callback "$service_url"

  local batch_id material_feed_count
  batch_id="$(jq -r '.batch_id' "$ARTIFACT_DIR/material-manual.json")"
  material_feed_count="$(gcloud logging read \
    "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE} AND textPayload:\"official_events_material_feed batch_id=${batch_id}\"" \
    --project "$PROJECT" --limit=20 --format='value(textPayload)' 2>/dev/null | wc -l | tr -d ' ')"
  printf '%s\n' "$material_feed_count" > "$ARTIFACT_DIR/material-feed-log-count.txt"
  log "Observed official_events_material_feed log count for batch $batch_id: $material_feed_count"
  if [[ "$material_feed_count" != "1" ]]; then
    log "WARNING: expected exactly one material-feed log. Review Cloud Run logging before Scheduler creation."
  fi
}

compute_deadline_seconds() {
  python3 - "$1" <<'PY'
import math, sys
elapsed = float(sys.argv[1])
seconds = math.ceil((elapsed * 3 + 60) / 60) * 60
print(max(120, min(1800, seconds)))
PY
}

scheduler_upsert() {
  local job="$1" schedule="$2" uri="$3" audience="$4" deadline="$5" token="$6"
  local action="create"
  if gcloud scheduler jobs describe "$job" --project "$PROJECT" --location "$REGION" >/dev/null 2>&1; then
    action="update"
  fi
  set +x
  gcloud scheduler jobs "$action" http "$job" \
    --project "$PROJECT" \
    --location "$REGION" \
    --schedule "$schedule" \
    --time-zone "Asia/Taipei" \
    --uri "$uri" \
    --http-method POST \
    --oidc-service-account-email "$SCHEDULER_SA" \
    --oidc-token-audience "$audience" \
    --headers "X-Ingestion-Token=${token}" \
    --max-retry-attempts 2 \
    --max-retry-duration 600s \
    --min-backoff 30s \
    --max-backoff 120s \
    --max-doublings 2 \
    --attempt-deadline "${deadline}s" \
    --quiet
}

create_schedulers() {
  require_tools
  production_guard
  [[ -f "$ARTIFACT_DIR/material-manual.json" && -f "$ARTIFACT_DIR/conference-manual.json" ]] || die "Run manual-validate first."
  local material_failed conference_failed material_elapsed conference_elapsed material_deadline conference_deadline service_url
  material_failed="$(jq -r '.failed_companies' "$ARTIFACT_DIR/material-manual.json")"
  conference_failed="$(jq -r '.failed_companies' "$ARTIFACT_DIR/conference-manual.json")"
  [[ "$material_failed" == "0" && "$conference_failed" == "0" ]] || die "Do not create Schedulers while technical failures remain."

  material_elapsed="$(jq -r '.elapsed_seconds' "$ARTIFACT_DIR/material-manual.json")"
  conference_elapsed="$(jq -r '.elapsed_seconds' "$ARTIFACT_DIR/conference-manual.json")"
  material_deadline="$(compute_deadline_seconds "$material_elapsed")"
  conference_deadline="$(compute_deadline_seconds "$conference_elapsed")"
  service_url="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')"

  local material_uri conference_uri secret_file token
  material_uri="${service_url}/api/v1/financial/admin/official-events/refresh-all?include_conferences=false&include_material_events=true&material_openapi_only=true&trigger=scheduler&batch_scope=classified"
  conference_uri="${service_url}/api/v1/financial/admin/official-events/refresh-all?include_conferences=true&include_material_events=false&extract_documents=false&trigger=scheduler&batch_scope=classified"

  secret_file="$(mktemp "$ARTIFACT_DIR/scheduler-secret.XXXXXX")"
  chmod 600 "$secret_file"
  set +x
  gcloud secrets versions access latest --secret "$INGESTION_SECRET" --project "$PROJECT" > "$secret_file"
  token="$(tr -d '\r\n' < "$secret_file")"

  log "Creating/updating material-event Scheduler with computed deadline ${material_deadline}s"
  scheduler_upsert "$MATERIAL_JOB" '5 * * * *' "$material_uri" "$service_url" "$material_deadline" "$token"

  log "Creating/updating investor-conference Scheduler with computed deadline ${conference_deadline}s"
  scheduler_upsert "$CONFERENCE_JOB" '15 19 * * 1-5' "$conference_uri" "$service_url" "$conference_deadline" "$token"

  unset token
  rm -f "$secret_file"

  safe_scheduler_row "$MATERIAL_JOB" | tee "$ARTIFACT_DIR/material-scheduler-after.safe.json"
  safe_scheduler_row "$CONFERENCE_JOB" | tee "$ARTIFACT_DIR/conference-scheduler-after.safe.json"
}

trigger_and_wait() {
  local job="$1" kind="$2" marker="$3"
  local since batch_id completion
  since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log "Force-running $job"
  gcloud scheduler jobs run "$job" --project "$PROJECT" --location "$REGION" --quiet

  batch_id=""
  for _ in $(seq 1 60); do
    batch_id="$(gcloud logging read \
      "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE} AND timestamp>=\"${since}\" AND textPayload:\"official_events_batch_started\" AND textPayload:\"trigger=scheduler\" AND textPayload:\"scope=classified\" AND textPayload:\"${marker}\"" \
      --project "$PROJECT" --order=asc --limit=20 --format='value(textPayload)' 2>/dev/null \
      | sed -n 's/.*batch_id=\([0-9a-f][0-9a-f]*\).*/\1/p' | head -n1)"
    [[ -n "$batch_id" ]] && break
    sleep 5
  done
  [[ -n "$batch_id" ]] || die "Could not observe Scheduler-started $kind batch in Cloud Run logs."
  log "Observed $kind Scheduler batch_id=$batch_id"

  completion=""
  for _ in $(seq 1 120); do
    completion="$(gcloud logging read \
      "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE} AND textPayload:\"official_events_batch_completed batch_id=${batch_id}\"" \
      --project "$PROJECT" --order=desc --limit=1 --format='value(textPayload)' 2>/dev/null || true)"
    [[ -n "$completion" ]] && break
    sleep 10
  done
  [[ -n "$completion" ]] || die "Timed out waiting for Scheduler-started $kind batch $batch_id."
  printf '%s\n' "$completion" | tee "$ARTIFACT_DIR/${kind}-scheduler-completion.safe.txt"
}

trigger_verify() {
  require_tools
  production_guard
  trigger_and_wait "$MATERIAL_JOB" "material" "conferences=False material_events=True material_openapi_only=True"
  trigger_and_wait "$CONFERENCE_JOB" "conference" "conferences=True material_events=False material_openapi_only=False"
  safe_scheduler_row "$MATERIAL_JOB" | tee "$ARTIFACT_DIR/material-scheduler-triggered.safe.json"
  safe_scheduler_row "$CONFERENCE_JOB" | tee "$ARTIFACT_DIR/conference-scheduler-triggered.safe.json"
}

verify() {
  require_tools
  assert_repo_state
  log "Cloud Run safe state"
  safe_service_json
  log "Financial Scheduler unchanged check"
  safe_scheduler_row "$FINANCIAL_JOB"
  log "Material Scheduler"
  safe_scheduler_row "$MATERIAL_JOB"
  log "Conference Scheduler"
  safe_scheduler_row "$CONFERENCE_JOB"
  log "Secret version metadata only"
  gcloud secrets versions list "$INGESTION_SECRET" --project "$PROJECT" --format='table(name,state,createTime)'
}

usage() {
  cat <<'USAGE'
Usage: bash deploy/round3_cloudshell.sh MODE

Read-only:
  preflight          Verify Git sync and inspect safe GCP metadata only.
  verify             Show safe Cloud Run/Scheduler/Secret metadata only.

Production-mutating (requires: export ROUND3_PRODUCTION_APPROVED=YES):
  deploy-candidate   Build HEAD and deploy a tagged 0%-traffic Cloud Run revision.
  candidate-smoke    Smoke candidate with 2330, 2454, 6770 using temporary secret files.
  promote            Shift 100% Cloud Run traffic to the tested candidate revision.
  manual-validate    Run 96-company material and conference batches against production.
  create-schedulers  Create/update the two Round 3 Scheduler jobs after validation.
  trigger-verify     Force-run both new Scheduler jobs and verify completion in safe Cloud Run logs.

This script never prints the ingestion-token value and safe Scheduler output excludes headers.
USAGE
}

main() {
  case "${1:-}" in
    preflight) preflight ;;
    deploy-candidate) deploy_candidate ;;
    candidate-smoke) candidate_smoke ;;
    promote) promote_candidate ;;
    manual-validate) manual_validate ;;
    create-schedulers) create_schedulers ;;
    trigger-verify) trigger_verify ;;
    verify) verify ;;
    *) usage; exit 2 ;;
  esac
}

main "$@"
