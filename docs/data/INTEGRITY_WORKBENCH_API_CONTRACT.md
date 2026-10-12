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
