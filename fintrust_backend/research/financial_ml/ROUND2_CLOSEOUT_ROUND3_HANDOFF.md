# FinTrust ML Round2 closeout and Round3 conditional handoff

2026-10-20 | Branch `feature/financial-ml-round2-closeout-round3-handoff-20261020`
| Parent: user-validated Round2 `feature/financial-ml-round2-review-gate-20261020`.

## Accepted actual Round2 user results

User ran the integrated offline stage locally and returned report hash
`f8d4a6606c44976ad50d2f26dce2a9291b838bcafb8741486f4be337e837b8c2`.

- Focused 13/13 PASS, 163 exact review units (7 case issuer-years;
  separately 12 alleged 6452 case quarters; 144 unlabeled comparison
  issuer-quarters across 12 issuers). Four official legal source documents
  have identity-supported content in the user's archived source review;
  **not** independently authenticated original publication or outcomes.
- Six of seven affected case target fiscal years have validated retrospective
  XBRL; one missing; of those case targets only one official retrospective
  15-original-paper-component vector is complete.
- Original as-first-published issuer financial versions: **0**; initial public
  misstatement revelation independently timed: **0**; outcome positives **0**;
  independently reviewed clean negatives **0**; supervised rows **0**.
- The untouched 1785 final historical replay must not be transferred to
  any development branch, feature selection, tuning or testing.

## Deliverable: Engineering complete ≠ evidence approval

New `round2_closeout_round3_bridge.py` is a read-only **independent
reconciliation of actual Round2 files**, not another data acquisition phase.
It verifies:

1. The user's accepted report SHA (when pinned), its frozen 9-input SHA
   manifest and 163 review/sample grain cardinalities.
2. Four existing Phase7 primary source records against the separate frozen
   case registry. For an archived court or SFIPC HTML, compare the actual
   **local file bytes** and its own receipt SHA/URL to the accepted report.
   A matching URL in a receipt is not proof of original server identity.
3. The 163 human-review template rows have not been silently converted to
   `Y=0` / `Y=1` or signed off without independent proof. Any edit,
   contradictory approval or missing expected source fails closed.
4. Round1 1,560 annual candidate rows, 1,624 segregated paper-source
   issuer-years, 144 actual comparison issuer-quarters, 24 fit-only
   candidate features, and 2,232 observed selected-feature positions.
   Verify no rows automatically admit fraud training and the 1785 case
   is absent from all training/intermediate data.

It produces **four different outputs** under
`data/financial_ml/round2_closure_round3_preflight/`:

| File | Usage |
|---|---|
| `round2_closure_and_round3_preflight.json` | Independent integrity, authentic-first-filing and outcome approval gates |
| `round2_official_document_archive_audit.csv` | One row per official source, with actual local byte/receipt SHA and remaining provenance questions |
| `round3_research_source_manifest.csv` | Immutable transfer manifests for provisional annual amounts, source-tier-segregated published formulas, and unlabeled quarter features |
| `round3_release_gates.json` | Machine-readable **separate** rules for exploratory research vs historical supervised fraud fitting |

**Two distinct signoffs:**
- Round2 software/integrity closeout succeeds **only after the user's real
  archived output is checked**.
- Round2 **research** outcome certification remains NOT APPROVED until
  independent period-specific sources, original-first-public filing,
  earliest notice timestamp and true negative follow-up are reviewed
  and approved. The software cannot authenticate judicial interpretation,
  official archival provenance, or absence of misconduct from a CSV.

For Round3, maintain independent exploratory paths:
- `annual_12_amount_candidate_index.csv`: FINMIND_PROVISIONAL numeric
  year-ahead regression, *not* misstatement classification.
- `annual_original_15_paper_candidate_index.csv`: only original published
  Beneish / Dechow definitions; segregate 64 MOPS retrospective and
  1,560 provider candidates, never silently fuse.
- `quarterly_sparse_feature_matrix.csv`: 144 **unlabeled** quarters, 24
  fit-selected exact XBRL fields and explicit observed/missing flags,
  usable for technical missingness or unsupervised diagnostics,
  **not** a true-normal fraud classifier or external test.

`round3_release_gates.json` keeps supervised classification, fraud PR-AUC
and 1785 as-of replay **false** until genuine source/time/label checks pass.

## Added official/public source *leads* (not automatic labels)

Use these references to prioritize a human primary-record review. Findings
are contextual and the URLs are *not* artifacts certified in the user's
local archived filing manifest.

1. **3027 盛達**: Taipei District Court criminal first-instance judgment
   **113年度金訴字第29號**, dated 2025-04-30:
   https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPDM%2C113%2C%E9%87%91%E8%A8%B4%2C29%2C20250430%2C1 .
   A reprint of the 2017-06-23 MOPS correction notice (MoneyDJ posted
   2017-06-26) says the change encompasses **2015Q2–2017Q1
   consolidated and individual reports** for IAS18 gross-vs-net
   agent revenue recognition; historic correction notice was triggered
   by TWSE letter 2017-06-05:
   https://www.moneydj.com/kmdj/news/newsviewer.aspx?a=6e505c57-1950-4870-97f6-6e536e9217e7 .
   **Do not** assume this mirror was the first public disclosure or
   apply the 2017 correction amount to the **original 2015 historical
   feature input**. Annual 2015/16 case targets remain the currently
   frozen developmental study until separately reviewed amendments.

2. **8299 群聯**: Supreme Court civil case
   **114年度台上字第859號 (2025-11-19)** was **vacated and
   remanded**. That ruling states a *separate* 2022 criminal judgment
   (High Court 111年度金上訴字第11號) was final in its description.
   Never confuse the civil director-removal proceeding's finality with
   the criminal conviction. Source:
   https://judgment.judicial.gov.tw/FJUD/printData.aspx?id=TPSV%2C114%2C%E5%8F%B0%E4%B8%8A%2C859%2C20251119%2C1 .
   Period-level accounts and original 2014 first filings still require
   review. The separate 2024 civil litigation also contains contested
   accounting/IFRS interpretation: avoid transferring all judicial
   statements wholesale into an automated label.

3. **6452 康友-KY**: The Investor Protection Center's
   2023-05-12 statement described **allegations** spanning
   2017Q2–2020Q1 in separately instituted commercial-court
   proceedings; it did not establish every quarter as an adjudicated
   positive. Source:
   https://www.sfipc.org.tw/News_Content.aspx?n=7458&s=571 .
   A separate official statement identifies a more *specific*
   alleged missing movable-property pledge disclosure in
   **2019Q3–2020Q1**:
   https://www.sfipc.org.tw/News_Content.aspx?n=7458&s=567 .
   Keep these allegations and mechanisms separate; search original
   financial footnotes before contemplating numeric XBRL-only signals.

## One clean real-data acceptance (no Phase1–14 rerun)

In **`Financial-Risk-Alert-System-ML\fintrust_backend`**, with
existing `ml-env` and clean tracked files:

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-round2-closeout-round3-handoff-20261020
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round2_closeout.ps1
```

If branch exists locally, use `git switch feature/financial-ml-round2-closeout-round3-handoff-20261020`.

The script runs only new focused regressions, checks the accepted
user-uploaded Round2 SHA, and performs an offline real-source audit.
**Do not rerun `verify_round2_review.ps1`** because it intentionally
preserves pre-existing review files. This prevents accidental overwrites
and unnecessary repeat downloads.

Return just
`round2_closure_and_round3_preflight.json` and
`round3_release_gates.json`, or the specific blocking error.

**This implementation does not close the manual research
adjudication requirement**. Software/integrity closeout is a separate
achievable milestone; verified positive/negative labels cannot be
invented from a case list, and a finance audit manager must not see
unsourced classification claims.
