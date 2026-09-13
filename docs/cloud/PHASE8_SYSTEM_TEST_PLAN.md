# Phase 8 — Integration / System Test Plan

This plan is intentionally separate from the later user/usability experiment. Its purpose is to answer: **does the integrated system produce technically correct, traceable and stable results?**

## A. Deployment and service health

| ID | Test | Expected result |
|---|---|---|
| SYS-01 | Open Flask `/health` | 200; reports web service and configured datastore backend |
| SYS-02 | Open FastAPI `/health` | 200; reports API service and persistence backend |
| SYS-03 | Flask `/api/financial/health` | Flask can reach FastAPI; no localhost dependency |
| SYS-04 | Restart/redeploy a Cloud Run revision | persistent records remain in Firestore |

## B. Datastore correctness

| ID | Test | Expected result |
|---|---|---|
| DB-01 | SQLite→Firestore migration | exact source/destination counts match |
| DB-02 | Migration fingerprint verification | SHA-256 fingerprint matches every migrated collection |
| DB-03 | Create a keyword after migration | new numeric ID is greater than migrated max ID |
| DB-04 | Update risk feature | Firestore update survives Cloud Run restart |
| DB-05 | Audit log write | before/after are native map values and admin provenance is preserved |
| DB-06 | Analysis record write | matched keywords/features are native arrays and persist |

## C. Authentication / authorization

| ID | Test | Expected result |
|---|---|---|
| AUTH-01 | Valid admin login | session created; `/api/auth/me` returns current admin |
| AUTH-02 | Wrong password | 401; no session created |
| AUTH-03 | Content reviewer calls system-admin endpoint | 403 |
| AUTH-04 | Disable last active system admin | rejected |
| AUTH-05 | Production missing `SECRET_KEY` | service fails fast rather than using development key |

## D. Financial evidence pipeline

| ID | Test | Expected result |
|---|---|---|
| FIN-01 | Company registry | 2330/2303/2454/3711 available |
| FIN-02 | Scheduled/manual refresh | run recorded with source provenance |
| FIN-03 | Historical metric calculation | formula, period, value and source fields are present |
| FIN-04 | Rule result | deterministic rule result matches stored inputs |
| FIN-05 | Latest snapshot | frontend response matches persisted snapshot |
| FIN-06 | `/metrics?latest_only=true` | returns latest run only; no 500 |
| FIN-07 | `/analysis-runs` | returns persisted run history; no 500 |
| FIN-08 | Direct fact ingestion | Firestore is used when `DATASTORE_BACKEND=firestore`; no local SQLite created |

## E. Official evidence / external-source failure handling

| ID | Test | Expected result |
|---|---|---|
| EXT-01 | TWSE source available | official event has title/date/source URL and stable identity |
| EXT-02 | Investor conference document available | extraction status + source document retained |
| EXT-03 | TWSE timeout/unavailable | controlled error/fallback; web process stays alive |
| EXT-04 | MOPS source failure | insufficient-data/error state is explicit; no fabricated values |
| EXT-05 | duplicate material event | dedupe prevents duplicate stored evidence |

## F. LLM behavior

| ID | Test | Expected result |
|---|---|---|
| LLM-01 | Gemini available | narrative is generated from deterministic evidence |
| LLM-02 | Gemini unavailable/key invalid | deterministic financial evidence still renders/fails softly |
| LLM-03 | Secret exposure scan | API/UI responses never expose Gemini key or ingestion token |
| LLM-04 | Numeric consistency | narrative does not replace authoritative stored value/rule severity |

## G. Claim verification API contracts

| ID | Test | Expected result |
|---|---|---|
| CLM-01 | `/claims/extract` | 200 structured claim, no request-field mismatch |
| CLM-02 | `/claims/verify` without stored evidence | structured `insufficient_evidence`, not 500 |
| CLM-03 | supported claim with evidence | verdict + calculation + official URLs returned |
| CLM-04 | contradicted claim | deterministic difference and contradiction explanation returned |

## H. Cloud smoke test

After deployment, run the non-destructive checker:

```powershell
python scripts/cloud_smoke_test.py `
  --web-url https://<flask-service-url> `
  --api-url https://<fastapi-service-url> `
  --ticker 2330
```

It does not trigger ingestion or write data. It checks health, Flask→FastAPI connectivity, persisted endpoint contracts and obvious sensitive-key exposure.
