# FinTrust user-first UI · 2026-11-24

## Branch and boundaries
- Development branch: feature/fintrust-user-first-ui-20261124
- Parent: feature/fintrust-phase23-integrate-phase11 (integrity/research/member/financial proxies included).
- Main, v4-integration, and parent feature branch have not been edited.
- No Flask / FastAPI / XBRL / ML calculation / database schema files changed in this UI implementation.
- Original detailed financial-integrity.js kept intact; old UI recoverable from parent branch.

## Site map
1. Homepage (index.html): immediate intent-oriented input, client-side .txt content, direct specialist shortcuts.
2. Check Analysis dropdown: Integrated Audit (analysis.html) and Financial Anomaly Audit (financial-audit.html).
   - Integrated Audit is one workflow with selectable methods, not a separate news site.
   - Financial Audit exposes formula/method/model availability and official data details.
3. Member Center (member.html): account settings, watchlist, notification preferences, notification history, honest report-history status.
4. Existing login.html and register.html preserved with unified nav.
Desktop dropdown hover/focus/click; mobile tap-to-open; Esc closes menus.

## Existing backend routes reused
- POST /api/integrity/assessments/preview: current archived financial evidence, research model readiness, JSD and issuer claim evidence; CURRENT_REVIEW only.
- POST /api/financial/claims/verify: user-supplied claim + ticker.
- GET /api/financial/companies/{ticker}/material-events: archived official events.
- POST /api/analyze: existing keyword/rule screening (not fraud probability).
- Existing /api/member/*: registration/profile/watchlist/preferences/notifications/history-state.
Existing Flask proxy routes stay unchanged. The browser never chooses the FastAPI host.

## LLM and unsupported capabilities
- Previously connected narrative-specific LLM untouched; the new homepage uses deterministic routing, NOT a generic LLM agent.
- Automatic scraping of all daily news is not implemented in this read-only workflow. Users may paste content to run supported backend checks.
- Only .txt files below 120 KB are locally read into the query. PDF/image/XBRL processing is NOT connected; unsupported files are not uploaded.
- Historical as-of analysis requires certified publication timestamps. CURRENT_REVIEW cannot be mislabeled as historical prediction.
- Missing Beneish/Dechow variables show as not computable; no synthetic values are substituted.
- Member individual analysis reports are not yet persisted by existing API. Watchlist and notification data are existing backend-backed capabilities.
- Preview result layouts are clearly marked as mock structure only, with no fabricated numeric results.

## Verification and use
Static contract checks passed for HTML IDs, navigation, Flask route names and JavaScript parsing. No live deployed runtime was available for end-to-end verification.

Run after existing Flask + FastAPI services are started:
    python scripts/fintrust_user_first_ui_smoke.py --base http://127.0.0.1:5000 --ticker 1785

The smoke checks pages and live Flask/FastAPI proxies with persist=false assessment. It fails rather than pretending a disconnected backend is healthy.

Before merge: run this smoke, manual desktop/mobile keyboard navigation check, test account features, confirm which supported company is available; review in feature branch before deploying.

## 2026-11-24 UI revision (user feedback)
- Homepage: one short query, three circular entrypoints, on-device recent company queries, and quick actions.
- The Chinese/English toggle uses explicitly authored string pairs in ft-i18n.js, not third-party machine translation. Financial statement and model labels are bilingual.
- Financial audit allows cross-industry ticker/name typeahead, and the industry dropdown is optional. Uploaded MOPS snapshot values cover 50 companies for 2021-2025. Directory-only entries such as 2330 show a no-snapshot state instead of fabricated scores.
- Recent searches save only ticker, short name and timestamp in device localStorage (last seven); not a full question or cross-device report.
- JCAATs financial anomaly classifier is NOT connected. The current Beneish/Dechow uploaded snapshot and integrity preview must not be labeled JCAATs predictions. Future optional integration needs an API with ticker, fiscal period, model name/version, feature inputs, score, calculation time and evidence provenance. Hide the JCAATs section until it exists.
- Preview is deployed separately to Vercel. Original Google Cloud Run URL is not overwritten; switching later requires deployment to the existing Cloud Run service plus Flask/FastAPI verification.


## Preview wiring, 2026-11-24 (Cloud Run backend + front-end demo)
- The Vercel preview uses a fixed-origin external reverse proxy in vercel.json: only /api/* and /health are forwarded to https://financial-risk-web-v53gsmuxdq-de.a.run.app. All frontend requests remain same-origin /api routes, so the production Flask/FastAPI contract remains unchanged. The backend cannot be considered reachable until this path is exercised from a browser or the smoke script. No general proxy endpoint or client-supplied origin is allowed.
- Existing live routes used: GET /api/financial/health, GET /api/financial/companies, GET /api/integrity/companies, POST /api/integrity/assessments/preview (CURRENT_REVIEW/persist=false), GET /api/financial/companies/{ticker}/material-events, POST /api/financial/claims/verify and POST /api/analyze (legacy text rules). Member endpoints remain Flask-session-backed.
- Live buttons invoke these existing routes. An explicit separate "介面示範 / UI demo" button invokes ft-demo.js and displays the actual uploaded MOPS 2021–2025 model values, where available; all unsupported official news/JSD/claim sections remain unverified placeholders, never fabricated responses.
- member-demo.html is an anonymous local-only preview (profile alias, watchlist and notification preferences), not account login or persistent backend records. /member.html remains behind the real membership authentication. Google login remains dependent on proper Firebase public web configuration and approved auth domains.
- If Cloud Run is not publicly reachable from the Vercel proxy or its deployed version lacks the endpoints, API calls fail explicitly. Local demo remains usable. Do not switch the original Cloud Run production site until same-origin API, credentials, member access and integration testing succeed.
- Standalone smoke test: python scripts/fintrust_user_first_ui_smoke.py --base https://fintrust-ui-preview-20261124.vercel.app --ticker 1785. The test does not persist or mutate financial evidence.
- JCAATs financial anomaly model is not integrated and never appears as a computed result.
