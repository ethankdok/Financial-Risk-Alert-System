# Literature input coverage matrix: 1785, FY2011–FY2025 (Beneish 1999 / Dechow 2011)

**Mapping status:** `literature_input_mapping_v2` with `literature_panel_v2`, `literature_zero_evidence_policy_v1` and `literature_source_gate_v1` (data-integrity correction of f83aa98; see `LITERATURE_INPUT_EVIDENCE_POLICY.md`). DRAFT pending the method owner. Matrix version `literature_input_coverage_v2`.

**Machine-readable matrices:**
- `literature_coverage_matrix_latest_available.json`
- `literature_coverage_matrix_original_only.json`

Both are under `fintrust_backend/data/literature_models/handoff_fix_final/evidence/` and inside the correction review ZIP. Each matrix has 1,395 rows. The f83aa98 matrices stay unchanged in `handoff/evidence/` and in the f83aa98 review ZIP.

**API:** the same matrix is served by `GET /api/v1/research/cases/{ticker}/literature/coverage`.

## 1. Columns (one row per model × variable × input × fiscal year × t-relative period)

| Group | Columns |
|---|---|
| Model and input | `model_id`, `variable`, `formula_component`, `canonical_or_new_metric` (always `new_literature_metric`; none of the 18 canonical facts are reused), `compustat_item` |
| Observation | `ticker`, `fiscal_year`, `relative_period` (t / t−1 / t−2), `statement_scope`, `accounting_framework` |
| Version | `version_policy`, `filing_version_id`, `side` (`original` / `restated` / `unknown_revision`) |
| Value | `period`, `value_twd`, `readiness` (`complete` / `missing`), `input_status` (typed status), `evidence_type`, `missing_reason`, `lines_not_presented`, `warnings` |
| Evidence | `zero_evidence` (rule, version, operands, fingerprint), `cross_filing_overlap` (t−2 overlap check), `alias_candidates` |
| Per-source provenance | `observation_id`, `source_concept`, `raw_sha256`, `locator` (XBRL context and decimals, or PDF page / column / printed line), `published_unit`, `extraction_method`, `artifact_available_at`, `pit_admitted` (always false) |

The matrix also carries:
- `artifact_diagnostics`: one entry per archived artifact (current extractor versions only) with its status, statement pages, page identity checks and, for TW-GAAP PDFs, the 20 statement identities with operands and differences;
- `input_status_counts`;
- `zero_evidence_records`.

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

## 3. Extraction result (XBRL `literature_line_extractor_v1` + TW-GAAP PDF `literature_twgaap_pdf_extractor_v2`)

**4,643 current line-level observations** came from 15 artifacts:
- 4,247 XBRL observations from 13 documents, unchanged since f83aa98;
- 396 TW-GAAP PDF observations from 2 reports. Version 2 keeps every balance-sheet account-code row, so the sections can be enumerated.

The observation digest is `a2dce891…e77793`.

**Sidecar after the correction:** 4,789 records, of which:
- the 4,393 f83aa98 records are preserved unchanged (append-only; the 146 v1 PDF records are no longer read);
- 396 v2 PDF records were appended.

| Status | Artifacts |
|---|---:|
| `extracted` | 15 |
| `statement_pages_not_machine_readable` | 12 |
| `tifrs_pdf_text_not_parsed_xbrl_is_structured_source` | 6 |

**The FY2011 and FY2012 original PDFs** (pages 5, 6 and 8) passed every check:
- unit 新台幣仟元, verified;
- printed ROC year, verified;
- consolidated title, verified;
- all 10 statement identities for both columns, **20 / 20 `verified`** per report.

The identities cover the balance, the asset sections and the exhaustive enumerations of current assets, investments, current liabilities, long-term liabilities and equity, plus gross profit, operating expenses and net income.

**Cross-check of the 2016 notice "pre" values** against the original annual reports (FY2011–2012, consolidated, 18 overlapping lines): **18 / 18 equal** (`notice_pre_vs_original_report_crosscheck.json`). These "pre" values are therefore the originally filed figures for those lines. This was established for these 18 lines only, not as a general rule.

## 4. Readiness by model, fiscal year and version series

Counts are input cells: Beneish has 47 per year and Dechow has 46 per year.

### `latest_available` (latest version type per year: restated > unknown_revision > original; no fallback)

| FY | Beneish inputs | Dechow inputs | Root cause when missing |
|---|---|---|---|
| 2011–2012 | 0 / 47 | 0 / 46 | The latest version (restated A06) has image-only statement pages: `source_unavailable` |
| 2013 | 47 / 47 | 45 / 46 | `stock_issued` not presented; t−2 = IFRS transition opening balance 2012-01-01 (flagged, balance identity verified) |
| 2014, 2016, 2024, 2025 | 47 / 47 | 45 / 46 | `stock_issued` not presented (issue = 1 from long-term debt proceeds) |
| 2015 | 47 / 47 | 44 / 46 | `stock_issued` not presented; receivables t−2 `cross_filing_overlap_mismatch` (2014: FY2015 filing 1,969,784 vs FY2014 filing 1,961,884 thousand) |
| 2017, 2019–2022 | 47 / 47 | 46 / 46 | — |
| 2018 | 47 / 47 | 45 / 46 | `long_term_debt_issued` not presented |
| 2023 | 47 / 47 | 44 / 46 | `stock_issued` not presented; total assets t−2 `cross_filing_overlap_mismatch` (2022: FY2023 filing 26,569,543 vs FY2022 filing 26,600,628 thousand) |

**FY2018 Dechow:** no **positive** issuance line exists for FY2018. Share proceeds are an explicit 0, and the long-term-debt proceeds line is not presented. `issue` is therefore UNKNOWN and the score is not computable.

### `original_only` (only versions typed `original`)

| FY | Beneish | Dechow | Root cause |
|---|---|---|---|
| 2011 | 47 / 47 | 44 / 46 | t−2 (FY2009) is missing: there is no FY2010 filing in the archive (`missing_t_minus_2`); preferred stock t / t−1 = `verified_zero` |
| 2012 | 47 / 47 | 46 / 46 | preferred stock t / t−1 = `verified_zero` (equity section 9,788,003 / 9,345,296 thousand exhaustively enumerated, no 3120 line); t−2 overlap 2011 verified |
| 2013–2015 | 0 | 0 | The original TIFRS reports (AI1) have image-only statement pages |
| 2016–2025 | 0 | 0 | `no_filing_version_typed_original` (versions are `unknown_revision`) |

### Totals

| Series | Complete cells | Missing cells | Missing by cause |
|---|---:|---:|---|
| `latest_available` | 1,199 (f83aa98: 1,209) | 196 | 186 `source_unavailable`, 8 `not_presented`, 2 `cross_filing_overlap_mismatch` |
| `original_only` | 184 | 1,211 | 930 `no_filing_version_typed_original`, 279 `source_unavailable`, 2 `missing_t_minus_2` |

**Evidence types of the complete cells:**

| Series | `explicit_line` | `presented_lines_sum` | `derived_difference` | `explicit_zero` | `verified_zero` |
|---|---:|---:|---:|---:|---:|
| `latest_available` | 818 | 348 | 26 | 7 | 0 |
| `original_only` | 125 | 54 | 0 | 1 | 4 |

**The 12 reviewed entries** (f83aa98: `complete` with no source) are now:

| Series | Entries | Corrected status |
|---|---|---|
| `latest_available` | 8 entries: `stock_issued` in FY2013, 2014, 2015, 2016, 2023, 2024 and 2025; `long_term_debt_issued` in FY2018 | all `not_presented` |
| `original_only` | 4 entries: `preferred_stock` at FY2011 t and t−1, and at FY2012 t and t−1 | all `verified_zero` |

**Warnings:**
- `ifrs_transition_opening_balance_used_as_prior_year_end` / `framework_transition`: 2 cells (FY2013 t−2).
- `cross_filing_overlap_verified`: 22 latest and 2 original cells.
- `arithmetic_identity_not_available_for_line`: 14 original-series cells (cash-flow labels).

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
