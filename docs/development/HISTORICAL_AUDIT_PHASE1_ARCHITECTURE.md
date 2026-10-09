# Historical Audit Case Ingestion — Phase 1 Architecture

Owner: Una (data acquisition, normalization, persistence, compatibility QA).
Branch: `feature/audit-case-historical-ingestion`, created from
`origin/v4-integration` at `5db17c195667c9fbf2f3247cdf83a9e3a8541c7e`
(verified equal to the remote HEAD on 2026-10-09; working tree clean).

Out of scope here: case chronology and misstatement literature (Yu-Jing),
JSD / Data Shift methodology (Ethan), misstatement indicators, frontend.

## 1. Gate 0 — repository audit (read-only, verified at the base commit)

| # | Area | Verified behaviour | Consequence for historical cases |
|---|---|---|---|
| 1 | `MopsInlineXbrlClient.fetch_history` / `RobustMopsInlineXbrlClient.fetch_history` | `if not 3 <= years <= 5: raise ValueError`; walks back from `end_roc_year` and tries up to `years + 2` candidates until enough *available* years are found | Substitutes the nearest available years; cannot express "exactly 2011–2016". Not widened; a separate range service is used. |
| 2 | `fetch_annual` / `load_package` | Download one consolidated (`report_id=C`) Q4 package via `t164sb01`, cache it, parse with twmops | Reusable *source*, but see rows 6–8. |
| 3 | `financial_filings` (`SqliteAnalysisRepository`) | `PRIMARY KEY (ticker, period)`; `ON CONFLICT … DO UPDATE` of `source_url`, `status`, `concept_matches_json`, `warnings_json`, `retrieved_at` | A second filing for the same period overwrites the first. Original and restated cannot coexist. |
| 4 | `normalized_financial_facts` identity (`fact_document_id`, `financial-fact-v2`) | sha256 of `[version, demo/official, ticker, metric, period, scope, statement_type, unit, source_kind, source_url]`; written with `INSERT OR REPLACE` | **No filing-version or content-hash component.** The MOPS URL for an annual report is identical before and after a restatement, so a restated value silently replaces the original row. |
| 5 | `historical_fact_rows` | Every MOPS historical fact is written with `statement_scope = "unknown"`; `financial_fact_from_row` later defaults missing historical scope to `consolidated` | Scope is asserted, not evidenced. Historical archive records scope from the taxonomy entry point instead. |
| 6 | MOPS cache (`_cache_path`, `_write_cache`) | `{ticker}_{roc}_Q4_C.ixbrl`, TTL 24h, overwritten in place, no hash | Raw bytes are a transient cache, not preserved evidence. |
| 7 | twmops `MOPSXBRLClient.download_xbrl_async` | On retry it sets `verify=False` (SSL verification disabled) | Not used by the historical path (own fetcher with `verify=True`). **Pre-existing production risk, reported, not changed here.** |
| 8 | twmops parsers | `XBRLContext` has no segment/scenario; lxml iXBRL fallback ignores `scale`/`sign`; the robust extractor prefers the *shortest context id* as a proxy for the non-dimensional total | Dimensional equity members could be mistaken for totals; iXBRL values could be 1,000× off. The historical parser reads dimensions, units, `scale`, `sign` directly. |
| 9 | `CompanyMasterRecord` | `market: Literal["TWSE"]`, `source_kind: Literal["twse_openapi"]`; `is_supported_master_record` requires TWSE + industry 24 | 1785 (TPEx) cannot and should not enter the Company Master. A separate case registry is used. |
| 10 | `validate_refresh_tickers` / `ALLOWED_BATCH_REFRESH_TICKERS` | Frozen set of `classified_tickers()` (reviewed semiconductor taxonomy) | 1785 is rejected; unchanged and covered by CASE-01. |
| 11 | `FinancialIngestionPipeline.refresh_company` | TWSE latest analysis → MOPS 3–5y history → AI analysis (LLM auto-enabled for official mode via `FINANCIAL_AI_AUTO_LLM_ENABLED`) → frontend snapshot → `save_pipeline_result(promote_latest=…)` | Writes `latest_analysis_snapshots`, triggers Gemini/Claude narrative paths. Never called by the historical path. |
| 12 | `IngestionRunRecord` | `pipeline: Literal["financial_backfill"]`, `requested_years` count semantics, shared `ingestion_runs` table/Firestore collection | Cannot express a bounded year range with per-year outcomes without changing a shared model. Separate run/attempt tables are used. |
| 13 | Persistence backends | `build_*_repository()` switch on `DATASTORE_BACKEND`; Firestore in production | The historical repository is SQLite-only and takes an explicit path; it never consults `DATASTORE_BACKEND`. |
| 14 | `docs/data/JSD_INPUT_CONTRACT.md` | Conference-PDF → JSD record contract | Untouched. Historical facts get a separate contract. |

### Audit questions

1. **Reusable safely:** `classify_mops_non_ixbrl_body` and the
   `FILING_NOT_FOUND / SOURCE_INVALID_CONTENT / SOURCE_UNAVAILABLE` diagnostics;
   the canonical field codes and the alias tables `FIELD_ALIASES`,
   `EXTENDED_FIELD_ALIASES`, `EXTRA_ALIASES` (as low-priority exact concept
   fallbacks); the `t164sb01` URL convention.
2. **Coupled to 3–5-year analysis:** `fetch_history`, `HistoricalFinancialAnalysisService`,
   `refresh_company`, `historical_fact_rows`, rule/AI/snapshot code.
3. **Writes latest snapshots / triggers AI:** `refresh_company` →
   `_run_ai_analysis` → `save_pipeline_result(promote_latest=True)`;
   `persist_snapshot_narrative`.
4. **Fact identity / dedup:** `fact_document_id` (row 4) and
   `deduplicate_financial_fact_rows` (prefers v2, consolidated, historical, latest timestamp).
5. **Can versions coexist?** No (rows 3–4).
6. **After a restatement:** the period's `financial_filings` row and every
   matching fact row are overwritten in place; the original value is lost.
7. **Scope / context / unit:** scope hard-coded `unknown` (row 5); context =
   annual date match + shortest id heuristic; unit = constant `新台幣元`, EPS `元／股`.
8. **TPEx without touching the universe:** isolated case registry
   (`app/services/historical_audit/cases/*.json`), no Company Master record.
9. **Raw XBRL bytes:** only a 24h overwritable cache today; now a content-addressed archive.
10. **Contracts at risk if changed in place:** `financial-fact-v2` ids (Firestore
    document ids), `financial_filings` PK, `/companies/{ticker}/facts` payload,
    `IngestionRunRecord`, `CompanyMasterRecord`. None are changed.

### Live-source finding that shaped the design

`t164sb01` serves **one document per period — the current one.** For 1785,
FY2013, FY2014 and FY2015 are served as reports whose audit-report facts
state they are restated (`tifrs-ar:ReviewAuditDate = 2016-11-11`, auditor text
「重編後…合併財務報告」). The originals published in 2014–2016 are not
retrievable from this endpoint. FY2011–FY2012 return MOPS's exact
"file does not exist" page (pre-IFRS years). Treating "first document this
pipeline downloaded" as `original` would therefore be wrong for exactly the
years the case is about.

## 2. Chosen architecture

```
cases/1785.json ─► case_registry ─┐
                                  ▼
official source (sources.py) ─► archive.py ─► xbrl_document.py ─► normalization.py
  t164sb01 | manifest | archive    SHA-256       contexts/units/     concept map, QA gate,
  allowlist, retries, backoff      immutable     dimensions/ix       identities, conflicts
                                  ▼
                       backfill.py (per-year isolation, one transaction per document)
                                  ▼
                    repository.py (isolated SQLite, additive tables)
                                  ▼
          reader.py (point-in-time, version policy) ─► export.py (CSV/JSON contract v1.0)
                                  ▼
               quality.py (integrity) · scripts/historical_audit_case.py (CLI)
```

Package: `fintrust_backend/app/services/historical_audit/`. It imports nothing
from `ingestion_pipeline`, `analysis_repository`, Firestore, AI/LLM or
scheduler modules (enforced by a test).

### Database contract (additive, schema_version 1)

| Table | Key / uniqueness | Purpose |
|---|---|---|
| `financial_filing_versions` | PK `filing_version_id`; UNIQUE `(ticker, period, statement_scope, content_hash)` | One immutable source artifact per period. Evidence fields (hash, path, URL, retrieved_at, scope, parser) never change. |
| `versioned_financial_facts` | PK `fact_id`; UNIQUE `(filing_version_id, metric_code, period, statement_scope, unit)` | Immutable normalized observations, exact `value_text` + `value` REAL. |
| `filing_version_annotations` | append-only | Every later change to `filing_version_type`, `source_published_at`, `available_at` (only unknown → known, with evidence). |
| `historical_ingestion_runs`, `historical_acquisition_attempts` | run / per-year attempt | Every attempt incl. failures, hashes of error bodies, URLs. |
| `historical_audit_cases`, `historical_schema_meta` | — | Registered case snapshot, schema version. |

Identity:

- `filing_version_id = "hfv1_" + sha256(["hfv1", ticker, period, statement_scope, content_hash])[:32]`
  — identical bytes ⇒ same version on every rerun; any byte change ⇒ new version.
  A new hash is **not** treated as an official restatement.
- `fact_id = "hff1_" + sha256(["hff1", filing_version_id, metric_code, period, statement_scope, unit])[:32]`
  — scope and unit are part of identity and can never merge.

Classification (`filing_version_type`):

- `restated` — only when the filing itself carries an explicit restated-statements
  phrase in its audit-report facts **and** its audit-report date is after
  30 June of FY+1; or when a case manifest declares it with verification evidence.
- `original` — only from a case manifest with verification evidence. Never inferred.
- `unknown_revision` — everything else. Conflicts between a declaration and
  the document's own evidence quarantine the version.

Time semantics (never substituted for each other):

| Field | Meaning | Source in Phase 1 |
|---|---|---|
| `source_published_at` | verified official publication timestamp | manifest only (with evidence) |
| `available_at` | earliest supported public-availability timestamp | manifest only; requires `availability_basis` + evidence ⇒ `availability_status = verified` |
| `retrieved_at` | when this pipeline downloaded the bytes | fetcher |
| `document_dated_at` | audit-report date inside the filing | XBRL `tifrs-ar:*AuditDate`; a lower bound only, **never** used for point-in-time eligibility |

### Compatibility strategy

- No existing table, key, model, endpoint, serializer or scheduler setting is
  modified. Historical tables live in a separate default file
  `fintrust_backend/data/historical_audit/historical_audit.sqlite3`.
- `HistoricalAuditRepository` refuses the paths named by
  `FINANCIAL_DATABASE_PATH`, `FINANCIAL_FACT_DATABASE_PATH` and the default
  pipeline files unless a test explicitly opts in (`allow_shared_database=True`,
  used only to prove coexistence).
- No FastAPI route is added; research consumers use the CLI/export contract.
- Rollback: delete the package, CLI, tests and docs; drop the isolated file.

## 3. Testing strategy

`tests/test_historical_audit_case.py` (CASE-01…CASE-14 + normalization rules),
`tests/test_historical_audit_e2e.py` (CLI smoke, fixture E2E incl. annotation and
offline reprocessing), `tests/test_historical_audit_live.py` (opt-in single live
request). Synthetic fixtures live in `tests/historical_audit_fixtures.py` and are
labelled as synthetic. Full backend suite run before and after. Results:
[`HISTORICAL_AUDIT_PHASE1_VALIDATION.md`](HISTORICAL_AUDIT_PHASE1_VALIDATION.md).

## 4. Known blockers / limits

- **Original (pre-restatement) FY2013–FY2015 filings** are not served by
  `t164sb01`. They need another official archive (see validation report §7).
- **FY2011–FY2012** (pre-IFRS, ROC GAAP) are not served by `t164sb01`. PDF
  annual reports can be imported via manifest, but PDF fact extraction is not
  implemented (archived as `extraction_pending`; no values derived).
- **Publication timestamps** are unverified for every live version, so strict
  point-in-time views are empty until verified `available_at` evidence is supplied.
- Comparative-period (prior-year) facts inside a filing are not persisted as
  facts in Phase 1; they remain in the archived raw bytes.
