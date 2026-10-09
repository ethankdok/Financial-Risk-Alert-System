# Historical Audit — Phase 1B Validation: Evidence Recovery & Point-in-Time

Date: 2026-10-10 · Branch `feature/audit-case-historical-ingestion` · Starting
commit `5b9acf7` (local only, verified in branch history; working tree clean).

**Outcome: PARTIAL.**
- **Recovered:** official publication and restatement evidence, officially
  labelled original/restated report pairs, TW-GAAP/IFRS summary history, and the
  first strict point-in-time-eligible observations backed by real verified timestamps.
- **Still missing:** machine-readable original statements, original
  first-publication times, and verified byte-level publication times for the
  restated/FY2016 XBRL.

Companion documents:
- [`HISTORICAL_SOURCE_EVIDENCE_INVENTORY.md`](../data/HISTORICAL_SOURCE_EVIDENCE_INVENTORY.md)
- [`HISTORICAL_PUBLICATION_TIMELINE.md`](../data/HISTORICAL_PUBLICATION_TIMELINE.md)
- [`HISTORICAL_FINANCIAL_FACTS_CONTRACT.md`](../data/HISTORICAL_FINANCIAL_FACTS_CONTRACT.md) (v1.1)
- Shareable snapshot: [`evidence/historical_audit_1785_phase1b_evidence.json`](evidence/historical_audit_1785_phase1b_evidence.json)

## 1. Gate A baseline (verified, not assumed)

| Check | Result |
|---|---|
| Branch / commit | `feature/audit-case-historical-ingestion` at `5b9acf7`, which is an ancestor of HEAD; no upstream |
| Phase 1 DB | 4 filing versions, 72 facts, 1 annotation, 3 runs, 18 attempts; FY2013–15 `restated`, FY2016 `unknown_revision`; all `unverified` |
| Raw XBRL | 4 files re-hashed; each SHA-256 equals its file name |
| Tests | 436 passed, 2 skipped (matches the Phase 1 report) |
| Backup | DB copied to the session scratchpad before any change |

Existing reusable components: the raw archive, `upsert_filing_version`
(evidence-immutable, append-only annotations), the official fetcher, the reader
and the export contract.

Regression risks:
- the CASE-13 legacy-schema test enumerates historical tables by name (updated to use the table registry)
- the facts export header (fields appended only)

## 2. What was built

| Module | Purpose |
|---|---|
| `historical_audit/evidence_parsers.py` | Deterministic parsers: TPEx announcements (Big5), MOPS t05st01 listing + detail, 重編前/重編後 tables, TWSE t57sb01 listing, TPEx 季報 `.xls` (header-label based, `xlrd`) |
| `historical_audit/evidence_store.py` | Additive schema (`evidence_schema_version = 1`): `historical_source_documents`, `historical_publication_events`, `publication_evidence_links`, `official_summary_observations`, `restatement_comparisons`, `observation_availability` |
| `historical_audit/evidence_import.py` | Reviewed-plan acquisition (reuses archived copies), offline import, quote verification, conservative linking, value-level corroboration |
| `historical_audit/evidence_export.py` | Separate CSV/JSON datasets and coverage matrix |
| `historical_audit/evidence_plans/1785.json` | 41 reviewed official requests with verbatim-quote event claims |
| `reader.py` | `effective_available_at` (version **or** observation level), `list_filing_versions_as_of` |
| `quality.py` | `eps_unit_investigation`, `unmapped_concept_report` |
| `sources.py` | `www.tpex.org.tw` allowlisted; POST support; XLS/HTML evidence detection; request descriptor recorded |
| CLI | `evidence-acquire`, `evidence-import`, `evidence-export`, `eps-investigation`, `concept-coverage` |
| `requirements-historical-audit.txt` | `xlrd` for research tooling only (production `requirements.txt` unchanged) |

Phase 1 tables, identities (`hfv1`/`hff1`), `schema_version = 1` and v1.0
export columns are unchanged.

### Linking rules (`publication_evidence_links`)

| Evidence | Link status |
|---|---|
| TWSE e-book upload record whose file size equals the downloaded bytes, 更(補)正 = 無, and no later correction notice for that revision | `verified_linkage`. Sets the PDF version's `available_at` to the upload time (conservative bound) |
| Same upload record when later corrections exist (restated reports) | `period_level_only` |
| Announcement that a restated report was filed / restatement disclosed | `period_level_only` |
| Correction notices (11-17 opinion, 12-05 notes, 2017-01-20 p.83) | `unverified_linkage`, with rationale (e.g. the XBRL contains the emphasis flag the 11-17 correction added) |
| Artifact audit date later than the stated filing date | `conflicting_evidence` |

**Observation-level availability:** a fact (or summary value) is eligible from
time *T* only if an official notice published at *T* states the identical
value for the same period, scope, framework and metric. No date is propagated
to unrelated values or versions.

## 3. Real-source results

Acquisition (`evidence-acquire`): 41/41 sources `acquired`, about 54 bounded
requests at ≥2 s spacing. A second run reused all 41 archived copies with zero
network requests. Import produced:
- 359 events and 158 comparison rows
- 13 PDF filing versions and 84 summary observations
- 59 links and 39 corroborations

There were **0 errors** and every quoted claim was found verbatim. A re-import inserted 0 rows.

### FY2011–FY2016 evidence matrix

| FY | Original evidence | Restated evidence | Summary evidence | Comparison (before/after) | Verified availability | PIT ready |
|---|---|---|---|---|---|---|
| 2011 | TW-GAAP PDF, consolidated + individual (scanned) | TW-GAAP PDF consolidated | TPEx O_2011Q4 (TW-GAAP, individual); 2 values corroborated | ✔ 2016-11-13 | original PDFs 2016-08-25 (conservative) | disclosure-only |
| 2012 | TW-GAAP PDF, consolidated + individual | TW-GAAP PDF consolidated | O_2012Q4 (TW-GAAP, individual); 2 corroborated | ✔ | original PDFs 2016-08-25 | disclosure-only |
| 2013 | IFRS PDF consolidated | XBRL + PDF consolidated | O_2013Q4 (IFRS, consolidated); 1 corroborated | ✔ | original PDF 2016-08-25 | partial: 9 XBRL facts from 2016-11-13 21:26:22 |
| 2014 | IFRS PDF consolidated | XBRL + PDF consolidated | O_2014Q4; 1 corroborated | ✔ | original PDF 2016-08-25 | partial: 9 facts |
| 2015 | IFRS PDF consolidated | XBRL + PDF consolidated | O_2015Q4 (pre-restatement values); 1 corroborated | ✔ | original PDF 2016-08-25 | partial: 9 facts |
| 2016 | none (no restatement evidence) | none | O_2016Q4 (unverified) | — | FY2016 PDF 2017-03-22 14:20:15 | no (XBRL time unverified) |

No year is complete: having a restated filing does not make a year ready. The
27 eligible XBRL facts (9 per year, FY2013–FY2015) cover revenue, cost of goods sold, gross profit,
net income, current assets, total assets, current liabilities, total
liabilities and equity. Inventory, receivables, cash flows and EPS remain
ineligible because no verified disclosure states them.

### Point-in-time eligibility, before vs after this phase

| Query | Phase 1 | Phase 1B |
|---|---|---|
| Strict `as_of` facts (any date) | 0 | 0 before 2016-11-13 21:26:22; 27 from then |
| Restatement comparison rows | n/a | 79 from 21:25:31 (individual), 158 from 21:26:22 |
| Filing versions with verified availability | 0 | 8 PDFs: 7 originals @ 2016-08-25, FY2016 @ 2017-03-22 |
| TPEx summary values | n/a | 84 stored, 12 eligible via corroboration |

### Gate G — data quality

- **EPS unit.**
  - All four XBRL filings declare EPS with `unitRef="TWD"` (decimals 2), although each defines an `EarningsPerShare` (TWD/shares) unit.
  - Values are per-share and unscaled. FY2015 restated −2.62 equals the TPEx announcement's 「每股虧損2.62元」 and O_2016Q4's comparative; FY2016 −1.23 equals O_2016Q4.
  - Decision: keep the stored unit `TWD/share` and keep the `eps_unit_declared_as_currency` warning, because the source declaration is inconsistent. Values are not relabelled or rescaled.
- **Unmapped concepts.**
  - 134–140 per filing. Grouped for review: receivables 5–6 (e.g. `NotesReceivableNet`, `OtherReceivables`, `DecreaseIncreaseInAccountsReceivable`), inventory 1 (`DecreaseIncreaseInInventories`), revenue 1–2 (`RevenueFromSaleOfGoods`, `OtherRevenue`), cost 1, assets 20–21, profit/OCI 17–21, cash flow 5–6, equity 9–12, other 72–74.
  - No new mappings were added. The report is `concept-coverage --output …`.

## 4. Acceptance matrix

Commands run from `fintrust_backend/` with `../.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`.

| ID | Result | Evidence |
|---|---|---|
| EVID-01 | PASS | `test_evid01_inventory_is_reproducible`: inventory identical after re-import; categories original/restated/summary/comparison/XBRL; hash matches bytes. Real: 45-row inventory |
| EVID-02 | PASS | `test_evid02_…`: missing quote → `quote_not_found` + error; HTTP 404 → `source_unavailable`. Real: Phase 1 FY2011/2012 `filing_not_found` attempts unchanged; GAAP originals recovered from the TWSE archive instead |
| EVID-03 | PASS | `test_evid03_…`: FY2012 TW-GAAP (2012 file) vs T-IFRS comparative (2013 file) kept apart; comparisons framework by year. Real scenario 5 |
| EVID-04 | PASS | `test_evid04_…`, real scenario 5: filing versions only `mops_xbrl_instance`/`official_pdf`; facts reader never returns summaries; 稅後純益 `requires_review` |
| EVID-05 | PASS | `test_evid05_…`: pre/post/difference/sign factor/disclosed_at/URL/hash; "as previously reported" semantics |
| EVID-06 | PASS | `test_evid06_…` (×2): verified only for size-matched uncorrected PDFs; size mismatch stays unverified; period-level/unverified/conflicting statuses; XBRL `available_at` never set |
| EVID-07 | PASS | `test_evid07_…`: undisclosed values (inventory) and uncorroborated summaries never eligible |
| EVID-08 | PASS | `test_evid08_…` + real scenarios 1–4: nothing at 21:26:21, eligible at 21:26:22; date-only notice from next Taipei midnight; FY2016 PDF not before 2017-03-22 14:20:15 |
| EVID-09 | PASS | `test_evid09_…`: second acquire makes 0 requests, second import inserts 0. Real: same (41 reused, 0 inserted) |
| EVID-10 | PASS | `test_evid10_…`; real: Phase 1 tables row-identical to the pre-phase backup, 4 XBRL hashes unchanged |
| EVID-11 | PASS | `test_evid11_…`: five datasets CSV/JSON headers; facts v1.1 appended fields; `as_of` refused where unsupported |
| EVID-12 | PASS | `test_historical_audit_case.py` + `test_historical_audit_e2e.py`: 39 passed (CASE-13 filter now uses the table registry; assertion unchanged) |
| EVID-13 | PASS | 2330/2454 contract subset (9 files): 76 passed |
| EVID-14 | PASS | `test_evid14_…`: Firestore client patched to raise, secrets absent from requests/files/exports; non-official plan URLs and duplicate keys rejected |

Real-data scenarios (`tests/test_historical_evidence_real.py`, run against a copy
of the local archive; skipped where the gitignored archive is absent): 6/6 PASS.

**Full regression: 457 passed, 2 skipped.** The baseline was 436 + 2; the
additions are 15 fixture tests and 6 real-scenario tests. The skips are the
pre-existing `reportlab` fixture and the opt-in live MOPS test. No failures.

## 5. Reproducible commands

```bash
cd fintrust_backend   # PY=../.venv/Scripts/python.exe ; research deps: pip install -r requirements-historical-audit.txt
$PY -m scripts.historical_audit_case evidence-acquire --ticker 1785 --dry-run          # list the 41 planned requests
$PY -m scripts.historical_audit_case evidence-acquire --ticker 1785 --report-json data/historical_audit/reports/phase1b-evidence-acquire-1.json
$PY -m scripts.historical_audit_case evidence-import  --ticker 1785 --report-json data/historical_audit/reports/phase1b-evidence-import-1.json
$PY -m scripts.historical_audit_case evidence-export  --ticker 1785 --dataset coverage_matrix --output data/historical_audit/exports/phase1b/1785_coverage_matrix.csv
$PY -m scripts.historical_audit_case evidence-export  --ticker 1785 --dataset restatement_comparisons --as-of 2016-11-13 --output data/historical_audit/exports/phase1b/1785_comparisons_asof_2016-11-13.csv
$PY -m scripts.historical_audit_case evidence-export  --ticker 1785 --dataset summary_observations --format json --output data/historical_audit/exports/phase1b/1785_summary_observations.json
$PY -m scripts.historical_audit_case evidence-export  --ticker 1785 --dataset publication_timeline --output data/historical_audit/exports/phase1b/1785_publication_timeline.csv
$PY -m scripts.historical_audit_case evidence-export  --ticker 1785 --dataset source_inventory --output data/historical_audit/exports/phase1b/1785_source_inventory.csv
$PY -m scripts.historical_audit_case export --ticker 1785 --as-of 2016-12-31 --version-policy latest_available --output data/historical_audit/exports/phase1b/1785_filing_facts_asof_2016-12-31.csv   # 27 rows
$PY -m scripts.historical_audit_case eps-investigation --ticker 1785 --output data/historical_audit/reports/phase1b-eps-investigation.json
$PY -m scripts.historical_audit_case concept-coverage  --ticker 1785 --output data/historical_audit/reports/phase1b-concept-coverage.json
$PY -m pytest -q -p no:cacheprovider tests/test_historical_evidence.py tests/test_historical_evidence_real.py
$PY -m pytest -q -p no:cacheprovider tests
```

All of the above were executed on 2026-10-09/10 (UTC) with the stated results.

## 6. Production safety

- Writes went only to the isolated `fintrust_backend/data/historical_audit/` (gitignored) and the session scratchpad.
- No Firestore, Cloud SQL, pipeline DB, scheduler, secrets, environment, deployment, push, merge or PR.
- Existing production files are untouched except `scripts`/`tests` belonging to this feature and the two historical-audit test expectations noted above.
- `requirements.txt` and both Dockerfiles are unchanged.
- **Network:**
  - about 54 pipeline requests and about 35 discovery requests to `www.tpex.org.tw`, `mopsov.twse.com.tw` and `doc.twse.com.tw`, all sequential and SSL-verified;
  - 3 Wayback CDX lookups (discovery lead only, nothing persisted);
  - `pip install xlrd` into the local venv.

## 7. Remaining work

**Yu-Jing (case research):**
- Official first-publication evidence for the 2012–2016 original annual reports. For example, a MOPS 財務報告更(補)正 history query or a TWSE archive upload log before 2016-08-25.
- Whether the restated XBRL/PDF bytes reflect the 11-17, 12-05 or 2017-01-20 correction round. MOPS 「財務報告更(補)正 查詢作業」 is referenced by the archive but was not queried.
- The FY2016 XBRL filing time.
- If needed for signals: a reliable (human-verified or OCR-validated) extraction of the scanned original statements. Their pre-restatement totals are already available as official 重編前 rows.

**Ethan:**
- Facts v1.1: 27 PIT-eligible restated facts. Plus `restatement_comparisons` (158 rows, eligible from 2016-11-13), `summary_observations` (84) and `coverage_matrix`.
- `pre_restatement_value` means "as previously reported per the 2016 notice". The first-published TPEx values can differ (e.g. FY2014 net income 451,927 vs 416,617).

**2017–2025 readiness:**
- The XBRL backfill, evidence plan format, parsers and linking rules are not year-specific.
- Each new year needs its own reviewed plan entries (e-book listing + PDF, material-information listing).
- Inline-XBRL years still need a first live validation.
- The TPEx summary parser handles both the 2011–2014 and 2015+ column layouts.
