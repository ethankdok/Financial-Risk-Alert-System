# Integrity Workbench Phase 1 — Literature → Feature Traceability Matrix

- Version: `integrity_literature_matrix_v1` (2026-10-12)
- Method approval for every row: **`DRAFT_PENDING_METHOD_OWNER_REVIEW`**. The method owner (Yu-Jing) has not
  reviewed this matrix. Literature research ownership stays with her; this file only records how the code uses it.
- Links are publisher DOI URLs. No full-text PDF is redistributed. No page numbers are cited unless they come
  from the earlier source-verified method lock.
- **Primary-text verification.** Only Beneish (1999) and Dechow et al. (2011) were checked against primary text,
  in `docs/research/BENEISH_1999_DECHOW_2011_METHOD_LOCK.md`:
  - Beneish (1999): `source_verified_author_manuscript`.
  - Dechow et al. (2011): `source_verified_published`.

  The other five papers were **not re-verified against their primary text in this project**. Their rows give only
  a general, abstract-level description, marked "not primary-verified". The descriptions must be checked before
  anything is written about those papers' samples or results.

## Matrix

| Paper | DOI | Original sample / outcome / method | Implementation (file / tests) | Supported output | Limitations | Tier |
|---|---|---|---|---|---|---|
| Beneish, M. D. (1999). *The Detection of Earnings Manipulation*. FAJ 55(5). | [10.2469/faj.v55.n5.2296](https://doi.org/10.2469/faj.v55.n5.2296) | **Verified (author manuscript):** 8-variable unweighted probit M-Score, 50 manipulators vs 1,708 controls, 1982–1988 (method lock §2). | `financial_research/beneish_1999.py` (unchanged), called by `integrity/adapters.py::LiteratureAdapter`. Tests: `test_integrity_phase1_composer.py::LiteratureTests`, plus the existing `test_literature_*` suites. | Production companies: `not_computable`, `raw_score=null`, full missing-input list, and pipeline-fact availability marked as not admitted. | No frozen, source-gated inputs for 2330/2454. The COMPUSTAT→Taiwan mapping is DRAFT. No Taiwan calibration. 1785 retrospective scores are never substituted. | implemented (engine) / **readiness_only** (production) |
| Dechow, Ge, Larson & Sloan (2011). *Predicting Material Accounting Misstatements*. CAR 28(1). | [10.1111/j.1911-3846.2010.01041.x](https://doi.org/10.1111/j.1911-3846.2010.01041.x) | **Verified (published):** Table 7 Model 1 logistic F-Score; scaled by the unconditional probability (method lock §3). | `financial_research/dechow_2011.py` (unchanged), called the same way. | Same as Beneish. | Not Piotroski's F-score. No verified Taiwan cutoff. Issuance absence is never assumed to be 0. | implemented (engine) / **readiness_only** (production) |
| Brazel, Jones & Zimbelman (2009). *Using Nonfinancial Measures to Assess Fraud Risk*. JAR 47(5). | [10.1111/j.1475-679X.2009.00349.x](https://doi.org/10.1111/j.1475-679X.2009.00349.x) | *Not primary-verified:* compares growth in financial performance with growth in related non-financial measures, such as capacity or employees. | `integrity/financial_checks.py::check_revenue_nfm` (F4). Tests: `test_integrity_phase1_checks.py::RevenueNfmTests`. | `unavailable` / `no_verified_nonfinancial_measure_series` for every real company. With synthetic verified inputs, the `growth_difference` path is tested and has no threshold. | No verified non-financial-measure data exists. F1/F2 are **not** a Brazel replication. No threshold and no score. | **readiness_only** |
| Larcker & Zakolyukina (2012). *Detecting Deceptive Discussions in Conference Calls*. JAR 50(2). | [10.1111/j.1475-679X.2012.00450.x](https://doi.org/10.1111/j.1475-679X.2012.00450.x) | *Not primary-verified:* linguistic features of earnings-call Q&A, labelled with later restatements. | None. Phase 1 only shows document and JSD availability, and keeps document type and language provenance (`JsdAdapter`). | — | MOPS presentation PDFs are not English call transcripts. JSD is not that paper's classifier. | **future** |
| Loughran & McDonald (2011). *When Is a Liability Not a Liability?* JF 66(1). | [10.1111/j.1540-6261.2010.01625.x](https://doi.org/10.1111/j.1540-6261.2010.01625.x) | *Not primary-verified:* finance-specific word lists for 10-K tone, in place of general dictionaries. | None. Gives the rationale for keeping the team's existing domain tokenizer: Ethan's JSD is reused unchanged. | — | The English lexicon is not imported into Chinese text. No claim that JSD predicts fraud. | design inspiration (**future**) |
| Bao, Ke, Li, Yu & Zhang (2020). *Detecting Accounting Fraud in Publicly Traded U.S. Firms Using a Machine Learning Approach*. JAR 58(1). (A 2022 erratum exists.) | [10.1111/1475-679X.12292](https://doi.org/10.1111/1475-679X.12292) | *Not primary-verified:* ensemble learning on raw accounting data, with out-of-sample ranking evaluation. | None. It is the Phase 2+ evaluation design: point-in-time labels, controls, PR-AUC and Precision@K. | — | No trained classifier and no point-in-time labels. The erratum must be read before any replication. | **future** |
| Barrot & Sauvagnat (2016). *Input Specificity and the Propagation of Idiosyncratic Shocks in Production Networks*. QJE 131(3). | [10.1093/qje/qjw018](https://doi.org/10.1093/qje/qjw018) | *Not primary-verified:* shocks to specific suppliers, identified through natural disasters, propagate to their customers. | `composer.next_checks` text only (`B2B_NO_NETWORK_INFERENCE`). | A B2B checklist that asks the user to confirm relationships. | No inferred supplier network and no probability of supply disruption. | design inspiration |

## Shared inputs: findings are not independent corroboration

| Workbench check | Shares figures with | Evidence family |
|---|---|---|
| F1 Revenue / AR alignment | Beneish DSRI and Dechow `ch_rec`. F1's gap (AR growth − revenue growth) is **related to but numerically different from** DSRI − 1: AR 200→250 with sales 1,000→1,100 gives F1 = 0.15 but DSRI − 1 = 0.136364. Only the auxiliary field `receivables_to_revenue_relative_change` equals DSRI − 1 (Phase 1.1, review CR-06) | `receivables`, `revenue` |
| F2 NI / CFO alignment | Beneish TATA; Dechow `rsst_acc` (accrual measures) | `net_income`, `operating_cash_flow` |
| F3 issuer claim vs filing | The same issuer reports both the presentation and the filing | `issuer_presentation` + the metric's family |

`composer.investigation_priority` counts each evidence family once and cites every finding or model component that
uses it. `independent_third_party_corroboration_count` is 0 for all real data.
