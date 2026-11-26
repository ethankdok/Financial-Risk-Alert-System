#!/usr/bin/env bash
# Two-service Cloud Run release. No production traffic changes during stage.
set -Eeuo pipefail
PROJECT="${PROJECT:-fintrust-alert-ccu}"
REGION="${REGION:-asia-east1}"
WEB="${WEB_SERVICE:-financial-risk-web}"
API="${API_SERVICE:-fintrust-api}"
EXPECTED_WEB="https://financial-risk-web-v53gsmuxdq-de.a.run.app"
STATE="${FINTRUST_RELEASE_STATE:-$HOME/.fintrust-user-first-release-state}"
MODE="${1:-preflight}"
die(){ echo "STOP: $*" >&2; exit 1; }
gc(){ gcloud "$@" --project="$PROJECT" --quiet; }
service_url(){ gc run services describe "$1" --region="$REGION" --format='value(status.url)'; }
serving(){ gc run services describe "$1" --region="$REGION" --format=json | python3 -c 'import sys,json; a=[x for x in json.load(sys.stdin)["status"]["traffic"] if x.get("percent",0)>0]; assert len(a)==1 and a[0]["percent"]==100 and a[0].get("revisionName"), "Expected one serving revision"; print(a[0]["revisionName"])'; }
tag_info(){ gc run services describe "$1" --region="$REGION" --format=json | python3 -c 'import sys,json; a=[x for x in json.load(sys.stdin)["status"]["traffic"] if x.get("tag")==sys.argv[1]]; assert len(a)==1 and a[0].get("url") and a[0].get("revisionName"), "Missing candidate tag"; print(a[0]["revisionName"]); print(a[0]["url"])' "$2"; }
image_base(){ gc run revisions describe "$1" --region="$REGION" --format='value(spec.containers[0].image)' | python3 -c 'import sys; s=sys.stdin.read().strip().split("@")[0]; assert "/" in s; print(s.rsplit(":",1)[0] if ":" in s.rsplit("/",1)[-1] else s)'; }
traffic(){ gc run services update-traffic "$1" --region="$REGION" --to-revisions="$2=100" >/dev/null; }
health(){ curl -fsS --max-time 45 "$1/health" | python3 -c 'import json,sys; x=json.load(sys.stdin); assert x.get("status")=="ok",x; print("PASS health")'; }
check_web_store(){ curl -fsS --max-time 45 "$1/health" | python3 -c 'import json,sys; x=json.load(sys.stdin); assert x.get("status")=="ok" and x.get("datastore_backend")=="firestore", "Flask is not using production Firestore"; print("PASS Firestore")'; }
assert_env(){
  gc run services describe "$1" --region="$REGION" --format=json | python3 -c 'import sys,json; d=json.load(sys.stdin); env={e["name"]:e.get("value") for e in d["spec"]["template"]["spec"]["containers"][0].get("env",[])}; pairs=[x.split("=",1) for x in sys.argv[1:]]; assert all(env.get(k)==v for k,v in pairs), "Production environment differs from expected; inspect existing service without disclosing secrets"' "${@:2}"
}
preflight(){
  command -v gcloud >/dev/null || die "Run in authenticated Google Cloud Shell"
  command -v python3 >/dev/null || die "python3 required"
  [[ "$(service_url "$WEB")" == "$EXPECTED_WEB" ]] || die "Web service URL differs from original production URL"
  API_URL="$(service_url "$API")"; [[ "$API_URL" == https://* ]] || die "Cannot resolve existing API URL"
  OLD_WEB="$(serving "$WEB")"; OLD_API="$(serving "$API")"
  assert_env "$WEB" APP_ENV=production FLASK_DATASTORE_BACKEND=firestore FINTRUST_API_BASE_URL="$API_URL"
  assert_env "$API" APP_ENV=production DATASTORE_BACKEND=firestore
  check_web_store "$EXPECTED_WEB"; health "$API_URL"
  printf 'Verified existing URL and serving revisions:\n%s %s\n%s %s\n' "$WEB" "$OLD_WEB" "$API" "$OLD_API"
}
clean_checkout(){
  [[ -z "$(git status --porcelain)" ]] || die "Use a clean checkout of the release branch"
  SHA="$(git rev-parse HEAD)"
  git merge-base --is-ancestor d60fa60df0bfc37293bb87b00d100cbec52a3b6f "$SHA" || die "Missing required release fixes"
}
smoke(){ python3 scripts/fintrust_user_first_ui_smoke.py --base "$1" --ticker 2330 --strict-full-stack; check_web_store "$1"; }
offline(){
  local venv
  venv="$(mktemp -d)"
  python3 -m venv "$venv"
  "$venv/bin/python" -m pip install -q -r requirements.txt -r fintrust_backend/requirements.txt
  "$venv/bin/python" -m unittest discover -s tests -p 'test_claim_verification_proxy.py'
  "$venv/bin/python" -m unittest discover -s tests -p 'test_public_company_directory.py'
  (cd fintrust_backend && "$venv/bin/python" -m unittest discover -s tests -p 'test_claim_verification.py')
  (cd fintrust_backend && "$venv/bin/python" -m unittest discover -s tests -p 'test_integrity_firestore_timestamps.py')
  command -v node >/dev/null || die "Node.js required for frontend regression"
  for f in ft-*.js; do node --check "$f"; done
  node tests/ft_frontend_route_smoke.cjs
  "$venv/bin/python" -m unittest discover -s tests -p 'test_managed_member_auth.py'
  rm -rf "$venv"
}
build_context(){
  CTX="$(mktemp -d)"
  # Export tracked files only, and only the paths needed by the existing Dockerfiles.
  mapfile -t paths < <(git ls-tree -r --name-only HEAD | python3 -c 'import sys; fixed={"Dockerfile.flask","Dockerfile.fastapi",".dockerignore","requirements.txt","ft-mops-data.json","fintrust_backend/requirements.txt","deploy/cloudbuild-flask.yaml","deploy/cloudbuild-fastapi.yaml"}; print("\n".join(p for p in map(str.strip,sys.stdin) if p in fixed or ("/" not in p and p.endswith((".py",".html",".js",".css"))) or p.startswith(("static/","templates/","fintrust_backend/app/"))))')
  git archive HEAD -- "${paths[@]}" | tar -x -C "$CTX"
}
stage(){
  [[ ! -e "$STATE" ]] || die "Existing release state: inspect before staging another release"
  preflight; clean_checkout; offline; build_context
  local stamp api_image web_image api_tag web_tag ai wi
  stamp="$(date -u +%y%m%d%H%M%S)"
  api_image="$(image_base "$OLD_API"):ui-$stamp"
  web_image="$(image_base "$OLD_WEB"):ui-$stamp"
  api_tag="ui-api-$stamp"; web_tag="ui-web-$stamp"
  gc builds submit "$CTX" --config="$CTX/deploy/cloudbuild-fastapi.yaml" --substitutions="_IMAGE=$api_image"
  gc builds submit "$CTX" --config="$CTX/deploy/cloudbuild-flask.yaml" --substitutions="_IMAGE=$web_image"
  rm -rf "$CTX"
  gc run deploy "$API" --region="$REGION" --image="$api_image" --revision-suffix="ui-$stamp" --no-traffic --tag="$api_tag"
  mapfile -t ai < <(tag_info "$API" "$api_tag")
  [[ "${#ai[@]}" == 2 ]] || die "API candidate not found"
  health "${ai[1]}"
  gc run deploy "$WEB" --region="$REGION" --image="$web_image" --revision-suffix="ui-$stamp" --no-traffic --tag="$web_tag" --update-env-vars="FINTRUST_API_BASE_URL=${ai[1]}"
  mapfile -t wi < <(tag_info "$WEB" "$web_tag")
  [[ "${#wi[@]}" == 2 ]] || die "Web candidate not found"
  [[ "$(serving "$WEB")" == "$OLD_WEB" && "$(serving "$API")" == "$OLD_API" ]] || die "Serving revisions changed unexpectedly"
  (umask 077; printf '%s\n' "$SHA" "$OLD_WEB" "$OLD_API" "${ai[0]}" "${ai[1]}" "${wi[0]}" "${wi[1]}" "$web_image" "$stamp" "$API_URL" > "$STATE")
  smoke "${wi[1]}"
  printf 'STAGED; production unchanged.\nCandidate website: %s\nVerify login, Google sign-in (if enabled), company search, file parsing, claim evidence and mobile UI manually. Then run promote --browser-verified.\n' "${wi[1]}"
}
repair_backend(){
  [[ -f "$STATE" ]] || die "No staged release state"
  mapfile -t s < "$STATE"; [[ "${#s[@]}" == 10 ]] || die "Invalid release state"
  clean_checkout
  [[ "$SHA" != "${s[0]}" ]] || die "Pull backend fix before repair"
  git merge-base --is-ancestor "${s[0]}" "$SHA" || die "Staged commit not an ancestor"
  # Reuse the previously built Flask image only when no Flask runtime source changed.
  local p
  while IFS= read -r p; do
    case "$p" in
      fintrust_backend/*|deploy/user_first_cloud_run_release.sh|.github/workflows/*|docs/*) ;;
      *) die "Frontend/runtime change requires full rebuild: $p" ;;
    esac
  done < <(git diff --name-only "${s[0]}" "$SHA")
  [[ "$(service_url "$WEB")" == "$EXPECTED_WEB" && "$(service_url "$API")" == "${s[9]}" ]] || die "Service URLs changed"
  [[ "$(serving "$WEB")" == "${s[1]}" && "$(serving "$API")" == "${s[2]}" ]] || die "Production traffic changed since staging"
  offline; build_context
  local stamp api_image api_tag web_tag ai wi
  stamp="$(date -u +%y%m%d%H%M%S)"
  api_image="$(image_base "${s[2]}"):ui-$stamp"
  api_tag="ui-api-$stamp"; web_tag="ui-web-$stamp"
  gc builds submit "$CTX" --config="$CTX/deploy/cloudbuild-fastapi.yaml" --substitutions="_IMAGE=$api_image"
  rm -rf "$CTX"
  gc run deploy "$API" --region="$REGION" --image="$api_image" --revision-suffix="ui-$stamp" --no-traffic --tag="$api_tag"
  mapfile -t ai < <(tag_info "$API" "$api_tag")
  [[ "${#ai[@]}" == 2 ]] || die "API candidate not found"
  health "${ai[1]}"
  gc run deploy "$WEB" --region="$REGION" --image="${s[7]}" --revision-suffix="ui-$stamp" --no-traffic --tag="$web_tag" --update-env-vars="FINTRUST_API_BASE_URL=${ai[1]}"
  mapfile -t wi < <(tag_info "$WEB" "$web_tag")
  [[ "${#wi[@]}" == 2 ]] || die "Web candidate not found"
  [[ "$(serving "$WEB")" == "${s[1]}" && "$(serving "$API")" == "${s[2]}" ]] || die "Serving revisions changed unexpectedly"
  # Keep rollback revisions and replace candidate state atomically.
  (umask 077; printf '%s\n' "$SHA" "${s[1]}" "${s[2]}" "${ai[0]}" "${ai[1]}" "${wi[0]}" "${wi[1]}" "${s[7]}" "$stamp" "${s[9]}" > "$STATE.tmp")
  mv "$STATE.tmp" "$STATE"
  smoke "${wi[1]}"
  printf 'STAGED; production unchanged.\nCandidate website: %s\nVerify browser operations before promote --browser-verified.\n' "${wi[1]}"
}
stage_auth(){
  [[ -f "$STATE" ]] || die "No staged release state"
  mapfile -t s < "$STATE"; [[ "${#s[@]}" == 10 ]] || die "Invalid release state"
  clean_checkout
  git merge-base --is-ancestor "${s[0]}" "$SHA" || die "Staged commit not an ancestor"
  [[ -z "$(git diff --name-only "${s[0]}" "$SHA" -- fintrust_backend Dockerfile.fastapi data_shift.py deploy/cloudbuild-fastapi.yaml)" ]] || die "FastAPI source changed; cannot reuse candidate"
  [[ "$(service_url "$WEB")" == "$EXPECTED_WEB" && "$(service_url "$API")" == "${s[9]}" ]] || die "Service URLs changed"
  [[ "$(serving "$WEB")" == "${s[1]}" && "$(serving "$API")" == "${s[2]}" ]] || die "Production traffic changed"
  health "${s[4]}"
  [[ -n "${FIREBASE_WEB_API_KEY:-}" && -n "${FIREBASE_WEB_APP_ID:-}" ]] || die "Set public Firebase web API key and app ID in Cloud Shell"
  offline; build_context
  local stamp web_image wi
  stamp="$(date -u +%y%m%d%H%M%S)"
  web_image="$(image_base "${s[1]}"):auth-$stamp"
  gc builds submit "$CTX" --config="$CTX/deploy/cloudbuild-flask.yaml" --substitutions="_IMAGE=$web_image"
  rm -rf "$CTX"
  gc run deploy "$WEB" --region="$REGION" --image="$web_image" --revision-suffix="auth-$stamp" --no-traffic --tag=google-login --update-env-vars="FINTRUST_API_BASE_URL=${s[4]},FIREBASE_PROJECT_ID=$PROJECT,FIREBASE_AUTH_DOMAIN=$PROJECT.firebaseapp.com,FIREBASE_WEB_API_KEY=$FIREBASE_WEB_API_KEY,FIREBASE_WEB_APP_ID=$FIREBASE_WEB_APP_ID"
  mapfile -t wi < <(tag_info "$WEB" google-login)
  [[ "${#wi[@]}" == 2 ]] || die "Auth candidate missing"
  [[ "$(serving "$WEB")" == "${s[1]}" && "$(serving "$API")" == "${s[2]}" ]] || die "Production traffic changed"
  smoke "${wi[1]}"
  auth_config "${wi[1]}"
  (umask 077; printf '%s\n' "$SHA" "${s[1]}" "${s[2]}" "${s[3]}" "${s[4]}" "${wi[0]}" "${wi[1]}" "$web_image" "$stamp" "${s[9]}" > "$STATE.tmp")
  mv "$STATE.tmp" "$STATE"
  printf 'AUTH STAGED; production unchanged.\nCandidate: %s/login.html\nAuthorize its hostname in Firebase and manually verify both sign-in methods.\n' "${wi[1]}"
}
auth_config(){
  curl -fsS --max-time 30 "$1/api/member/auth/web-config" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["configured"] and d["firebase"]["projectId"]==sys.argv[1] and not d["local_password_enabled"]; print("PASS managed Firebase configuration")' "$PROJECT"
}
promote(){
  [[ "${2:-}" == --browser-verified ]] || die "Manual browser verification is required before promotion"
  [[ -f "$STATE" ]] || die "No staged release state"
  # Do not source a file as executable shell code.
  mapfile -t s < "$STATE"; [[ "${#s[@]}" == 10 ]] || die "Invalid release state"
  clean_checkout; [[ "$SHA" == "${s[0]}" ]] || die "Checkout changed since staging"
  [[ "$(service_url "$WEB")" == "$EXPECTED_WEB" && "$(service_url "$API")" == "${s[9]}" ]] || die "Service URLs changed"
  [[ "$(serving "$WEB")" == "${s[1]}" && "$(serving "$API")" == "${s[2]}" ]] || die "Production traffic changed since staging"
  smoke "${s[6]}"
  auth_config "${s[6]}"
  local final_tag="ui-final-${s[8]}"
  local promoted=0
  rollback_on_error(){
    local rc=$?
    trap - EXIT
    if (( rc != 0 && promoted == 1 )); then
      echo "Release failed: restoring previous pinned revisions" >&2
      traffic "$WEB" "${s[1]}" || echo "MANUAL web rollback required" >&2
      traffic "$API" "${s[2]}" || echo "MANUAL API rollback required" >&2
    fi
    exit "$rc"
  }
  trap rollback_on_error EXIT
  promoted=1
  traffic "$API" "${s[3]}"
  # Deploy identical web image, but restore the stable API URL for future API updates.
  gc run deploy "$WEB" --region="$REGION" --image="${s[7]}" --revision-suffix="ui-final-${s[8]}" --no-traffic --tag="$final_tag" --update-env-vars="FINTRUST_API_BASE_URL=${s[9]}"
  mapfile -t fin < <(tag_info "$WEB" "$final_tag")
  [[ "${#fin[@]}" == 2 ]] || die "Final web candidate missing"
  smoke "${fin[1]}"
  auth_config "${fin[1]}"
  traffic "$WEB" "${fin[0]}"
  [[ "$(serving "$WEB")" == "${fin[0]}" && "$(serving "$API")" == "${s[3]}" ]] || die "Traffic verification failed"
  smoke "$EXPECTED_WEB"
  auth_config "$EXPECTED_WEB"
  promoted=0; trap - EXIT
  printf 'PROMOTED: %s\nPrevious revisions retained: %s %s\n' "$EXPECTED_WEB" "${s[1]}" "${s[2]}"
  printf 'Rollback if needed: gcloud run services update-traffic %s --project=%s --region=%s --to-revisions=%s=100; repeat for %s revision %s\n' "$WEB" "$PROJECT" "$REGION" "${s[1]}" "$API" "${s[2]}"
}
case "$MODE" in
  preflight) preflight ;;
  stage) stage ;;
  repair-backend) repair_backend ;;
  stage-auth) stage_auth ;;
  promote) promote "$@" ;;
  *) die "Usage: bash deploy/user_first_cloud_run_release.sh {preflight|stage|repair-backend|stage-auth|promote --browser-verified}" ;;
esac
