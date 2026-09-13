# Phase 7 — Cloud Run Production Preparation

## Target architecture

```text
Browser
  → financial-risk-web (Flask, Cloud Run)
      → fintrust-api (FastAPI, Cloud Run)
          → Firestore
          → MOPS / TWSE official sources
          → Gemini
```

Both Cloud Run services should use `asia-east1` so the application and Firestore can be kept in Taiwan when the Firestore database is also created in `asia-east1`.

## Container entrypoints

- `Dockerfile.flask`: Gunicorn, one worker + threads, listens on Cloud Run's injected `$PORT`.
- `Dockerfile.fastapi`: Uvicorn, listens on `$PORT`.
- `/healthz` is available on both services.

## Production datastore settings

Flask:

```text
APP_ENV=production
FLASK_DATASTORE_BACKEND=firestore
GOOGLE_CLOUD_PROJECT=<project-id>
ALLOW_DEMO_SEED_DATA=false
```

FastAPI:

```text
APP_ENV=production
DATASTORE_BACKEND=firestore
GOOGLE_CLOUD_PROJECT=<project-id>
```

No runtime SQLite path is required in production.

## Secrets

Secret Manager should hold:

- `SECRET_KEY` → injected into Flask as `SECRET_KEY`;
- `INGESTION_API_TOKEN` → injected into FastAPI as `INGESTION_API_TOKEN`;
- the same ingestion secret → injected into Flask as `FINTRUST_INGESTION_TOKEN`;
- `GEMINI_API_KEY` → injected into FastAPI.

Never store the values in `.env.example`, GitHub, Dockerfile, Cloud Build YAML, or frontend JavaScript.

## Non-secret configuration

Flask:

```text
FINTRUST_API_BASE_URL=https://<fintrust-api-cloud-run-url>
```

FastAPI:

```text
FINANCIAL_LLM_PROVIDER=gemini
FINANCIAL_LLM_MODEL=<selected-model>
FINANCIAL_AI_AUTO_LLM_ENABLED=true
```

Because browsers call Flask and Flask calls FastAPI server-to-server, CORS does not need to expose the FastAPI service broadly to browsers.

## Service identities

Use Cloud Run service accounts / Application Default Credentials to access Firestore. Do not upload a service-account JSON key into the repository or container.

The runtime service identity needs Firestore read/write permission. If secrets are attached from Secret Manager, it also needs permission to access those secrets.

## Build artifacts

The repo contains two Dockerfiles because Flask and FastAPI are separate Cloud Run services:

```text
Dockerfile.flask
Dockerfile.fastapi
```

and Cloud Build configs:

```text
deploy/cloudbuild-flask.yaml
deploy/cloudbuild-fastapi.yaml
```

The actual build/deploy commands are intentionally deferred until the Google Cloud project, Firestore database, Artifact Registry repository, service accounts and secrets exist.

## Domain strategy

First validate the stable Cloud Run URL. Custom domain work comes only after integration tests pass. Do not use DNS configuration to debug application deployment problems.
