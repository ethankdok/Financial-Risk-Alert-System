# Phase 2B — 1785 FY2020–FY2022, Conference Recovery and PIT Evidence — Validation

Date: 2026-10-11 (Asia/Taipei).

Branch `feature/historical-1785-fy2020-2022`, created from the verified Phase 2A head `951bd88`. The Phase 2A
branch is preserved.

Nothing was pushed, merged or deployed. Firestore/GCS and production were not accessed, no LLM was called, and the
conference pipeline ran text-only.

## Outcome

| Track | Result |
|---|---|
| FY2020–FY2022 financial ingestion | 3 inline-XBRL filings, 18 facts each (54), core coverage 17/17; idempotent; identities exact |
| Official evidence | 27 new sources (24 source documents + 3 XBRL filings; corrected from "30" in the carryover review); 3 annual board-approval notices with key figures; 3 note/interim corrections; no restatement found |
| Conference recovery | 2018/2019 backlog (14) and 2020–2022 (14): **28/28 downloaded and hash-verified**; 0 failed requests |
| PIT improvement | **21 new PIT-eligible facts** (FY2020–2022, 7 per year), dated at the value level by board-approval notices; 0 for FY2017–2019 |
| Integrity | every pre-Phase-2B DB row byte-identical; all 424 pre-existing archive files unchanged; all 6 earlier package files unchanged |
| Packages | `fintrust_1785_2011_2022_full.zip` and `fintrust_1785_2011_2022_asof_2023-12-31.zip` (+ sidecar), verified outside the repository |

## Gate 0 — baseline

- **Starting state.** HEAD `951bd88` with a clean tree and intact ancestry (`698d2cd`).
- **Backups and digests.** The database is backed up as `backups/historical_audit.pre-phase2b.sqlite3` (SHA-256
  identical to the live file). Per-table row digests were saved, the archive inventory was hashed (424 files), and
  all 6 existing package files were hashed.
- **Release pairs.** Both existing release pairs are valid.
- **Cloud and LLM settings.** `HISTORICAL_CLOUD_SYNC_ENABLED`, `DATASTORE_BACKEND` and `GOOGLE_APPLICATION_CREDENTIALS`
  are unset. `GEMINI_API_KEY` is present in the shell, but the multimodal provider is unset. The recovery runner
  also blanks both provider variables and asserts that no interpreter exists.

## Gate 1 — FY2020–FY2022 financial acquisition

Each year was a bounded batch: one dry run, then two live runs (the second for idempotency) of
`backfill --source-strategy mops_t164sb01`.

| FY | Format | Entry point | Facts | Core | Quality | 2nd run | SHA-256 (prefix) |
|---|---|---|---|---|---|---|---|
| 2020 | inline XBRL | `tifrs-ci-cr-2020-06-30` | 18 | 17/17 | validated | 0 inserted | `43afc3f3` |
| 2021 | inline XBRL | `tifrs-ci-cr-2020-06-30` | 18 | 17/17 | validated | 0 inserted | `c82f57f4` |
| 2022 | inline XBRL | `tifrs-ci-cr-2020-06-30` | 18 | 17/17 | validated | 0 inserted | `7f4b5fa9` |

**Expected against extracted.** All 18 supported canonical metrics were extracted in each year: 17 core metrics
plus R&D.

**Taxonomy.** FY2020–2022 use the same `ifrs-full`/`tifrs` concepts as FY2019. The only non-primary mapping is the
documented capex alias (`PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`). Cash shows
`deduplicated_2_identical_facts`, which is identical duplicate tags.

**Correctness checks:**

- revenue − COGS = gross profit, and liabilities + equity = assets, hold exactly every year;
- current assets ≤ total assets and current liabilities ≤ total liabilities;
- no exponent text, with fixed-point storage;
- units are TWD, with EPS in TWD/share.

**Revision.** Every version is `unknown_revision`, which is not claimed "original" (see Gate 2).

## Gate 2 — evidence and timeline

**Discovery sources:**

- TWSE e-book listings ROC 109–111;
- MOPS material-information listings **ROC 110–114**. The search window runs through 2025, so later corrections to
  FY2020–2022 are covered;
- TPEx `O_2020Q4`–`O_2022Q4`. Their values equal the XBRL exactly for revenue, operating income and EPS, including
  prior-year comparatives.

**Annual PDFs.** For FY2020 and FY2021, AI1 and AI3 are **verified** (2021-03-08, 2022-03-18; 更(補)正 無, size
match). For FY2022 they are **unverified**, because the column is blank.

**Notices.** These are additive plan entries, and their events are quoted verbatim:

- **Board approvals of the annual consolidated report** (clause 31; values imported only after the verbatim claim
  is verified):
  - `mops:20210305:173820:1` (FY2020);
  - `mops:20220316:175938:2` (FY2021);
  - `mops:20230302:223839:3` (FY2022).
- **Corrections:**
  - `mops:20210427:145546:1`: FY2017 note 6 reclassification, "並不影響損益";
  - `mops:20220602:134747:3`: 2020/2021 Q1–Q3 interim periods, "對109年度之損益無影響";
  - `mops:20230411:171742:3`: FY2022 related-party note, a unit typo 元→千元, "對損益金額並無影響".
- **Context:** `mops:20200212:174610:1` is the FY2019 AGM convening notice. It carries no figures.

**Import.**

- Run 1: events 308, disclosed values 30, PDF versions 6, summaries 42, links 18, value-level corroborations 21.
- Run 2: **all counts 0**.

The new correction links attach to FY2017 and FY2022 artifacts as `unverified_linkage`. They are additions; no
existing link row changed.

**Request log** (official hosts only):

| Group | Requests |
|---|---|
| MOPS `t164sb01` | 6 (3 years × 2 runs) |
| Discovery | 11 |
| TWSE e-book PDFs | 6 files, each a step-9 page plus the PDF |
| Notice details | 7 |
| Conference pipeline | 33 |

## Gate 3 — conference recovery (2018–2022)

The runner is `scripts/recover_historical_conference_pdfs.py`, a thin wrapper around the existing
`run_mops_pdf_pipeline`:

- per-year batches;
- 2 s pacing and one ×4 backoff retry;
- a stop on HTTP 403/429 or 3 consecutive failures;
- resumable through the manifests' SHA-256 values;
- text-only.

| Year | Listing | Meetings (rows) | Expected | Downloaded and hash-verified | Missing | Failed | Non-PDF | Pages (text) | Distinct files | JSD-ready | Publication time |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2018 | conference_found | 5 | 10 | 10 | 0 | 0 | 0 | 240 (240) | 4 | 0 | unverified |
| 2019 | conference_found | 2 | 4 | 4 | 0 | 0 | 0 | 55 (55) | 4 | 0 | unverified |
| 2020 | conference_found | 1 | 2 | 2 | 0 | 0 | 0 | 20 (20) | 2 | 0 | unverified |
| 2021 | conference_found | 2 | 4 | 4 | 0 | 0 | 0 | 26 (26) | 4 | 0 | unverified |
| 2022 | conference_found | 5 | 8 | 8 | 0 | 0 | 0 | 225 (207) | 8 | 0 | unverified |

**Duplicates in 2018.** The 10 files of 2018 are 4 distinct documents:

- the 2018-02-07 deck is listed twice per language;
- the May deck is one file per language listed for the meetings of 05/03, 05/04 and 05/08.

`conference_documents.csv` gains `content_duplicate_of` and `language_pair_key` (additive). A content-addressed
output is written once per SHA-256. The first package build **failed closed** on this point, with "Conflicting
content for conference/pages/…", because identical bytes carried per-listing metadata; that was fixed and a test
added.

**JSD readiness: 0 of 32.**

- **Reason.** The unchanged adapter marks every document `period_unconfirmed`, and 6 duplicates also get
  `duplicate_document`. The adapter was not changed.
- **Archival text is kept.** All 32 corpus rows are `archival_only`.
- **Pipeline status.** The pipeline status `failed` reflects only its visual-review gate, since every page is
  `visual_review_required` when semantic analysis is off. Acquisition and text extraction are complete.

**Coverage audit.** The 2018 and 2019 rows from Phase 2A (`document_missing`, 0 downloaded) remain as history. The
new rows (`conference_found`, 10/10 and 4/4) carry a new listing hash, because MOPS listing bytes differ between
fetches. The recorder now updates only status columns when the same listing hash is recorded again; no
pre-Phase-2B row was modified (digest-verified).

## Gate 4 — PIT evidence improvement

### Route A — implemented: annual board-approval notices

The table is `disclosed_financial_values`, with corroboration kind `financial_report_disclosure`. A fact is dated
only when every one of these matches exactly:

- fiscal year, with a full-year period;
- metric, through a fixed label table;
- scope, from the notice subject;
- framework;
- normalized unit and value.

The fact's version must not be restated, and no restatement evidence may exist for the period.

| FY | Notice (Taipei) | Newly eligible | Not stated (still ineligible) | Rejected match |
|---|---|---|---|---|
| 2020 | 2021-03-05 17:38:20 | revenue, gross_profit, operating_income, net_income, eps, total_assets, total_liabilities | 11: AR, capex, cash, COGS, current assets/liabilities, equity, inventory, investing/operating cash flow, R&D | `equity`: the notice states parent-attributable equity (8,220,267 thousand), not total equity (8,506,283) |
| 2021 | 2022-03-16 17:59:38 | same 7 | same 11 | same (12,117,801 vs 12,437,989) |
| 2022 | 2023-03-02 22:38:39 | same 7 | same 11 | same (12,789,724 vs 13,203,479) |

**Exact cutoff boundaries (real-data tests):**

| as-of (Taipei) | PIT facts |
|---|---|
| 2021-03-05 17:38:19 | 0 |
| 2021-03-05 17:38:20 | 7 |
| 2023-03-02 22:38:38 | 14 |
| 2023-03-02 22:38:39 | 21 |

All facts as of 2023-12-31: **48** (27 + 21).

**Artifacts unchanged.** Every XBRL artifact keeps `availability_status = unverified` and `available_at = null`.
Only the stated values are dated, with the notice as `availability_evidence_*`.

**Strict verifier.** The shipped verifier independently re-parses the raw board notice (`parse_board_report_notice`)
and re-derives each such fact. Seven real-data mutations fail for a named reason: value, unit, metric, scope,
period, evidence identity and evidence kind. Unsupported or non-board notices fail closed.

### Route B — feasibility only: values from verified PDFs

| Item | Finding |
|---|---|
| FY2019 PDF (verified 2020-02-14) | **no text layer** (93 scanned pages); impossible without OCR, so FY2017–2019 stay 0 |
| FY2020/2021 PDFs (verified 2021-03-08 / 2022-03-18) | text layer present. 10 of the 11 non-notice metrics appear verbatim on statement pages 9–15; capex is not found verbatim |
| Earliest benefit | the PDF upload time is *after* the board notice, so it could only add the 11 non-notice metrics, from the upload time |
| Decision | **not implemented.** String presence is not line-item identity; a sound version needs a statement-table parser that binds label, column (current versus comparative period) and unit, plus an independent verifier. Proposed as a separate, testable work item |

## Gate 5 — compatibility (read-only)

The read-only checks covered:

- the CLI `query`, `export` (including PIT `--as-of 2023-12-31`: 48 rows) and `quality` (all integrity checks 0);
- every `evidence-export` dataset, including the new `disclosed_financial_values` (30 rows);
- `research_access` (local);
- mock-cloud parity on the real archive for FY2011–2022 at 4 cutoffs, including the new evidence kind.

The database digest was identical before and after these checks. No FastAPI route exists for historical data; none
was added. No frontend, Flask, LLM, risk-scoring or JSD-algorithm code changed.

**Defect found and fixed.** `coverage_matrix` raised `KeyError` for years whose PIT facts come from a non-restatement
disclosure. It now reports them ("7 of 18 … dated by an official financial-report disclosure"); FY2011–2019 output
is byte-identical to the Phase 2A package.

**FY2016 EPS** (−1.23 against −1.39 in the FY2017 comparative) remains unresolved. No new source explains it.

## Gate 6 — packages

Both were published through the journaled release (`scripts/rebuild_historical_packages.py --rebuild both
--start-year 2011 --end-year 2022 --as-of 2023-12-31 --strict-filename …`).

| File (`fintrust_backend/data/historical_audit/packages/`) | Bytes | SHA-256 |
|---|---|---|
| `fintrust_1785_2011_2022_full.zip` | 179,871,856 | `3d4cba560cfd8e46cf521291604583724b7ca2eb520384f35157caa2ee66221b` |
| `fintrust_1785_2011_2022_asof_2023-12-31.zip` | 34,934,369 | `61042b7f17834077b67c77037be2202802a074cbefe39b7771be2d9aed1f4d56` |
| `fintrust_1785_2011_2022_asof_2023-12-31.audit.json` | — | `1cdd0d5b55d5b98b4cd1706b157b6d4838157aa57c24204a24ab8e1153b44198` |

**Full package:**

- 208 verified files;
- 180 facts (48 PIT-eligible), 35 versions, 163 summaries, 158 comparisons;
- 30 disclosed values, 856 events;
- 32 conference documents (26 distinct, 712 pages);
- 131 raw files.

**Strict package:**

- 48 verified files;
- 48 facts, all with a withheld artifact identity;
- 14 versions, 12 summaries, 158 comparisons, 728 events;
- inventory 20, raw 34.

The sidecar excludes conference documents (34), versions (21), events (128), source documents (38) and summaries
(151).

**Verification:**

- **Integrity.** ZIP CRC passes, and the shipped verifier passes under system Python 3.14 (`python -I`) outside the
  repository, on the ZIP and on the safely extracted folder.
- **Sidecar.** It binds the strict ZIP through `package_sha256`, `content_digest` and `package_file`, and the
  release pair is valid.
- **Leakage.** No 2024+ or modern markers, all timestamps are Taipei, and there is no workbook, XML or conference
  content.
- **Earlier packages.** All 6 earlier package files are unchanged (`sha256sum -c`).
- **Recovery.** Interrupted-publication recovery is covered by `test_historical_release_pair.py` (9 tests).

## Gate 7 — test results (actual)

| Tier | Result |
|---|---|
| Historical (pytest), all modules | 147 passed, 2 skipped |
| — fixture | 108 passed, including board-notice parsers, recovery-runner stop conditions, duplicate conference documents and coverage roles |
| — real local archive (`test_historical_evidence_real.py`) | 29 passed (incl. 6 Phase 2B tests and FY2011–2022 mock-cloud parity) |
| — mock cloud (`test_historical_cloud.py`) | 10 passed |
| — emulator | skipped (Firestore emulator not configured) |
| — live MOPS test | skipped (opt-in) |
| Historical (plain `unittest`) | 149 run, OK, 2 skipped |
| Conference / JSD / 2330 / 2454 (`-k`) | 185 passed |
| Full backend regression | 544 passed, 3 skipped (+ reportlab PDF fixture) |
| Live-source checks | the bounded live acquisitions above: 6 + 11 + 6 + 7 + 33 requests, all successful |

## Cumulative FY2011–FY2022

| FY | Facts | PIT facts | PIT evidence | Verified artifacts | Conference files (distinct) |
|---|---|---|---|---|---|
| 2011–2012 | 0 (scanned originals) | 0 | before/after disclosure only | original PDFs (2016-08-25) | 2011: 2 (1 meeting) |
| 2013–2015 | 54 | 27 | restatement notice 2016-11-13 | original PDFs | — |
| 2016 | 18 | 0 | — | PDF 2017-03-22 | — |
| 2017 | 18 | 0 | — | — | 2 (2) |
| 2018 | 18 | 0 | — | — | 10 (4) |
| 2019 | 18 | 0 | — | PDFs 2020-02-14 | 4 (4) |
| 2020 | 18 | 7 | board notice 2021-03-05 | PDFs 2021-03-08 | 2 (2) |
| 2021 | 18 | 7 | board notice 2022-03-16 | PDFs 2022-03-18 | 4 (4) |
| 2022 | 18 | 7 | board notice 2023-03-02 | — | 8 (8) |

## Remaining limitations

- **No verified XBRL publication time** for any year. PIT eligibility is value-level only.
- **11 of 18 metrics per FY2020–2022 year** are not PIT-eligible. Route B is a proposal.
- **FY2017–2019:** 0 PIT facts. The FY2019 PDF is scanned, and no board notice with figures exists.
- **FY2022 PDFs** are unverified (blank 更(補)正; corrected 2023-04-11).
- **Conference documents.** 0 are JSD-ready (`period_unconfirmed`), and all publication times are unverified.
- **FY2016 comparative EPS** discrepancy unresolved.
- **Emulator and live-MOPS test tiers** were not run.

## Phase 2C readiness

The procedure is now proven across a taxonomy transition, inline XBRL, a new disclosure kind, duplicate conference
listings and an interrupted-build failure (which failed closed).

FY2023–2025 can follow the same gates:

- MOPS listings ROC 112–114 are already archived;
- the 2023-08 and 2024-08-12 related-party note corrections (FY2023 Q3/Q4) are already identified.

Watch for:

- the 2025-08-11 XBRL correction (Q2 2025);
- new board-notice formats (the verifier fails closed until it is extended);
- larger conference volumes.

## Carryover review fixes (after `98952ce`)

### F-2B-01 — conference recovery exit status

**Reproduced.** For a year whose listing named 2 PDFs and archived neither, `recover_historical_conference_pdfs`
exited **0**.

**Root cause.**

- The runner returned non-zero only for `StopRecovery`.
- `run_mops_pdf_pipeline` catches every per-document and listing exception and records it in `errors`, so a
  `StopRecovery` raised by the transport mid-year never propagated. A stop condition would also have been
  swallowed.

**Fix.**

- **Two separate statuses per year.** `classify_year` derives `acquisition_status` from the listing and the
  hash-verified archived files only: `complete`, `no_official_record`, `no_documents_listed`, `partial`, `failed`
  or `stopped`. It reports `review_status` separately: `visual_review_pending` is expected while LLM/OCR analysis
  is disabled, and it never fails a run.
- **The stop is tracked on the transport.** Every later request short-circuits, and later years become
  `not_attempted`.
- **Exit codes.** 0 = all years complete, no record or nothing listed; 1 = any year partial or failed;
  2 = stopped.
- **Testability.** `run_recovery(...)` is injectable for offline tests.

**Tests** (`ConferenceRecoveryExitStatusTests`, 5 tests):

- the classifier matrix;
- complete years with review pending exit 0;
- a failed year followed by a complete year: both run, exit 1;
- a partial download exits 1;
- a stop swallowed inside the pipeline still stops the run: exit 2, and the next year is `not_attempted`.

### F-2B-02 — missing document counts

**Reproduced.** With a listing of 2 documents and none archived, the row read `document_missing`, expected 2,
downloaded 0, but **missing 0**. `missing_documents` came only from a pipeline manifest's integrity block.

**Fix.** `ConferenceCoverageRecorder.attachment_counts` computes all counts by attachment identity (file name):

- **expected:** the union of the verified official listing and the pipeline manifest; a file listed in several rows
  or twice in the manifest counts once;
- **archived:** an expected file that exists and re-hashes to its manifest SHA-256;
- **missing:** expected − archived;
- **failed:** downloads the manifest records as failed. These give `download_failed`.

**Tests.**

- Zero downloads: missing 2. Partial: 1/1. Complete: 2/0. Failed download: `download_failed`.
- A duplicated listing entry counts once.
- A file whose bytes no longer match is not archived.
- The package's `conference_coverage.csv` reports the same totals.

**Existing rows.** Rows recorded before the fix are not rewritten. The historical Phase 2A rows for 2018/2019
(`document_missing`, missing 0) remain as history; the latest rows (`conference_found`, 10/10 and 4/4, missing 0)
are correct.

### Strict verifier — disclosure-dated facts with a public artifact

**Found.**

- `strict_facts` marks a fact `verified_public_artifact` whenever its filing version is public before the cutoff,
  while its `availability_evidence_kind` can still be `financial_report_disclosure` or `restatement_disclosure`
  (the disclosure being earlier).
- In that case the verifier only checked that the version was included. It did not resolve or re-derive the
  disclosure.
- With consistent CSV/JSON, the `98952ce` verifier **accepted** packages with an unresolvable disclosure hash, a
  mismatched observation time, or a `filing_artifact` time that was not the version's own. This was demonstrated
  offline against the committed verifier.

No released package contains such a fact; every disclosure-dated fact there has a withheld artifact.

**Fix.**

- Artifact status and evidence kind are verified independently.
- Every disclosure-kind fact must resolve its included disclosure, with equal observation and effective times; a
  board-dated fact is re-derived from the raw notice in both branches.
- A `filing_artifact` fact must carry its included version's verified time.
- Unknown evidence kinds fail closed.

All three released strict packages still verify.

**Tests.**

- Fixture: `test_disclosure_dated_fact_with_a_verified_artifact_is_still_verified`, with 5 mutations; CSV and
  JSON are kept consistent so only semantics can catch them.
- Real tier: 2 new cases in `RealPhase2bFy2020To2022`, a tampered value and a wrong scope with a public artifact.

### Documentation

- **Inventory counts.** The source-evidence inventory now separates per-phase and cumulative counts:

  | | Phase 1 | Phase 2A | Phase 2B | Total |
  |---|---|---|---|---|
  | Source documents | 41 | 18 | 24 | 83 |
  | MOPS XBRL filings | 4 | 3 | 3 | 10 |
  | Inventory rows | 45 | 21 | 27 | 93 |

- **Corrected figure.** The Phase 2B figure "30 sources" was an arithmetic error and is corrected to 27.
- **Released ZIP not rebuilt.** The released `fintrust_1785_2011_2022_full.zip` embeds the earlier inventory text
  (with "30"). It is unchanged on purpose, so its hash stays stable.

### Reproduction

Run from `fintrust_backend/`:

```bash
python ../docs/development/evidence/historical_audit_phase2b_carryover_repro.py --before 98952ce
```

Before → after:

- F-2B-01 exit code: 0 → 1;
- F-2B-02 `missing_documents`: 0 → 2.
