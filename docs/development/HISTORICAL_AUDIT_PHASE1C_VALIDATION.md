# Historical Audit — Phase 1C Validation: Research Package Portability & Cloud Storage Adapters

Date: 2026-10-10 · Branch `feature/historical-research-portability-cloud` (local,
no upstream), created from the reviewed commit `265b9ed`. That commit is on
`feature/audit-case-historical-ingestion`, which remains at `265b9ed`.

**Outcome:**
- The portable research package is **ready for teammates**. It is built from the
  real 1785 archive and verified outside the repository.
- GCS/Firestore adapters are **implemented and tested with mocks** (fixture and
  real archive). The emulator test was **not run** and nothing was run against
  isolated or production cloud. Cloud features are **disabled by default**.

## 1. Gate 0 — independent audit

See [`HISTORICAL_AUDIT_PRE_PHASE1C_REVIEW.md`](HISTORICAL_AUDIT_PRE_PHASE1C_REVIEW.md).
- No CRITICAL findings. Four HIGH and two MEDIUM findings were fixed in `265b9ed`:
  - H1: corroboration side follows revision
  - H2: comparisons require verified claims
  - H3: v1.2 availability-evidence identity and quality-report alignment
  - H4: research-cutoff tests
  - M2: path containment
  - M1: documented reproducibility
- **Key research limit:** before the 2016-05-13 revelation the archive has **no
  verifiably public inputs**. Strict pre-event detection backtests are not
  supported yet; November-2016 PIT success is restatement analysis only.

Phase 1C found and fixed three more defects through its own failure-injection tests:
- a corrupted artifact aborted the package build (`eps_unit_investigation` now reports instead of raising);
- `safe_extract` extracted unlisted members before verification (it now verifies first);
- `isolated-test` accepted a production-looking project when only the bucket was marked as test.

## 2. Modified / added source files (Phase 1C commit `8d40ca3` + this report's commit)

| File | Change |
|---|---|
| `historical_audit/research_package.py` | new: deterministic ZIP builder |
| `historical_audit/package_verify.py` | new: stdlib verifier and safe extraction (shipped in packages) |
| `historical_audit/object_storage.py` | new: content-addressed create-only GCS/local stores |
| `historical_audit/firestore_repository.py` | new: additive Firestore mirror |
| `historical_audit/cloud_sync.py` | new: recoverable sync with persisted state |
| `historical_audit/cloud_config.py` | new: fail-closed configuration, ADC clients |
| `historical_audit/research_access.py` | new: unified local/cloud read contract |
| `historical_audit/reader.py`, `evidence_export.py` | refactor: shared `finalize_*` rules (behaviour unchanged; 73 tests) |
| `historical_audit/quality.py` | EPS investigation no longer aborts on unreadable artifacts |
| `scripts/historical_audit_case.py` | `research-package build|verify`, `cloud-sync plan|run|status` |
| `scripts/build_historical_review_bundle.py` | new: review bundle from tracked files |
| tests | `test_historical_research_package.py`, `test_historical_cloud.py`, `test_historical_cloud_emulator.py`, `historical_cloud_fakes.py`; real-archive mock contract test; safety guard extended to lazy imports |
| docs | `HISTORICAL_RESEARCH_PACKAGE_CONTRACT.md`, `HISTORICAL_CLOUD_STORAGE_DESIGN.md`, this report |

No production module, endpoint, model, `requirements.txt`, Dockerfile or
scheduler was changed. `git diff 5db17c1` touches only historical-audit paths.

## 3. Real research packages (1785, built 2026-10-10)

| Package (gitignored `fintrust_backend/data/historical_audit/packages/`) | content_digest | Files | Size | Contents |
|---|---|---|---|---|
| `fintrust_1785_2011_2016_full.zip` | `119ef875cf434f119905023553d40decb6579f9ed6fb4d21a52f48e0c1a87a8d` | 63 | 36.8 MB | 72 facts (27 PIT-eligible), 17 filing versions (all raw included), 79 summaries, 158 comparisons, 359 events, 45 inventory rows, 26 missing-evidence rows; conference `unavailable_for_ticker` |
| `fintrust_1785_asof_2016-11-14.zip` (`latest_available`) | `690a0ce7dba21d79ab8eab941910814d5ef6411855f4822c20e6a56318511b22` | 63 | 36.8 MB | 27 facts, 158 comparisons |

Independent verification:
1. The package was extracted with `safe_extract` into a fresh scratch directory outside the repository.
2. The **shipped** `validation/verify_package.py` was run with `python -I`, with no repo code on the path.
3. Result: `{"status": "verified", "files_verified": 61}` for both the ZIP and the extracted folder.

Reproducibility: rebuilds with a fixed `generated_at` were byte-identical
(SHA-256 `bb466924…`), and an unfixed `generated_at` gave the same `content_digest`.

Conference PDFs: the local archive (`data/historical-conference-pdfs`) holds
2303/2330/2408/2454/3034 only, **not 1785**. The package records this
explicitly. Inclusion, separation from financial data and JSD-contract embedding
are tested with a fixture archive (PORT-05).

## 4. Tests

Command: `cd fintrust_backend && ../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests`

| Run | Result |
|---|---|
| This machine (with gitignored 1785 archive) | **491 passed, 3 skipped**: live MOPS (opt-in), Firestore emulator (not configured), `reportlab` (pre-existing) |
| Fresh worktree of `8d40ca3` (no local data) | **481 passed, 13 skipped**: the 10 real-archive tests also skip |

| ID | Tier | Result | Test |
|---|---|---|---|
| PORT-01 | fixture | PASS | `Port01To03Tests.test_port01_…` + real build (§3) |
| PORT-02 | fixture | PASS | manifest/parameters/checksum chain; byte-identical rebuild; digest stable |
| PORT-03 | fixture + real | PASS | extracted copy verified by subprocess `python -I verify_package.py` in another temp dir; real package (§3) |
| PORT-04 | fixture | PASS | deleted PDF → `missing_locally`, tampered XBRL → `failed_integrity`; neither included; completeness `partial` |
| PORT-05 | fixture | PASS | no archive → `unavailable_no_archive_configured`; fixture archive → `conference/` + JSD contract; facts unchanged |
| PORT-06 | fixture | PASS | as_of/policy package equals reader output; original/restated kept; PIT evidence columns present |
| CLOUD-01 | mock | PASS | content-addressed names; created / exists_same / conflict; corrupted download detected; local store path containment |
| CLOUD-02 | mock | PASS | dry-run writes nothing; second sync: 0 new uploads, all records `exists_same`; PDF dedup |
| CLOUD-03 | mock | PASS | every version is its own document; differing content → `FirestoreConflictError`; unknown→verified fill only |
| CLOUD-04 | mock | PASS | injected upload interruption → `incomplete`, no dangling metadata, resume same run → `complete`; injected Firestore write failure → `incomplete` → retry `complete`; corrupted object → `incomplete`; missing local source blocks completion |
| CLOUD-05 | mock (fixture + **real archive**) | PASS | local vs Firestore backends equal for facts (4 cutoffs/policies), versions, comparisons, summaries; real 1785 archive incl. 2016-05-12 / 2016-11-14 / 2017-12-31 |
| CLOUD-06 | unit | PASS | disabled by default; production refused (even with approval env, since the CLI never allows it); production project/bucket refused for isolated-test; emulator requires host; non-`historical_research` prefix refused; missing ADC → `CloudSafetyError`; CLI refuses without opt-in |
| Emulator | emulator | **NOT RUN** | `test_historical_cloud_emulator.py`: emulator component not installed |
| Isolated cloud / production | — | **NOT RUN** (not authorized) | — |
| REG-01 | — | PASS | Phase 1A tests (`test_historical_audit_case.py`, `_e2e.py`) |
| REG-02 | — | PASS | Phase 1B tests (`test_historical_evidence*.py`, `test_historical_review_fixes.py`) |
| REG-03 | — | PASS | 2330/2454 subset (9 files): 76 passed |
| REG-04 | — | PASS | conference PDF / JSD subset (12 files): 142 passed, 1 skipped (`reportlab`) |

The failure-injection coverage requested by the brief appears in the matrix as follows:

| Injected failure | Covered by |
|---|---|
| Missing source file | PORT-04; `test_missing_local_source_blocks_completion` |
| Corrupted artifact | PORT-04; CLOUD-01; CLOUD-04 |
| Invalid checksum / tampered or unlisted files | `PackageFailureInjectionTests` |
| GCS upload interruption | CLOUD-04 |
| Firestore metadata write failure | CLOUD-04 |
| Incomplete sync state | CLOUD-04 (`cloud-sync status`) |
| Malformed package paths (`..`, absolute, drive, backslash, hidden, symlink) | `PackageFailureInjectionTests` |
| Missing cloud credentials | CLOUD-06 |

## 5. Reproducible workflow (commands executed)

```bash
cd fintrust_backend          # PY=../.venv/Scripts/python.exe
$PY -m scripts.historical_audit_case research-package build --ticker 1785 \
    --include-conference --conference-root data/historical-conference-pdfs \
    --output data/historical_audit/packages/fintrust_1785_2011_2016_full.zip
$PY -m scripts.historical_audit_case research-package build --ticker 1785 --as-of 2016-11-14 \
    --version-policy latest_available --output data/historical_audit/packages/fintrust_1785_asof_2016-11-14.zip
$PY -m scripts.historical_audit_case research-package verify data/historical_audit/packages/fintrust_1785_2011_2016_full.zip
$PY -m scripts.historical_audit_case cloud-sync plan --ticker 1785      # → CloudSyncDisabledError (default)
$PY -m scripts.build_historical_review_bundle --output data/historical_audit/review_bundles/fintrust_historical_audit_review.zip
$PY -m pytest -q -p no:cacheprovider tests
# Teammates (no FinTrust code needed):
python validation/verify_package.py fintrust_1785_2011_2016_full.zip
```

## 6. Security controls verified

- **Packages contain only** generated datasets, contract documents, the verifier, and raw files read through the SHA-256-checked archive. No DB, `.env`, credentials or local paths; a test checks for the temp root path and credential names.
- **Paths:** safe POSIX paths only. Builder, verifier and extractor reject `..`, absolute, drive, backslash, hidden and symlink entries, duplicates and oversize archives. Extraction happens only after full verification.
- **Cloud:**
  - disabled by default; production unreachable from tooling; ADC only;
  - collections forced to the `historical_research_*` namespace;
  - create-only objects and records;
  - no IAM, bucket, scheduler, Secret Manager or deployment changes.
- **Local path:** the ingestion, research and packaging modules import no cloud or production-writer code. This is enforced by a test that also covers lazy imports.

## 7. Data compatibility and migration readiness

- **Firestore ids** are the archive's deterministic ids, and documents mirror local rows. Local and cloud reads agree field by field (CLOUD-05, real archive).
- **Facts contract stays at v1.2.** Package schema is 1.0, and the conference JSD contract is unchanged.
- **Before any production migration:**
  1. emulator run;
  2. isolated-project run with real clients;
  3. infrastructure and IAM review;
  4. explicit approval;
  5. a decision on package storage (local only today).

## 8. Known limitations

- **Mock tests are not cloud E2E.** No emulator, isolated-cloud or production run took place.
- **Platform-dependent digest.** Git CRLF conversion on Windows checkouts can change the bytes of the embedded `verify_package.py`, so `content_digest` is reproducible per checkout platform. Datasets and raw evidence are unaffected.
- **No 1785 conference PDFs** exist locally.
- **Large packages.** The full package is 36.8 MB because it embeds original PDFs; `--no-raw-evidence` builds a data-only package.
- **Phase 1B evidence limits remain:**
  - no machine-readable originals;
  - unverified original publication times;
  - no strict pre-event inputs.

## 9. Source review bundle

`fintrust_backend/data/historical_audit/review_bundles/fintrust_historical_audit_review.zip` (gitignored)
is built by `scripts/build_historical_review_bundle.py`. It contains only
*tracked* historical-audit sources, tests, docs and contracts at the bundled
commit, plus `REVIEW/schema.sql` (empty-DB schema), `REVIEW/commits.txt`,
`REVIEW/diffstat.txt` and `REVIEW/MANIFEST.json` (per-file SHA-256). Raw
archives, databases, packages, credentials, environment files and caches are
excluded by construction.
