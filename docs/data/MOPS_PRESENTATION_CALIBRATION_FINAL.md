# MOPS presentation calibration — final evidence

Status: three company profiles are active in production (Firestore `shift_calibrations`) and read
dynamically by the deployed bridge. No Cloud Run deployment, IAM, secret or GCS change was made.

> JSD / Cosine measure the shift in the text distribution between two adjacent quarterly official
> documents. They do **not** prove fraud, truthfulness, financial distress or investment risk.

## 1. Method boundary

- Method A only: teammate `data_shift.calculate_jsd` / `calculate_cosine_similarity`, and the
  teammate calibration `calibrate_tsmc_shift.pair()` / `analyze()` (quality rule ≥ 5,000 characters
  and length ratio ≥ 0.50, history pairs entirely before the target, P90/P95 and P10/P05,
  combined rule JSD ≥ P90 AND Cosine ≤ P10, minimum 30 history pairs). Nothing in them was changed.
- They are loaded unmodified from the research commit into a temporary directory
  (`scripts/calibrate_conference_scope.py`); records keep their real document type
  (`earnings_presentation`), and the teammate's transcript-only `load()` is not used.
- Corpus: FinTrust's official MOPS t100sb02_1 conference PDFs, page-order native pypdf text.
  No OCR text, no Gemini output and no semantic labels enter the corpus.
- English scopes only; no zh-Hant, pooled or industry profiles.

## 2–3. References

| | |
|---|---|
| Teammate method reference | `origin/feature/tsmc-quarterly-corpus` @ `5b914937dc3cb2294851e0386c67270d20547e7e` |
| Calculator (`data_shift.py`, LF-normalized SHA-256) | `aa94cf9ed19bcd30ad0666ecddf3c7c5ea10a17868f66bf389278a649f86318b` |
| Method version | `earnings-en-full-pairwise-tfidf-v1` |
| Source family | `mops_t100sb02_1_conference_pdf` |
| Extraction method | `mops_conference_pipeline:pypdf_extract_text_per_page` |
| Preprocessing version | `fintrust-conference-document-text-v1` |

The method reference and the corpus provenance are separate: the presentation corpus was built by
FinTrust, not by the research branch.

## 4. Exact-scope matching rule

A profile applies only when ticker, document type, language, extraction method, preprocessing
version, method version and calculator hash all equal the target pair's, and the profile's history
ends before the target's first period (`app/services/jsd_calibration.py::matches`).

## 5–8. Results (target 2025Q2 → 2025Q3)

| Ticker | Scope | Status | History pairs | History window | Profile ID |
|---|---|---|---:|---|---|
| 2454 聯發科 | earnings_presentation / en | **active** | 33 | 2016Q4 → 2025Q1 | `jsdcal-2454-a91b3fb2a272e16d825d` |
| 2303 聯電 | earnings_presentation / en | **active** | 33 | 2016Q4 → 2025Q1 | `jsdcal-2303-d9257f696c2f8890f73a` |
| 2408 南亞科 | earnings_presentation / en | **active** | 33 | 2016Q4 → 2025Q1 | `jsdcal-2408-753145a4c1a508b7f356` |
| 2330 台積電 | earnings_presentation / en | rejected: `quality_insufficient` | ≤ 27 possible | — | — |
| 3034 聯詠 | financial_results_release / en | rejected: `insufficient_history` | 29 | — | — |

Thresholds:

| Ticker | JSD P90 | JSD P95 | Cosine P10 | Cosine P05 |
|---|---:|---:|---:|---:|
| 2454 | 0.123233 | 0.157584 | 0.913993 | 0.896558 |
| 2303 | 0.058240 | 0.063898 | 0.933246 | 0.927862 |
| 2408 | 0.253229 | 0.278425 | 0.753274 | 0.710629 |

Target metrics (identical in local research and production):

| Ticker | JSD | Cosine | Drift result |
|---|---:|---:|---|
| 2454 | 0.078121 | 0.944793 | 未達雙指標歷史漂移門檻 |
| 2303 | 0.030654 | 0.969959 | 未達雙指標歷史漂移門檻 |
| 2408 | 0.214895 | 0.782977 | 未達雙指標歷史漂移門檻 |

Rejections:

- **2330** — four quarterly decks (2019Q3, 2019Q4, 2020Q2, 2020Q3) exist on MOPS only as PowerPoint
  files, and sampled decks are genuinely short (2016Q2: 4,633 and 2018Q2: 4,762 characters; pypdf and
  PyMuPDF agree; chart slides are raster images). At most 27 quality-passing history pairs remain.
  Must stay uncalibrated.
- **3034** — 2017Q4 could not be acquired (MOPS HTTP 502) and the 2023Q4 release prints another
  quarter ("4Q22") for its own figures, so its period stays unconfirmed. 29 history pairs < 30.

## 9. No-leakage proof

For every accepted profile the latest history pair ends at 2025Q1, strictly before the target's
first period 2025Q2, and the teammate `analyze()` only admits pairs whose both quarters precede the
target (`docs/data/calibration/<ticker>-earnings_presentation-en.calibration.json`,
`no_leakage_proof`).

## 10. Production before / after

Public `POST /api/v1/financial/data-shift/analyze`, `period_1=2025Q2`, `period_2=2025Q3`
(`docs/data/calibration/production-baseline-before-activation.json`,
`production-after-activation.json`). Profiles were created one at a time (create-only), each
followed by this check before the next.

| Ticker | JSD before = after | Cosine before = after | Calibration before → after |
|---|---|---|---|
| 2454 | 0.078121 | 0.944793 | unavailable → calibrated (33 pairs) |
| 2303 | 0.030654 | 0.969959 | unavailable → calibrated (33 pairs) |
| 2408 | 0.214895 | 0.782977 | unavailable → calibrated (33 pairs) |
| 2330 | 0.232142 | 0.676225 | unavailable → unavailable |
| 3034 | quality_insufficient | — | not_evaluated → not_evaluated |

For all five: document type, language, data quality, method and preprocessing versions and the
official source documents (SHA-256) were identical before and after. Thresholds shown by production
equal the dry-run profiles exactly; the production target document hashes equal the profiles' target
hashes.

## 11–12. Firestore and isolation

`shift_calibrations` now holds four profiles: the three above and the pre-existing TSMC transcript
profile `jsdcal-2330-d0bcbeb14e2f72be10a1` (`full_earnings_transcript`, `en_may_include_translation`,
investor.tsmc.com transcripts). Each new document equals its dry-run profile (apart from
`imported_at`); re-running the importer reports `unchanged`. The transcript profile is still present
and is not applied to 2330 MOPS presentations (it differs in document type, language, extraction,
preprocessing and history window). 2330 and 3034 remain uncalibrated.

A headless-Chrome check of the production result page showed, for 2454: 已校準（33 組歷史相鄰季）,
the thresholds, drift result, official sources and method/version; and for 2330: 尚無相符歷史校準.

## 13. Source gaps

- Official non-PDF (PowerPoint) attachments on MOPS: 2330 (2019Q3, 2019Q4, 2020Q2, 2020Q3), and some
  files of 3711 (2020), 2379 (2018), 6770 (2021). Recorded, never downloaded.
- No MOPS listing (查無資料): 3711 2017; 6770 2017–2020.
- 2379 2025Q2 deck publishes its tables as images (short native text in both extractors).
- 6770 decks are genuinely short (about 2,500–3,000 characters).

## 14. Limitations

- Thresholds are per company, document type, language and method version; they are not transferable.
- Q4 decks of 2454 and 2408 carry full-year material and are longer; the highest historical JSD pairs
  involve Q4 transitions. The 2025Q2 → 2025Q3 target is not a Q4 transition.
- The teammate's own validation used full earnings-call transcripts; here its unmodified functions are
  applied to official presentations.
- Historical PDFs used for calibration are kept locally only; the profiles store no text, only metrics
  and document hashes.
- Identity v6 (committed, not deployed) would let production pair 3034's English releases; this does
  not change the 3034 calibration result.
