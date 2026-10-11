# Method lock — Beneish (1999) M-Score and Dechow et al. (2011) Model 1 F-Score

**Status:** formulas, coefficients, transformations and scaling are locked to the paper texts below.
Machine-readable lock: `fintrust_backend/app/services/financial_research/literature_method_registry.py` (`literature_method_registry_v1`).

**Interpretation status:** `DRAFT_PENDING_METHOD_OWNER_REVIEW` (Yu-Jing). The arithmetic is a faithful reproduction. Approval is still needed for the Taiwan input mapping, local applicability and any interpretation.

Every value below was read from the paper text itself. None was taken from a secondary website.

## 1. Source texts used for verification

The paper copies are kept only in the local scratchpad. They are **not** committed, **not** in the review ZIP and **not** redistributed.

### Beneish (1999)

- **Citation:** Beneish, M. D. (1999). *The Detection of Earnings Manipulation*. Financial Analysts Journal 55(5), 24–36.
- **DOI:** 10.2469/faj.v55.n5.2296
- **Text verified:**
  - Author's manuscript dated "June 1999", 27 pages, 153,381 bytes.
  - SHA-256 `78b2f0143770c9c06871ba8e8d8fb764fc95a4dd379ae37e1c301d16c42faffe`.
  - Retrieved 2026-10-12 from `https://www.calctopia.com/papers/beneish1999.pdf`, a third-party host of the working paper.
- **Status:** `source_verified_author_manuscript`.
- **Published version:** the CFA Institute text is members-only and was not accessed. FAJ page numbers are therefore **not mapped** (`published_version_crosscheck = not_performed`).

### Dechow, Ge, Larson & Sloan (2011)

- **Citation:** Dechow, Ge, Larson & Sloan (2011). *Predicting Material Accounting Misstatements*. Contemporary Accounting Research 28(1), 17–82.
- **DOI:** 10.1111/j.1911-3846.2010.01041.x
- **Text verified:**
  - Published journal version, 67 PDF pages, 752,761 bytes.
  - SHA-256 `e1a6e49ce1e10ad893eefe7fd5264c95fe841bd55f1ee68e82998445a4dc15dc`.
  - Hosted by the Center for Audit Quality: `https://www.thecaq.org/wp-content/uploads/2018/03/Dechow-et-al-2011-Contemporary_Accounting_Research.pdf`.
  - CAAA copyright notice: no redistribution.
  - Page mapping: journal page = PDF page + 15.
- **Status:** `source_verified_published`.
- **Not used for verification:** the OSU teaching note and the SSRN manuscript (cited only).

## 2. Beneish (1999): eight-variable unweighted probit

**Variant:** Table 3, Panel A, row "Unweighted Probit" (manuscript p. 24). Estimation sample: 50 manipulators and 1,708 controls, 1982–1988.

This is **not**:
- the WESML row (−4.954, .789, .459, .306, .701, .033, −.006, 3.937, −.264);
- a five-variable variant;
- Beneish, Lee & Nichols (2013).

**Definitions** come from Table 2 (manuscript p. 23, COMPUSTAT item numbers in brackets). Year *t* is the year being evaluated and *t−1* is the year before.

| Variable | Definition (Table 2) | Coefficient (Table 3) |
|---|---|---:|
| Constant | — | −4.840 |
| DSRI | (Receivables[2]ₜ/Sales[12]ₜ) / (Receivablesₜ₋₁/Salesₜ₋₁) | 0.920 |
| GMI | [(Salesₜ₋₁−COGS[41]ₜ₋₁)/Salesₜ₋₁] / [(Salesₜ−COGSₜ)/Salesₜ] | 0.528 |
| AQI | [1−(CA[4]ₜ+PPE[8]ₜ)/TA[6]ₜ] / [1−(CAₜ₋₁+PPEₜ₋₁)/TAₜ₋₁] (no "securities" term in 1999) | 0.404 |
| SGI | Salesₜ/Salesₜ₋₁ | 0.892 |
| DEPI | [Depₜ₋₁/(Depₜ₋₁+PPEₜ₋₁)] / [Depₜ/(Depₜ+PPEₜ)], Dep = item 14 less 65 | 0.115 |
| SGAI | (SGA[189]ₜ/Salesₜ) / (SGAₜ₋₁/Salesₜ₋₁) | −0.172 |
| LVGI | [(LTD[9]ₜ+CL[5]ₜ)/TAₜ] / [(LTDₜ₋₁+CLₜ₋₁)/TAₜ₋₁] | −0.327 |
| TATA | [(ΔCA[4]−ΔCash[1]) − (ΔCL[5]−ΔCurrent maturities of LTD[44]−ΔIncome tax payable[71]) − D&A[14]] / TA[6]ₜ | 4.679 |

**Score and transformation:**
- Score: M = constant + Σ coefficient × variable (the probit index).
- Probability: Φ(M) is shown only as the probability of the original unweighted, oversampled estimation sample.

**Original-sample benchmark** (text p. 17, Table 5): at error-cost ratios of 20:1 or 30:1, classify when the probability exceeds .0376, which is a score above **−1.78**. This is reported **only as an original US-sample reference point**. It is not a Taiwan cutoff and never becomes a label.

**TATA** uses the paper's working-capital definition. It is **not** income minus CFO, and **not** the existing `earnings_cashflow_gap_proxy`.

**Sample treatments the paper describes but this implementation does not apply** (p. 12):
- 1%/99% winsorization (a sample-level step);
- setting AQI to 1 when its t−1 denominator is zero;
- setting DEPI and SGAI to 1 when the COMPUSTAT item is missing.

Such cases are reported as `not_computable` with a reason instead.

## 3. Dechow et al. (2011): Table 7 Model 1 (financial-statement variables only)

**Sources in the paper:**
- Coefficients: Table 7 Panel A, Model 1 column (CAR pp. 55–56).
- Definitions: Table 3 (CAR pp. 35–38).
- Probability and scaling: CAR pp. 60–61.

This is **not** Model 2 or Model 3, **not** a recalibrated version, and **not** Piotroski's F-score.

| Variable | Definition (Table 3; COMPUSTAT DATA items) | Periods | Coefficient |
|---|---|---|---:|
| Intercept | — | — | −7.893 |
| rsst_acc | (ΔWC + ΔNCO + ΔFIN) / average total assets (see the formulas below) | t, t−1 | 0.790 |
| ch_rec | ΔAccounts receivable[2] / average total assets | t, t−1 | 2.518 |
| ch_inv | ΔInventory[3] / average total assets | t, t−1 | 1.191 |
| soft_assets | (TA[6] − PP&E[8] − Cash and cash equivalent[1]) / TA | t | 1.979 |
| ch_cs | % change in cash sales, where cash sales = Sales[12] − ΔAR[2] | t, t−1, **t−2** | 0.171 |
| ch_roa | Earningsₜ[18]/avg TAₜ − Earningsₜ₋₁/avg TAₜ₋₁ | t, t−1, **t−2** | −0.932 |
| issue | 1 if securities were issued in year t (DATA 108 > 0 or DATA 111 > 0) | t | 1.029 |

RSST components:
- WC = (CA[4] − CHE[1]) − (CL[5] − DLC[34])
- NCO = (TA[6] − CA − IVAO[32]) − (LT[181] − CL − DLTT[9])
- FIN = (IVST[193] + IVAO[32]) − (DLTT + DLC + PSTK[130])

**Transformation:**
- Probability = e^PV/(1+e^PV). It is evaluated with a numerically stable branch in 50-digit Decimal arithmetic.
- **F-Score** = probability ÷ **0.0037**, the unconditional rate 494/(132,967+494) (CAR p. 61). This base rate is specific to the US sample.

**Reference example** (the paper's own worked example, Enron 2000, CAR p. 61): predicted value −4.575, probability 0.01020, **F-Score 2.76**. The engine reproduces −4.575458, 0.010197 and 2.755822; the test `test_dechow_reproduces_the_published_enron_example` checks this.

**Original-sample reference points:** F-Score = 1.00 is the unconditional expectation; the Model 1 quintile-5 minimum is 1.397. Neither is a Taiwan threshold.

**Issuance rule:** `issue` = 1 only with a positive issuance line for year *t*. If there is no such evidence the value is **UNKNOWN, never 0**, and the score is not computable.

**Winsorization** (sample-level) is not applied.

## 4. Fail-closed gates (implemented and tested)

- **Verification level:** a published score is computed only if every coefficient, the intercept, the transformation and the scaling are at `source_verified_published` or `source_verified_author_manuscript`, and every value is an exact decimal. If any element is `secondary_only` or `unverified`, the status is `model_formula_unverified` and the score is `null`.
- **Coefficient set:** the set must match the model's variables exactly. Reusing the Beneish table for Dechow, or supplying a truncated set, is refused.
- **Partial results:** missing components produce a component panel with status `not_computable`. A partial sum is never reported.

## 5. Unresolved items (for the method owner and the reviewer)

1. **Beneish source:** enabling the Beneish score on the author's manuscript (published FAJ text not accessed) is a reviewer decision. Setting the registry level to `unverified` disables it.
2. **Taiwan mapping of COMPUSTAT items** (`literature_input_mapping_v1`) is DRAFT. The main choices:
   - receivables include other receivables;
   - SG&A excludes R&D (COMPUSTAT XSGA usually includes it);
   - DLTT excludes IFRS 16 lease liabilities;
   - CHE/IVST exclude restricted deposits and hedging derivatives;
   - IVAO excludes equity-method investments;
   - IB is consolidated profit from continuing operations.
3. **IFRS 16 (FY2019+):** depreciation may include right-of-use assets. The result is flagged, not adjusted.
4. **FY2013 t−2:** the IFRS transition opening balance at 2012-01-01 is used as the 2011 year-end balance (flagged).
5. **Statement-line absence** inside a parsed, complete statement is treated as "line not presented" (listed per value). It is not a filled zero.
