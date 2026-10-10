# 1785 Conference Recovery, Strict PIT Packaging Fix & Research ZIP Rebuild — Validation

Date: 2026-10-10 · Branch `feature/historical-research-portability-cloud` · starting commit `e5f13e5`
(clean tree; `265b9ed` in history; no upstream).

**Outcome:**
- The retrospective research ZIP is **ready to share** with Yu-Jing and Ethan. It
  now contains the recovered official 2011 conference documents.
- The strict as-of ZIP is **safe for historical backtesting at its cutoff
  (2016-11-14)**. Note that its usable content is limited to the restatement
  disclosure era: before 2016-05-13 nothing is verifiably public.

## 1. Confirmed defect (schema-1.0 as-of package) and fix

Reproduced in the previous `fintrust_1785_asof_2016-11-14.zip`:
- all 17 filing versions, including the FY2016 PDF (`available_at` 2017-03-22) and the unverified FY2016 XBRL;
- 110 of 359 timeline events public after the cutoff;
- all 45 raw artifacts;
- an unfiltered inventory and coverage matrix.

Fix (package schema 1.1, `research_package.py`, `strict_package.py`, `package_verify.py`):

- **Two explicit modes.** `retrospective` refuses `as_of`; any `as_of` produces a `strict_point_in_time` package.
- **Every strict dataset and raw file is filtered** by verified pre-cutoff availability. Filing artifacts must have their own verified time. Source documents must be single-publication notices; listing and workbook snapshots are never included.
- **Facts dated by an earlier disclosure** keep the value but withhold the later artifact's identity (`artifact_reference_status = withheld_not_public_at_cutoff`). `observation_available_at`, `filing_available_at` and `effective_available_at` are separate (facts contract v1.3).
- **Conference documents** are excluded unless their availability is verified, which none is.
- **No future data in `data/`.** Retrieval timestamps move to `validation/provenance.csv`. Coverage and missing-evidence files are recomputed from the strict subset, and only generic contracts ship.
- **Fail-closed checks.** The build fails on any post-cutoff date in `data/`. The shipped verifier independently re-checks dates, raw-evidence admissibility and the absence of conference material.

## 2. Conference recovery

Reused unchanged:
- `scripts/sync_mops_conference_pdfs.py` and `run_mops_pdf_pipeline` (MOPS `t100sb02_1`, FileDownLoad form, page extraction, identity);
- `FileConferencePdfArchiveRepository`;
- the JSD adapter.

Market `otc`. LLM, OCR and GCS publishing were forced off for every run:
- `GEMINI_API_KEY` and `ANTHROPIC_API_KEY` were removed from the environment;
- the multimodal, OCR and archive-publish variables were set to empty strings.

Archive root: `fintrust_backend/data/historical-conference-pdfs/1785/`.

| Year | Role | Status | Documents |
|---|---|---|---|
| 2010 | context | conference_found | 2 (99/01/26, 99/11/04) |
| **2011** | core | **conference_found** | **2 (100/03/25: zh M001, en E001)** |
| 2012–2016 | core | no_official_record_found (MOPS 「查無資料」, identical response SHA `87e52938…`) | 0 |
| 2017 | context | conference_found | 2 (106/04/14) |

Details, hashes and per-document quality are in [`../data/HISTORICAL_1785_CONFERENCE_COVERAGE.md`](../data/HISTORICAL_1785_CONFERENCE_COVERAGE.md).

- **The 2011 PDFs.** `178520110325M001.pdf` (SHA-256 `b97553ff…`, 47 pages, 46 with text, cover page low-text) and `178520110325E001.pdf` (`c69c9dd3…`, 47 pages, all with text). Both are selectable text and unencrypted.
- **JSD readiness.** The unchanged adapter marks 0 documents JSD-ready, because every period is unconfirmed (annual decks). The text is exported as an archival corpus.
- **Publication availability** is unverified for every document: MOPS gives meeting dates only.
- **Operational note.** The default semantic and visual pass stalled for more than 40 minutes on a 2010 deck, so the process was stopped. 2010 and 2017 were re-run with the pipeline's documented `semantic_analysis=False`, which leaves page text, hashes and identity unaffected.
- **Listing evidence.** Listing responses for every year are preserved as hashed evidence (`conference-coverage`). The recorder spaces network requests 2 s apart; the first 2012–2016 run predates that change and sent 5 requests about 0.2 s apart.

## 3. Replacement packages (same directory)

`C:\Users\samue\Documents\GitHub\Financial-Risk-Alert-System\fintrust_backend\data\historical_audit\packages\`

| File | Bytes | SHA-256 | Mode / content_digest |
|---|---|---|---|
| `fintrust_1785_2011_2016_full.zip` | 44,941,248 | `693e867155de00ebded16ffece99f6b32179d306e369028eee4045f6dfbaa826` | retrospective / `ced936746ba922b4…` |
| `fintrust_1785_asof_2016-11-14.zip` | 7,138,572 | `84be7e2439b9e9dabdf2b28cfc470e73bb243841b576a35de094deea26749f49` | strict_point_in_time / `384aefa451c69072…` |

The previous versions are in `packages/previous/`, with hashes identical to the originals:
- `fintrust_1785_2011_2016_full.zip`: 36,785,393 bytes, `b89e990d…`
- `fintrust_1785_asof_2016-11-14.zip`: 36,781,260 bytes, `63031bdd…`

`packages/previous/REPLACEMENT_REPORT.json` records every step.

| | Previous full | New full | Previous as-of | New strict as-of |
|---|---|---|---|---|
| Mode | — (schema 1.0) | retrospective | — (leaky) | strict_point_in_time |
| Filing versions | 17 | 17 | 17 | **7** (original PDFs verified public 2016-08-25) |
| Facts | 72 | 72 | 27 (with later XBRL ids) | 27 (dated by the 2016-11-13 notice, artifact withheld) |
| Timeline events | 359 | 359 | 359 | **249** |
| Raw evidence files | 45 | 53 (+2 conference PDFs, +6 listing responses) | 45 | **11** (7 PDFs + 4 pre-cutoff notices) |
| Conference documents | 0 | 2 (2011; 4 context-year documents excluded and counted) | 0 | 0 (6 excluded: unverified availability) |

Replacement procedure (`scripts/rebuild_historical_packages.py`, all steps passed):
1. back up the current ZIPs;
2. build under temporary names;
3. in-process verification;
4. the shipped verifier run with `python -I` outside the repository;
5. extract outside the repository and verify each folder;
6. strict leakage checks (dates, raw admissibility, no XML/XLS/listings/conference, no `2017-`, `106年`, `105/12`, `2016-12-` or `2016-11-15/16/17` markers outside raw evidence);
7. conference provenance (PDF hashes equal the conference archive, text and page files present, no local paths);
8. atomic `os.replace`.

## 4. Tests

| ID | Tier | Result | Evidence |
|---|---|---|---|
| CONF-01 | live | PASS | MOPS t100sb02_1 (otc) queried for 2010–2017 with the existing pipeline |
| CONF-02 | live + real | PASS | 2011 M001/E001 acquired via the official listing form; `RealConferenceAndStrictPackage.test_2011_official_conference_pdfs` (exact SHA-256, 47 pages, meeting date 100/03/25) |
| CONF-03 | live + fixture | PASS | coverage table 2011–2016; `test_conf03_08_year_by_year_status_and_missing_years` |
| CONF-04 | fixture + real | PASS | original bytes and SHA-256 in the package equal the archive |
| CONF-05 | fixture + real | PASS | page index statuses; 93/94 core pages with text |
| CONF-06 | fixture + real | PASS | presentations never labelled transcripts |
| CONF-07 | fixture | PASS | JSD corpus keeps the contract header, unconfirmed periods not JSD-ready; verified-period fixture is JSD-ready |
| CONF-08 | fixture + live | PASS | 「查無資料」 → `no_official_record_found`; transport failure → `official_listing_unavailable`; both in `missing_evidence.csv` |
| CONF-09 | real | PASS | full ZIP has the 2011 PDFs, text, pages and coverage |
| CONF-10 | fixture + real | PASS | strict requirements 1–8 (`test_strict_requirements_1_to_8`, `test_strict_package_has_no_future_information`) |
| CONF-11 | fixture + real | PASS | conference and unverified artifacts excluded; earlier-cutoff package is empty of later evidence |
| CONF-12 | fixture + real | PASS | requirement 9 (tampered timeline / extra later raw file rejected by the verifier); requirement 10 (verified after clean extraction, subprocess `-I`) |
| CONF-13 | real | PASS | facts, versions, comparisons, summaries, events, documents and links row-identical to the pre-1C backup; XBRL hashes unchanged |
| CONF-14 | — | PASS | conference/JSD subset (12 files): 142 passed, 1 skipped; 2330/2454 subset: 76 passed |
| CONF-15 | — | PASS | no cloud, Firestore, GCS, deploy or push; LLM env removed for acquisition; no secrets in packages |

Full backend suite (this machine, with local archives): **502 passed, 3 skipped**
(live MOPS opt-in, Firestore emulator, `reportlab`). Fresh worktree of the implementation commit
(no local archives): **490 passed, 15 skipped** — the 12 real-data tests skip there.

## 5. Safety

- **Production services were not modified.** `git diff` covers only historical-audit modules, scripts, tests and docs.
- **No cloud activity.** GCS and Firestore sync stayed disabled, and the conference archive publish flag was empty.
- **Observation.** The unchanged JSD adapter resolves company identity through `get_company()`, which, for an unseeded ticker, opens the company master selected by `DATASTORE_BACKEND`. Here that was local SQLite. Run package builds with the SQLite default.

## 6. Commands executed

```bash
cd fintrust_backend
env -u GEMINI_API_KEY -u FINANCIAL_LLM_PROVIDER -u ANTHROPIC_API_KEY CONFERENCE_PDF_MULTIMODAL_PROVIDER= \
    CONFERENCE_PDF_OCR_PROVIDER= CONFERENCE_PDF_ARCHIVE_PUBLISH= \
    python -m scripts.sync_mops_conference_pdfs --ticker 1785 --year <2011..2016> --market otc --output data/historical-conference-pdfs
# 2010, 2017: run_mops_pdf_pipeline(..., semantic_analysis=False) with the same environment
python -m scripts.historical_audit_case conference-coverage --ticker 1785 --from-year 2011 --to-year 2016 --market otc
python -m scripts.historical_audit_case conference-coverage --ticker 1785 --from-year 2010 --to-year 2010 --market otc
python -m scripts.historical_audit_case conference-coverage --ticker 1785 --from-year 2017 --to-year 2017 --market otc
python -m scripts.rebuild_historical_packages --as-of 2016-11-14
python -m pytest -q -p no:cacheprovider tests
```

Fresh worktree of the implementation commit: 490 passed, 15 skipped (measured).
