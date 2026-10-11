# Phase 3 method specification — DRAFT, pending method-owner approval

**Status: `DRAFT_PENDING_METHOD_OWNER_REVIEW`.** Method ownership: 雨靚 (Yu-Jing) for accounting-case methods, feature
interpretation and literature applicability; Ethan for JSD/drift. The arithmetic below is implemented and tested
(exact Decimal, reproducible runs); the **research interpretation and parameter choices are not approved** and must not be
presented as calibrated research results. Code: `fintrust_backend/app/services/financial_research/`.

## M1 — Restatement bridge (RQ-A, retrospective, hindsight=true)

- Input: the 158 official comparison rows of the MOPS notices `mops:20161113:212531:2` (individual) and
  `mops:20161113:212622:3` (consolidated), FY2011–FY2015, verified baseline (byte-identical to Phase 1C).
- Per row: `pre_twd = pre × 1000 × sign_factor`, `post_twd` likewise, `delta = post − pre`; the notice text is kept as
  published; the notice's own difference column is checked (`difference_check`). FY2011–2012 TW-GAAP, FY2013+ TIFRS
  (`regime_check`; no cross-regime comparison).
- `delta_pct = delta / |pre|` only if `denominator_status = stable`: not zero, no sign reversal, and
  `|pre| ≥ 1 % × |pre revenue|` of the same notice/scope/year. **The 1 % near-zero threshold is a DRAFT parameter.**
- Margins (gross, COGS/sales, operating, net) only when all same-side components exist in the same notice/scope/year;
  identity `revenue − COGS = gross profit` checked on both sides. Inventory is not in the notices → `not_computable`.
- Pre side semantics: "as disclosed in the 2016 notice", not proven to be the first-published figure.

**Computed consolidated results (descriptive, not predictive; TWD):**

| FY | Regime | ΔCOGS | ΔGross profit | ΔNet income | ΔEquity | ΔCurrent liabilities | Gross margin pre → post |
|---|---|---:|---:|---:|---:|---:|---|
| 2011 | TW-GAAP | +1,670,662,000 | −1,670,662,000 | −2,228,481,000 (sign reversal) | −2,229,816,000 | +1,667,747,000 | 3.5619 % → 1.2283 % |
| 2012 | TW-GAAP | +1,007,152,000 | −1,007,152,000 | −246,528,000 | −2,476,018,000 | +1,374,953,000 | 2.1109 % → 0.7495 % |
| 2013 | TIFRS | +967,367,000 | −967,367,000 | −341,424,000 | −2,769,859,000 | +2,793,425,000 | 5.7970 % → 2.9718 % |
| 2014 | TIFRS | +662,419,000 | −662,419,000 | −406,151,000 (near-zero base) | −3,176,057,000 | +3,581,395,000 | 3.0496 % → 1.8069 % |
| 2015 | TIFRS | −95,361,000 | +99,061,000 | +3,911,000 | −3,171,914,000 | +4,807,581,000 | 0.4067 % → 0.5680 % |

Hypothesis linkage is **direction-only and descriptive** (H1 17/20, H2 7/10, H4 8/10 observations in the expected
direction; H3 has no directional expectation). The legal classification of H1–H4 (court finding vs litigation allegation vs
company disclosure) is **unverified**; the cited judgment is not archived in this repository.

## M2 — Explainable single features (RQ-B)

Registry `feature_registry_v1`: gross margin, COGS/sales, operating margin, net margin, inventory/assets, inventory
turnover (needs comparable t−1), Δinventory/average assets and Δreceivables/average assets (Dechow et al. 2011 component
definitions), receivables/sales, `earnings_cashflow_gap_proxy` (**explicitly a proxy**, not RSST accruals and not Beneish
TATA), liabilities/assets, and `source_value_gap` (reconciliation only). States `computed` / `not_computable` /
`not_applicable` with a fixed missing-reason catalog; a reported 0 is a real value, missing is never 0.

**STRICT_AS_OF feasibility:** before the 2016-05-13 revelation (and up to 2016-11-13 21:26:22 +08:00, exclusive) there is
**no verified point-in-time financial observation** of 1785 → `insufficient_point_in_time_evidence`. Early-warning
predictive performance cannot be demonstrated from these data; no AUC/precision is reported.

## Literature models (gates only)

| Model | Status | Blocking inputs |
|---|---|---|
| Beneish (1999) 8-variable M-Score | `not_computable` | PPE, securities, depreciation, SG&A, long-term debt, current maturities of LTD, income-tax payable (AQI, DEPI, SGAI, LVGI, TATA) |
| Dechow et al. (2011) F-Score model 1 | `not_computable` | RSST accrual components, soft-asset inputs (PPE), issuance indicator |
| Jones / Modified Jones / Kothari | `not_computable` | multi-company industry panel, PPE |

No coefficients are shipped; DSRI, GMI and SGI are shown only as descriptive component indices, never as a score. US
thresholds are not Taiwan fraud probabilities. Adding inputs requires a new, separately sourced metric set (not a reuse of
the 18 canonical metrics).

## M3 — Cross-source reconciliation (RQ-C)

Board-notice vs filed XBRL: 40 match, 2 `mismatch_unresolved`, 18 `not_comparable` (unmapped lines such as
期末歸屬於母公司業主之權益, 稅前淨利, 歸屬於母公司業主淨利). Restatement post side vs restated XBRL: 27 match, 67 `not_comparable`
(no filed fact for the period/scope; v2 fails closed on framework, regime, version, unit, sign, side and availability). TPEx summaries: 45
`not_comparable` (scope inferred by matching XBRL revenue — circular). **FY2025**: total assets 34,436,171 vs 34,434,450 and
total liabilities 19,423,635 vs 19,421,914 thousand TWD (each 1,721); audited PDF (SHA `fc715140…`) page 8 equals the filed
XBRL; total equity 15,012,536 identical. Cause unverified; no correction/reclassification/fraud wording; not routed to risk.

## Decisions requested from the method owner

1. Approve or change the 1 % near-zero denominator rule and the margin set.
2. Approve the feature registry wording, the proxy designation and the 2013 (first TIFRS year) t−1 policy.
3. Classify H1–H4 by judgment paragraph (finding / allegation / disclosure) and archive the judgment if it is to be cited.
4. Decide whether additional statement lines (PPE, depreciation, SG&A, LTD) should be sourced for literature models.

## JSD readiness handoff (Ethan)

1785 archive: 44 file records, 38 distinct SHA-256, 1,190 pages (1,139 with text), 26 listing meeting rows, **0 JSD-ready**
(`period_unconfirmed` 44, `duplicate_document` 6, `publication_unverified` 44). FinTrust reports `jsd.status=NOT_APPLICABLE`,
`value=null`. The contract (`docs/data/JSD_INPUT_CONTRACT.md`), adapter, tokenizer, thresholds and calibration are unchanged.
To make records ready, a reviewer must verify `YYYYQn` from document content (not meeting dates); presentations remain
non-transcript and are never fed to transcript calibration.
