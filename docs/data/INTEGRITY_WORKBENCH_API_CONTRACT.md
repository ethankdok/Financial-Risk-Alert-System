# Integrity Workbench API contract (`integrity_workbench_contract_v1`)

Read-only. Nothing in this API persists, ingests, refreshes, extracts documents, fetches live MOPS data or calls an LLM. Every amount is returned as a Decimal string.

## FastAPI (`/api/v1/integrity`)

| Method | Path | Notes |
|---|---|---|
| GET | `/companies` | Lists the reviewed seed companies, each with `persisted_snapshot`. |
| GET | `/companies/{ticker}/readiness` | Per-module availability. No JSD calculation or claim verification runs here. |
| POST | `/assessments/preview` | Body: `{"ticker", "review_mode": "CURRENT_REVIEW", "persist": false, "sections": [...]}` |

Request rules for `POST /assessments/preview`:

- Unknown fields are rejected with `extra="forbid"`.
- `persist` accepts only `false`.
- `sections` is a subset of `financial_checks`, `literature`, `jsd` and `claims`.

| Status | Meaning |
|---|---|
| 404 | `ticker_not_supported`. The ticker is not a registered company. Research case 1785 also returns 404. |
| 409 | `review_mode_not_supported`. Sent for `STRICT_AS_OF`, because the facts carry no publication instant. |
| 422 | Invalid body, `persist: true`, an extra field, or an unknown section. |
| 503 | `integrity_data_unavailable`. The fact repository cannot be read. |

### Preview response

**Request echo and mode**
- `ticker`, `company`, `review_mode` (always `CURRENT_REVIEW`).
- `point_in_time_supported=false`, `hindsight=false`, plus a note.
- `persist=false`.

**Dates and approval**
- `generated_at`.
- `data_latest_available_at` is always null, because publication times are unknown.
- `data_latest_ingested_at`.
- `method_approval` is `DRAFT_PENDING_METHOD_OWNER_REVIEW`.
- `disclaimers`.

**Coverage and overview**
- `source_coverage`.
- `financial_overview`: annual MOPS XBRL rows and the official-sources summary, with live fetch off.

**Findings**
- `financial_findings[]`: F1, F2 and F4, plus data-quality findings.
- `claim_checks[]` and `claim_findings[]`: F3 checks.
- `narrative_findings[]`: present only when a calibrated, compatible JSD pair exists.

**Paper models**
- `paper_models[]`: Beneish and Dechow, both `not_computable` with `raw_score=null`.

**Data shift**
- `data_shift`: raw JSD and Cosine, the compatibility checks, and `calibration_status`.
- `drift_level` is null unless the shift is calibrated.

**Evidence and next steps**
- `evidence_records[]`: typed `EvidenceRecord`s. Links are on the official allowlist only, and missing metadata is listed in `missing_fields`.
- `investigation_priority`: the queue rule and its version, `triggered_by`, the distinct evidence families, an independent-corroboration count, and `fraud_probability=null`.
- `next_checks[]`: B2B checks, each with `is_risk_conclusion=false`.
- `missing_data[]`.

**Versions and digests**
- `method_versions`, `dependency_digests`.

### Enums

| Field | Values |
|---|---|
| `FindingStatus` | `descriptive_divergence`, `within_screening_heuristic`, `descriptive_gap`, `supported`, `conflicting`, `insufficient_evidence`, `inconclusive`, `not_computable`, `not_comparable`, `unavailable` |
| `FindingFamily` | `model_screening`, `financial_consistency`, `source_discrepancy`, `narrative_change`, `data_quality` |
| `ReviewQueue` | `requires_verification`, `monitor`, `insufficient_evidence`, `no_item_triggered` |

`no_item_triggered` is not a low-risk statement.

## Flask proxy (`/api/integrity`)

The routes `/companies`, `/companies/<ticker>/readiness` and `/assessments/preview` forward to the FastAPI service. The proxy:

- checks the ticker pattern;
- whitelists the body fields;
- always sends `persist: false`;
- never sends the ingestion token;
- passes backend status codes 403, 404, 409, 422 and 503 through with their detail, and returns 502 when the backend is unreachable.

The page is `financial-integrity.html` with `financial-integrity.js`. It uses `textContent` only.

---

## Phase 1.1 (`integrity_workbench_contract_v2`)

### Old → new field mapping (v1 → v2)

| v1 | v2 | Change |
|---|---|---|
| `Finding.period` / `status` | Unchanged names | Now always describe the **latest fiscal year** (CR-02). |
| — | `Finding.latest_fact_fiscal_year`, `latest_period_status`, `freshness_status`, `last_computable` | New. `freshness_status` is one of `current`, `latest_period_not_computable`, `no_computable_period` or `not_applicable`. |
| — | Response `freshness` | `latest_fact_fiscal_year`, `stale_findings[]`, `rule`. |
| — | Response `assumptions[]` | `report_id=C` → consolidated; FY ends 31 Dec; no source SHA or publication time; validated MOPS only. |
| `EvidenceRecord.independence` | Adds `unverified_source` | Used for rows whose URL fails validation (CR-01). |
| — | `EvidenceRecord.source_trust`, `candidate_evidence_ids`, `selection_policy` | New (CR-01 / CR-03). |
| `F2.computed.net_income_minus_cfo_twd` | Kept, plus `cfo_minus_net_income_twd` | Both sign conventions are reported (CR-06). |
| — | `ClaimCheck.quote_extraction` | Re-verified quote lineage (CR-04). |
| `investigation_priority` | Adds `stale_findings` | A stale finding can neither trigger nor clear the queue. |

### Method version changes

The version identifiers changed as follows. `alignment`, `facts_adapter`, `claims_adapter`, `f1`, `f2`, `composer` and `review_queue_rule` moved from v1 to v2. `issuer_statement_registry` also moved to v2. These stayed at v1 or are new at v1: `literature_readiness_adapter`, `jsd_adapter`, `f4_revenue_nfm_readiness`, `quote_extraction` (new), `case_1785_view` (new) and `case_1785_event_registry` (new). These are engineering version identifiers. They do not mean the method has been approved; method approval remains `DRAFT_PENDING_METHOD_OWNER_REVIEW`. Genuine 2330/2454/3711 decision fields are identical to the accepted `0c51a74` output.

### Retrospective research case (`RETROSPECTIVE_CASE`)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/integrity/research-cases/{ticker}/summary?version_policy=latest_available\|original_only` | Only `1785` is served; any other ticker returns 404 `research_case_not_supported`, with no substitution. `version_policy` is required (422 if it is missing or unknown). |

How the endpoint works:

- It is read-only and never persists anything.
- It recomputes on demand through `ResearchService.build_run` dry runs, using the unchanged Beneish and Dechow engines.
- It makes no LLM calls and no live network requests.

Response fields:

| Field | Content |
|---|---|
| `review_mode`, `hindsight`, `banner`, `separation` | `review_mode = RETROSPECTIVE_CASE`, `hindsight = true`, plus the banner and the separation notice. |
| `dataset_identity` | Run id, digests, method version and `matches_accepted_run`. |
| `counts`, `baseline_check` | Matched against the accepted 26/34 result, the withdrawn cells and the FY2012 value. |
| `cells[]` | Status, score, components and bounded observations (at most 4 per component, plus a total). Also missing reasons, filing versions and zero-proof use. |
| `series` | GMI, TATA, ch_inv, rsst_acc and soft_assets. |
| `inventory_turnover_readiness[]` | Readiness only; no values. |
| `crosswalk[]` | The feature crosswalk. |
| `strict_pre_event` | Computed at the 2016-05-13 cutoff; null scores. |
| `events[]` | Each event carries a verification status (`verified_official_document`, `official_listing_only` or `needs_source_verification`) and has `used_in_model_calculation=false`. |
| `event_registry`, `restatement_evidence`, `limitations` | Registry metadata, the restatement evidence and the stated limitations. |

When the data is unavailable, the endpoint returns 200 with `status = source_unavailable` and instructions, and no scores.

The Flask proxy path is `GET /api/integrity/research-cases/<ticker>/summary`. It checks the ticker pattern and whitelists `version_policy`, returning 400 otherwise. It passes 404/422/503 through.

The page is `financial-integrity-case.html`, reached through one link from `financial-integrity.html`.
