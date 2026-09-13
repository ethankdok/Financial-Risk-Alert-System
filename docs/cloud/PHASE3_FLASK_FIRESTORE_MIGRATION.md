# Phase 3 — Flask SQLite → Firestore Migration

## Goal

Move the existing Flask operational data from `financial_risk.db` into the Firestore collections introduced in Phase 2 without changing IDs, password hashes, audit history, or analysis-record contents.

## Safety model

`scripts/migrate_flask_sqlite_to_firestore.py` is **dry-run by default**. It will only write when `--execute` is explicitly supplied.

The write path also refuses to touch non-empty destination collections unless `--allow-existing` is explicitly supplied. This prevents an accidental migration into a live project that already contains newer data.

Authentication uses Google Application Default Credentials (ADC). No service-account JSON file or secret is stored in the repository.

## Transformations

- `admins`: exact IDs and password hashes are preserved.
- `keywords`: exact IDs and foreign-key integer references are preserved.
- `risk_features.keywords_json` → Firestore native `keywords` array.
- `audit_logs.before_json` / `after_json` → Firestore native `before` / `after` maps.
- `analysis_records.matched_keywords_json` / `matched_features_json` → native arrays.
- `_meta/counters` is initialized to the maximum migrated integer ID per collection, so Phase 2's Firestore repository continues allocating compatible numeric IDs.

## Verification

After an executed migration, the script reads every migrated collection back from Firestore and compares:

1. exact document count;
2. canonical SHA-256 fingerprint of every record;
3. exact preserved integer IDs.

The script exits non-zero if any collection fails verification.

## Commands to run later on the developer machine

Dry-run only:

```powershell
python scripts/migrate_flask_sqlite_to_firestore.py --database financial_risk.db
```

Real migration (after Firestore + ADC are configured):

```powershell
python scripts/migrate_flask_sqlite_to_firestore.py `
  --database financial_risk.db `
  --project YOUR_PROJECT_ID `
  --execute `
  --report phase3-migration-report.json
```

Do **not** add `--allow-existing` on the first production migration. If the script reports non-empty collections, inspect the project before proceeding.
