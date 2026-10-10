# 1785 光洋科 — Official Investor-Conference Coverage (2010–2017)

Source: MOPS 法人說明會 listing `ajax_t100sb02_1` (market `otc`) and the official
`FileDownLoad` form, acquired with the existing conference pipeline
(`mops_conference_pdf_pipeline`, unchanged). Retrieved 2026-10-10 (UTC). Raw bytes
are archived locally (gitignored) under `fintrust_backend/data/historical-conference-pdfs/1785/`
and in the historical-audit raw archive (listing responses).

Core research range: **2011–2016**. 2010 and 2017 are context only and are not
in the core package unless `--include-context-years` is used. They are always
marked by `research_role`.

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
| 2017 | post_period_context | conference_found | 1 | 106/04/14 | 2 / 2 | 0 | `4f17dee1733f5299…` |

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
