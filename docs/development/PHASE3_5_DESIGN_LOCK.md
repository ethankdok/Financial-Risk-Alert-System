# Phase 3–5 design lock: architecture → repository mapping

Locked before implementation, from a read-only inventory of the local repository at
`506b64cb62f9a31353d87444f0080fa6540cf759` (`feature/historical-1785-fy2023-2025`). Integration branch:
`feature/phase3-5-research-integration`. Inputs: `docs/development/phase3_5_handoff/` (one-pass prompt,
architecture v2, Phase 2C independent audit; untracked, preserved, not committed).

## 1. Actual system boundaries (verified, not assumed)

| Layer | Actual implementation | Notes |
|---|---|---|
| FastAPI | `fintrust_backend/app/main.py` + `app/routers/{financial,conference_pdfs,official_events,text_mining}.py`, prefix `/api/v1/financial` | Auth for writes: `require_ingestion_token` (`X-Ingestion-Token`, `INGESTION_API_TOKEN`); GET routes are unauthenticated; CORS from `CORS_ALLOW_ORIGINS` |
| Flask | root `app.py` + `financial_routes.py` blueprint (proxy through `fintrust_client.FinTrustClient`), `data_shift.py` blueprint | Serves static HTML/JS from repo root; session auth for admins |
| Frontend | **Plain HTML + inline/vanilla JS + `style.css`** at the repo root (`financial-evidence.html`, `result.html`, `official-data-shift.js`, …) | **There is no React/Tailwind/Vite in this repository.** The research UI follows the actual vanilla style. Node (v22) is used by existing tests to execute page scripts against a fake DOM |
| Historical research data | `fintrust_backend/data/historical_audit/historical_audit.sqlite3` (gitignored), raw archive `data/historical_audit/raw`, conference archive `data/historical-conference-pdfs` | Approved, immutable for this phase |
| Research read contract | `app/services/historical_audit/research_access.py` (`ResearchBackend`, `LocalResearchBackend`, `FirestoreResearchBackend`) | Reused; extended additively (disclosed values, publication events) with SQLite/Firestore parity |
| Conference → JSD | `conference_jsd_corpus_adapter.py`, `conference_document_identity.py`, `docs/data/JSD_INPUT_CONTRACT.md`; teammate JSD (`data_shift.py`, `jsd_method.py`, SHA-pinned) | Read-only; not modified |
| Cloud | `historical_audit/cloud_config.py` (fail-closed, disabled by default), `cloud_sync.py`, `firestore_repository.py`, `object_storage.py`; `Dockerfile.fastapi/flask`, `deploy/cloudbuild-*.yaml`, `docs/cloud/*` | No live resources touched |
| Production universe | `company_registry.py`, company master, `refresh_all()` | 1785 never added |

Tooling verified locally: Python 3.14 venv (FastAPI 0.141, Flask 3.1, pypdf 6.18, PyMuPDF), Node 22, Chrome/Edge
(headless screenshots), gcloud SDK **without** the Firestore emulator component, Java 25, no Docker.

## 2. Mapping

| Architecture item | Status | Repository decision |
|---|---|---|
| `ResearchBackend` | existing → reused | Added `list_disclosed_values`, `list_publication_events` to both backends (parity-tested) |
| Feature registry / input snapshot / evidence policy / bridge / features / literature gates / reconciliation / text bridge / runs | missing → implemented | New package `fintrust_backend/app/services/financial_research/` |
| Case registry (events, hypotheses, legal sources) | partially existing (`historical_audit/cases/1785.json`, identity only) → extended | `financial_research/case_knowledge.py` (events & hypotheses, source class) ; labels isolated in `financial_research/case_labels.py` |
| Derived-results persistence | missing → implemented | **Separate** SQLite file `data/historical_audit/research_results.sqlite3` (append-only, SQL triggers forbid UPDATE/DELETE). The approved historical DB is opened read-only and never migrated |
| Firestore parity for derived results | missing → implemented | `financial_research/result_store.py` `FirestoreResearchResultStore` (fake + emulator-gated tests); collections prefixed `historical_research_results` |
| API | missing → implemented | `app/routers/historical_research.py`, prefix `/api/v1/research` |
| Flask proxy | existing pattern → extended | new `research_routes.py` blueprint (`/api/research/...`), `FinTrustClient` methods; no calculation in Flask |
| Research UI | missing → implemented | `historical-research.html` + `historical-research.js` (six views) |
| Beneish / Dechow full models | **unavailable → explicitly not delivered** | Readiness gates only (`not_computable`); no coefficients shipped |
| Jones / Modified Jones / Kothari | **unavailable** | `not_computable` (no multi-company panel) |
| 1785 JSD values | **unavailable** | 0 JSD-ready records; status only |
| Firestore emulator run | **environment-blocked** (component not installed, no Docker) | emulator tests stay gated; reproduction command documented |
| Live cloud / deployment | **not authorized** | runbooks + read-only preflight only |

## 3. Analysis modes (mandatory everywhere)

`RETROSPECTIVE_FORENSIC` (hindsight=true), `STRICT_AS_OF` (requires timezone-aware `cutoff_at`, exclusive:
`effective_available_at < cutoff_at`), `CURRENT_EVIDENCE_RECONCILIATION`. No default: a missing mode is a 422.
`cutoff_at` is rejected for the other two modes (no ambiguous mixed requests). Strict inputs come only from
`ResearchBackend.list_facts(as_of=cutoff_at − 1 µs)` (the reader's as-of is inclusive for datetimes), and every
returned row is re-checked `< cutoff_at`; nothing ever falls back to full data.

## 4. Locked API (FastAPI, prefix `/api/v1/research`)

| Method & path | Modes | Notes |
|---|---|---|
| `GET /health` | – | readiness of dataset & result store (no paths) |
| `GET /cases` | – | registered historical cases only (`production_universe=false`) |
| `GET /cases/{ticker}` | – | overview, coverage, mode badges |
| `GET /cases/{ticker}/timeline` | RETRO, STRICT | evidence tier E1/E2-capable, precision, pagination |
| `GET /cases/{ticker}/restatement-bridge` | RETRO, STRICT | `scope=consolidated|individual|all` |
| `POST /financial-signals/compute` | all three | dry-run by default; `persist=true` needs `X-Ingestion-Token` |
| `GET /cases/{ticker}/feature-registry` | all three | definitions + literature readiness |
| `GET /cases/{ticker}/source-discrepancies` | RECON only | match / mismatch_unresolved / not_comparable |
| `GET /cases/{ticker}/text-readiness` | RETRO, STRICT | archive & JSD readiness, never a JSD number |
| `GET /runs/{run_id}` | – | immutable persisted run |

Errors: `422` invalid/missing mode, missing cutoff, naive datetime, out-of-range years; `404` unknown ticker (production
tickers are not research cases); `409` mode not supported by endpoint; `503` research dataset unavailable. Responses
never contain filesystem paths, raw bytes or non-official URLs (host allowlist).

## 5. Locked derived-result schema (`research_results.sqlite3`)

`research_dataset_snapshots`, `research_methods`, `research_runs`, `research_features`,
`research_restatement_bridges`, `source_discrepancies`, `case_research_labels`. Run identity
`rrun1_<sha256(method_version, input_digest, canonical parameters)[:32]>` → re-running identical input is idempotent;
a correction is a new run (`supersedes_run_id`), never an overwrite. `created_at`/`git_commit` are reviewer metadata,
excluded from digests. Labels are read only through `case_labels.py`, which feature/policy modules may not import
(AST-tested).

## 6. Ownership

Method specs are versioned `DRAFT_PENDING_METHOD_OWNER_REVIEW` (Yu-Jing). JSD algorithms, thresholds, tokenizer and
calibration remain Ethan's; FinTrust only reports readiness from the unchanged adapter.
