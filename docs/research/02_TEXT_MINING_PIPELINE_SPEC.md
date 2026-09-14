# Text Mining Pipeline Spec

Phase 11A freezes the proposed Text Mining / Evidence v2 research design. This document is a specification only. It does not implement new segmentation, classification, metrics, storage, UI, or API behavior.

## Current Baseline

Current Data Shift baseline:

```text
raw/prepared text
-> tokenize
-> term frequency distribution
-> Jensen-Shannon Divergence
```

and:

```text
raw/prepared text
-> TF-IDF
-> cosine similarity
```

Confirmed current behavior:

- `data_shift.py` accepts explicit `text_1` / `text_2` through `POST /api/data-shift`.
- `POST /api/data-shift/auto` loads latest two STRUX prepared transcripts for a ticker at request time, not Flask startup.
- `load_strux_dataset()` calls `pd.read_parquet()` after `resolve_strux_path()` finds `DATA_SHIFT_PARQUET` or a known local fallback.
- The STRUX auto route requires columns `ticker`, `date`, and `prepared_remarks`, then flattens `prepared_remarks` into `prepared_text`.
- Tokenization currently keeps English words, Chinese character runs of length two or more, and percentages.
- English stopwords include scikit-learn `ENGLISH_STOP_WORDS` plus project stopwords such as `quarter`, `company`, `conference`, `operator`, and `thanks`.
- JSD uses `math.log2`; current empirical thresholds are `P90 = 0.366397`, `P95 = 0.389590`, `P99 = 0.436144`.
- TF-IDF cosine thresholds are `P05 = 0.618645`, `P10 = 0.664451`.
- Data quality rules are `MIN_TEXT_LENGTH = 5000` and `MIN_LENGTH_RATIO = 0.50`.
- Data Shift reports emerging terms, disappearing terms, warnings, metric method, and quality results.

The current STRUX baseline must remain available for experiment and ablation comparison. V2 must not silently replace it.

## Proposed V2 Architecture

```text
Official Source
-> Document Acquisition
-> Document Extraction
-> Section Segmentation
-> Sentence Segmentation
-> Text Cleaning
-> Relevance Filtering
-> Financial Topic Tagging
-> Text Mining
-> Period Comparison
-> JSD / Cosine
-> Emerging / Disappearing Evidence
-> Evidence Provenance
```

This architecture defines research layers. It does not require all layers to ship together.

## Section Segmentation

Candidate section labels:

| Section | Meaning |
| --- | --- |
| `management_prepared_remarks` | Management presentation or prepared remarks. |
| `financial_results` | Reported operating or financial results. |
| `business_outlook` | Guidance, outlook, forecasts, management expectations. |
| `product_and_technology` | Product roadmap, R&D, technology migration. |
| `capacity_and_capex` | Expansion, capacity, equipment, capital expenditure. |
| `demand_and_inventory` | Demand, inventory, channel digestion, customer pull patterns. |
| `cash_and_financing` | Cash flow, liquidity, financing, debt. |
| `qa` | Question and answer section. |
| `material_event_description` | Material-event body or official explanation text. |
| `other` | Content not clearly assigned to another section. |

Do not assume all sources contain all sections. Material events may contain only title/body fields. Company IR pages may contain document links and metadata without full transcript sections.

## Sentence Segmentation

V2 sentence segmentation must support:

- Traditional Chinese punctuation such as `。`, `！`, `？`, `；`.
- English punctuation and abbreviations.
- Mixed Chinese-English sentences such as product names, accounting terms, and ticker references.
- Numbers, percentages, currency units, ROC dates, fiscal quarters, and financial units.
- Bullet points and table-derived rows from presentations or announcements.
- Stable `sentence_id` generation within each document and section.

Candidate implementation choices may include deterministic punctuation rules, a Traditional Chinese NLP segmenter, or a hybrid approach. Phase 11A does not choose or implement a library.

## Text Cleaning

V2 cleaning should be separately measurable and reversible enough for provenance:

- Remove duplicate headers, footers, page numbers, navigation text, operator instructions, and repeated safe-harbor blocks.
- Preserve original text in provenance.
- Preserve normalized text as the metric input.
- Avoid deleting company-specific caveats, risks, outlook, and uncertainty language.

## Relevance Filtering

Deterministic baseline:

- Keyword / topic lexicon based filtering.
- Section-aware inclusion/exclusion rules.
- Explicitly log which keyword or section rule selected a sentence.

Proposed V2 options:

- Rule-based filtering with canonical financial topics.
- Statistical or ML binary classifier trained against human Ground Truth.
- Embedding-based relevance scoring.

Recommended starting point: an explainable deterministic baseline before introducing opaque models. Any trained or embedding-based system must be evaluated against human Ground Truth and must not redefine Ground Truth.

## Financial Topic Tagging

Topic tagging should use the canonical research taxonomy:

`outlook`, `capacity_capex`, `demand_inventory`, `revenue_orders`, `rd_product`, `cash_financing`, `ma_investment`, `operation_disruption`, `legal_regulatory`, `governance`, `other`.

Current code labels must be mapped to canonical labels in research outputs. Production enums are not changed in Phase 11A.

## Text Mining Outputs

For each period/document, produce:

| Output | Definition |
| --- | --- |
| `term_frequency` | Token counts and normalized token rates. |
| `tfidf_terms` | TF-IDF weighted terms for the document/period comparison corpus. |
| `topic_counts` | Count of relevant sentences by canonical topic. |
| `topic_proportions` | Topic count divided by total relevant sentence count. |
| `relevant_sentence_count` | Number of sentences passing relevance filtering. |
| `candidate_sentence_count` | Number of candidate sentences after segmentation. |
| `coverage_ratio` | `relevant sentences / candidate sentences`. |

`coverage_ratio` is not model accuracy. It describes document coverage after filtering.

## JSD Layers

V2 defines three conceptually separate metrics:

### A. `word_distribution_jsd`

Compare lexical term distributions. This is the closest extension of the current Data Shift JSD baseline.

### B. `topic_distribution_jsd`

Compare canonical financial topic distributions across periods. This requires reliable sentence-level relevance and topic labels.

### C. `cosine_similarity`

Compare textual/vector similarity. Current baseline uses TF-IDF cosine over tokenized text.

Do not create an arbitrary combined weighted score in Phase 11A. The experiment must first determine whether combining metrics improves performance.

Optional future comparison `JSD + Cosine` must not define weights before validation.

## Explainability Requirement

Every drift result should eventually identify:

- Which topics increased.
- Which topics decreased.
- Which terms emerged.
- Which terms disappeared.
- Which source sentences support the change.
- Which official source/document each supporting sentence came from.

## Current Implementation Gap

Confirmed gaps between current implementation at `4840bfca` and proposed V2:

- Current Data Shift works primarily at whole/prepared text level and does not segment official documents into sections/sentences.
- Current JSD is lexical word/token distribution only; there is no topic-distribution JSD layer.
- Current cosine similarity is TF-IDF over the two input texts; it does not use sentence-level relevance filtering.
- Current Chinese tokenization is regex-based, not semantic segmentation.
- Current emerging/disappearing evidence is term-level only; it does not yet link terms back to supporting source sentences.
- Current official document extraction is preview-oriented: it returns text previews, statuses, debug data, and limitations.
- Current evidence card summarizes persisted snapshots/events and source statuses, but it does not provide sentence-level evidence chains.
