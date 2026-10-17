# Normal-only financial anomaly detection — experiment registry v1

## Rationale
Normal-reference data cover many issuers and years. Officially confirmed anomalies/major misstatement cases serve independent **evaluation**, not training labels for the initial one-class baselines. A company without a documented enforcement notice is *not automatically confirmed normal*; normal-reference acceptance requires explicit cohort review, followup horizon and timing.

| ID | Feature set | Model | Fit cohort | Evaluated output |
|---|---|---|---|---|
| A0 | Pilot's 15 canonical/descriptive features | Isolation Forest | Reviewed normal years only | Distributional anomaly scores, case rank, held-out independent labels where available |
| A1 | Same | MLP reconstruction | Same | Reconstruction error, same test protocol |
| A2 | Literature-authoritative Beneish 8 + Dechow 7 | Isolation Forest | Same | Incremental value of literature variables (*after engine integration*) |
| A3 | Literature + financial fundamentals | CatBoost/Isolation Forest/Autoencoder | Same | Group ablation (*planned*) |
| A4 | Approved history + stable annual sequences | GRU / TCN / small Transformer autoencoder | Same | Temporal-ablation and reconstruction/forecast-error results (*planned*) |
| A5 | Harmonized SEC US-GAAP ratios pretrained, TW TIFRS normal fine-tune | Denoising AE/sequence encoder | US reference then Taiwan reference | Transfer versus Taiwan-only under identical held-out set (*planned*) |

## Split & labeling contract

1. Split **by observation availability** and year: fit on earlier years, calibrate threshold using distinct later normal years; score later test years; never tune models on test scores or known positive cases.
2. Run a **company-disjoint robustness** split. Exclude reserved 1785 from both fit and validation completely; the model may score it as a separate case. No case-aware model selection.
3. Limit training normals to case-reviewed companies/years with dated evidence and configured future followup horizon. Retrospective review is not evidence that the cohort was available at the earlier historical prediction date.
4. Financial source filing/version/time must be coherent within an observation; no post-event restatement as historical as-of evidence.
5. Treat top-15 feature selection as a future experiment fit on *training folds only*, using stability plus permutation/SHAP-style explanations; do not mistake highest anomaly score contribution for causal proof of wrongdoing.
6. Compare **Precision@K, anomaly recall for externally confirmed cases, normal false-positive rate, PR-AUC, positive-class F1, calibrated threshold stability** where data permit; do not claim F1 when test is unlabeled or single-class.

## Acceptance gates

- **G0** — Source readiness: enough independent companies/years, provenance and accounting-framework mapping verified; no live DB writes.
- **G1** — Cohort readiness: documented normal review, enough normal train/validation firms and independent abnormal test examples.
- **G2** — Normal-only smoke tests and out-of-time plus firm-disjoint baseline comparison.
- **G3** — Literature feature ablation, with `not_computable` reports not silent imputation of paper scores.
- **G4** — Optional pretrained model only after a verified SEC-to-TIFRS common schema, and report negative transfer if present.