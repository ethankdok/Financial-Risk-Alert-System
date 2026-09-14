# Phase 1 — Runtime Datastore Inventory and Firestore Target Schema

Baseline: `v4-integration` @ `d85334d196eb59f6150501384ced78bb3a957de9` (FinTrust Financial Evidence already merged)

This document freezes the datastore scope before Cloud Run deployment. Phase 1 does **not** change runtime persistence yet; it identifies every production SQLite dependency, classifies whether it must migrate, and defines the target Firestore collections so later phases can be implemented without changing API behavior accidentally.

## 1. Runtime datastore inventory

### Flask application — must migrate before Cloud Run

`app.py` opens `financial_risk.db` directly through `sqlite3`. The database is part of request-time behavior, so Cloud Run's ephemeral filesystem is not an acceptable production datastore.

| SQLite table | Current purpose | API/runtime usage | Firestore target | Migration priority |
| --- | --- | --- | --- | --- |
| `admins` | Administrator accounts, password hashes, roles, active status | login, `/api/auth/me`, admin CRUD, authorization | `admins` | P0 |
| `keywords` | Approved risk keywords | keyword CRUD, `/api/analyze` | `keywords` | P0 |
| `risk_features` | Risk feature definitions and weights | feature CRUD, `/api/analyze` | `risk_features` | P0 |
| `audit_logs` | Admin action history | `audit()`, list/clear audit logs | `audit_logs` | P0 |
| `analysis_records` | User text risk-analysis history | write on every `/api/analyze` request | `analysis_records` | P0 |

Additional Flask behavior tied to SQLite semantics:

- integer auto-increment IDs are exposed to the frontend and used in route parameters;
- `admins.username`, `keywords.phrase`, and `risk_features.name` are unique;
- admin soft-disable is used instead of deletion so audit history remains attributable;
- at least one active `系統管理員` must remain;
- `risk_features.keywords_json` becomes a native Firestore array;
- `audit_logs.before_json` / `after_json` become native Firestore maps;
- `analysis_records.matched_keywords_json` / `matched_features_json` become native arrays/maps.

### FastAPI financial analysis — Firestore already supported

The scheduled/combined financial analysis repository already supports `DATASTORE_BACKEND=firestore` through `FirestoreAnalysisRepository`. Production should set the backend to Firestore. The SQLite implementation in `analysis_repository.py` may remain as a local/test fallback and is **not** a production blocker by itself.

Existing Firestore collections in FinTrust:

- `analysis_runs`
- `financial_filings`
- `normalized_financial_facts`
- `calculated_metrics`
- `rule_results`
- `latest_analysis_snapshots`
- `official_events`

### FastAPI fact-ingest endpoint — must migrate before Cloud Run

`get_fact_repository()` still constructs `FinancialFactRepository` with `FINANCIAL_DATABASE_PATH` and `financial_facts.sqlite3`. The protected endpoint `/api/v1/financial/facts/ingest` therefore has an unconditional runtime SQLite dependency.

A later cloud-datastore phase will replace this path with the same cloud-backed evidence repository used by the financial pipeline, or a Firestore implementation of the `FinancialFactRepository` contract. Until then this is a known production blocker.

## 2. Target Flask Firestore schema

All Flask collections live in the same Google Cloud project as the existing FinTrust collections.

### `admins/{id}`

```text
id: integer
username: string              # unique
password_hash: string
display_name: string
role: string                  # 系統管理員 | 內容審核員
is_active: integer            # keep 0/1 in API for compatibility
created_at: timestamp
```

Implementation note: keep the public `id` numeric during the first migration so existing Flask routes and frontend JavaScript do not need an ID-format change. New IDs will be allocated transactionally from `_meta/counters`.

### `keywords/{id}`

```text
id: integer
phrase: string                # unique
category: string
risk: string
source: string
reason: string
status: string                # active | inactive
approved_by: integer | null
approved_at: timestamp
updated_by: integer | null
updated_at: timestamp
```

### `risk_features/{id}`

```text
id: integer
name: string                  # unique
dimension: string
weight: integer
keywords: array<string>
definition: string
explain: string
status: string
updated_by: integer | null
updated_at: timestamp
```

### `audit_logs/{id}`

```text
id: integer
admin_id: integer | null
action: string
target: string
summary: string
before: map | null
after: map | null
created_at: timestamp
```

The API presenter will still emit the current frontend fields (`adminId`, `adminName`, `time`, `before`, `after`). Firestore storage format is allowed to be cleaner than the HTTP response shape.

### `analysis_records/{id}`

```text
id: integer
query_text: string
risk_score: integer
raw_score: integer
risk_level: string
matched_keywords: array<map>
matched_features: array<map>
created_at: timestamp
```

### `_meta/counters`

```text
admins: integer
keywords: integer
risk_features: integer
audit_logs: integer
analysis_records: integer
```

Counter allocation must use a Firestore transaction. This is a compatibility choice for the first cloud migration; it preserves current numeric IDs and avoids changing existing `<int:...>` Flask routes during the datastore move.

## 3. Query/index plan

The Flask admin dataset is small, so the Firestore implementation should prefer simple single-field reads plus application-side sorting where that avoids unnecessary composite indexes.

Required behaviors:

- find active admin by `username`;
- fetch active admin by numeric `id`;
- list keywords newest first and resolve `updated_by` display name;
- reject duplicate keyword `phrase`;
- list risk features newest first;
- reject duplicate risk feature `name`;
- count active system administrators before demotion/deactivation;
- list latest 500 audit logs with admin identity;
- list active keywords/features for `/api/analyze`.

Uniqueness checks must be performed in transactions in Phase 2/3 where a create/update race could otherwise introduce duplicates.

## 4. Migration invariants

The later SQLite → Firestore migration is not considered successful unless all of the following hold:

1. Row/document counts match for all five Flask datasets.
2. Existing numeric IDs are preserved.
3. Password hashes are copied verbatim; plaintext passwords are never exported.
4. `keywords_json` is decoded to a native array.
5. `before_json`, `after_json`, `matched_keywords_json`, and `matched_features_json` are decoded before writing.
6. Timestamps are written as Firestore timestamps, while API responses preserve the current UI-compatible text format.
7. No `.db`, `.sqlite`, `.env`, API key, ingestion token, or session secret is committed.
8. Existing Flask endpoint response shapes remain compatible unless a change is explicitly documented and tested.

## 5. Production-blocker classification

### Must be removed from production runtime

- `app.py` direct use of `sqlite3` / `financial_risk.db`.
- `fintrust_backend/app/dependencies.py:get_fact_repository()` fixed SQLite repository for `/facts/ingest`.

### Allowed to remain after cloud migration

- `SqliteAnalysisRepository` as an explicit local/test fallback when `DATASTORE_BACKEND=sqlite`.
- SQLite usage in tests, diagnostics, one-time migration scripts, and local development utilities.

## 6. Phase 1 acceptance criteria

- [x] All runtime SQLite references inventoried.
- [x] Each reference classified as production blocker or allowed fallback.
- [x] Five Flask tables mapped to Firestore collections.
- [x] Native Firestore representations defined for JSON-in-SQLite fields.
- [x] Numeric-ID compatibility strategy defined.
- [x] Migration invariants documented.
- [x] Automated datastore audit script added.

Next phase: implement the Flask repository abstraction and Firestore repository without changing endpoint behavior.
