# FinTrust Round4 engineering closeout and research presentation handoff

Branch: `feature/financial-ml-round4-explainability-handoff-20261020` (derived from
user-accepted Round3 `feature/financial-ml-round3-model-evaluation-20261020`).

## Real Round3 evidence received 2026-10-20

User uploaded final real-data `round3_real_data_model_report.json`; its
SHA-256 is **766fa54e83763c39634605e983a3928e0fd8055e7fa06b72fc767bfa037ce380**.

- 399 next-year numeric prediction windows: fit 192 (2016–20), validation
  82 (2021–22), holdout 125 (2023–25); 12 FINMIND_PROVISIONAL financial
  amounts, NOT officially certified original 15 Beneish/Dechow facts.
- Eight trained annual models, one CatBoost not installed. Pre-specified
  validation metric Signed-log MAE picks `persistence`=**2.452108**,
  ahead of RandomForest=2.851232, Ridge=2.973503, Transformer=2.988281,
  TCN=2.990243, LSTM=3.059894, GRU=3.298458, MLP=3.461845.
- Random Forest lowest *holdout* scaled RMSE=**1.969583**, but model
  selection cannot be changed on holdout; persistence lowest holdout
  Signed-log MAE=**1.721371**. Not fraud precision or accuracy.
- Strict issuer/time joint FY split: fit 147 (30 firms), validation
  18 (9 firms), test **6 rows across only 2 firms**. Holdout R²:
  persistence **0.111075**, Ridge **−1.849521**,
  Random Forest **−4.805580**. Tiny independent test makes
  generalization claims fragile.
- Frozen official retrospective quarter source: 144 issuer-quarters,
  132 validated candidate, 9 missing, 3 invalid. 24 fit-selected
  exact-concept/grain financial fields, 2,232 observed cells. Strict
  joint fit/validation/test: 20/9/6 quarters.
- Four novelty models on **unlabeled** quarters: test fraction over
  training P95 threshold IF 0%, LOF 66.7%, One-Class SVM 100%, PCA 100%.
  Validation fractions are 100% for all four. Strong method disagreement
  or distribution shift, not verified fraud/detection accuracy.
- Zero independent verified positive/negative outcomes, zero certified
  first-filed original financial vintage/publication, and 1785
  deliberately excluded from development. Fraud F1/PR-AUC must be null.

## Implemented Round4 research engineering

Module `round4_research_handoff.py` uses the local user-accepted source
report and already saved Round1/Round2/Round3 artifacts. It does not repeat
Round3 fitting, retrieve Internet sources or mutate operational databases.

1. **Input contract + anti-leakage:** verify exact user-uploaded Round3 report
   hash, Round2 manifest and Round3 source gate hashes. Reject any inserted
   fraud labels, changes to source tiers, or reinterpretation of missing
   original filings. The case 1785 remains excluded.
2. **Model explanation:** on historical validation FY2021–22 only, load
   the locally produced trusted fit-only preprocessing/model checkpoints,
   rebuild the frozen 399 complete windows from archived annual CSV, and
   verify training-scaler center/scale against the checkpoint.
   For **Ridge and Random Forest**, shuffle each of 12 financial variables'
   entire 3-year history together across validation companies (5 repeats),
   calculate mean/std increase in signed-log-MAE. This is **predictive
   permutation sensitivity**, NOT official Beneish/Dechow feature ranking,
   SHAP values, causal effect, or financial fraud explanation. SHAP is not
   manufactured for the Persistence baseline or unlabelled models.
3. **Model robust comparison:** show validation-selected Persistence vs
   test-only supplementary metrics; joint issuer+time test n=6/2 firms;
   keep historical source limitations visible.
4. **Quarter agreement:** retain the four methods' per-quarter
   known-outcome=UNKNOWN, summarize ensemble test/validation votes
   for the 15 available disjoint quarters and calculate pairwise
   Jaccard disagreement on the six unlabeled test quarters.
5. **Audit manager handoff:** export quantitative CSVs and clear
   risk/limitations register. Distinguish production-ready advisory
   evidence from research-only score placeholders.
6. **1785 PIT replay:** BLOCKED until independent original first filings,
   publication dates, initial legal disclosure and frozen model criteria
   are review-certified. This cannot be solved by writing code alone.

All outputs write to a new directory. Any prior result directory is
intentionally immutable.

## One local Windows execution

Inside the existing `Financial-Risk-Alert-System-ML\\fintrust_backend`
worktree, with `ml-env` active and tracked files clean:

```powershell
git status --short
git fetch origin
git switch --track origin/feature/financial-ml-round4-explainability-handoff-20261020
powershell -ExecutionPolicy Bypass -File .\\research\\financial_ml\\verify_round4_research.ps1
```

If the branch exists use `git switch feature/financial-ml-round4-explainability-handoff-20261020`.
No prior phases are rerun. Prerequisites: sklearn, numpy, joblib already
available from Round3. `catboost` is not necessary for Round4 permutation.

Output:
`Financial-Risk-Alert-System\\fintrust_backend\\data\\financial_ml\\round4_explainability_handoff`

Upload `round4_research_handoff_report.json`, plus
`round4_validation_permutation_importance.csv` to include
actual feature importance in the final presentation.

## Editable presentation draft (separate artifact)

A first editable PowerPoint draft (22 slides) has been generated from the
user-uploaded real Round3 report, explaining exact data counts, 15 paper
features vs 24 quarterly QName candidates, 9 annual model statuses,
8 observed annual metric sets, strict joint-split weakness, four quarterly
novelty method scores, missing true fraud outcomes, and the planned
Round4 interpretability/PIT safety gate.

Do not put Round4 feature-importance numbers in those slides until the
above real Round4 acceptance report is returned. Slide text, chart bars,
shapes and model comparison table remain editable in PowerPoint/Canva.
