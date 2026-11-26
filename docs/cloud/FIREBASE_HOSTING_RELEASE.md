# FinTrust Hosting release

Use existing project fintrust-alert-ccu, Cloud Run asia-east1. No backend migration.
1. Stage the updated Flask image via stage-auth with the Firebase public web app identifiers. Retain the validated API revision.
2. Authorize the candidate domain and both intended Hosting domains in Firebase Authentication. Verify Google, verified password registration, reset, linking, and logout manually.
3. Promote only after browser and API tests. Existing run.app remains available.
4. Run bash deploy/firebase-hosting-release.sh fintrust-ccu. If unavailable, explicitly select fintrust-alert-ccu. The script requires the promoted revision and uses an empty public directory plus Cloud Run rewrite; no repo files are uploaded.
5. Verify Hosting login independently. Hosting forwards only __session; member/admin APIs are no-store. Cookies are scoped to each hostname, so sign in again after changing domains. Hosting has a 60-second request limit; keep direct Cloud Run URL for requests exceeding that limit.
