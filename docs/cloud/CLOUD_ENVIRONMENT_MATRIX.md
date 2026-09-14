# Cloud Environment Matrix

| Variable | Flask local | Flask Cloud Run | FastAPI local | FastAPI Cloud Run | Secret? |
|---|---|---|---|---|---|
| `APP_ENV` | `development` | `production` | `development` | `production` | No |
| `GOOGLE_CLOUD_PROJECT` | optional | required | optional | required | No |
| `SECRET_KEY` | optional dev fallback | required | — | — | Yes |
| `FLASK_DATASTORE_BACKEND` | `sqlite` | `firestore` | — | — | No |
| `ALLOW_DEMO_SEED_DATA` | `true` | `false` | — | — | No |
| `FINTRUST_API_BASE_URL` | localhost FastAPI | Cloud Run FastAPI URL | — | — | No |
| `FINTRUST_INGESTION_TOKEN` | optional | required for protected proxy actions | — | — | Yes |
| `DATASTORE_BACKEND` | — | — | `sqlite` | `firestore` | No |
| `INGESTION_API_TOKEN` | — | — | optional dev | required production | Yes |
| `GEMINI_API_KEY` | — | — | local `.env` | Secret Manager | Yes |
| `FINANCIAL_LLM_PROVIDER` | — | — | `gemini` | `gemini` | No |
| `FINANCIAL_LLM_MODEL` | — | — | configured model | configured model | No |
| `CORS_ALLOW_ORIGINS` | — | — | localhost | Flask origin only if browser access is ever needed | No |

`FINTRUST_INGESTION_TOKEN` and `INGESTION_API_TOKEN` are two environment-variable names for the same shared secret: Flask sends it; FastAPI validates it.
