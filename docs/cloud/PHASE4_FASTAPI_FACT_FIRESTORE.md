# Phase 4 — Remove FastAPI Direct-Ingest Runtime SQLite Blocker

## Goal

The main scheduled analysis pipeline already supports `DATASTORE_BACKEND=firestore`, but `/api/v1/financial/facts/ingest` previously instantiated a separate SQLite-only `FinancialFactRepository`. On Cloud Run this would create an ephemeral `financial_facts.sqlite3` file.

Phase 4 makes the fact-ingest repository follow the same `DATASTORE_BACKEND` setting as the rest of FinTrust.

## Result

`fact_repository.py` now provides:

- `SqliteFinancialFactRepository` for local/test compatibility;
- `FirestoreFinancialFactRepository` for production;
- `build_fact_repository()` selected by `DATASTORE_BACKEND`.

Firestore writes ingested facts into the existing `normalized_financial_facts` collection rather than creating another cloud collection. Ingested records use `analysis_type=ingested` and preserve source URL, taxonomy concept, statement scope, filing timestamp and demo status.

The protected ingest endpoint now performs:

```text
FactIngestRequest.facts
    → repository.upsert_many(...)
    → normalized_financial_facts
```

and returns the number of accepted facts.

## Production settings

```text
DATASTORE_BACKEND=firestore
GOOGLE_CLOUD_PROJECT=<project-id>
```

No local runtime SQLite path is required in Cloud Run.

## Local fallback

With no environment change, development remains SQLite-compatible:

```text
DATASTORE_BACKEND=sqlite
FINANCIAL_FACT_DATABASE_PATH=./data/financial_facts.sqlite3
```

## Validation scope

The offline tests cover SQLite upsert/update behavior and the Firestore serialization round-trip. Real Firestore read/write will be validated after a Google Cloud project and ADC credentials are available.
