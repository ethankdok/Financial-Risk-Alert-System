# Ground Truth Annotation Guide

Phase 11A freezes the research annotation method for Text Mining / Evidence v2. This document is a research specification only. It does not change current production enums, routes, algorithms, dependencies, or datastore behavior.

## Current Baseline

Current implementation at `4840bfca` does not use sentence-level human labels. Official evidence is represented at the financial snapshot, investor conference, material event, and document-preview level.

Confirmed current behavior:

- `data_shift.py` compares whole/prepared text inputs using token-frequency Jensen-Shannon Divergence and TF-IDF cosine similarity.
- JSD uses `math.log2`, with current empirical thresholds `P90 = 0.366397`, `P95 = 0.389590`, `P99 = 0.436144`.
- Cosine thresholds are `P05 = 0.618645`, `P10 = 0.664451`.
- Data quality rules are `MIN_TEXT_LENGTH = 5000` and `MIN_LENGTH_RATIO = 0.50`.
- Data Shift also reports emerging terms, disappearing terms, and quality warnings.
- Official conference/material-event topic inference is deterministic keyword matching, not human annotation.
- Current official evidence provenance is event/document level, not fully sentence level.

The STRUX baseline must remain available for experiment and ablation comparison. It must not be deleted, silently replaced, or redefined by v2.

## Proposed V2

V2 will introduce a human annotated Ground Truth dataset at sentence or meaningful textual-unit level. System output, deterministic rules, statistical models, embedding models, and LLM output may be evaluated against this Ground Truth, but none of them may be treated as Ground Truth.

## Unit Of Annotation

Primary annotation unit:

`ONE SENTENCE / meaningful textual unit`

Entire documents are not the primary annotation unit. A document can be used as a sampling frame, but annotation rows must point to a specific sentence or coherent short textual unit.

Each row must include at least:

| Field | Description |
| --- | --- |
| `sample_id` | Stable annotation row id. |
| `ticker` | Company ticker. |
| `company_name` | Company name shown in source metadata. |
| `source_type` | Example: `investor_conference`, `material_event`, `official_ir`, `financial_snapshot`. |
| `source_name` | Current source label such as `mops`, `twse_openapi`, or `company_official_ir`. |
| `source_url` | Official source page or API endpoint. |
| `document_url` | Direct document URL when available. |
| `document_id` | Stable source document id or derived hash. |
| `period` | Fiscal or event period. |
| `event_date` | Source event date if available. |
| `section` | Section label when segmentation is available. |
| `sentence_id` | Stable id within document/section. |
| `original_text` | Original sentence text before model transformation. |
| `relevant_label` | `1` for financially useful text, `0` otherwise. |
| `primary_topic` | One canonical topic from this guide. |
| `secondary_topics` | Optional semicolon-separated canonical topics. |
| `forward_looking` | Whether the sentence discusses outlook, plans, forecasts, guidance, or future operations. |
| `risk_relevant` | Whether the sentence is useful for risk/evidence assessment. |
| `annotator_id` | Human annotator id. |
| `annotation_round` | Pilot/final/adjudication round marker. |
| `annotation_notes` | Free text for boundary decisions, uncertainty, or source issues. |

## Relevant / Irrelevant Definition

Use `relevant_label = 1` when the sentence contains information that could materially help evaluate company operations, financial condition, future outlook, demand, inventory, orders, capacity, capital expenditure, products, R&D, cash flow, financing, investment, M&A, operational disruption, legal/regulatory risk, governance, or other decision-relevant company developments.

Use `relevant_label = 0` for greetings, operator instructions, conference logistics, speaker introductions, generic thanks, copyright/disclaimer boilerplate, duplicate headers, page navigation, pure formatting text, and generic statements without company-specific information.

Synthetic boundary examples:

| Example | Label | Notes |
| --- | --- | --- |
| "Revenue grew because shipments for the main product family increased in the second half." | 1 | Company-specific revenue and demand signal. |
| "Management expects inventory adjustment to continue for one more quarter." | 1 | Forward-looking inventory signal. |
| "The board approved capital expenditure for additional production equipment." | 1 | Capex and capacity signal. |
| "Free cash flow decreased due to higher equipment payments." | 1 | Cash-flow and capex signal. |
| "A major customer postponed orders after a product transition." | 1 | Orders and demand risk. |
| "The company received a regulatory penalty related to disclosure controls." | 1 | Legal/regulatory and governance risk. |
| "The new platform entered mass production and contributed to gross margin improvement." | 1 | Product and financial condition signal. |
| "A factory outage reduced output for approximately one week." | 1 | Operational disruption. |
| "The company completed an equity investment in a strategic supplier." | 1 | Investment and supply-chain signal. |
| "Management said demand visibility remains limited." | 1 | Outlook and demand uncertainty. |
| "Good afternoon and welcome to today's conference call." | 0 | Greeting/logistics. |
| "Please press star one to ask a question." | 0 | Operator instruction. |
| "The presentation materials are available on the website." | 0 | Logistics only unless it includes substantive details. |
| "Thank you, operator." | 0 | Generic thanks. |
| "This document may contain forward-looking statements." | 0 | Boilerplate unless paired with company-specific guidance. |
| "Page 12." | 0 | Formatting/navigation. |
| "The speaker introduced the executive team." | 0 | Introduction without substantive content. |
| "Please refer to the safe harbor notice." | 0 | Boilerplate. |
| "The meeting started at 2 PM." | 0 | Logistics only. |
| "We remain committed to creating long-term value." | 0 | Generic statement without company-specific evidence. |

Do not create examples that pretend to be real company quotations. The examples above are synthetic.

## Canonical Topic Taxonomy

Use one canonical research taxonomy across investor conference and material event sources:

| Canonical label | Definition |
| --- | --- |
| `outlook` | Guidance, forecast, management expectation, future outlook, or visibility. |
| `capacity_capex` | Capacity, expansion, equipment, fabs, production planning, capital expenditure. |
| `demand_inventory` | Demand, inventory, stock adjustment, customer pull-in/push-out, channel digestion. |
| `revenue_orders` | Revenue, orders, backlog, customer demand tied directly to sales. |
| `rd_product` | R&D, new products, roadmap, product mix, technology transition. |
| `cash_financing` | Cash flow, debt, financing, liquidity, working capital. |
| `ma_investment` | M&A, investment, acquisition, disposal, strategic holdings. |
| `operation_disruption` | Factory interruption, outage, natural disaster, supply disruption, shutdown. |
| `legal_regulatory` | Litigation, penalty, regulation, compliance, legal exposure. |
| `governance` | Board, management, internal control, governance events. |
| `other` | Financially relevant but not covered above, or uncertain topic. |

Mapping from current code labels to canonical labels:

| Current code label | Canonical label |
| --- | --- |
| `outlook` | `outlook` |
| `financial_outlook` | `outlook` |
| `capacity_or_capex` | `capacity_capex` |
| `inventory_or_demand` | `demand_inventory` |
| `revenue_or_orders` | `revenue_orders` |
| `rd_or_product` | `rd_product` |
| `cash_flow_or_financing` | `cash_financing` |
| `financing_or_debt` | `cash_financing` |
| `ma_or_investment` | `ma_investment` |
| `operation_disruption` | `operation_disruption` |
| `legal_or_penalty` | `legal_regulatory` |
| `governance` | `governance` |
| `other` | `other` |

Current production enums must not be modified in Phase 11A.

## Annotation Process

Use a two-stage process.

Pilot:

- Annotate 200 sentences.
- Use at least two human annotators.
- Calculate inter-annotator agreement before system evaluation.
- Use Cohen's Kappa for Relevant / Irrelevant and, where appropriate, topic classification.

Project operational criteria:

| Kappa range | Interpretation | Required action |
| --- | --- | --- |
| `kappa >= 0.80` | Strong agreement. | Continue to final dataset. |
| `0.60 <= kappa < 0.80` | Acceptable but needs review. | Review disagreement categories before final annotation. |
| `kappa < 0.60` | Annotation definition is unstable. | Revise guide before experiment continues. |

These are project operational criteria, not universal regulatory thresholds.

After pilot:

- Target at least 400 total annotated sentences if sufficient official data is available.
- Try to include at least 3 semiconductor companies.
- Try to include at least 2 source types.
- Prefer investor conference and material event sources.
- If enough official documents are unavailable, document the limitation instead of fabricating data.

## Ground Truth Rule

Ground Truth must be human annotated.

LLM output must not be treated as Ground Truth. A future LLM extractor may be compared against the human Ground Truth as one model, but it cannot define the labels used to evaluate itself.

## Current Implementation Gap

Confirmed gaps between current implementation at `4840bfca` and proposed V2:

- Current Data Shift works on whole/prepared text inputs; it does not use sentence-level Ground Truth.
- Current Chinese tokenization is regex-based (`[\u4e00-\u9fff]{2,}`), not semantic word segmentation.
- Current relevance and topic inference for official evidence is deterministic keyword-based.
- Current conference and material-event models store event/document fields and previews, not sentence-level annotation fields.
- Current evidence provenance contains source URLs, document URLs, event IDs, statuses, previews, and limitations, but not a complete sentence-level chain from source to JSD/Cosine input.
- Current tests verify parsers, source labels, stable identities, idempotent event persistence, and aggregation, but do not evaluate extraction precision/recall/F1 against human labels.
