# Historical Audit Case Ingestion — Phase 1 Validation Report

Date: 2026-10-09 · Branch `feature/audit-case-historical-ingestion` · Base
`5db17c195667c9fbf2f3247cdf83a9e3a8541c7e` · Python 3.14.0 (repo `.venv`).

**Outcome: PARTIAL.** The implementation, version-aware persistence,
point-in-time reader, export contract and all automated tests pass, and four
of six years were acquired from the official source. Still incomplete:
FY2011–FY2012 sources, the original (pre-restatement) FY2013–FY2015 filings,
and verified publication timestamps for every version.

Shareable evidence: [`evidence/historical_audit_1785_2011_2016_live.json`](evidence/historical_audit_1785_2011_2016_live.json).
Raw archives, SQLite and exports stay in `fintrust_backend/data/historical_audit/` (gitignored).

## 1. Live backfill — 1785, 2011FY–2016FY (`t164sb01`, consolidated annual)

Run 1 `3cb1b3860ded42b7b7b8bde88633bf4a` (2026-10-09 15:17 UTC), concurrency 1, ≥2 s spacing.

| FY | Acquisition | SHA-256 (prefix) | Bytes | Parser | Version type | Audit-report date | Publication | Facts | Core | QA |
|---|---|---|---|---|---|---|---|---|---|---|
| 2011 | `filing_not_found` (exact MOPS not-found page) | `f9198822…` (error body) | 281 | — | — | — | — | 0 | 0/17 | — |
| 2012 | `filing_not_found` (exact MOPS not-found page) | `f9198822…` (error body) | 281 | — | — | — | — | 0 | 0/17 | — |
| 2013 | `available` | `6bf36dc7…` | 281,676 | xbrl_instance (tifrs-ci-cr-2013-03-31) | **restated** | 2016-11-11 | unverified | 18 | 17/17 | validated_with_warnings |
| 2014 | `available` | `4d720af5…` | 349,550 | xbrl_instance (tifrs-ci-cr-2013-03-31) | **restated** | 2016-11-11 | unverified | 18 | 17/17 | validated_with_warnings |
| 2015 | `available` | `02e3bf2e…` | 327,797 | xbrl_instance | **restated** | 2016-11-11 | unverified | 18 | 17/17 | validated_with_warnings |
| 2016 | `available` | `c88a70a3…` | 352,386 | xbrl_instance (tifrs-ci-cr-2015-03-31) | unknown_revision | 2017-03-21 | unverified | 18 | 17/17 | validated_with_warnings |

Source URL pattern: `https://mopsov.twse.com.tw/server-java/FileDownLoad?functionName=t164sb01&step=9&co_id=1785&year={FY}&season=4&report_id=C`.
Full hashes, version ids and evidence strings are in the evidence JSON.

Findings:

1. **Official files obtained:** FY2013–FY2016 XBRL instances. FY2011/2012:
   the endpoint returned the exact "下載檔名或路徑不正確" page. That proves
   only that `t164sb01` has no file; it does not prove that no filing exists
   (these are pre-IFRS years).
2. **Normalized facts:** 4 versions × 18 facts = 72 facts, consolidated scope
   (entry point `…-ci-cr-…`). All 17 core fields plus R&D for every acquired
   year. Balance-sheet and gross-profit identities passed for all four years.
3. **Restated:** FY2013, FY2014 and FY2015 self-identify as restated: audit
   date 2016-11-11 and auditor text such as 「重編後民國103年及102年12月31日之合併資產負債表」
   and 「如重編後財務報表附註十二、10所述」.
   **Original:** none. The originals (published 2014–2016) are not served by this endpoint.
   **Unknown:** FY2016. No restatement wording; MOPS serving it does not prove it is the original.
4. **Publication dates verified:** none. `available_at` and
   `source_published_at` are NULL for every version, and `document_dated_at`
   (audit date) is recorded as a lower bound only. Strict `as_of` queries
   therefore return 0 rows. This is the intended fail-closed behaviour, not an error.
5. **Missing key fields:** none for FY2013–FY2016. FY2011–FY2012 have no data.
6. **Taxonomy/context issues:** EPS is tagged with unit `TWD` instead of the
   filing's own `EarningsPerShare` (TWD/shares) unit in all four years. The
   value is kept as `TWD/share` with `quality_status = warning`
   (`eps_unit_declared_as_currency`). 134–140 current-period statement concepts
   per year are not mapped to canonical fields. They are listed per version in
   `diagnostics_json.unmapped_current_period_concepts`, not discarded.
7. **Classifier correction recorded in the audit trail:** the first run
   classified FY2015 as `unknown_revision`, because its auditor wording
   (「重編後合併財務報告」) was not matched. After the fix, an offline
   `--source-strategy archive` reprocess made no network calls. It re-verified
   all hashes and wrote one annotation (`unknown_revision → restated`, source
   `archive_reprocess`) without creating a new version.
8. **Duplicate detection / rerun:** run 2 `a32fb8fb13714fd3a035fce13ce3abad` (2026-10-09 15:18 UTC) downloaded
   byte-identical files: 0 new versions and 0 facts inserted. Totals stayed at
   4 versions and 72 facts, with 18 attempts logged across three runs.
   `quality`: duplicate fact identities 0, duplicate versions 0, orphan facts 0,
   facts missing provenance 0, archive hash failures 0.
9. **Needs further official archive research:** FY2011–FY2012 (any form) and
   the original FY2013–FY2015 filings, plus publication timestamps for all
   versions (see §7).

## 2. Acceptance matrix

Commands run from `fintrust_backend/` with `../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider …`.

| ID | Result | Evidence (test → key assertions) |
|---|---|---|
| CASE-01 | PASS | `Case01RegistrationIsolationTests` — case is `1785/TPEX/光洋科`; `SEMICONDUCTOR_COMPANIES` unchanged after a backfill; 1785 absent from seeds, `classified_tickers`, `ALLOWED_BATCH_REFRESH_TICKERS`, `production_eligible_tickers`; `validate_refresh_tickers(["1785"])` and `refresh_all(tickers=["1785"])` raise; `get_company("1785")` is None; 2330/2454 resolve unchanged; `CompanyMasterRecord(market="TPEX")` still invalid |
| CASE-02 | PASS | `Case02ExactRangeTests` — requested years exactly 2011…2016 (season 4, report C); 2011/2012 stay `filing_not_found`, no substitute years; dry run plans 6 years and creates no DB/archive; range validation |
| CASE-03 | PASS | `test_case03_…` — two 2014FY versions (`original`, `restated`) and both inventory values persisted |
| CASE-04 | PASS | `test_case04_…` — rerun: version/fact/annotation counts unchanged, `facts_inserted = 0`, same version ids; live rerun likewise (§1.8) |
| CASE-05 | PASS | `test_case05_…` — changed bytes ⇒ new version, both `unknown_revision`, both revenue values kept |
| CASE-06 | PASS | `Case06ProvenanceTests` — every fact joins to a version whose SHA-256 equals the archived bytes; tampering detected by `quality` |
| CASE-07 | PASS | `Case07PointInTimeTests` — FY2014 invisible at 2014-12-31; FY2015 (available 2016-03-31) invisible on 2016-03-30; restated invisible before its timestamp (exact UTC boundary), selected after; `original_only`, `earliest_available`; unverified versions excluded from any `as_of`; naive datetime rejected |
| CASE-08 | PASS | `Case08ErrorIsolationTests` — 503 (3 bounded attempts), throttle page, malformed XML, connection error, each isolated; other years `available`; error bodies archived; quarantine for entity mismatch, wrong-period document, insufficient core fields |
| CASE-09 | PASS | Full suite 436 passed / 2 skipped (baseline 397 passed / 1 skipped, +39 new). Existing 2330/2454 contract tests: 76 passed (`test_canonical_fact_contract`, `test_ingestion_runs`, `test_api_contracts`, `test_firestore_fact_compatibility`, `test_fact_repository`, `test_preserve_last_good_snapshot`, `test_financial_migration_safety`, `test_company_universe`, `test_semiconductor_expansion`) |
| CASE-10 | PASS | `Case10SnapshotIsolationTests` — backfill into a DB holding a latest snapshot: all 7 production tables byte-identical before/after, with `refresh_company`, `save_pipeline_result`, `AIFinancialAnalysisService.analyze_report` patched to raise; import scan forbids pipeline/repository/Firestore/LLM/scheduler imports |
| CASE-11 | PASS | `Case11ApiCompatibilityTests` — `/companies/2330/facts` and `/companies` responses identical after applying the historical schema to the same DB; 1785 absent from `/companies`, `/companies/1785/facts` count 0; no historical route in OpenAPI |
| CASE-12 | PASS | `Case12ExportContractTests` + smoke — CSV header and JSON `fields` equal the documented order; contract name/version; byte-identical repeated CSV; sorted order; strict `as_of`; test fixtures excluded by default |
| CASE-13 | PASS | `Case13MigrationTests` — 3× migration on a legacy DB: legacy schema SQL and rows unchanged, `schema_version = 1`, legacy readers work; production paths refused (also for dry-run planning) |
| CASE-14 | PASS | `Case14ProductionSafetyTests` — with `DATASTORE_BACKEND=firestore` and `firestore.Client` patched to raise, the run succeeds; injected secret values appear in no request, file, DB or export; non-HTTPS / non-allowlisted hosts and off-allowlist redirects rejected; manifest cannot claim `original` or `available_at` without evidence |

Additional: `NormalizationQualityTests` (prior-year comparative and dimensional
equity member ignored, notes concept not mapped, missing ≠ 0, identity warning,
unknown scope kept unknown, conflicting duplicates rejected, iXBRL `scale`/`sign`,
PDF ⇒ `extraction_pending`), restatement wording variants.

Smoke / E2E / live:

| Test | Result |
|---|---|
| `test_historical_audit_e2e.py::HistoricalAuditSmokeTest` (CLI: init-db → dry-run → backfill ×2 → quality → query → as-of → export CSV/JSON) | **Fixture PASS** |
| `test_historical_audit_e2e.py::HistoricalAuditE2ETest` (stubbed official source → restated version → manifest annotation → PIT → export → offline reprocess) | **Fixture PASS** |
| `FINTRUST_LIVE_MOPS=1 … tests/test_historical_audit_live.py` (1 request: 1785 FY2013) | **Live source acquisition PASS** |
| Live 2011–2016 backfill (§1) | **PARTIAL**: 4/6 years; historical publication verification incomplete |

Fixture tests use synthetic documents. They do not prove that real original or
restated filings were retrieved.

## 3. Reproducible commands (all executed on 2026-10-09)

Run from `fintrust_backend/`; `PY=../.venv/Scripts/python.exe` (Windows) or the venv's `python`.

```bash
$PY -m scripts.historical_audit_case cases
$PY -m scripts.historical_audit_case init-db --ticker 1785
$PY -m scripts.historical_audit_case backfill --ticker 1785 --start-year 2011 --end-year 2016 --dry-run
$PY -m scripts.historical_audit_case backfill --ticker 1785 --start-year 2011 --end-year 2016 \
    --report-json data/historical_audit/reports/live-run-1.json
$PY -m scripts.historical_audit_case backfill --ticker 1785 --source-strategy archive      # offline reprocess
$PY -m scripts.historical_audit_case backfill --ticker 1785 --source-strategy manifest --manifest path/to/manifest.json   # path is an example; format below (exercised by the smoke/E2E tests)
$PY -m scripts.historical_audit_case quality --ticker 1785 --output data/historical_audit/reports/quality.json
$PY -m scripts.historical_audit_case query --ticker 1785 --metric inventory --metric revenue
$PY -m scripts.historical_audit_case query --ticker 1785 --as-of 2016-12-31 --version-policy latest_available
$PY -m scripts.historical_audit_case export --ticker 1785 --format csv --output data/historical_audit/exports/1785_2011_2016_all_versions.csv
$PY -m scripts.historical_audit_case export --ticker 1785 --format json --output data/historical_audit/exports/1785_2011_2016_all_versions.json
$PY -m scripts.historical_audit_case export --ticker 1785 --format csv --as-of 2016-12-31 --version-policy latest_available \
    --output data/historical_audit/exports/1785_asof_2016-12-31.csv    # 0 rows until availability is verified

$PY -m pytest -q -p no:cacheprovider tests/test_historical_audit_case.py                          # acceptance matrix
$PY -m pytest -q -p no:cacheprovider tests/test_historical_audit_e2e.py                           # smoke + E2E
FINTRUST_LIVE_MOPS=1 $PY -m pytest -q -p no:cacheprovider tests/test_historical_audit_live.py     # live (1 request)
$PY -m pytest -q -p no:cacheprovider tests                                                        # full regression
```

Defaults: database `./data/historical_audit/historical_audit.sqlite3`, archive
`./data/historical_audit/raw`, years from the case file (2011–2016).

### Case manifest (for research-supplied evidence)

```json
{"manifest_version": 1, "ticker": "1785", "documents": [
  {"period": "2014FY", "source_kind": "mops_xbrl_instance",
   "source_url": "https://mopsov.twse.com.tw/…", "local_path": "optional/relative/file.xml",
   "statement_scope": "consolidated", "filing_version_type": "unknown_revision",
   "source_published_at": null, "available_at": null, "availability_basis": null,
   "verification_evidence": []}]}
```

`filing_version_type` other than `unknown_revision` needs `verification_evidence`.
`available_at` needs both `availability_basis` and `verification_evidence`.
`source_url` must be an allowlisted official HTTPS host (`mopsov.twse.com.tw`,
`mops.twse.com.tw`, `doc.twse.com.tw`). Re-importing bytes that are already
archived only fills unknown fields, through logged annotations.

## 4. Production safety

- Only the isolated SQLite file and local archive were written. No Firestore,
  Cloud SQL, production pipeline DB, scheduler, Secret Manager or environment changes.
- No existing file was modified (`git status` shows only new files). No
  snapshot promotion, AI/LLM call, deployment, push, merge or PR.
- Live traffic: 6 + 6 GET requests to `mopsov.twse.com.tw` across two runs,
  plus 1 for the live test and 5 exploratory probes during the audit
  (FY2013 C and A, FY2011, FY2012, FY2016). All
  were bounded, sequential and SSL-verified.

## 5–7. Remaining work

- **Yu-Jing (evidence needed):** official sources for the original FY2013–FY2015
  annual reports and FY2011–FY2012 statements (e.g. TWSE/TPEx electronic-document
  archive `doc.twse.com.tw`, MOPS restatement announcements), each with its
  verified publication timestamp and basis. Supply them via a case manifest;
  verified `available_at` values turn on strict point-in-time eligibility.
- **Ethan:** `HISTORICAL_FINANCIAL_FACTS_CONTRACT.md` v1.0 and the CSV/JSON
  exports (72 facts, 4 restated/unknown versions) are ready. They currently
  have no point-in-time-eligible rows.
- **2017–2025 extension:** same CLI with `--start-year 2017 --end-year 2025`.
  The inline-XBRL path (`scale`/`sign`, `ifrs-full`) is covered by fixtures but
  not yet by live data. Check taxonomy drift with the per-version `unmapped`
  diagnostics. Keep requests at concurrency 1.
- **Before `feature/financial-misstatement-signals`:** verified availability
  timestamps, at least one verified original/restated pair, PDF extraction (or
  structured pre-IFRS XBRL) for FY2011–FY2012, and comparative-period facts if
  the signals compare restated prior-year figures.
- **Pre-existing risk (not changed):** twmops `MOPSXBRLClient` disables SSL
  verification on retry in the production MOPS path.
