# Literature input coverage matrix: 1785, FY2011–FY2025 (Beneish 1999 / Dechow 2011)

**Mapping status:** `literature_input_mapping_v1`, DRAFT pending the method owner.

**Machine-readable matrices:**
- `literature_coverage_matrix_latest_available.json`
- `literature_coverage_matrix_original_only.json`

Both are under `fintrust_backend/data/literature_models/handoff/evidence/` and inside the review ZIP. Each matrix has 1,395 rows.

**API:** the same matrix is served by `GET /api/v1/research/cases/{ticker}/literature/coverage`.

## 1. Columns (one row per model × variable × input × fiscal year × t-relative period)

| Group | Columns |
|---|---|
| Model and input | `model_id`, `variable`, `formula_component`, `canonical_or_new_metric` (always `new_literature_metric`; none of the 18 canonical facts are reused), `compustat_item` |
| Observation | `ticker`, `fiscal_year`, `relative_period` (t / t−1 / t−2), `statement_scope`, `accounting_framework` |
| Version | `version_policy`, `filing_version_id`, `side` (`original` / `restated` / `unknown_revision`) |
| Value | `period`, `value_twd`, `readiness` (`complete` / `missing`), `missing_reason`, `lines_not_presented`, `warnings` |
| Per-source provenance | `observation_id`, `source_concept`, `raw_sha256`, `locator` (XBRL context and decimals, or PDF page / column / printed line), `published_unit`, `extraction_method`, `artifact_available_at`, `pit_admitted` (always false) |

The matrix also carries `artifact_diagnostics`: one entry per archived artifact with its status, statement pages, identity checks and arithmetic checks.

## 2. Inventory before extraction (approved archive, no new download)

| Source | Years | Version | Machine-readable statements |
|---|---|---|---|
| MOPS XBRL instance (`mops_xbrl_instance`) | FY2013–2018 | FY2013–15 `restated` (MOPS serves only the current version); FY2016–18 `unknown_revision` | yes |
| MOPS inline XBRL | FY2019–2025 | `unknown_revision` | yes |
| TWSE annual report PDF, consolidated, A02 | FY2011–2012 | `original` (TW-GAAP) | **yes**: text layer with account codes |
| TWSE annual report PDF, restated A06 / AI4 | FY2011–2015 | `restated` | no: statement pages are images |
| TWSE annual report PDF, original AI1 | FY2013–2015 | `original` (TIFRS) | no: statement pages are images |
| TWSE annual report PDF, AI1 | FY2016–2018 | `unknown_revision` | no: images |
| TWSE annual report PDF, AI1 | FY2019–2025 | `unknown_revision` | text, but not parsed (the XBRL of the same version is the structured source) |
| MOPS XBRL | FY2011–2012 | — | `filing_not_found`; recorded three times in the approved acquisition log, so not retried |

**Bounded acquisition: none was performed (0 network requests).** All structured statements reachable from official sources are already archived:
- The missing items are either unavailable from MOPS (pre-2013 XBRL; superseded original-version XBRL) or image-only PDFs.
- OCR was not used; it would be heuristic extraction of official records.
- Re-downloading archived bytes was unnecessary because every artifact's SHA-256 was re-verified.

## 3. Extraction result (`literature_line_extractor_v1`)

**4,393 line-level observations** came from 15 artifacts (13 XBRL documents and 2 TW-GAAP PDFs). The observation digest is `1dc6ef8c…748d93`. A second run created 0 new records.

| Status | Artifacts |
|---|---:|
| `extracted` | 15 |
| `statement_pages_not_machine_readable` | 12 |
| `tifrs_pdf_text_not_parsed_xbrl_is_structured_source` | 6 |

**The FY2011 and FY2012 original PDFs** (pages 5, 6 and 8) passed every check:
- unit 新台幣仟元, verified;
- printed ROC year, verified;
- consolidated title, verified;
- total assets = total liabilities + equity, for both columns;
- net sales − operating costs = gross profit, for both columns.

**Cross-check of the 2016 notice "pre" values** against the original annual reports (FY2011–2012, consolidated, 18 overlapping lines): **18 / 18 equal** (`notice_pre_vs_original_report_crosscheck.json`). These "pre" values are therefore the originally filed figures for those lines. This was established for these 18 lines only, not as a general rule.

## 4. Readiness by model, fiscal year and version series

Counts are input cells: Beneish has 47 per year and Dechow has 46 per year.

### `latest_available` (latest version type per year: restated > unknown_revision > original; no fallback)

| FY | Beneish inputs | Dechow inputs | Root cause when missing |
|---|---|---|---|
| 2011–2012 | 0 / 47 | 0 / 46 | The latest version (restated A06) has image-only statement pages: `source_unavailable` |
| 2013 | 47 / 47 | 46 / 46 | t−2 = IFRS transition opening balance 2012-01-01 (flagged) |
| 2014–2025 | 47 / 47 each | 46 / 46 each | — |

**FY2018 Dechow:** all 46 inputs are present, but no **positive** issuance line exists for FY2018 (share proceeds 0, no long-term-debt proceeds line). `issue` is therefore UNKNOWN and the score is not computable.

### `original_only` (only versions typed `original`)

| FY | Beneish | Dechow | Root cause |
|---|---|---|---|
| 2011 | 47 / 47 | 44 / 46 | t−2 (FY2009) is missing: there is no FY2010 filing in the archive (`missing_t_minus_2`) |
| 2012 | 47 / 47 | 46 / 46 | — |
| 2013–2015 | 0 | 0 | The original TIFRS reports (AI1) have image-only statement pages |
| 2016–2025 | 0 | 0 | `no_filing_version_typed_original` (versions are `unknown_revision`) |

### Totals

| Series | Complete cells | Missing cells | Missing by cause |
|---|---:|---:|---|
| `latest_available` | 1,209 | 186 | all `source_unavailable` |
| `original_only` | 184 | 1,211 | 930 `no_filing_version_typed_original`, 279 `source_unavailable`, 2 `missing_t_minus_2` |

**Warnings:**
- `no_listed_line_presented_in_complete_statement` (8 latest / 4 original): for example, no preferred-share or short-term-investment line is presented. The value is 0 by statement-line absence, recorded per value.
- `ifrs_transition_opening_balance_used_as_prior_year_end`: 2 cells (FY2013 t−2).

### Strict mode

**STRICT_AS_OF admits 0 literature observations** at 2016-05-13 00:00, 2016-11-13 21:26:22 and 2016-11-13 21:26:23 (+08:00). The current strict contract accepts only observation-level timestamps of canonical facts, so `pit_admitted` is false for every literature observation.

## 5. Distinctions kept (never substituted)

- **Revenue vs cash sales:** cash sales are derived as Sales − ΔAR.
- **Receivables:** notes, accounts, related-party and other receivables, never "trade only" mixed with "total".
- **PPE vs CAPEX:** PPE comes from the balance sheet; CAPEX is never used.
- **Depreciation vs D&A:** DEPI uses depreciation only; TATA uses depreciation plus amortization.
- **SG&A vs R&D:** R&D is excluded from SG&A.
- **Earnings vs CFO:** RSST accruals are never NI − CFO.
- **Scope, framework and version:** consolidated vs individual, TIFRS vs TW_GAAP, and original vs restated are never mixed inside one model-year.
- **Units:** thousand-TWD values are converted exactly; deduction-printed costs are sign-normalised and checked by the gross-profit identity.
