# Evidence Provenance Spec

Phase 11A freezes the proposed sentence-level evidence provenance model for Text Mining / Evidence v2. This document is a research specification only. It does not create database tables, migrations, API routes, UI changes, or Firestore writes.

## Current Baseline

Confirmed current official evidence behavior at `4840bfca`:

- `OfficialEvidenceSummary` aggregates financial snapshots, investor conferences, material events, source links, readiness, and limitations.
- `OfficialEvidenceCardResponse` builds a frontend payload with financial snapshot, key metrics, rule cards, conferences, material events, disclosure claims, sources, source status, limitations, and frontend hints.
- `InvestorConferenceRecord` and `MaterialEventRecord` include stable event IDs, source URLs, document URLs where available, status, preview text, related metrics, claims, and limitations.
- `OfficialDocumentExtractionResult` includes source/document URLs, document kind, extraction status, text preview, text length, claims, limitations, error/debug fields, and retrieval time.
- Official event persistence uses `save_official_events()` and stores event-level payload JSON keyed by event type and stable identity.
- Current provenance is source/event/document oriented, not sentence-level.

Current Data Shift behavior:

- `POST /api/data-shift` compares supplied texts.
- `POST /api/data-shift/auto` loads latest two STRUX transcripts at request time.
- JSD, cosine, emerging terms, disappearing terms, and data quality warnings are returned, but supporting terms are not linked back to source sentences.

## Proposed V2 Sentence-Level Schema

Required fields:

| Field | Description |
| --- | --- |
| `evidence_id` | Stable id for this sentence-level evidence item. |
| `ticker` | Company ticker. |
| `company_name` | Company name. |
| `source_type` | Source category, such as `investor_conference`, `material_event`, `official_ir`, `financial_snapshot`. |
| `source_name` | Concrete source label such as `mops`, `twse_openapi`, or `company_official_ir`. |
| `source_url` | Official source page or OpenAPI URL. |
| `document_url` | Direct document URL when available. |
| `event_date` | Event or disclosure date when available. |
| `period` | Fiscal period, event period, or comparison period. |
| `retrieved_at` | Retrieval timestamp. |
| `document_kind` | Current kinds include `html`, `pdf`, `presentation`, `spreadsheet`, `transcript`, `video`, `unknown`. |
| `extraction_status` | Extraction state, e.g. `text_extracted`, `document_link_found`, `metadata_only`, `blocked_by_source`. |
| `parser_version` | Version/name of parser used to produce this item. |
| `document_hash` | Hash of downloaded artifact or stable source metadata when artifact is unavailable. |
| `text_hash` | Hash of extracted normalized text used by metrics. |
| `section` | Section label from segmentation. |
| `sentence_id` | Stable id within source document/section. |
| `original_text` | Original sentence text. |
| `relevant` | Human/system relevance decision, with provenance of method. |
| `primary_topic` | Canonical primary topic. |
| `secondary_topics` | Optional canonical secondary topics. |
| `related_metrics` | Metrics connected to this evidence, such as `revenue_growth_yoy` or `capex_intensity`. |
| `extraction_method` | Human, rule-based, parser, classifier, embedding, or LLM-assisted method marker. |
| `confidence` | Confidence score if produced by a system; nullable for human labels. |
| `limitations` | Source, extraction, parsing, or annotation limitations. |

## Provenance Chain

Intended chain:

```text
Official site
-> document URL
-> downloaded artifact
-> extracted text
-> section
-> sentence
-> relevance decision
-> topic decision
-> JSD/Cosine input
-> final risk/evidence output
```

Every displayed textual claim must be traceable back to official source evidence. If the system only has metadata or a blocked source, the display must say so instead of implying full-text extraction.

## Source Transparency

Current sources found in code:

| Source | Current code behavior |
| --- | --- |
| MOPS investor conference source | `MOPS_BASE = https://mops.twse.com.tw/mops/web`, conference query path `t100sb07_1`, with GET/AJAX/POST variants. |
| MOPS material event source | Material event query path `t05st01`, with GET/AJAX/POST variants and optional detail-page parsing. |
| TWSE Material Events OpenAPI | `https://openapi.twse.com.tw/v1/opendata/t187ap04_L`; used for material events and for detecting investor-conference announcements. |
| Official company IR fallback for `2330` | TSMC investor quarterly results / investor meeting URLs are listed as fallback candidates. |
| Official company IR fallback for `2303` | UMC quarterly results / IR event URLs are listed as fallback candidates. |
| Official company IR fallback for `2454` | MediaTek investor relations financial information and IR event URLs are listed; current parser extracts quarterly earnings document links. |
| Official company IR fallback for `3711` | ASE official financial/website URLs are listed as fallback candidates. |

Current source status meanings:

| Label | Meaning |
| --- | --- |
| `LIVE OFFICIAL DATA` | The system fetched official source data directly and parsed usable data. |
| `OFFICIAL DOCUMENT LINK` | The system found or preserved an official document URL, but may not have extracted full text. |
| `SEEDED INDEX FALLBACK` | A narrow source-labelled fallback using known official URLs after official company sites return 403. This is not live crawling. |
| `METADATA ONLY` | The system has source/event metadata or query entry points without usable document text. |
| `BLOCKED SOURCE` | The official source blocked access, returned a security page, or produced 401/403/429-like behavior. |

Current limitations confirmed from source:

- Official source blocking is explicitly detected for some MOPS/security-page and company-IR 403 cases.
- MOPS live fetch can return blocked, error, no usable HTML, or parser-debug-only states.
- TWSE OpenAPI material events do not provide a MOPS detail page URL in that feed; the system preserves dates, clauses, title, and description text.
- Document extraction supports text-like responses and attempts PDF extraction through `pypdf`, but complicated PDFs, tables, and video are not guaranteed to be parsed.
- Video/webcast URLs are classified as `video` and preserved for manual/frontend use; video is not directly parsed.
- Seeded official IR fallback currently exists for a narrow set of official URLs and must not be described as live crawling.
- Manual review is required when extraction status is metadata-only, blocked, unsupported, or preview-only.

## Display Rule

Displayed textual evidence should include:

- Source name and URL.
- Document URL when available.
- Status or extraction status.
- Sentence or preview text.
- Limitations.
- Linkage to related metric/topic where applicable.

If the system cannot provide sentence-level provenance for a displayed claim, the UI/API should mark the claim as document-level or preview-level evidence until V2 provenance is implemented.

## Current Implementation Gap

Confirmed gaps between current implementation at `4840bfca` and proposed V2:

- Current evidence provenance is event/document level, not fully sentence level.
- Current event IDs are stable hashes for event identity, not sentence evidence IDs.
- Current document hashes and text hashes are not consistently stored as first-class provenance fields for official text evidence.
- Current `source_evidence` stores labels/topics/previews, but it is not a full chain from downloaded artifact to sentence to metric input.
- Current document extraction is preview-oriented and exposes limitations/debug status; it does not yet provide a full extracted corpus with section and sentence IDs.
- Current evidence cards expose source status and limitations, but not sentence-level support for each drift term, topic increase/decrease, or displayed textual claim.
