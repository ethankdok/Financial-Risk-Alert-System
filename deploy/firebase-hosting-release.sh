#!/usr/bin/env bash
# Deploy a clean Hosting domain only after the approved Cloud Run release is promoted.
set -euo pipefail
PROJECT=fintrust-alert-ccu
SITE="${1:-fintrust-ccu}"
STATE="${FINTRUST_RELEASE_STATE:-$HOME/.fintrust-user-first-release-state}"
REGION=asia-east1
WEB=financial-risk-web
[[ "$SITE" == fintrust-ccu || "$SITE" == fintrust-alert-ccu ]] || { echo "Use one of the approved site IDs"; exit 1; }
[[ -f "$STATE" ]] || { echo "No release state"; exit 1; }
mapfile -t s < "$STATE"
[[ "${#s[@]}" == 10 && "$(git rev-parse HEAD)" == "${s[0]}" ]] || { echo "Stage current release first"; exit 1; }
serving(){
 gcloud run services describe "$1" --project="$PROJECT" --region="$REGION" --format=json | python3 -c 'import json,sys; a=[t for t in json.load(sys.stdin)["status"]["traffic"] if t.get("percent",0)>0]; assert len(a)==1 and a[0]["percent"]==100; print(a[0]["revisionName"])'
}
[[ "$(serving "$WEB")" == "$WEB-ui-final-${s[8]}" && "$(serving fintrust-api)" == "${s[3]}" ]] || { echo "STOP: promote and verify the new Cloud Run revision before publishing Hosting"; exit 1; }
CLI=(npx --yes firebase-tools)
"${CLI[@]}" hosting:sites:list --project "$PROJECT" --json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d.get("status")=="success", d; print(json.dumps(d["result"]))' > /tmp/fintrust-hosting-sites.json
if ! python3 - "$SITE" /tmp/fintrust-hosting-sites.json <<'PY'
import sys,json
d=json.load(open(sys.argv[2]))
sites=d.get("sites",[]) if isinstance(d,dict) else d
assert isinstance(sites,list)
sys.exit(0 if any(str(s.get("name","")).split("/")[-1]==sys.argv[1] or s.get("siteId")==sys.argv[1] for s in sites) else 1)
PY
then
 "${CLI[@]}" hosting:sites:create "$SITE" --project "$PROJECT"
fi
CTX="$(mktemp -d)"
trap 'rm -rf "$CTX"' EXIT
mkdir "$CTX/public"
# Only an empty public directory: do not upload repository, secrets, financial files or source.
python3 - "$SITE" "$CTX/firebase.json" <<'PY'
import json,sys
json.dump({"hosting":{"site":sys.argv[1],"public":"public","rewrites":[{"source":"**","run":{"serviceId":"financial-risk-web","region":"asia-east1"}}]}},open(sys.argv[2],"w"),indent=2)
PY
(cd "$CTX" && "${CLI[@]}" deploy --only hosting --project "$PROJECT" --config firebase.json)
URL="https://$SITE.web.app"
python3 scripts/fintrust_user_first_ui_smoke.py --base "$URL" --ticker 2330 --strict-full-stack
curl -fsS "$URL/api/member/auth/web-config" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["configured"] and d["firebase"]["projectId"]=="fintrust-alert-ccu"; print("PASS Firebase configuration")'
echo "Hosting published: $URL"
echo "Authorize $SITE.web.app in Firebase Authentication and test both sign-in methods and logout on this domain."
