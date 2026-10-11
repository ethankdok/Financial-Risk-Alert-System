# Historical research API contract (Phase 4)

Implemented in `fintrust_backend/app/routers/historical_research.py` (FastAPI, prefix `/api/v1/research`), proxied by
`research_routes.py` (Flask, prefix `/api/research`). OpenAPI snapshot of these routes: `docs/data/openapi_research_v1.json`
(generated from the running app; 11 paths). Everything here is **read-only research evidence** about reviewed historical
cases; it is not investment advice, not a fraud determination and never feeds risk thresholds, scores or notifications.

## Analysis modes (required, no default, no fallback)

| Mode | Meaning | `cutoff_at` |
|---|---|---|
| `RETROSPECTIVE_FORENSIC` | Full archive incl. the 2016-11-13 restatement notices; `hindsight=true` | forbidden (422) |
| `STRICT_AS_OF` | Only observations with `effective_available_at < cutoff_at` | **required**, timezone-aware ISO-8601 instant, exclusive |
| `CURRENT_EVIDENCE_RECONCILIATION` | Exact cross-source comparison of currently verifiable official sources | forbidden (422) |

A bare date (`2016-05-13`) or naive datetime is rejected (`cutoff_at_not_instant` / `cutoff_at_naive`). Strict views read
only the reader's point-in-time rows; every row is re-checked against the cutoff and nothing is filled from full data.

## Endpoints

| Method / path | Modes | Response essentials |
|---|---|---|
| `GET /health` | – | `status` (`ready`/`degraded`), dataset / conference archive / PDF evidence availability (booleans only) |
| `GET /cases` | – | registered historical cases, `production_universe=false`, priority period vs research coverage |
| `GET /cases/{ticker}` | – | coverage counts (facts 234, PIT 67, comparisons 158, events 919, versions 44), key events with evidence tier, hypotheses with source class |
| `GET /cases/{ticker}/timeline` | RETRO, STRICT | events with `available_from`, `publication_precision`, `evidence_tier` (`E1_official_listing_metadata` / `E2_verified_notice_quote` / `E2_verified_official_document`), `source_document_included`; `evidence_tier`, `limit` (≤1000), `offset` |
| `GET /cases/{ticker}/restatement-bridge` | RETRO, STRICT | `rows` (158 in RETRO), `year_bridges`, `heatmap`, `integrity`, `hypothesis_links` (RETRO only), `warning`; `scope=all|consolidated|individual` |
| `GET /cases/{ticker}/feature-registry` | all | feature definitions (formula, version, required metrics, policies, literature reference, proxy flag, allowed modes, approval status) + literature-model readiness |
| `GET /cases/{ticker}/source-discrepancies` | RECON | `counts` per comparison type (board notice 40/2/18; restatement post side 27/0/67; TPEx 0/0/45), `consistency` (`INCONSISTENT` / `CONSISTENT` / `INCONCLUSIVE_NOT_COMPARABLE`), `comparisons` with fail-closed `reasons`, `discrepancies` (FY2025: 2 items × 1,721 thousand TWD; PDF evidence with exact version, SHA-256 and unit/fiscal-year/scope `identity_checks`), `dependency_digests`, `routes_to_risk_score=false` |
| `GET /cases/{ticker}/text-readiness` | RETRO, STRICT | archive (44 records / 38 SHA / 1,190 pages / 1,139 text pages / 26 listing rows), `jsd_ready_records=0`, `jsd={"status":"NOT_APPLICABLE","value":null}` |
| `POST /financial-signals/compute` | all | body `{ticker, analysis_mode, cutoff_at?, start_year?, end_year?, version_policy, persist=false, supersedes_run_id?}` → `run_id`, `input_digest`, `output_digest`, `persisted`, `created`, `result` |
| `GET /runs/{run_id}` | – | immutable persisted run (`rrun1_<32 hex>`) incl. snapshot identity and output |
| `GET /runs/{run_id}/verify` | – | recompute from the current archive: `reproducible` / `inputs_changed_since_run` / `output_differs_for_same_input` |

`version_policy` is required for computation (`latest_available` | `earliest_available` | `original_only`). Years must lie
within the case's research coverage (1785: 2011–2025), at most 15 per request.

## Errors

| HTTP | `detail.error_code` examples |
|---|---|
| 404 | `not_a_historical_research_case` (e.g. 2330/2454 — production tickers are not research cases), `run_not_found` |
| 409 | `analysis_mode_not_supported` (e.g. reconciliation on the timeline, RETRO on source-discrepancies) |
| 422 | `analysis_mode_required`, `analysis_mode_invalid`, `cutoff_at_required`, `cutoff_at_not_instant`, `cutoff_at_naive`, `cutoff_at_not_allowed`, `version_policy_required`, `year_range_invalid`, `year_range_too_large`; FastAPI validation for patterns |
| 401 / 503 | `persist=true` without a valid `X-Ingestion-Token` (503 in production when no token is configured) |
| 503 | `research_dataset_unavailable` (dataset not provisioned in this deployment) |

## Reconciliation inputs are frozen (v2, debug pass)

In `CURRENT_EVIDENCE_RECONCILIATION` the snapshot also freezes the TPEx summary rows (`summary_view_v1`, no retrieval
metadata) and the audited-PDF evidence used for the output (`pdf_balance_sheet_totals_v2`: exact filing version, content
SHA-256, page, extracted lines and identity checks, or an explicit `unavailable` record with a reason). These dependencies
and their versions are part of `input_digest` and therefore of `run_id`; `dependency_digests` reports each one. PDF
equality is claimed only when unit, fiscal year and consolidated scope are all `verified`; otherwise the check is
`not_comparable` with reasons and `null` equality. Strict and retrospective digests are unchanged.

## Statuses shown to users

`READY`, `PARTIAL`, `NOT_COMPUTABLE` (incl. `insufficient_point_in_time_evidence`), `EVIDENCE_UNVERIFIED`, `INCONSISTENT`,
`NOT_APPLICABLE`, `NOT_READY`; per value `computed` / `not_computable` / `not_applicable` with `missing_reasons`
(`missing_input`, `no_verified_observation_before_cutoff`, `missing_prior_period`, `zero_denominator`,
`negative_denominator`, `version_mismatch`, `scope_mismatch`, `unit_mismatch`, `accounting_regime_break`,
`framework_unknown`, `feature_not_applicable_in_mode`). Missing evidence is never rendered as low risk.

## Provenance carried per value

Ticker, period, statement scope, accounting framework, metric, exact Decimal string, unit, filing version id and type,
`effective_available_at` + `availability_scope`, availability evidence kind/ref/hash/URL, `observation_evidence_status`
(E2) and `artifact_evidence_status` (E3/E0) as independent dimensions, artifact SHA/URL (withheld in strict mode when the
artifact was not public at the cutoff), method/registry versions, `analysis_mode`, cutoff, `input_digest`. Retrieval and
creation times are reviewer metadata (`created_at`, `git_commit` in persisted runs only) and never part of a digest.

## Safety properties

- Only official regulator URLs (`mopsov/mops/doc/www.twse.com.tw`, `emops.twse.com.tw`, `www.tpex.org.tw`) are emitted;
  anything else is withheld (`null`). No filesystem paths, raw bytes or ZIPs are returned.
- GET routes never create files; the result store is created only by an authorized `persist=true` or the CLI.
- The Flask proxy whitelists query parameters per view, validates tickers and run ids, forces `persist=false`,
  and passes FastAPI 404/409/422/503 through with their structured detail.
