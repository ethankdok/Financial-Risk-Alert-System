# Phase 2A — 1785 FY2017–FY2019 Historical Expansion — Validation

Date: 2026-10-11 (Asia/Taipei).

Branch `feature/historical-1785-fy2017-2019`. It was created from the verified Phase 1C head `698d2cd`, which is
`bcc634b` plus the Gate 0 carryover fix.

Nothing was pushed, merged or deployed. Firestore/GCS sync stayed disabled, and no production database was touched.

## Outcome

- **New fiscal years.** FY2017, FY2018 and FY2019 are ingested into the isolated SQLite research database. Each
  year has 18 normalized facts with 17/17 core fields.
- **Evidence.** Official PDFs, publication evidence, TPEx summaries and material-information notices are archived
  and linked. Both ingestion and import are idempotent.
- **FY2011–FY2016 data is unchanged.** Every pre-Phase-2A row of every table is still present, byte-identical.
- **Existing ZIPs are unchanged.** The 2011–2016 full ZIP, the 2016-11-14 strict ZIP and its sidecar keep their
  SHA-256.
- **New versioned packages:**
  - `fintrust_1785_2011_2019_full.zip` (retrospective);
  - `fintrust_1785_2011_2019_asof_2020-12-31.zip`, with its sidecar (strict).
- **Point in time.** No FY2017–FY2019 financial fact is point-in-time eligible. Neither the XBRL bytes nor any
  disclosure provides a verified publication time. Only the FY2019 PDFs have one (2020-02-14).

## Gate 0 — carryover

- **State checked.** Git status was clean at `bcc634b` with intact ancestry. The database, raw archive and package
  hashes were verified.
- **Fix.** `--check-release` with neither a strict ZIP nor a sidecar now fails (`failed_no_release_found`). A lone
  sidecar also fails closed (`incomplete release pair`). Two isolated fixture tests were added in
  `test_historical_release_pair.py::MissingReleaseTests`.
- **Commit.** `698d2cd` on the Phase 1C branch; the Phase 2A branch was then created from it.

## Implementation (reuse first)

| Component | Change |
|---|---|
| `backfill` (MOPS `t164sb01`) | unchanged flow; FY2017–2019 fetched with the existing strategy |
| `models.decimal_text` + `backfill` | **defect fix**: `value_text` was `str(Decimal)`, which renders scaled iXBRL values in exponent notation (`2.1986662E+10`). It is now fixed-point text. The fix was proven identical for all 72 existing facts before use |
| `evidence_plans/1785.json` | **additive**: 21 sources (listings, PDFs, notices, summaries) and 3 events with verbatim quotes |
| `evidence_import` | the unverified e-book link rationale now states the actual reason(s): blank/non-無 更(補)正, size mismatch, later corrections |
| `conference_coverage` | **defect fix**: a listing that names documents while no pipeline manifest exists is `document_missing`, with counts and meeting dates taken from the verified listing. Previously it read `conference_found` with 0 expected documents |
| `conference_package` | coverage `research_role` is recomputed from the package's year range, consistent with documents; the `document_missing` detail is status-specific |
| `rebuild_historical_packages` | `--strict-filename` (validated plain `*.zip` name) for versioned strict packages |

Normalization and taxonomy were reviewed before deciding that no change was needed:

- **FY2018 taxonomy.** It moves from `ifrs:` to `ifrs-full:` (`Revenue`, `ProfitLossFromOperatingActivities`, and
  `PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities` via the existing shared alias).
- **FY2019 format.** It is inline XBRL.
- **Mapping.** All metrics map to primary concepts, apart from the documented capex alias, with no conflicting
  alternates.
- **Accounting identities.** Revenue − COGS = gross profit, and assets = liabilities + equity, hold exactly for
  every year.
- **Warnings.** FY2017/FY2018 `validated_with_warnings` comes from the known `eps_unit_declared_as_currency` only.

## Deliverable 1 — FY2017–FY2019 coverage matrix

| FY | MOPS XBRL (format, facts) | Version type | XBRL availability | TWSE PDFs (consolidated / individual) | PDF availability | TPEx summary | Notices | PIT-ready facts |
|---|---|---|---|---|---|---|---|---|
| 2017 | XBRL instance, 18 | unknown_revision | unverified | AI1 / AI3 | **unverified**: listed 2018-03-27, 更(補)正 blank | O_2017Q4 (values = XBRL) | board dividend resolution 2018-03-21 | 0 |
| 2018 | XBRL instance, 18 | unknown_revision | unverified; correction linked | AI1 / AI3 | **unverified**: listed 2019-03-28, 更(補)正 blank; correction linked | O_2018Q4 (new 速動 column ignored; values = XBRL) | **2019-05-29 note-9 correction + re-upload** | 0 |
| 2019 | **inline XBRL**, 18 | unknown_revision | unverified | AI1 / AI3 | **verified 2020-02-14 14:58:52 / 14:59:25** | O_2019Q4 (values = XBRL) | — | 0 |

Source availability, data quality and parse success are reported separately:

| FY | Retrieved | Parsed | Quality | Publication evidence |
|---|---|---|---|---|
| 2017 | yes | yes | warnings (EPS unit) | upload listed but not verifiable |
| 2018 | yes | yes | warnings (EPS unit) | upload listed but not verifiable; correction notice |
| 2019 | yes | yes | validated | PDF verified; XBRL unverified |

No 重編 (restatement) of FY2017–FY2019 appears in the MOPS material-information listings for ROC 107, 108 and 109
(48, 45 and 76 rows). Every version is therefore `unknown_revision`, never claimed "original".

## Deliverable 2 — official source and evidence inventory

The detailed inventory is in `docs/data/HISTORICAL_SOURCE_EVIDENCE_INVENTORY.md`, section *Phase 2A*, with the
timeline in `docs/data/HISTORICAL_PUBLICATION_TIMELINE.md`. Every new artifact keeps:

- its URL and SHA-256;
- its fiscal year, scope and framework (TIFRS);
- its taxonomy entry point and filing identity (`hfv1_`);
- its publication evidence and its retrieval time.

**Request log** (all to allow-listed official hosts, 2026-10-11 UTC):

| Group | Requests | Notes |
|---|---|---|
| MOPS `t164sb01` FY2017–2019 | 9 downloads, 3 per backfill run | the second and third runs follow the database restore and are the idempotency run; the content hashes were identical every time |
| Discovery | 9 | TWSE e-book listings ROC 106–108, MOPS material listings ROC 107–109, TPEx `O_2017Q4`–`O_2019Q4` |
| TWSE e-book PDFs | 6 files | each is a step-9 page plus the PDF |
| MOPS notice details | 3 | |
| MOPS conference listings | 4 | 2018 and 2019 twice: the first recording had the recorder defect, was deleted and re-recorded |

Conference PDFs were **not** downloaded.

## Deliverable 3 — database insertion and idempotency

| Table | Before | After |
|---|---|---|
| financial_filing_versions | 17 | 26 |
| versioned_financial_facts | 72 | 126 |
| historical_source_documents | 41 | 59 |
| historical_publication_events | 359 | 548 |
| publication_evidence_links | 59 | 72 |
| official_summary_observations | 84 | 126 |
| historical_acquisition_attempts | 18 | 24 |
| historical_ingestion_runs | 3 | 5 |
| historical_conference_coverage | 8 | 10 |
| restatement_comparisons, observation_availability, cases, annotations | unchanged | unchanged |

Idempotency:

- **Backfill.** The second run inserted 0 facts and created no new version, with the same three content hashes.
- **Evidence import.** The second run produced empty counts.

Every pre-Phase-2A row is present byte-identical: a digest comparison, per table, of the sorted row sets against
`backups/historical_audit.pre-phase2a.sqlite3`. The only difference is the `sqlite_sequence` counter.

Recovery actions taken, both within this phase:

1. **Database restore.** The first FY2019 ingestion stored exponent text, so the database was restored from the
   pre-Phase-2A backup and the data re-ingested with the fix. The defective copy is kept in the session scratchpad
   only.
2. **Link regeneration.** The 13 links created in this phase were regenerated after the rationale fix. Only rows
   targeting FY2017+ versions were deleted, and pre-Phase-2A rows were re-verified as unchanged.

## Deliverable 4 — version and PIT validation (real archive)

`RealPhase2aFy2017To2019` has 4 tests:

- **XBRL per year.** Exactly one XBRL version per year: consolidated, `unknown_revision`, unverified. There are 18
  facts per year, no exponent text, and the accounting identities hold.
- **No PIT eligibility.** `list_historical_facts(..., as_of="2026-10-11")` returns **0** FY2017–2019 facts.
- **FY2019 publication boundary:**

  | as-of | FY2019 versions |
  |---|---|
  | 2020-02-14 14:58:51 | none |
  | 14:58:52 | consolidated |
  | 14:59:25 | + individual |

- **FY2017/FY2018 PDFs.** Both stay unverified, and the 2019-05-29 correction is linked as `unverified_linkage` to
  the FY2018 XBRL and both FY2018 PDFs.

**Data finding.** The FY2017 filing's own XBRL presents FY2016 EPS as −1.39, against −1.23 in the FY2016 filing.
Net income attributable to owners of the parent is unchanged (−485,453 thousand). This is recorded as a
retrospectively adjusted comparative with no stated reason; it is not treated as a restatement.

## Deliverable 5 — research exports (new names; existing ZIPs preserved)

| Package | SHA-256 | Files | Verification |
|---|---|---|---|
| `fintrust_1785_2011_2019_full.zip` | `9cbbd789d05d7652884b04f4ed2e865c9070557937ed34afec6476c70c92cb5e` | 111 | verified (ZIP + extracted, shipped verifier, `python -I`, outside the repository) |
| `fintrust_1785_2011_2019_asof_2020-12-31.zip` | `7268951fdee67c3fd99465a45595f94550838aeacfb6d12affbd984e4559e0d7` | 37 | verified, semantic strict checks, release pair valid |
| `fintrust_1785_2011_2019_asof_2020-12-31.audit.json` | `75751ee061a4777d741b59a19673a21f965cc95557de044730ea75d679030773` | — | binds the strict ZIP |
| `fintrust_1785_2011_2016_full.zip` (unchanged) | `693e867155de00ebded16ffece99f6b32179d306e369028eee4045f6dfbaa826` | — | `sha256sum -c` OK |
| `fintrust_1785_asof_2016-11-14.zip` (unchanged) | `304934a4a2e05dc16439155b267554a99a731ff6c07fa95e1cd05f25504f2bcf` | — | `sha256sum -c` OK, pair valid |

Strict package counts:

- facts 27, versions 10, summaries 12;
- comparisons 158, events 548;
- inventory 13, raw 23.

Its leakage checks passed: no post-cutoff or modern markers, every timestamp is Taipei, and no workbook, XML or
conference content.

Superseded intermediate builds of the new full ZIP are kept in `packages/previous/intermediate_phase2a/`.

## Deliverable 6 — smoke/E2E and regression

| Tier | Result |
|---|---|
| Historical (pytest): fixture / real / mock cloud | 134 passed, 2 skipped (live MOPS opt-in; Firestore emulator not configured) |
| — real local archive (`test_historical_evidence_real.py`) | 23 passed (incl. 4 new Phase 2A tests) |
| — mock cloud (`test_historical_cloud.py`) | 10 passed |
| Historical (plain `unittest`) | 136 run, OK, 2 skipped |
| Conference / JSD / 2330 / 2454 (`-k`) | 181 passed |
| Full backend regression | 531 passed, 3 skipped (+ reportlab PDF fixture) |
| Read-only CLI smoke | query, `--as-of` query (0 PIT rows), export (126 rows, no exponent values), quality (all integrity checks 0); database digest identical before and after |

## Remaining limitations

- **No verified XBRL publication time.** No FY2017–FY2019 XBRL file has one. A point-in-time study of these years
  needs corroboration, for example extracting values from the verified FY2019 PDF text or official notices that
  state them. That is a new corroboration mechanism and was deliberately not added in Phase 2A.
- **FY2017/FY2018 PDFs.** They are unverified because the archive's 更(補)正 column is blank. The rule (require 無)
  was not relaxed.
- **FY2018 correction.** Whether the FY2018 artifacts are the corrected 2019-05-29 re-upload is unresolved; the
  correction is note-only according to the notice.
- **Conference documents.** 2018 (10) and 2019 (4) are listed by MOPS but not downloaded.
- **FY2016 comparative EPS.** The reason for the adjustment is not established.
- **Case default range.** The case registry default range remains 2011–2016, so existing commands and packages
  stay stable. FY2017–2019 commands pass `--start-year/--end-year` explicitly.

## Readiness for FY2020–FY2022

The pipeline handled a taxonomy change, inline XBRL, a new workbook column and a correction notice without
weakening any rule. The idempotency and preservation checks are automated. FY2020–FY2022 can begin with the same
procedure:

1. Back up and digest the database.
2. Run a dry run, then the bounded backfill.
3. Run discovery for e-book listings ROC 109–111, MOPS listings ROC 110–112 and TPEx `O_2020Q4`–`O_2022Q4`.
4. Make additive plan entries, with events quoted verbatim from archived notices.
5. Run the offline import twice.
6. Build new versioned packages.

Watch for further taxonomy revisions (2020+), an `ifrs-full` EPS unit, and any restatement notices in ROC 110–112.
