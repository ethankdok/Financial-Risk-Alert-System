# FinTrust ML Finalization — Round 2: primary-source / outcome review gate

**Research-only implementation:** 2026-10-20.
**Branch:** `feature/financial-ml-round2-review-gate-20261020`.
**Base:** accepted Round1 `feature/financial-ml-closeout-round1-unified-20261019` @ `443ee1aff9874f8213ae8eea902fdf03480dfd63`.

## Precise goal and stop condition

Round1 datasets were source-joined and verified on the user's real Windows research archives:
17/17 focused tests; 120 issuers / 1,560 years; 535 complete annual provisional
12-amount rows; 11/64 complete MOPS retrospective 15-paper-component years;
132/144 official comparison quarters; 24 fit-only exact-concept quarter candidates.
The four known gaps were NOT resolved by Round1: original first-filed version,
publication timestamp, independently reviewed adverse event periods, and
credible fully followed-up negatives. The final 1785 case stays held out.

Round2 must not infer a 0 or 1 label simply from a lawsuit, a retrospective
score, an official download SHA, a selected current listing, a missing media
mention, or a manual form. A reviewed normal comparison needs a documented
follow-up interval and negative screening evidence. A known misstatement
candidate needs period-specific adjudication and primary archived evidence.
For historical `as-of` experiments, the report's **first published version**
and original availability time must be separately verified. Later legal
evidence may support retrospective ground truth but was NOT known to historical
model developers.

## Completed work in this Round2 engineering increment

New `round2_evidence_review.py` consumes **existing outputs**, offline:

- Prior Round1 accepted report (source and holdout gates; SHA cross-check
  with already accepted Phase10 case-feature CSV).
- Phase1 case registry seed: three separately assessed case identities.
- Phase7 per-document judicial / SFIPC identity review (content identity
  is evidence for *review*, not a legal finding).
- Phase8 original filing candidate intake and previous integrated outcome gate
  (a stored file with a claimed timestamp is NOT certified original).
- Phase10 official retrospective case 15-feature evidence (13 source company-years).
- Round1 case-source tier and quarter-index/sparse comparison views.

The builder constructs separate non-overlapping units:

| Research view | Expected rows | Default status |
|---|---:|---|
| 3027 / 8299 / 6452 candidate affected annual fiscal years | 7 | UNKNOWN |
| 6452 alleged individual 2017Q2–2020Q1 quarters | 12 | UNKNOWN |
| 12 present-day selected comparison issuers × 12 quarters | 144 | UNKNOWN |
| Independent reviewer template | 163 | NOT_REVIEWED |

Case rows are NOT independent adjudicated positives. Quarterly comparison
rows are NOT verified negatives; observed financial facts are NOT labels.
The annual case view deliberately counts only seven target years; the thirteen
different case XBRL source-years include the prior-year feature dependencies.
These are different dataset grains.

Generated files under `data/financial_ml/round2_evidence_review/`:
- `round2_case_year_review.csv`: official case source SHA, retrospective
  paper feature coverage, legal status and source-specific blockers.
- `round2_case_quarter_review.csv`: separate 6452 allegation reporting periods.
- `round2_unreviewed_comparison_quarters.csv`: missing quarter,
  historical-listing, original-vintage and independent normal-screening gaps.
- `round2_independent_review_template.csv`: blank evidence/document/timestamp
  and reviewer-identity fields. This file is a **human review worksheet**,
  NOT a method for automatic approval or model-label ingestion.
- `round2_evidence_review_report.json`: counted source statuses, explicit
  zero-approved supervised labels, immutable input SHA manifest.

The builder fails if previous sources silently promote UNKNOWN outcomes,
if approved-training flags are forged, if first-event holdout leaks, if
Phase10 case CSV changes since Round1, if case raw SHA differs between
Phase10 and the Round1 case view, or if comparison quarterly SHA differs
between the frozen sparse/index views. Existing reviewer output files
are never overwritten.

**Tests authored:** 13 focused synthetic test cases covering separate
sampling grains, refusal to assume lawsuit=positive, exact source lineage,
no unreviewed 0/1, heldout-case exclusion, duplicate quarters, missing Phase8
artifacts, and no overwrite of reviewers' files.
This GitHub work has **not** been executed against the user's local
research archives in this ChatGPT session. Test code committed is not a
substitute for observed `unittest` PASS.

## Single Windows acceptance — no old phases replay

In the clean dedicated `Financial-Risk-Alert-System-ML` worktree
(check `git status --short` first and preserve any uncommitted changes):

```powershell
git fetch origin
git switch --track origin/feature/financial-ml-round2-review-gate-20261020
powershell -ExecutionPolicy Bypass -File .\research\financial_ml\verify_round2_review.ps1
```

**Run these commands while in `Financial-Risk-Alert-System-ML\fintrust_backend`.**
If the local tracking branch already exists, use
`git switch feature/financial-ml-round2-review-gate-20261020` instead of
`git switch --track`. The PowerShell script identifies the repository root
automatically, runs only the new focused regressions, reads the real old
archive folder and generates exactly one review packet; no Phase1–14
rerun, no network, no model training, no Flask/FastAPI/Firestore, no
GCP deployment or production writes.

One artifact to return:

`Financial-Risk-Alert-System\fintrust_backend\data\financial_ml\round2_evidence_review\round2_evidence_review_report.json`

If a safety gate fails, return the specific error/traceback instead. Do not
delete or rewrite previous data to force passing.

## What remains to **finish** Round2 (explicitly not yet done)

The first engineering increment creates an auditable and reproducible
**review worklist**, not verified outcomes. Subsequent Round2 work must
secure *independently reviewable* archived notices (as-original filing
identity + original market-public timestamp), reconcile exact judicial
findings by reporting period and legal finality, and review true normal
follow-up per company/period. Where impossible, leave the periods UNKNOWN.

Re-use Phase1/7/8/9/10 adapters instead of reimplementing crawler or
Beneish/Dechow formulas. Only after the research method owner signs off
on period-specific evidence and the availability rules may a *separate*
label-admission function be implemented and experimentally tested.
Until then Round3 supervised classification remains BLOCKED;
unlabeled anomaly or amount forecasting remains a separate, explicitly
different experiment. **Do not call this entire Round2 complete.**
