# Phase 2 — Flask Repository Layer + Firestore Backend

Baseline: `feature/cloud-deployment` created from `v4-integration` @ `d85334d196eb59f6150501384ced78bb3a957de9`.

## Goal

Remove direct request-time SQL from `app.py` without changing the public Flask API. The application now talks to a datastore repository contract, with two implementations:

- `SqliteFlaskDataRepository` — local/test compatibility and migration verification.
- `FirestoreFlaskDataRepository` — target production datastore for Cloud Run.

The backend is selected by:

```text
FLASK_DATASTORE_BACKEND=sqlite|firestore
```

Default remains `sqlite` so existing local development continues to work before Firestore credentials are configured.

## Files

- `flask_data_repository.py` — repository protocol plus SQLite and Firestore implementations.
- `app.py` — routes now call repository methods instead of issuing SQL.
- `requirements.txt` — adds `google-cloud-firestore` for the Flask service.
- `tests/test_flask_data_repository.py` — local repository regression tests.
- `scripts/audit_runtime_datastores.py` — classifies Flask SQLite as an allowed fallback instead of a production blocker.

## Compatibility decisions

- Existing integer IDs remain unchanged.
- Firestore document IDs use the numeric ID converted to string.
- `_meta/counters` allocates new integer IDs transactionally.
- `risk_features.keywords` is a native Firestore array.
- audit `before` / `after` and analysis match details are native maps/arrays.
- HTTP response fields remain compatible with the current frontend.
- Password hashes never appear in admin API responses or audit payloads.

## Demo seed safety

Local SQLite still creates the existing demo accounts and seed content automatically.

Firestore does **not** auto-create demo accounts unless explicitly enabled:

```text
ALLOW_DEMO_SEED_DATA=true
```

Production should leave this unset/false and receive admin/keyword/feature data through the migration step.

## Production environment (later Cloud Run phase)

```text
FLASK_DATASTORE_BACKEND=firestore
GOOGLE_CLOUD_PROJECT=<project-id>
ALLOW_DEMO_SEED_DATA=false
```

Cloud Run should use its service account / Application Default Credentials rather than a committed service-account JSON key.

## Validation completed in Phase 2

- Python compilation: PASS.
- SQLite repository regression tests: 3/3 PASS.
- Datastore audit: PASS, zero unclassified runtime datastore references.
- FastAPI fact-ingest SQLite dependency remains a known blocker for a later phase.

## Not done yet

Phase 2 intentionally does not migrate the existing `financial_risk.db` contents into Firestore. The next datastore phase will add a one-time migration/verification command and then validate the Flask API against a real Firestore project.
