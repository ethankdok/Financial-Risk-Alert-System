# Literature-model data-integrity correction: validation (independent review of f83aa98, LIT-F01..F04)

## Scope and version

| Item | Value |
|---|---|
| Branch | `feature/literature-models-beneish-dechow` (local only; no push, merge or PR) |
| Reviewed commit | `f83aa98d04c37e34e7480349c33b85cb12933218` |
| Commits | `1eeee88` code and tests; `d441805` docs and evidence tooling (**verification ran at this commit**); a final report commit that adds documents only |
| Specification | `docs/development/FinTrust_Beneish_Dechow_Consolidated_Review_Fixes_Claude_Prompt_2026-10-12.md` (untracked, unchanged) |
| Review | `docs/development/FinTrust_Beneish_Dechow_Independent_Code_Audit_f83aa98_2026-10-12.md` (untracked, unchanged) |
| Test log | `fintrust_backend/data/literature_models/handoff_fix_final/LITERATURE_DATA_INTEGRITY_FIX_TEST_RESULTS.txt` (UTF-8; 29 stages, each with its real exit code, plus 3 logged first attempts that failed for harness / cleanup reasons and were re-run) |

This was a bounded correction pass. The Beneish and Dechow engines, coefficients, transformations, the registry and
the API surface are unchanged; only the inputs they receive are corrected.

## 1. Findings and corrections

| Finding | Correction | Files |
|---|---|---|
| **LIT-F01 (P1)** `sum` returned `computed/0` when no listed line was presented | `not_presented` (never 0). Every computed input has a typed `evidence_type`. Zero-evidence policy `literature_zero_evidence_policy_v1` has one documented rule (`twgaap_equity_section_exhaustive_enumeration`). Its records (rule, version, operands, findings, fingerprint) are frozen in `snapshot.literature_zero_evidence`, which is part of the input digest. Issuance metrics can never have a zero rule. | `literature_inputs.py`, `literature_comparison.py`, `input_snapshot.py` |
| **LIT-F02 (P2)** failed / incomplete PDF arithmetic did not block inputs | TW-GAAP PDF extractor v2 keeps every balance-sheet code row and evaluates 10 identities per column (`verified` / `mismatch` / `incomplete`). The diagnostics carry page, period, unit, scope, rule, SHA, operands and difference. The source gate blocks only the covered lines of that column. XBRL instants need `Assets = Liabilities + Equity`. | `literature_extraction.py`, `literature_inputs.py` |
| **LIT-F03 (P2)** disagreeing `one_of` aliases picked the first | `mapping_conflict` with every candidate and value; agreeing aliases are all recorded (`alias_candidates`, source observations); permutation invariant | `literature_inputs.py` |
| **LIT-F04 (P2)** t−2 from another filing without coherence checks | t−2 is used only if the overlapping year t−1 agrees (`cross_filing_overlap_mismatch` / `_unverifiable`, with metric, period, filing ids, version types and values). The IFRS-transition opening balance is used only in the first year of a framework, flagged and gated. | `literature_inputs.py`, `literature_comparison.py` |

**New versions (all in the run's method version and the input digest):**
- `literature_input_mapping_v2`
- `literature_panel_v2`
- `literature_zero_evidence_policy_v1`
- `literature_source_gate_v1`
- `literature_twgaap_pdf_extractor_v2` (identities `twgaap_statement_identities_v1`)

XBRL extractor `literature_line_extractor_v1` is unchanged.

## 2. Real-data effect (1785, both version series)

| Item | f83aa98 | Corrected |
|---|---|---|
| Reviewed `latest_available` entries (complete, no source) | 8 × `computed/0` | 8 × `not_presented` (`stock_issued` FY2013–16, 2023–25; `long_term_debt_issued` FY2018) |
| Reviewed `original_only` entries (preferred stock) | 4 × `computed/0` | 4 × `verified_zero` (equity sections 8,795,797 / 9,345,296 / 9,788,003 thousand exhaustively enumerated; no 3120 / 特別股 line) |
| TW-GAAP identities, FY2011 and FY2012 reports | 2 checks per column (`verified` / `failed_or_incomplete`) | 10 per column; 20 / 20 `verified` per report |
| Alias conflicts | not checked | 0 conflicts; 28 inputs with two agreeing candidates |
| t−2 overlap checks | none | `latest_available`: 22 verified, 2 mismatch; `original_only`: 2 verified |
| Beneish, `latest_available` | 13 computed | 13 computed, all identical |
| Dechow, `latest_available` | 12 computed | **10 computed**: FY2015 (receivables 2014: 1,969,784 vs 1,961,884 thousand) and FY2023 (total assets 2022: 26,569,543 vs 26,600,628 thousand) withdrawn |
| `original_only` | Beneish FY2011 −1.730106, FY2012 −2.286269; Dechow FY2012 0.892005 | identical (Dechow FY2012 now rests on documented `verified_zero` evidence) |
| Year-model cells (both series, 60) | 28 computed / 32 not computable | **26 computed / 34 not computable** |
| Comparable pairs (`latest_available`) | 12 (7 same side) | 10 (5 same side) |
| STRICT_AS_OF (three cutoffs) | null | null (0 observations admitted) |

**Delta table:** `literature_data_integrity_correction_evidence.json`. 58 of the 60 cells are unchanged (all 26
remaining scores are byte-identical) and 2 scores are withdrawn. No score value changed.

**Corrected runs** (they supersede the f83aa98 evidence runs, which were never persisted):

| Series | Corrected run | Supersedes |
|---|---|---|
| `latest_available` | `rrun1_1648246ccaca6ea204bcd347fc83d247` | `rrun1_94c4ffe2c129d7a5640239bb5fda2542` |
| `original_only` | `rrun1_fab682f2390383952588b6b0522503ab` | `rrun1_8d74e4bba6acee88bc4fd0113bc50900` |

## 3. Test and evidence matrix (from the log)

**How it was run:** the final verification ran on 2026-10-12 at `d441805`, sequentially with one heavy stage at a
time. A runner (`stage.py`) captured each process's real exit code through `subprocess` and used `bash -o pipefail` for
shell stages, so no pipeline could mask a failure. Free RAM was about 2.7–3.1 GB throughout.

**Earlier interrupted attempt:** a previous all-in-one background run was stopped by Claude Code's memory-pressure
guard during the backend suite. Its partial log is kept as `previous_interrupted_run_log.txt`; it is **not** used as
evidence. The earlier interim counts (backend 690 / 5) are superseded by the counts below.

| Stage | Command (summary) | Exit | Result |
|---|---|---:|---|
| A1 syntax | `py_compile` of every Python file changed since f83aa98; `node --check` | 0 | ok |
| A2 data integrity | `pytest -v tests/test_literature_data_integrity.py` | 0 | **26 passed** (fixture, renderer, REAL) |
| A3 literature | `pytest -v tests/test_literature_models.py tests/test_literature_ui_chain.py` | 0 | **33 passed** (incl. Enron 2.76, Beneish −2.243743) |
| A4 research units | 6 Phase 3–5 research test files | 0 | 68 passed, 2 skipped (emulator-only, run in C1) |
| A5 falsifiability | `mutation_check.py` (in-memory reversion) | 0 | all 4 reversions detected; tracked files unchanged |
| B1 backend full | `pytest -q -rs tests` (single process) | 0 | **691 passed, 5 skipped** |
| B2 root full | `pytest -q -rs tests` (after B1 exited) | 0 | **148 passed** |
| B3 historical (subset of B1) | `tests/test_historical_*.py` | 0 | 167 passed, 2 skipped |
| B4 conference / JSD (subset of B1) | conference, MOPS PDF, JSD bridge / contract, IR archive | 0 | 151 passed, 1 skipped; no JSD / conference file changed since db7ee69 |
| B5 2330 / 2454 (subset of B1) | `-k "2330 or 2454 or tsmc or mediatek"` | 0 | 7 passed |
| B6 pyarrow 23.0.1 venv, backend | isolated venv (pyarrow 23.0.1, pandas 2.3.3, xlrd 2.0.2) | 0 | **691 passed, 5 skipped** |
| B7 pyarrow 23.0.1 venv, root | same venv | 0 | 148 passed |
| B8 fresh worktree | detached worktree at HEAD, no local data | 0 | 625 passed, 71 skipped (real-data tiers skip); worktree removed |
| C1 Firestore emulator | firebase-tools 13, project `demo-fintrust` | 0 | **7 passed** (emulator) |
| C2 port 8085 | listener check | 0 | first check found the emulator JVM (PID 28048, `cloud-firestore-emulator … --project_id demo-fintrust`) still listening; it was stopped **by PID only**, then the check passed (both attempts logged) |
| C3 E2E | `scripts.research_ui_smoke` (real FastAPI + Flask, headless Chrome) | 0 | ok: 16 HTTP checks, 9 views, fresh screenshots; Flask/FastAPI literature output digest parity |
| C4 ports after E2E | listener check | 0 | no leftover listener |
| C5 preflight | `scripts.research_cloud_preflight` (read-only) | 0 | ok, `writes_performed=none` (first attempt failed only because the runner had not created the output folder; logged) |
| D1 re-extraction | dry run + idempotent append | 0 | digest `a2dce891…e77793`; **0 new** records (first attempt: same runner folder issue; the sidecar was verified unchanged at 4,789 / 66 / 2 before the re-run) |
| D2 sidecar append-only | `check_sidecar.py` | 0 | 4,393 / 33 / 1 f83aa98 rows identical; +396 / +33 / +1; UPDATE / DELETE triggers present |
| D3 evidence | `literature_evidence.py --previous-results …` | 0 | regenerated; byte-identical to the interim evidence; OpenAPI unchanged |
| D4 outcome re-check | `check_outcome.py` | 0 | 26 / 34; only Dechow FY2015 and FY2023 changed; 26 scores identical; 8 `not_presented`; 4 `verified_zero` (15–16 operands each); identities 20 / 20 ×2; STRICT null ×3 |
| D5 persisted runs | `check_runs.py` | 0 | 5 reproducible + 1 `method_version_changed` (`source_inputs_unchanged=true`); 8 pre-existing tables identical; `research_literature_scores` 0 rows |
| D6 f83aa98 handoff | `sha256sum -c` over 43 files | 0 | all identical |
| D7 approved data | `scripts.research_baseline --compare` (pre-literature-pass baseline) | 0 | IDENTICAL: 16 tables, 12 ZIP / sidecars, raw archive (274 files), conference archive (4,735 files); `after.json` byte-identical to the pre-correction snapshot |
| E1 ruff | changed Python since f83aa98 | 0 (runner) | 7 findings, listed in §6 |
| E2 bandit | research code, router, Flask proxy, app.py | 0 (runner) | 5 findings, listed in §6 |
| E3 pip-audit | both requirements files | 0 | no known vulnerabilities |
| E4 secrets | pattern scan of diff f83aa98..HEAD and evidence | 0 | 0 / 0 (pattern scan only, not a proof of absence) |

**Mock vs emulator:**
- 5 mock cloud tests run inside B1.
- 7 Firestore emulator tests run in C1.
- The 3 emulator-gated tests skip in B1 (`FIRESTORE_EMULATOR_HOST` not set) and run in C1.

## 4. Required independently falsifiable tests (`tests/test_literature_data_integrity.py`)

| Requirement | Test(s) |
|---|---|
| Explicit zero vs missing line vs structural zero | `test_explicit_zero_absent_line_and_verified_structural_zero_are_distinct` |
| Synthetic data without a preferred line is never `computed/0` | `test_reviewer_repro_no_preferred_line_is_never_computed_zero`; `test_absent_sum_lines_never_score_through_the_full_engine` |
| Zero proof tampering, printed preferred line | `test_zero_proof_fails_closed_on_tampering_and_uses_a_printed_preferred_line` |
| Issuance absence never 0 | `test_issuance_absence_is_never_a_zero` |
| Rule version and fingerprint in the input digest | `test_zero_evidence_is_frozen_into_the_input_digest` |
| Reviewed 8 latest + 4 original entries (real) | `test_reviewed_latest_source_empty_entries_are_not_presented`; `test_reviewed_original_preferred_stock_entries_are_verified_zero` |
| Broken balance identity / inconsistent gross profit | `test_broken_balance_identity_never_reaches_a_published_score`; `test_inconsistent_gross_profit_blocks_sales_and_costs`; real corrupted copy `test_corrupted_copy_of_the_real_fy2012_report_never_scores` |
| verified / mismatch / incomplete | `test_extractor_distinguishes_verified_mismatch_and_incomplete`; `test_incomplete_identity_and_unverified_page_identity_block_only_their_lines`; `test_xbrl_balance_identity_gates_instants` |
| Verified FY2011–12 facts stay usable | `test_clean_original_reports_score_both_models`; FY2011 assertions in the broken-identity tests; `test_real_original_report_identities_are_all_verified` |
| `OperatingRevenue=1000` and `Revenue=2000` | `test_disagreeing_aliases_fail_closed_without_a_first_alias_value`; `test_conflict_is_permutation_invariant`; `test_agreeing_aliases_are_all_recorded_and_in_the_digest` |
| t−2 overlap mismatch; same framework, different version; IFRS transition; order | `test_overlap_mismatch_rejects_t_minus_2_and_names_metric_period_and_versions`; `test_same_framework_different_version_needs_the_same_overlap`; `test_unverifiable_overlap_is_not_computable`; `test_ifrs_transition_opening_balance_only_for_the_first_tifrs_year`; `test_cross_filing_results_are_order_independent` |
| UI shows typed evidence | `test_typed_statuses_zero_proof_and_overlap_are_visible` |
| Enron / Beneish golden arithmetic | `test_dechow_reproduces_the_published_enron_example`; `test_beneish_hand_example_through_the_full_engine`; `test_dechow_fixture_components_are_independently_derived` |

**Falsifiability:** each correction was reverted in memory only and the matching tests were re-run. No tracked file was
changed (scratch script `mutation_check.py`; its output is in the log). Every reversion was detected:

| Correction reverted | Tests that failed |
|---|---|
| F01 | 2 / 10 |
| F02 | 4 / 7 |
| F03 | 2 / 3 |
| F04 | 3 / 5 |

All of them pass when restored.

**Test fixtures adjusted in `test_literature_models.py`:**
- The synthetic TIFRS fixture now presents an explicit `0` short-term-investment line. Before, it relied on the old `computed/0` behaviour; the hand-derived Beneish M = −2.243743 is unchanged.
- It also presents `Equity`, so the XBRL balance identity can be evaluated.
- The REAL assertion for Dechow FY2015 (0.890320) is replaced by the documented withdrawal.

## 5. Data integrity and isolation

- **Approved data:** the historical SQLite (opened `mode=ro`), the raw and conference archives, the 12 ZIP / sidecar packages and the JSD code are unchanged (`research_baseline --compare` against the pre-literature-pass baseline: IDENTICAL).
- **234 / 158 / 67:** the facts, restatement comparisons and PIT-eligible facts are unchanged.
- **Literature sidecar:** append-only. All 4,393 f83aa98 observations, 33 diagnostics and 1 run are byte-identical; 396 v2 PDF observations, 33 diagnostics and 1 run were appended. Old PDF observations are not read by the current method.
- **Result store:** no write in this pass. The pre-existing rows are identical, and `research_literature_scores` still has 0 rows.
- **f83aa98 handoff:** all 43 files, including the review ZIP `58b2a3aa…` and the index `1e10762b…`, are byte-identical. The final correction evidence is in a new folder, `handoff_fix_final/`. The interim folder `handoff_fix/` from the interrupted session is left untouched; its evidence JSON is byte-identical to the final regeneration.
- **Strict cutoffs, publication evidence, risk / JSD boundaries:** unchanged. No OCR. No network, cloud write, paid API, push, merge or deploy.

## 6. Lint and static analysis (reviewed)

**ruff 0.17.0** (`--select E,F,W,B,S`, line length 130, documented ignores) on the Python changed since f83aa98
reports 7 findings:

| Rule | Location | Assessment |
|---|---|---|
| E501 | `docs/development/evidence/literature_evidence.py:76` | pre-existing line (f83aa98) |
| E501 | `fintrust_backend/app/services/financial_research/service.py:244` | pre-existing line |
| E501 | `fintrust_backend/scripts/research_ui_smoke.py:112` | pre-existing line |
| S105 | `literature_extraction.py:202` | comparison with the dash placeholder `"-"`, not a password |
| S311 ×3 | `test_literature_data_integrity.py:352`, `:457`; `test_literature_models.py:370` | deterministic seeded shuffles in permutation tests |

**bandit 1.9.4** reports 5 findings:

| Rule | Severity | Location | Assessment |
|---|---|---|---|
| B201 | High | `app.py:1337` | `debug=True` in the local `__main__` entry; pre-existing, not changed by this pass, not used by the deployment images. Reported, not suppressed. |
| B105 | Low | `literature_extraction.py:202` | same false positive as S105 |
| B608 | Medium | `literature_store.py:128`, `:185`; `result_store.py:269` | table and column names come from constant tuples; values are bound parameters; pre-existing |

## 7. Blocked or not run

- **GCS emulator:** not available.
- **Live MOPS tests:** opt-in, and no network was used.
- **Staging / production:** not authorised; only the read-only preflight was run.
- **Restated FY2011–2015 and original FY2013–2015 PDFs:** image-only. No OCR was used, so no same-year original-vs-restated score exists.

## 8. Method-owner decisions (Yu-Jing), not chosen silently

See `docs/research/LITERATURE_INPUT_EVIDENCE_POLICY.md` §6:
- the equity-enumeration zero rule;
- the partial-sum presentation rule;
- an overlap-explanation register;
- preferred shares presented as liabilities;
- cash-flow labels on page identity only;
- the earlier Beneish manuscript decision, the DRAFT mapping and the IFRS-transition opening balance.
