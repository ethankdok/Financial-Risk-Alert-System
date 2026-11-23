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
