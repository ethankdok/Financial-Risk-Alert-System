# Conference-PDF → JSD input contract (FinTrust side)

FinTrust supplies standardized, provenance-checked document records. The JSD
research code (teammate branch `feature/tsmc-quarterly-corpus`, inspected at
`5b91493`) is an external consumer: JSD, cosine, tokenizer, data-quality
thresholds, historical calibration, percentile thresholds and drift rules stay
there and are not reimplemented or modified here.

## Record contract (`app/services/conference_jsd_corpus_adapter.py`)

Columns, in the teammate corpus order (`tsmc_quarterly_text.csv`):

`ticker, company, industry, year, quarter, period, document_type, language, text, source_page, source_pdf, sha256, text_length`

| Field | FinTrust value |
|---|---|
| `period` | `YYYYQn`, validated from the PDF cover/results agenda; never inferred from a publication date |
| `document_type` | `full_earnings_transcript`, `earnings_presentation`, `investor_presentation`, `analyst_conference_presentation`, `financial_results_release`, `other_official_conference_document`, `unknown` |
| `language` | `en`, `zh-Hant`, `bilingual` (declared by MOPS column, checked against text) |
| `industry` | project taxonomy mapped to `semiconductor_foundry`, `semiconductor_fabless`, `semiconductor_osat`, `semiconductor_memory`, `semiconductor_discrete_power`, … |
| `text` | page-order text of the original official PDF; bare page-number lines removed; no semantic labels, OCR duplicates or model output |
| `source_page` / `source_pdf` | MOPS t100sb02_1 listing URL / MOPS FileDownLoad reference (served as a form POST) |
| `sha256` | SHA-256 of the downloaded PDF bytes |

FinTrust provenance (period validation status and method, claimed vs detected
period, document-type method/confidence/evidence, quarantine reasons, archive
backend, acquisition time) is kept outside the contract in `provenance` and in
the text-free `*_index.csv`.

## Flags

- `jsd_ready`: valid ticker, validated period, known type, non-empty official
  text, official source URLs, SHA-256, language, text length; not quarantined;
  not a byte-identical duplicate. It is **not** a calibration-suitability claim.
- `comparable_for_pairwise_shift`: same ticker, same `document_type`, same
  language, adjacent fiscal quarters, both `jsd_ready` (metadata only).
- `transcript_calibration_compatible`: both records are `full_earnings_transcript`.
  Presentations and releases are never fed into transcript calibration.

## Fail-closed identity rules (`app/services/conference_document_identity.py`)

- Source-claimed period (MOPS summary 擇要訊息, URL path) must equal the period in
  the document; disagreement → quarantine (`source_period_disagrees_with_document`).
- Identical bytes under different periods → quarantine all copies
  (`sha256_reused_across_periods`); identical bytes under the same period →
  one record, the rest `duplicate_of`.
- Several different documents for the same ticker/period/type/language →
  quarantine (`multiple_documents_same_period`).
- Half-year (`2H24`) or annual decks carry no fiscal quarter and stay `unconfirmed`.

## Benchmarks

- **TSMC (2330).** Teammate corpus: investor.tsmc.com earnings-call
  transcripts, `full_earnings_transcript`, `en_may_include_translation`.
  FinTrust MOPS source: the earnings-conference **presentation deck**
  (`earnings_presentation`, `en` and `zh-Hant`). Same ticker/period semantics,
  SHA and text-length behaviour; different document type by design, so FinTrust
  2330 records are not transcript-calibration compatible and are not relabeled.
- **MediaTek (2454).** The official 2024Q3 transcript URL recorded by the
  teammate (`…/Quarterly Earnings Release-2024Q3/…逐字稿.pdf`) verifies as
  2024Q3 from its cover ("MediaTek 3Q24 Earnings Call") and is typed
  `full_earnings_transcript` from call structure (prepared remarks + question
  turns). Presented under a 2023Q3 claim, the same bytes are quarantined
  (`source_period_disagrees_with_document`); the same SHA under two periods
  quarantines both (`sha256_reused_across_periods`).

## Compatibility evidence (ephemeral, unmodified teammate code)

Loaded with `git show` into a temporary directory by
`tests/test_teammate_jsd_contract.py`; nothing is copied into this repository.

- `analyze_data_shift` accepts adapter pairs. Real MOPS decks, English,
  2025Q2→2025Q3: TSMC JSD 0.232 / cosine 0.676; MediaTek JSD 0.078 / cosine
  0.945; data quality passed. Compatibility evidence only, not a risk verdict.
- `calibrate_tsmc_shift.load` reads an adapter transcript corpus unchanged and
  rejects the presentation corpus with "No full earnings transcripts".
