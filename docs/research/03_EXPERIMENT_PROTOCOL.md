# Experiment Protocol

Phase 11A freezes the Text Mining / Evidence v2 experimental protocol. This document is a research specification only. It does not implement experiments, model training, data migration, or UI changes.

## Current Baseline

Confirmed current baseline at `4840bfca`:

- Data Shift uses whole/prepared text inputs.
- Word/token distribution drift is measured with Jensen-Shannon Divergence using `log2`.
- Current JSD thresholds are empirical STRUX thresholds: `P90 = 0.366397`, `P95 = 0.389590`, `P99 = 0.436144`.
- Current cosine thresholds are `P05 = 0.618645`, `P10 = 0.664451`.
- Current data quality thresholds are `MIN_TEXT_LENGTH = 5000` and `MIN_LENGTH_RATIO = 0.50`.
- Current outputs include JSD, cosine similarity, emerging terms, disappearing terms, data quality warnings, and method metadata.
- Current official event/topic extraction is deterministic keyword-based and event/document-level.

The current STRUX baseline remains an explicit experiment condition.

## Experiment 1 - Relevant Text Extraction

Research question:

Does domain-aware relevance filtering improve extraction of financially useful text compared with the current simple keyword/raw-text approach?

Compare:

| Variant | Description |
| --- | --- |
| `E1-A` | Current/basic keyword baseline. |
| `E1-B` | Keyword + section information. |
| `E1-C` | Proposed relevance filtering. |

Ground Truth:

- Human annotation at sentence / meaningful textual-unit level.
- LLM output is not Ground Truth.
- Report Cohen's Kappa for human annotators before system evaluation.

Binary relevance evaluation:

- Precision.
- Recall.
- F1.
- Confusion Matrix.

Topic classification evaluation:

- Macro-F1.
- Weighted-F1.
- Confusion Matrix.

Do not mix relevance accuracy and topic accuracy. Relevance is binary. Topic classification is multi-class or multi-label, depending on the final annotation design.

## Experiment 2 - Data Shift Metric Comparison

Research question:

Which metric better reflects meaningful period-to-period narrative change?

Methods:

| Method | Description |
| --- | --- |
| `M1 Raw-text Word JSD` | Current raw/prepared text lexical JSD baseline. |
| `M2 Cleaned-text Word JSD` | Word JSD after boilerplate/text cleaning. |
| `M3 Relevant-text Word JSD` | Word JSD using only relevant sentences. |
| `M4 Topic Distribution JSD` | JSD over canonical topic proportions. |
| `M5 TF-IDF Cosine Similarity` | Current or cleaned/relevant text TF-IDF cosine comparison. |
| `M6 JSD + Cosine` | Optional experimental comparison only. |

Do not define M6 weighting before validation.

Human drift annotation:

| Label | Meaning |
| --- | --- |
| `0` | Normal / low change. Narrative emphasis is broadly consistent across periods. |
| `1` | Noticeable change. Some important topics or terms change, but not enough to indicate a broad narrative shift. |
| `2` | Substantial change. Major topics, risks, strategy, outlook, or operational emphasis change across periods. |

Evaluation:

- Primary ordinal evaluation: Spearman correlation between metric value and human drift label.
- If converted to binary: Macro-F1, Precision, Recall.
- ROC-AUC may only be reported if binary labels are explicitly defined and there are enough positive/negative samples.
- Do not report ROC-AUC automatically.

## Experiment 3 - Ablation Study

Research question:

Which preprocessing component actually improves drift detection?

Compare:

| Variant | Description |
| --- | --- |
| `A` | Raw full text. |
| `B` | Boilerplate removal only. |
| `C` | Relevant sentences only. |
| `D` | Relevant sentences + section segmentation. |
| `E` | Relevant sentences + topic distribution. |

Measure:

- JSD behavior.
- Cosine behavior.
- Correlation with human drift labels.
- Classification F1 where binary/ordinal conversion is explicitly defined.

The goal is to determine whether preprocessing adds measurable value, not to assume preprocessing is automatically better.

## Experimental Dataset Design

Preferred companies:

- `2330`
- `2303`
- `2454`
- `3711`

Do not require all four if official source data is insufficient.

Text extraction dataset:

- Pilot: at least 200 sentences.
- Desired final: at least 400 sentences, if sufficient official data is available.

Drift experiment:

- Pilot: at least 12 document/period pairs.
- Desired final: at least 30 pairs if official historical data supports this.

Never fabricate missing historical documents. If official documents are blocked, unavailable, metadata-only, or insufficient, record that limitation as part of the study.

## Leakage Prevention

If a classifier is later trained:

- Do not randomly split sentences from the same document across train/test.
- Prefer splitting by company + document + period, or by entire document.

Reason:

Sentences from the same document share vocabulary, formatting, boilerplate, financial period, management phrasing, and source artifacts. Random sentence splitting can let the model memorize document-specific language and overstate performance.

## Reproducibility

Record for each sample, run, or metric output:

- Source URL.
- Document URL.
- Document hash.
- Text hash.
- Retrieval time.
- Parser version.
- Annotation guideline version.
- Metric implementation version.
- Threshold version.
- Random seed if relevant.

## Current Implementation Gap

Confirmed gaps between current implementation at `4840bfca` and proposed V2:

- Current tests do not evaluate text extraction precision, recall, F1, or confusion matrices against human annotation.
- Current Data Shift thresholds are empirical operational thresholds, not validated against a human drift annotation dataset.
- Current official event tests verify parser extraction, topic/category detection, identity stability, and idempotent persistence, not ordinal drift quality.
- Current Data Shift exposes JSD and cosine separately and does not use a validated combined score.
- Current repository stores official events as event-level payloads; it does not store experiment samples, annotator labels, kappa results, or sentence-level metric inputs.
- Current source limitations such as blocked official pages, metadata-only responses, and preview-only extraction are surfaced as limitations, but they are not yet part of a reproducible experimental sampling log.
