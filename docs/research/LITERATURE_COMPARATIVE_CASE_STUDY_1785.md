# Comparative case study: 1785 (光洋科) under Beneish (1999) and Dechow et al. (2011)

**Status:** `DRAFT_PENDING_METHOD_OWNER_REVIEW`.

**What this is:** an informational research reproduction.

**What this is not:**
- a fraud finding, a Taiwan-calibrated probability, an investment signal or a risk label;
- an input to the production risk score;
- part of the 2330/2454 universe (1785 remains outside it).

**Every value below is `hindsight=true`** (RETROSPECTIVE_FORENSIC).

**Revision:** corrected by the data-integrity pass on the independent review of f83aa98 (LIT-F01..F04). Two current-filing Dechow scores are withdrawn (FY2015, FY2023) and every other score is unchanged; see §7 and `LITERATURE_INPUT_EVIDENCE_POLICY.md`.

**Evidence:**
- `literature_case_study_1785_results.json` (run ids, input and output digests, every component and missing input);
- coverage matrices (`LITERATURE_INPUT_COVERAGE_MATRIX.md`);
- method lock (`BENEISH_1999_DECHOW_2011_METHOD_LOCK.md`).

## 1. Unit of observation

Every score is identified by:

(ticker, FY, consolidated scope, accounting framework, filing version / side, as-of cutoff, model version)

Both models run on one frozen snapshot per version series:

| Series | Corrected run id | Input digest | Output digest | Supersedes (f83aa98) |
|---|---|---|---|---|
| `latest_available` | `rrun1_1648246ccaca6ea204bcd347fc83d247` | `c37b7d3f3c0db47e68c45713bc8b890b55eb24264998da40cb05b078f5a21d62` | `5da642dc50e9b7d2aae7e41e8de23e3f2ca470b81cb59c3a6a6df956c162f838` | `rrun1_94c4ffe2c129d7a5640239bb5fda2542` |
| `original_only` | `rrun1_fab682f2390383952588b6b0522503ab` | `dddb603607bb998a3bd65330c2ba4b222ad16d7f0e2c1d11a9aec96584409fe6` | `1203b870edb7a35c803320a059d4d3f1279c68b64e8dd338ee4501ccd6bcceee` | `rrun1_8d74e4bba6acee88bc4fd0113bc50900` |

Method version of both corrected runs: `beneish_1999_full8_v1`, `dechow_2011_model1_v1`, `literature_comparison_v1`, `literature_method_registry_v1`, `literature_input_mapping_v2`, `literature_panel_v2`, `literature_line_extractor_v1`, `literature_twgaap_pdf_extractor_v2`, `literature_zero_evidence_policy_v1`, `literature_source_gate_v1`.

## 2. Current-filing series (`latest_available`, TIFRS XBRL)

FY2013–2015 are **post-restatement** versions; FY2016+ are `unknown_revision`.

| FY | Version | Beneish M | Φ(M), original sample | Dechow F | Probability, original model |
|---|---|---:|---:|---:|---:|
| 2011 | restated A06 (statements are images) | null: `source_unavailable` | — | null: `source_unavailable` | — |
| 2012 | restated A06 (statements are images) | null: `source_unavailable` | — | null: `source_unavailable` | — |
| 2013 | restated XBRL | −2.942811 | 0.00163 | 0.718185 | 0.002657 |
| 2014 | restated XBRL | −2.300361 | 0.0107 | 0.984084 | 0.003641 |
| 2015 | restated XBRL | −2.240182 | 0.0125 | null: `cross_filing_overlap_mismatch` (receivables 2014; f83aa98: 0.890320) | — |
| 2016 | unknown_revision | −1.966158 | 0.0246 | 0.606719 | 0.002245 |
| 2017 | unknown_revision | −2.845221 | 0.00222 | 0.838371 | 0.003102 |
| 2018 | unknown_revision | −2.343705 | 0.00955 | null: `issuance_absence_not_evidenced` | — |
| 2019 | unknown_revision | −2.158304 | 0.0155 | 1.193183 | 0.004415 |
| 2020 | unknown_revision | −1.741389 | 0.0408 | 0.867494 | 0.003210 |
| 2021 | unknown_revision | −2.337868 | 0.00970 | 1.019585 | 0.003772 |
| 2022 | unknown_revision | −2.725250 | 0.00321 | 0.933320 | 0.003453 |
| 2023 | unknown_revision | −2.573939 | 0.00503 | null: `cross_filing_overlap_mismatch` (total assets 2022; f83aa98: 0.867745) | — |
| 2024 | unknown_revision | −2.340483 | 0.00963 | 1.224214 | 0.004530 |
| 2025 | unknown_revision | −2.310722 | 0.0104 | 1.266284 | 0.004685 |

**Coverage:**
- 15 years requested;
- Beneish computed in 13 years and Dechow in 10 (f83aa98: 12);
- **10 comparable pairs** (same observation, both computed; f83aa98: 12).

**Descriptive concordance** (side of the original US reference points: Beneish −1.78, Dechow 1.00): 5 of 10 pairs fall on the same side (f83aa98: 7 of 12). This is **not** agreement on fraud and not validation.

**Why FY2015 and FY2023 are withdrawn.** Dechow's ch_cs and ch_roa need t−2 balances, which come from the prior year's filing. Before combining the two filings, the corrected panel checks that both filings report the same value for the overlapping year t−1.

| FY | Overlapping value | Year-t filing | Prior filing | Difference |
|---|---|---:|---:|---:|
| 2015 | Receivables at 2014-12-31 | 1,969,784 thousand (FY2015 restated) | 1,961,884 thousand (FY2014 restated) | +7,900 thousand |
| 2023 | Total assets at 2022-12-31 | 26,569,543 thousand (FY2023) | 26,600,628 thousand (FY2022) | −31,085 thousand |

The year-t filing reclassified or restated its comparative column. Mixing the two bases would measure a change across different presentations, so the component is `not_computable`.

The FY2023 difference is consistent with a retrospective presentation change: assets and liabilities fall by the same amount and equity is unchanged. It is **not** treated as explained without an approved explanation register.

**FY2025:** the 1,721-thousand-TWD source gaps found by reconciliation are **not** classified by either score. Literature scores are refused in CURRENT_EVIDENCE_RECONCILIATION (HTTP 409).

## 3. Original-filing series (`original_only`)

| FY | Framework / version | Beneish M | Φ(M) | Dechow F | Reason if null |
|---|---|---:|---:|---:|---|
| 2011 | TW_GAAP original A02 | **−1.730106** | 0.0418 | null | `missing_t_minus_2`: AR and total assets at FY2009 are needed; no FY2010 filing is archived |
| 2012 | TW_GAAP original A02 | −2.286269 | 0.0111 | 0.892005 | — (preferred stock t / t−1 = `verified_zero` by the equity-section proof; t−2 overlap 2011 verified) |
| 2013–2015 | original AI1 | null | — | null | `source_unavailable`: statement pages are image-only |
| 2016–2025 | — | null | — | null | `no_filing_version_typed_original` |

**Provenance of the original series:** the FY2011–2012 inputs are the originally filed consolidated statements. The 2016 notice "pre" values equal those reports on all 18 overlapping lines. The FY2011 index exceeds the original US-sample benchmark −1.78 (−1.730 > −1.78). This is a **descriptive** observation about one firm-year. It is not evidence that the model "detected" the case:
- one firm-year cannot establish detection;
- the US cutoff is not a Taiwan threshold;
- the FY2011 Dechow score is not computable from the archive.

## 4. What can and cannot be compared

**Same year, original vs restated: not possible in this archive.**
- For FY2011–2012 only the originals are machine-readable; the restated A06 reports are images.
- For FY2013–2015 only the restated XBRL is machine-readable; the original AI1 reports are images.

So no year has both sides computed, and **no "pre vs post" score delta is reported**. No values were grafted from the opposite side or from later filings to manufacture a complete side.

**Mechanism-level evidence remains descriptive and separate.** The restatement bridge (M1) shows, for example, the 2012 inventory difference: the original TW-GAAP value is 8,385,235 thousand TWD and the IFRS comparative in the FY2013 restated XBRL is 7,065,796 thousand TWD.

**STRICT_AS_OF:** at 2016-05-13 and around the 2016-11-13 21:26:22 one-second boundary, both scores are **null** (`insufficient_point_in_time_evidence`; 0 admitted observations). There is no backdated 2015 score.

**No performance claims:** no AUC, precision, sensitivity, specificity, confidence interval or significance. A single known case cannot show that one model outperforms the other.

## 5. Optional future design (not executed): a separate labelled Taiwan sample

| Element | Design |
|---|---|
| Labels | Court judgments, FSC sanctions and TWSE/TPEx restatement notices, classified by paragraph (finding vs allegation vs company disclosure) and archived with SHA-256. Never inferred from scores or from source gaps. |
| Non-cases | Industry- and size-matched firms with no enforcement or restatement within a stated window. |
| Class imbalance | Report base rates. Use weighted or case-control estimation; re-scale probabilities with the Taiwan base rate (as with Dechow's 0.0037) rather than the US rate. |
| Time-based splits | Train on earlier years, test on later years. Add an external validation period. |
| Point-in-time data | Use only original-version filings with verified publication timestamps. This needs the strict-contract extension decided by the method owner. |
| Universe | A separately approved research registry. 1785 is not added to the production semiconductor list, and the 96 companies are not downloaded automatically. |

## 6. Limitations

- **US-sample models:** the coefficients and base rates come from 1980s–2000s US samples (COMPUSTAT; SEC AAERs). The Taiwan mapping of COMPUSTAT items is DRAFT. Key choices: SG&A excludes R&D; IFRS 16 lease debt is excluded; FY2019+ depreciation may include right-of-use assets; the FY2013 t−2 comes from the IFRS transition opening balance.
- **Beneish source:** the coefficients were verified on the author's June-1999 manuscript; the published FAJ text was not accessed.
- **Single-firm case:** a single firm and a hindsight reconstruction. Interpretation belongs to the method owner (Yu-Jing).

## 7. Data-integrity correction: f83aa98 vs corrected results

| Series | Model | FY | f83aa98 | Corrected | Reason |
|---|---|---|---:|---:|---|
| `latest_available` | Dechow | 2015 | 0.890320 | null | `cross_filing_overlap_mismatch` (receivables 2014) |
| `latest_available` | Dechow | 2023 | 0.867745 | null | `cross_filing_overlap_mismatch` (total assets 2022) |
| all others (58 year-model cells) | — | — | — | identical | the 26 remaining computed scores are byte-identical; null cells keep their null status |

**What changed in the inputs, not the scores:**
- **The 8 current-filing issuance entries** that f83aa98 showed as `complete` with no source are now `not_presented`. The Dechow `issue` indicator already relied only on positive evidence, so no score changed.
- **The 4 original-series preferred-stock entries** now carry a verified structural zero. The TW-GAAP equity section is exhaustively enumerated (Σ printed equity lines = 3XXX) and has no 3120 / 特別股 line. FY2012 Dechow 0.892005 therefore stands with documented evidence. If the method owner withdraws this zero-evidence rule, FY2012 Dechow becomes not computable.

**Totals:**

| Year-model cells | f83aa98 | Corrected |
|---|---:|---:|
| Computed | 28 | 26 |
| Not computable | 32 | 34 |

These are counted over both series (60 cells).

