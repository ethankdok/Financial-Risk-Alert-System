# Comparative case study: 1785 (光洋科) under Beneish (1999) and Dechow et al. (2011)

**Status:** `DRAFT_PENDING_METHOD_OWNER_REVIEW`.

**What this is:** an informational research reproduction.

**What this is not:**
- a fraud finding, a Taiwan-calibrated probability, an investment signal or a risk label;
- an input to the production risk score;
- part of the 2330/2454 universe (1785 remains outside it).

**Every value below is `hindsight=true`** (RETROSPECTIVE_FORENSIC).

**Evidence:**
- `literature_case_study_1785_results.json` (run ids, input and output digests, every component and missing input);
- coverage matrices (`LITERATURE_INPUT_COVERAGE_MATRIX.md`);
- method lock (`BENEISH_1999_DECHOW_2011_METHOD_LOCK.md`).

## 1. Unit of observation

Every score is identified by:

(ticker, FY, consolidated scope, accounting framework, filing version / side, as-of cutoff, model version)

Both models run on one frozen snapshot per version series:

| Series | Run id (method `literature_comparison_v1`) | Input digest | Output digest |
|---|---|---|---|
| `latest_available` | `rrun1_94c4ffe2c129d7a5640239bb5fda2542` | `840ebca2f9d70123c557fe249088e38b0db7c937f037072a9b17b453ee317c61` | `53eb599512a94937bc00bf5ebbb58c48cfe50d2e5c315702c8c69d6096d58300` |
| `original_only` | `rrun1_8d74e4bba6acee88bc4fd0113bc50900` | `b874a78ba9e91e710b63e1fc4cec4315890dc2e9dfaa1656d23e3a6fed74f3d0` | `32bd48c9a6f09fe52179e2b7b89e728e64f7acb58862ba6add5dccfaec322c11` |

## 2. Current-filing series (`latest_available`, TIFRS XBRL)

FY2013–2015 are **post-restatement** versions; FY2016+ are `unknown_revision`.

| FY | Version | Beneish M | Φ(M), original sample | Dechow F | Probability, original model |
|---|---|---:|---:|---:|---:|
| 2011 | restated A06 (statements are images) | null: `source_unavailable` | — | null: `source_unavailable` | — |
| 2012 | restated A06 (statements are images) | null: `source_unavailable` | — | null: `source_unavailable` | — |
| 2013 | restated XBRL | −2.942811 | 0.00163 | 0.718185 | 0.002657 |
| 2014 | restated XBRL | −2.300361 | 0.0107 | 0.984084 | 0.003641 |
| 2015 | restated XBRL | −2.240182 | 0.0125 | 0.890320 | 0.003294 |
| 2016 | unknown_revision | −1.966158 | 0.0246 | 0.606719 | 0.002245 |
| 2017 | unknown_revision | −2.845221 | 0.00222 | 0.838371 | 0.003102 |
| 2018 | unknown_revision | −2.343705 | 0.00955 | null: `issuance_absence_not_evidenced` | — |
| 2019 | unknown_revision | −2.158304 | 0.0155 | 1.193183 | 0.004415 |
| 2020 | unknown_revision | −1.741389 | 0.0408 | 0.867494 | 0.003210 |
| 2021 | unknown_revision | −2.337868 | 0.00970 | 1.019585 | 0.003772 |
| 2022 | unknown_revision | −2.725250 | 0.00321 | 0.933320 | 0.003453 |
| 2023 | unknown_revision | −2.573939 | 0.00503 | 0.867745 | 0.003211 |
| 2024 | unknown_revision | −2.340483 | 0.00963 | 1.224214 | 0.004530 |
| 2025 | unknown_revision | −2.310722 | 0.0104 | 1.266284 | 0.004685 |

**Coverage:**
- 15 years requested;
- Beneish computed in 13 years and Dechow in 12;
- **12 comparable pairs** (same observation, both computed).

**Descriptive concordance** (side of the original US reference points: Beneish −1.78, Dechow 1.00): 7 of 12 pairs fall on the same side. This is **not** agreement on fraud and not validation.

**FY2025:** the 1,721-thousand-TWD source gaps found by reconciliation are **not** classified by either score. Literature scores are refused in CURRENT_EVIDENCE_RECONCILIATION (HTTP 409).

## 3. Original-filing series (`original_only`)

| FY | Framework / version | Beneish M | Φ(M) | Dechow F | Reason if null |
|---|---|---:|---:|---:|---|
| 2011 | TW_GAAP original A02 | **−1.730106** | 0.0418 | null | `missing_t_minus_2`: AR and total assets at FY2009 are needed; no FY2010 filing is archived |
| 2012 | TW_GAAP original A02 | −2.286269 | 0.0111 | 0.892005 | — |
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
