# Historical Research Cloud Storage Design (Phase 1C)

Status: **implemented and tested with mocks; disabled by default; not deployed.**
No real GCS bucket or Firestore database was written in Phase 1C.

## Components

| Module | Role |
|---|---|
| `historical_audit/cloud_config.py` | Fail-closed configuration (`HistoricalCloudConfig.from_env`), ADC client construction |
| `historical_audit/object_storage.py` | `ObjectStore` interface; `GcsObjectStore`, `LocalObjectStore`; content-addressed names |
| `historical_audit/firestore_repository.py` | Additive Firestore mirror (`historical_research_*` collections), create-only writes |
| `historical_audit/cloud_sync.py` | Recoverable 6-step GCS → Firestore synchronization with persisted per-item state |
| `historical_audit/research_access.py` | `ResearchBackend` read contract: `LocalResearchBackend`, `FirestoreResearchBackend` |

Reused from `conference_pdf_archive_storage.py`:
- the helpers `_is_not_found` and `_sha256`;
- the principles of SHA-256 in object metadata, create-only `if_generation_match=0`, skip-same/conflict-different, dry-run by default, and Application Default Credentials.

The conference archive keeps its own prefix (`conference-pdf-archive/`), publisher
and JSD contract. Phase 1C references it and does not re-upload it.

## Object layout (GCS)

```
[<HISTORICAL_CLOUD_OBJECT_PREFIX>/]
  historical-financial-filings/<ticker>/sha256/<aa>/<sha256>.<xml|pdf|html|zip>
  historical-regulatory-disclosures/<ticker>/sha256/<aa>/<sha256>.<html>
  historical-official-summaries/<ticker>/sha256/<aa>/<sha256>.xls
  historical-research-packages/<ticker>/sha256/<aa>/<content_digest>.zip   (reserved; packages are local in Phase 1C)
  conference-pdf-archive/…                                                (existing layout, unchanged)
```

- **Identity = content.** Identical bytes give one object, with no duplicate storage. A report PDF that is both a filing version and a source document is one object; the mock test shows the object count is below the artifact count.
- **Immutable.** Creation uses `if_generation_match=0`. An existing object with the same SHA-256 is `exists_same`; a different one is a `conflict` and is never replaced (no overwrite flag exists).
- **Verified.** Objects carry `metadata.sha256`. After upload the object is downloaded and re-hashed, and the sync refuses to proceed on mismatch.
- **Bounded retries.** Up to 3 attempts with exponential backoff, and only for transient errors (`ServiceUnavailable`, `TooManyRequests`, timeouts …). A precondition failure is resolved by comparing content, never by retrying a write.
- **Cost.** One write per distinct artifact (45 distinct objects, 40.1 MB for 1785) and re-runs cost reads only. Bucket lifecycle, versioning and retention policies are left to the deployment review.

## Firestore model

Collections: `<prefix>_cases`, `_filing_versions`, `_facts`, `_source_documents`,
`_publication_events`, `_evidence_links`, `_comparisons`, `_summary_observations`,
`_observation_availability`, `_objects`, `_packages`, `_sync_runs`. The prefix
must start with `historical_research` (enforced in config and repository).

- **Document ids** are the archive's deterministic ids (`hfv1_…`, `hff1_…`, `hpe1_…`, `hrc1_…`, `hso1_…`, `hoa2_…`, `hsd1_…`). The production `financial-fact-v2` identity is **not** reused: it would collapse distinct filing versions.
- **Documents mirror the local rows** plus `object_bucket` / `object_name` on filing versions and source documents, and `_record_sha256`.
- **Writes are create-only.**
  - Same content gives `exists_same`.
  - Differences limited to filling an unknown annotation field give `filled`: `filing_version_type` from `unknown_revision`, or `available_at` / `availability_*` / `source_published_at` from null or `unverified`.
  - Anything else raises `FirestoreConflictError` and is not written.
- **Production collections are untouched:** `normalized_financial_facts`, `companies`, snapshots and ingestion runs. Ticker 1785 stays a historical research case; company resolution is not modified.

## Synchronization (no shared transaction)

Per item, persisted in the isolated SQLite DB (`historical_cloud_sync_runs`, `historical_cloud_sync_items`):

| Step | Item state | Failure state |
|---|---|---|
| 1 Validate local evidence (archive re-hash) | `validated` | `failed_validation` |
| 2 Upload missing object (create-only) | `uploaded` | `upload_conflict` / `upload_error` |
| 3 Verify object (download + re-hash) | `object_verified` | `object_verification_failed` |
| 4 Write Firestore metadata (records whose objects are verified; dependants only when their parents are written) | `metadata_written` | error recorded on the run |
| 5 Read back records and object stats | `consistent` | reported as inconsistent |
| 6 Run `complete` only if every item is `consistent` and no error occurred | — | run stays `incomplete` |

- A failed or interrupted run stays `incomplete` and is discoverable (`cloud-sync status`).
- The next `cloud-sync run` resumes the latest incomplete run for the same target and skips already-verified objects.
- Because objects and records are create-only, a retry never duplicates or overwrites.
- Metadata is never written for an artifact whose object is missing (no dangling references).
- Dry-run (`cloud-sync plan`, or `run` without `--execute`) performs read-only `stat` calls and writes nothing.

## Configuration and safety

| Variable | Meaning |
|---|---|
| `HISTORICAL_CLOUD_SYNC_ENABLED` | must be `true`; default off. Otherwise `CloudSyncDisabledError` |
| `HISTORICAL_CLOUD_ENVIRONMENT` | `emulator` (requires `FIRESTORE_EMULATOR_HOST`), `isolated-test`, or `production` |
| `HISTORICAL_CLOUD_PROJECT`, `HISTORICAL_CLOUD_BUCKET` | required. For `isolated-test`, **each** must contain test/dev/sandbox/staging and differ from `GOOGLE_CLOUD_PROJECT` / production archive buckets |
| `HISTORICAL_CLOUD_COLLECTION_PREFIX` | default `historical_research`; must start with it |
| `HISTORICAL_CLOUD_OBJECT_PREFIX` | optional object-name prefix |
| `HISTORICAL_CLOUD_PRODUCTION_APPROVAL` | production also needs `allow_production=True`, which the CLI never passes. Production is therefore unreachable from Phase 1C tooling |

- **Credentials** come from Application Default Credentials only. Missing ADC raises `CloudSafetyError`.
- **No key material** is in the source, the config or the packages.
- **The local path never imports cloud code.** The ingestion, research and packaging modules import no cloud code; this is enforced by `test_package_has_no_production_writer_imports`.

## Read contract (future API)

`ResearchBackend` exposes these read-only calls. They are the intended shape for a future API; no FastAPI route was added.

- `list_facts(ticker, start, end, as_of=None, version_policy="all")`
- `list_filing_versions(ticker, start, end)`
- `list_restatement_comparisons(ticker, as_of=None)`
- `list_summary_observations(ticker, as_of=None)`

Both backends feed the same rules (`reader.finalize_fact_rows`,
`evidence_export.finalize_comparisons`, `finalize_summaries`). Field-by-field
equality is tested on fixtures and on the real 1785 archive (mock cloud).

## Deployment prerequisites (Phase 5, not done)

1. **Approved infrastructure.** An isolated project and bucket (uniform bucket-level access, no public access, retention policy), a Firestore database, and a dedicated service account granted `storage.objectCreator` + `storage.objectViewer` on that bucket and `datastore.user` only.
2. **Emulator run.** `tests/test_historical_cloud_emulator.py` against a local Firestore emulator. It was NOT RUN in Phase 1C (the emulator component is not installed).
3. **Isolated-test end-to-end run** with real clients, then a review of costs and `cloud-sync status`.
4. **Production change request.** The `allow_production` path needs code review and an explicit approval; it is not reachable today.
5. **Composite indexes.** Phase 1C queries use only single-field `ticker` equality.
