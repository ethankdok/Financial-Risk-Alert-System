# 1785 光洋科 — Official Investor-Conference Coverage (2010–2025)

Source: MOPS 法人說明會 listing `ajax_t100sb02_1` (market `otc`) and the official
`FileDownLoad` form, acquired with the existing conference pipeline
(`mops_conference_pdf_pipeline`, unchanged). Retrieved 2026-10-10 (UTC). Raw bytes
are archived locally (gitignored) under `fintrust_backend/data/historical-conference-pdfs/1785/`
and in the historical-audit raw archive (listing responses).

The core research range is set **per package** by its fiscal-year range:
- the FY2011–2016 packages treat 2010 and 2017 as context;
- the FY2011–2019 packages (Phase 2A) treat 2011–2019 as core.

Context years are included only with `--include-context-years`. Every row is marked by `research_role`, which is
recomputed from the package range; the role stored when the listing was recorded is not used.

## Year-by-year status

| Year | Role | Status | Rows | Meeting dates | Expected / downloaded | Non-PDF | Listing response SHA-256 |
|---|---|---|---|---|---|---|---|
| 2010 | pre_period_context | conference_found | 2 | 99/01/26, 99/11/04 | 2 / 2 | 0 | `192059958493dba2…` |
| 2011 | core | conference_found | 1 | 100/03/25 | 2 / 2 | 0 | `c3a024dbace4e086…` |
| 2012 | core | no_official_record_found | 0 | — | 0 / 0 | 0 | `87e52938f7b40c03…` (MOPS 「查無資料」) |
| 2013 | core | no_official_record_found | 0 | — | 0 / 0 | 0 | `87e52938f7b40c03…` |
| 2014 | core | no_official_record_found | 0 | — | 0 / 0 | 0 | `87e52938f7b40c03…` |
| 2015 | core | no_official_record_found | 0 | — | 0 / 0 | 0 | `87e52938f7b40c03…` |
| 2016 | core | no_official_record_found | 0 | — | 0 / 0 | 0 | `87e52938f7b40c03…` |
| 2017 | core in FY2011–2019 packages | conference_found | 1 | 106/04/14 | 2 / 2 | 0 | `4f17dee1733f5299…` |
| 2018 | core in FY2011–2019+ packages | conference_found (Phase 2B; `document_missing` in Phase 2A) | 5 | 107/02/07, 107/05/03, 107/05/04, 107/05/08 | 10 / 10 | 0 | `45ed41dfb23c0f14…` |
| 2019 | core in FY2011–2019+ packages | conference_found (Phase 2B; `document_missing` in Phase 2A) | 2 | 108/05/23, 108/08/14 | 4 / 4 | 0 | `a01dc7cc9618eb95…` |
| 2020 | core in FY2011–2022 packages | conference_found | 1 | 109/09/10 | 2 / 2 | 0 | `8d0d34f107721bff…` |
| 2021 | core in FY2011–2022 packages | conference_found | 2 | 110/10/22, 110/11/19 | 4 / 4 | 0 | `b65609904106fb6b…` |
| 2022 | core in FY2011–2022 packages | conference_found | 5 | 111/04/13, 111/04/27, 111/09/22–29, 111/11/22, 111/12/01–02 | 8 / 8 | 0 | `de99c94d090ee716…` |

The 2018 and 2019 listings were recorded in Phase 2A (2026-10-11 UTC). Their documents are listed by MOPS but were
**not downloaded**: conference acquisition is outside the scope of Phase 2A. Before a recorder fix in Phase 2A,
such a year would have read `conference_found` with 0 expected documents, because the counts came only from a
pipeline manifest. They now come from the verified official listing.

- **No-data years.** The five no-data responses are byte-identical MOPS 「查無資料」 pages. That shows the official listing has no record for those years. It does **not** prove that no conference took place.
- **The third-party index** (finmoconf.diveinvest.net) was used only as a discovery lead. It agrees with the official result (2011-03-25 and 2017-04-14 for 2011–2017) and is not stored as evidence.

## Recovered documents

| Year | File (MOPS) | Listing column | Detected language | Pages | Text pages (≥30 chars) | Identity (existing rules) | SHA-256 |
|---|---|---|---|---|---|---|---|
| 2011 | `178520110325M001.pdf` | zh | zh-Hant | 47 | 46 (p.1 cover: low text) | other_official_conference_document (0.3), period unconfirmed | `b97553ff849f7100931267bab29f7f452a3a9f07a013ddaa9fd1a90af957cea6` |
| 2011 | `178520110325E001.pdf` | en | en | 47 | 47 | investor_presentation (0.75), period unconfirmed | `c69c9dd3a6df1506b2343ce20e1442ad9aeb97540baaf5e0e18f0318df77ebdb` |
| 2010 | `178520100126M001.pdf` | zh | en | 33 | 33 | other_official_conference_document (0.3), unconfirmed | `60ba68ba26e363fc7428e867d9f4067ed41149c8abd6dbafa85b6a741cfd18a5` |
| 2010 | `178520101104M001.pdf` | zh | en | 44 | 44 | other_official_conference_document (0.3), unconfirmed | `d15b4b029657a23d31c6041bd832dd5e5da13a9845b27bef2f119c93ae8ea06b` |
| 2017 | `178520170414E001.pdf` | en | en | 26 | 26 | other_official_conference_document (0.3), unconfirmed | `793850272274a0a40b5c4a85e33f524953de4b619c7e36a6f66491485f9cfb0b` |
| 2017 | `178520170414M001.pdf` | zh | en | 26 | 26 | other_official_conference_document (0.3), unconfirmed | `d898e91ed2c43e2e3fb6317a39138e340491f305395d0f1c712fdbb1fe34ae31` |

- **Official access.** The lead URL `https://mopsov.twse.com.tw/nas/STR/178520110325M001.pdf` names the same official file. The pipeline obtained it through the listing's FileDownLoad form, so the direct-URL fallback was not needed.
- **Validation.** Every file was checked to be a PDF (`%PDF-`), unencrypted, listed for ticker 1785 / 光洋科, and stored unchanged with its SHA-256.
- **Extraction.** Text is page-order selectable text (`text_extraction_method = selectable_text`). No OCR was run and no LLM was used. Every page is `visual_review_required`, because charts and figures are not machine-verified; this flags chart content, not missing text.
- **Language disagreements.** For several files the MOPS column disagrees with the detected text language. Both values are reported as `listing_language` and `document_language`.
- **2010 and 2017 processing.** The default semantic and visual analysis stalled on a 2010 deck, so those years were re-run with the pipeline's documented text-only mode (`semantic_analysis=False`). Page text, hashes and identity are unaffected.

## JSD compatibility

The unchanged JSD adapter rules mark **0 documents JSD-ready**:
- **No quarter.** Each deck covers a whole year or strategy, so `period_validation_status = unconfirmed`. A meeting date is never used to infer a fiscal quarter.
- **Never relabelled.** No document is relabelled as a transcript.
- **No sub-industry invented.** The adapter's industry value is used as is; no semiconductor sub-industry is invented for 1785.
- **Not enough for calibration.** A single in-range conference cannot support longitudinal JSD calibration.

All text is still provided as an archival corpus (`data/conference_text_corpus.csv`,
`archival_only = true`). `data/conference_jsd_corpus.csv` keeps the JSD contract
header and has no rows.

## Point-in-time status

MOPS lists only meeting dates (date precision). No upload or first-public
timestamp was found for any presentation, so `publication_availability_status =
unverified` everywhere. Conference documents are therefore **excluded from strict
point-in-time packages**; a cover date such as 2011.03.25 is not publication evidence.

## Remaining gaps

- Official confirmation of conferences in 2012–2016 outside MOPS, for example company IR archives or TPEx invitations.
- Publication timestamps of the presentations.
- Verified quarterly periods (none exist; these are annual decks).

## Phase 2B recovery (2018–2022)

All 28 listed documents were downloaded and hash-verified. The recovery used the existing pipeline through
`scripts/recover_historical_conference_pdfs.py`:

- bounded and resumable, with 2 s pacing, one backoff retry, and a stop on HTTP 403/429 or 3 consecutive failures;
- 33 requests in total (11 for 2018, 5 for 2019, 17 for 2020–2022), none of which failed;
- text-only: no OCR and no LLM.

The 2018 and 2019 rows from Phase 2A are kept as history. The listing bytes differ between fetches, so the new
status rows have a new listing hash.

| Year | Files | Distinct documents | Language pairs | Pages (text) | Notes |
|---|---|---|---|---|---|
| 2018 | 10 | **4** | 2 presentations × zh/en | 240 (240) | The 02/07 deck is listed twice per language (E001≡E003, M001≡M003). The May deck is one file per language listed for **three** meeting dates (05/03, 05/04, 05/08) |
| 2019 | 4 | 4 | 2 × zh/en | 55 (55) | 05/23 and 08/14 |
| 2020 | 2 | 2 | 1 × zh/en | 20 (20) | 09/10 |
| 2021 | 4 | 4 | 2 × zh/en | 26 (26) | 10/22 and 11/19 |
| 2022 | 8 | 8 | 4 × zh/en | 225 (207) | 18 pages are low-text/image pages; a deck may cover several meeting dates |

Research semantics:

- **Duplicate content.** `content_duplicate_of` in `conference_documents.csv` names the first file with identical
  bytes. Such a row is not a separate document.
- **Language pairs.** `language_pair_key` groups the M (Chinese) and E (English) versions of one listing entry.
  They are one presentation, not two observations.
- **Meeting dates.** A meeting date is not a publication time. All documents keep
  `publication_availability_status = unverified` and stay excluded from strict packages.
- **Pipeline status.** The pipeline reports `failed` for these years only because every page is flagged
  `visual_review_required`: semantic visual analysis is deliberately off. Acquisition and text extraction are
  complete.
- **JSD readiness** is decided by the unchanged adapter and reported in the package and the validation report.

## Phase 2C recovery (2023–2025) and cumulative coverage 2011–2025

For 2023–2025 the runner reported `complete` for every year, with coverage `consistent` (re-hashed archive counts),
review status `visual_review_pending`, exit 0, and 15 requests, none failed. No OCR or LLM was used.

| Year | Listing | Listing rows (meetings) | Files | Distinct by content | Language-pair keys | Pages (text) |
|---|---|---|---|---|---|---|
| 2011 | conference_found | 1 | 2 | 2 | 1 | 94 (93) |
| 2012–2016 | no_official_record_found (MOPS 「查無資料」) | 0 | 0 | 0 | 0 | 0 |
| 2017 | conference_found | 1 | 2 | 2 | 1 | 52 (52) |
| 2018 | conference_found | 5 | 10 | 4 | 5 | 240 (240) |
| 2019 | conference_found | 2 | 4 | 4 | 2 | 55 (55) |
| 2020 | conference_found | 1 | 2 | 2 | 1 | 20 (20) |
| 2021 | conference_found | 2 | 4 | 4 | 2 | 26 (26) |
| 2022 | conference_found | 5 | 8 | 8 | 4 | 225 (207) |
| 2023 | conference_found | 6 | 6 | 6 | 3 | 242 (224) |
| 2024 | conference_found | 2 | 4 | 4 | 2 | 176 (166) |
| 2025 | conference_found | 1 | 2 | 2 | 1 | 60 (56) |
| **2011–2025** | | **26** | **44** | **38** | **22** | **1,190 (1,139)** |

2010 (2 files, context only) is outside this range. How to read the columns:

- A **listing row** is one MOPS meeting entry; one deck can serve several rows (2018 May: three dates).
- **Distinct by content** removes byte-identical re-listings (`content_duplicate_of`).
- A **language-pair key** groups the M (Chinese) and E (English) files of one listing entry. Re-listed identical
  decks keep separate keys, so the number of distinct presentations is lower: about 19 for 2011–2025, i.e. the
  distinct files divided by language.
- **Quarterly observations** for JSD: **0**. Every document is `period_unconfirmed` under the unchanged JSD
  contract (re-listings also get `duplicate_document`), and publication times stay unverified. The archival text
  is complete and kept.
