# FinTrust × JCAATs: future integration contract (planning only)

Status: NOT CONNECTED. This design must not be presented as an existing classifier endpoint.

## 1. Existing callable backend paths
- Flask: POST /api/financial/admin/companies/{ticker}/refresh, admin-session protected; uses FinTrustClient.refresh_company and downstream /api/v1/financial/admin/companies/{ticker}/refresh with ingestion-token handling.
- Flask: POST /api/financial/admin/companies/{ticker}/unified-refresh, admin-session protected; downstream /api/v1/financial/admin/companies/{ticker}/unified-refresh. This is a **refresh** path, NOT a JCAATs model-inference path.
- Flask: GET /api/financial/companies/{ticker}/analysis/latest (current persisted financial analysis).
- Flask: GET /api/financial/companies/{ticker}/metrics and /card (existing official evidence, screening rules, narrative shift).
- Flask: POST /api/integrity/assessments/preview exists on the feature branch but currently returns 404 from deployed Cloud Run. Do not use it as a required live dependency.
- The uploaded MOPS iXBRL source snapshot is separate from the above Cloud Run semiconductor operating analyses; it contains Beneish/Dechow values for 50 companies across oil/gas and electronics distribution (2021-2025).

## 2. Preferred JCAATs architecture
**A. JCAATs acts as job trigger:** authenticate an operator/server with least privilege -> enqueue a requested company/fiscal-period job -> orchestrator invokes an explicitly allowlisted Python pipeline entrypoint (company roster, official evidence ingestion, as-of X feature computation, anomaly scoring) -> persist a versioned assessment with evidence references -> front-end GET results. This works ONLY if the actual anomaly scoring module is in the FinTrust Python environment. The existing refresh route does not prove that JCAATs is integrated.

**B. JCAATs does the scoring:** after shared canonical X features are exported, JCAATs trains/scores and exports machine-readable scored rows. FinTrust validates, ingests, and displays the scores with model version and source metadata. Merely triggering FinTrust .py would NOT reproduce JCAATs scores if scoring happens inside JCAATs.

## 3. Data contract for every future model result
- identity: ticker, fiscal_year, filing_period, scope (consolidated vs separate), industry, cutoff_at, first-published filing reference, model_name, model_version;
- provenance: each X input's source report, reporting period, original/revised filing version, units, source concept and missing flags; no post-label or revision leakage when claiming prediction;
- compute: feature_vector, feature_calculation_version, input_coverage, missing_reason, risk_score if available, alert_policy version (do NOT reuse arbitrary cutoffs);
- execution: job_id, status (queued/running/succeeded/failed), requested_at, completed_at, error_code and immutable result reference;
- prediction: label taxonomy (Y1–Y4 as defined by research), training/test time split, approved calibration and quality-review status.

## 4. Safety and rollout
- Never expose a generic remote 'execute Python file' endpoint, arbitrary shell commands, model training from the browser, or ingestion credentials in JavaScript.
- Use a stable, authenticated API to create an allowlisted queued job, not direct synchronous execution of slow scripts in Flask.
- Keep the existing backend's MOPS source, historical versions, financial rules, JSD and official claims independent from JCAATs optional scored results.
- The UI has one **企業健檢** entry, with modules for official financial health, upload-based Beneish/Dechow computations, JSD and source evidence. Only show a JCAATs-specific tab once a real model result API exists.
- Deploy/test on a separate branch and preview, preserve Cloud Run production until validated; enforce idempotency and prevent duplicates.
