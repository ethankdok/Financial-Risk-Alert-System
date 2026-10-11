# Phase 3–5 consolidated debug pass — validation

Input: independent review of commit `e4fb1e7943dc59680f087b6e6b3f3abd8590566a` (debug specification
`docs/development/FinTrust_Phase3-5_Consolidated_Debug_Prompt_2026-10-11.md`, untracked user input; the file name differs
from the `PHASE3_5_CONSOLIDATED_DEBUG_PROMPT.md` path cited in the request). Branch `feature/phase3-5-research-integration`.
Fix commit `612c517`. None of the findings concerned the official financial values; the approved archive is unchanged.

## Before / after reproduction

`python docs/development/evidence/phase3_5_debug_repro.py` runs the reviewer cases in a temporary worktree of `e4fb1e7`
("before") and in the working tree ("after"), each in its own interpreter with its own unmodified modules:

| Finding | Reviewer case | before (`e4fb1e7`) | after |
|---|---|---|---|
| P1-F01 | TPEx summary 100 → 200 | input digest **unchanged**, output digest changed (→ deterministic-run conflict on persist) | input digest and run id change; identical inputs → identical run id / output digest |
| P1-F02 | notice TIFRS vs XBRL `WRONG_FRAMEWORK`, equal amounts | `match`, no reason | `not_comparable` (`framework_mismatch`) |
| P2-F03 | PDF unit unverified, line 100 vs 100,000 TWD | `equals_filed_xbrl=True`, `equals_board_notice=True` | `not_comparable` (`unit:unit_unverified`), equality `null` |
| P2-F04 | config prefix `historical_research_staging_abc` | store prefix `historical_research_results` | `historical_research_staging_abc_results` |

## Root causes and fixes

**P1-F01 (frozen dependencies).** `reconcile()` queried `backend.list_summary_observations()` and
`pdf_provider.statement_totals()` after the snapshot digest was taken. Now `source_reconciliation.freeze_dependencies()`
runs inside `ResearchService.snapshot()` for every `CURRENT_EVIDENCE_RECONCILIATION` request (standalone reconciliation
runs and `financial_signals` runs alike). It freezes a typed view of the summary rows without retrieval metadata
(`summary_view_v1`) and the PDF evidence used for the output. That evidence is either an `extracted` record (version id,
re-verified SHA-256, page, lines, identity checks, parser version) or an explicit `unavailable` record with a reason.
PDF evidence is frozen exactly for the fiscal years with an unresolved board-notice mismatch, which is a pure function of
the frozen facts and notices. `InputSnapshot` includes these and their versions (`reconciliation_dependency_versions`)
in `input_digest`, and reports per-dependency `dependency_digests`. The run method identity now contains the PDF parser
version (`source_reconciliation_v2+pdf_balance_sheet_totals_v2`). `reconcile(snapshot)` refuses unfrozen snapshots
(`reconciliation_inputs_not_frozen`). Strict and retrospective snapshots and their digests are unchanged; no
reconciliation data enters PIT model inputs.

**P1-F02 (fail-closed compatibility).** Restatement post-side and board-notice comparisons require, on top of the
period/scope/metric key, all of the following:
- the same full-year period;
- a known filed-fact framework equal to the notice framework and consistent with the fiscal year's regime;
- verified notice availability;
- a convertible notice unit and equal fact unit;
- a valid sign factor (±1);
- a present post-side label and value;
- `filing_version_type == restated` (restatement), or not `restated` and the annual board-approval kind (board notice).

Anything uncertain is `not_comparable` with explicit reasons. Comparison rows without a filed fact are now reported
(`no_filed_fact_same_period_scope_metric`) instead of being silently skipped.

**P2-F03 (PDF identity).** `ArchivePdfEvidenceProvider.statement_evidence()` selects the single consolidated annual
PDF whose `filing_version_type` equals the compared XBRL version's. It never selects by sort order: an ambiguous set or
no compatible version yields `unavailable`. The provider re-hashes the bytes against the version's `content_hash` and
records three checks:
- `unit` (單位：新台幣千元);
- `fiscal_year` (ROC reporting year on the page = FY − 1911);
- `statement_scope` (合併資產負債表).

`pdf_check()` claims equality only when all three are `verified`. Otherwise each check is `not_comparable` with reasons
and `null` equality.

**P2-F04 (namespace).** `result_sync.result_prefix(config)` = `<config.collection_prefix>_results`, validated by
`RESULT_PREFIX_PATTERN` (`historical_research[_<ns>]_results`). Writes are allowed only to `emulator` and `isolated-test`
configurations; anything else raises `PermissionError`. The default prefix still maps to `historical_research_results`.

## Additional hardening

1. **Endpoint compatibility.** All routes, modes and status codes are unchanged; the API/Flask/UI chain tests pass.
2. **Flask static route.** The `0427418` fix is kept. Names containing `backup`, `_before_`, `.bak`, `.orig`, `.tmp`,
   `~`, `:`, `%` or NUL are now also refused. New tests cover encoded, double-encoded and backslash traversal, `::$DATA`,
   NUL, and backup files. A further test asserts that every root `.html/.js/.css` on disk is a tracked site file, and that
   all of them still serve.
3. **Consistency state.** `consistency()` returns `INCONSISTENT` if any comparable pair differs, `CONSISTENT` only if
   at least one pair matched, and otherwise `INCONCLUSIVE_NOT_COMPARABLE`. The UI labels this 「無可比較項目（不判定一致）」.
4. **pyarrow.** PYSEC-2026-113 is fixed in 23.0.1. The declared range is now `pyarrow>=23.0.1,<24.0` (root
   `requirements.txt`), which is what the Flask image installs.
   - Compatibility was verified in an isolated venv with pyarrow 23.0.1 and pandas 2.3.3: the root suite and the
     parquet-using JSD/adapter suites pass. `data_shift.py` (frozen, SHA-pinned) only calls `pd.read_parquet`.
   - The developer's existing local `.venv` still has 22.0.0 and was not modified; reinstalling from `requirements.txt`
     updates it.
5. **Methods and JSD.** Methods remain `DRAFT_PENDING_METHOD_OWNER_REVIEW`. Ethan's JSD algorithm, thresholds and
   readiness rules are untouched.

## Lint exceptions (not "clean")

`ruff 0.17.0 --select E,F,W,B,S --line-length 130` on all Phase 3–5 files reports **51** findings, all reviewed and
accepted:
- 38 × E501: long lines (data tables / long assertions);
- 10 × B008: FastAPI `Depends(...)` defaults, the framework idiom also used by the existing routers;
- 3 × S608: table names from fixed tuples or `sqlite_master`, never user input.

Ignored by policy:
- S101: asserts in tests;
- S603/S607: fixed-argv subprocess;
- S310: localhost or configured URLs;
- E731: lambdas in tests.

bandit reports two findings:
- B201: the pre-existing `debug=True` in `app.py`'s local `__main__` only;
- B608: the same constant-tuple false positive.

## Preserved baselines (real archive)

| Item | Value |
|---|---|
| Canonical facts | 234 |
| Restatement comparisons | 158 |
| Strict PIT facts | 67 |
| Board notice vs XBRL | 40 match / 2 `mismatch_unresolved` / 18 `not_comparable` |
| Restatement post side vs restated XBRL | 27 match / 0 mismatch / 67 `not_comparable` (no filed fact; previously skipped silently) |
| FY2025 | total assets and total liabilities each 1,721 thousand TWD; cause unverified, no fraud label, not routed to risk |

The FY2025 PDF evidence is version `hfv1_8fa5f75c…`, SHA `fc715140…`, page 8, ROC year 114, with unit, fiscal-year and
scope all verified. The `research_baseline` comparison of all 16 tables, 12 packages and both archives is IDENTICAL.

Previously persisted reconciliation runs (made before v2) are kept unchanged (append-only). `GET /runs/{id}/verify` now
reports `inputs_changed_since_run` for them, because their snapshot did not freeze the dependencies. A new v2 run is the
correction.
