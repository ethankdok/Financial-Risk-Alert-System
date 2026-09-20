# Development Context Audit (2026-09-20)

This checkpoint distinguishes verified repository/deployment facts from historical
claims. It is not a production migration or deployment approval.

## Repository and branch topology

Verified after `git fetch origin --prune`:

| Ref | SHA | Relationship / scope |
| --- | --- | --- |
| `origin/main` | `34eb1ef` | Old minimal line; ancestor of the later branches, not the integration source. |
| `origin/v4-integration` | `4840bfca855630625d5b298912ec713e74a42296` | Cloud/v4 source merge base. |
| `origin/feature/database-expansion` | `23333d54ce721d9dada59850f4c8ef64e5c9e809` | One commit after v4; database design and first implementation, not merged into release as a whole. |
| `origin/feature/release-delivery` | `a4463252860b0da7b1ed29562d00aaa9275f80d8` | Fourteen commits after v4; current working branch. |
| local `feature/real-experiments-ml-validation` | `111d49d` | Ancestor of release-delivery; no branch of this name currently exists on origin. |

The merge base of database-expansion and release-delivery is `4840bfc`.
They are divergent, so database-expansion must be integrated semantically rather
than merged indiscriminately. The Phase 14 local branch is already represented
in release-delivery history. The historical local identifier `24b0278` is absent
from local objects, refs, reflogs, and the GitHub commit endpoint; only
`23333d54...` can currently be inspected. No force push or ancestry claim is
justified without the full missing object or an exported tree.

`UnaLu027/fintrust-alert` has no Git ancestor in common with this repository.
However, all 54 blobs under its `backend/app` feature branch tree match the blobs
imported under `fintrust_backend/app` by current-repository commit `c18ab90`
(path prefix changed). This is a content import, not shared Git history.

## Deployment versus Git

Cloud Run service metadata was queried directly on 2026-09-20:

| Service | Revision / image tag | Traffic | Source relationship |
| --- | --- | --- | --- |
| `fintrust-api` | `fintrust-api-release-e2e880e` / `release-e2e880e2fb09` | 100% | Commit prefix `e2e880e`; behind current branch. |
| `financial-risk-web` | `financial-risk-web-release-e2e880e` / `release-e2e880e2fb09` | 100% | Commit prefix `e2e880e`; behind current branch. |

The current GitHub branch additionally contains `a446325` (financial-evidence UI
polish). That commit must not be described as deployed. No deployment or traffic
change was performed during this audit.

## Functional ownership and data boundaries

| Domain | Current implementation | Persistence boundary |
| --- | --- | --- |
| Flask risk analysis/admin/member UI | `app.py`, `flask_data_repository.py`, `member_services.py` | Flask repository collections/tables; its `analysis_records` are text-risk records, not financial runs. |
| Existing STRUX Data Shift | `data_shift.py`, `result.html`, `script.js` | Separate protected/manual Data Shift contract; unchanged by this work. |
| Flask financial proxy | `financial_routes.py`, `fintrust_client.py` | Reads FastAPI contracts; does not become a second financial fact writer. |
| FastAPI official financial pipeline | `fintrust_backend/app/routers/financial.py`, `ingestion_pipeline.py`, TWSE/MOPS clients and normalizers | Financial repository collections below. |
| Official events/evidence | official-event source, ingestion, extraction and repository services | `official_events`; read by evidence/text-intelligence services and Flask proxy. |
| Text intelligence / narrative shift | text-intelligence services and unified orchestrator | `text_model_runs`, `text_evidence`; distinct from STRUX whole-document Data Shift. |
| Phase 14 research | experiment scripts, research fixtures and reports | Offline weak-supervision artifacts only; not promoted as production financial facts. |

### Collection writers and readers

| Collection/table | Primary writer | Primary reader |
| --- | --- | --- |
| `admins`, `keywords`, `risk_features`, `audit_logs`, `analysis_records` | Flask `FlaskDataRepository` routes | Flask admin/risk-analysis routes |
| member credentials/profile/watchlist/preferences/history | `member_services.py` through Flask repository | Member APIs and notification processor |
| `companies` | company-universe sync + company master repository | ingestion company resolution and company APIs |
| `financial_filings`, `normalized_financial_facts`, `analysis_runs`, `calculated_metrics`, `rule_results`, `latest_analysis_snapshots` | `AnalysisRepository` pipeline; direct fact ingestion uses the same canonical fact collection | financial APIs, rules, snapshots, claim verification |
| `ingestion_runs` | ingestion-run repository | ingestion status/audit APIs |
| `official_events` | official-event ingestion/promotion services | evidence browser, text intelligence, Flask proxy |
| `text_model_runs`, `text_evidence` | text-intelligence/research promotion services | evidence and narrative-shift APIs/admin UI |

## Verified implementation risks and corrections

Verified against code and the checked-in local SQLite cache, not inferred from
documents:

- The cache has 148 normalized facts, six monthly facts using a quarterly period,
  and twelve latest facts using the income-statement URL as a fallback source.
- The cache contains 2330 annual Q4 facts for 2022-2024 and 2454 annual Q4 facts
  for 2021-2025. The database referenced by the old 5/5 backfill report is not
  present, so that historical success cannot be reproduced from this checkout.
- `companies` and `ingestion_runs` are absent from the checked-in cache. Its
  migration audit therefore remains blocked even after period/source repair.
- Monthly current, previous-month and prior-year-month facts now use canonical
  metric `monthly_revenue`, distinct calendar periods and retained `source_field`.
- Exact source coverage is required; `latest_fact_rows` no longer borrows the
  first available statement source.
- `filed_at` remains unknown when the official filing time is unknown;
  `retrieved_at` is not substituted as announcement/filing time.
- Fact key v2 is shared by pipeline and direct ingestion and excludes the write
  path's `analysis_type`. Migration reports and blocks source-key collisions.
- Batch `refresh_all` is explicitly isolated to 2330/2454 and does not traverse
  every company-master row.

## Migration and scheduling gates

`prepare_financial_sqlite_shadow.py` creates a new copy and refuses to overwrite
an existing output. It does not invent missing company/ingestion metadata.
`migrate_financial_sqlite_to_firestore.py` is dry-run by default, requires the
database audit to pass, converts timestamp fields, preflights target conflicts,
detects legacy/v2 key coexistence, writes in bounded batches, verifies reads,
and only then permits reviewed legacy deletion.

`deploy/cloud-scheduler-financial-refresh.example.yaml` is an unapplied example.
It is scoped to 2330/2454. Cloud Scheduler creation, token provisioning,
production Firestore execution, and deployment remain explicit external gates.

## Fresh 2330/2454 isolation verification

A new official-source run was executed on 2026-09-20 into a newly created
system-temporary SQLite database. It did not reuse the checked-in cache:

- Company-universe sync read 96 TWSE semiconductor companies, with no duplicate
  ticker, while financial refresh executed only 2330 and 2454.
- Both tickers completed five annual filings (`2021FY` through `2025FY`).
- Each ticker produced 91 facts and 112 metrics; demo facts, blank sources,
  duplicate fact keys and duplicate metric keys were all zero.
- 2330 had 4/20 insufficient-data rules; 2454 had 3/20. Neither exceeded the
  configured 25% quality threshold.
- The database contract audit returned `PASS`, including zero monthly-period,
  source-dataset, orphan and SQLite-integrity findings.
- Firestore migration dry-run selected 2 company documents and 464 documents in
  total. It returned `execute=false` and `source_conflicts=[]`.

The 464-document collection breakdown was:

| Collection | Documents | Company/run scope |
| --- | ---: | --- |
| `companies` | 2 | 2330 and 2454 only (the 96-row source universe is not promoted wholesale) |
| `financial_filings` | 10 | Five annual periods per company |
| `normalized_financial_facts` | 182 | 91 canonical facts per company |
| `analysis_runs` | 2 | Latest analysis run per company |
| `calculated_metrics` | 224 | 112 metrics from each selected analysis run |
| `rule_results` | 40 | 20 rule rows from each selected analysis run |
| `latest_analysis_snapshots` | 2 | One latest pointer per company |
| `ingestion_runs` | 2 | Latest ingestion run per company |

The same official sources were fetched a second time into the same temporary
database. Entity collections stayed stable (`companies` 2 selected, filings 10,
facts 182, snapshots 2). Physical append-only history changed as expected:
analysis runs 2→4, metrics 224→448, rules 40→80 and ingestion runs 2→4. An
unbounded migration would therefore grow from 464 to 732 documents. The
migration selector now deliberately includes only the latest analysis and
ingestion run for each approved ticker, keeping the reviewed promotion scope at
464 documents. Full run-history archival remains a separate migration concern.

The first-run plan fingerprint was
`610a10e5ad5b363b5ef5da1a2fd164c4bfd5eda84d585d99de1d4c2cfab510f0`.
After the source rerun, the latest-run-only 464-document fingerprint is
`201fbb212ecf940e79d785888e8ab0d6c806a6352ee1138c160bcef815ff095b`.
The count remains stable while run IDs, retrieval timestamps and current-source
metadata correctly make the content fingerprint change.

No Firestore client was created by the dry-run and no production data changed.

## Unconfirmed items

- The unavailable `24b0278` tree and its exact differences from `23333d54`.
- Production Firestore collection contents, legacy fact-key inventory and
  migration preflight. No production read/write was performed in this step.
- Scheduler service account/IAM and secret-delivery implementation.
- Formal human-ground-truth performance for Phase 14; current evidence remains
  weak supervision and must be labelled as such.

## Preservation requirements

Preserve Flask risk scoring, protected STRUX Data Shift pages/contracts, official
evidence and Text Intelligence, member/admin behavior, and research/production
data separation. Do not merge Flask text-risk `analysis_records` with FastAPI
financial `analysis_runs`, and do not promote research fixtures into production
financial collections.
