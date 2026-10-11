# Literature-model one-pass validation: Beneish (1999) and Dechow et al. (2011)

## Scope and version

| Item | Value |
|---|---|
| Branch | `feature/literature-models-beneish-dechow` (local only; no push, merge or PR) |
| Starting point | `db7ee699244244e0a5f6fa636a867e4390e7ec17`, the approved Phase 3–5 HEAD |
| Archive baseline | `506b64c`, an ancestor of this branch |
| Commits | `cc45d99` code and tests; `f358ff5` docs, evidence and tooling (**verification ran at this commit**); a final report commit that adds documents only |
| Diff `db7ee69..f358ff5` | 36 files, +5,106 / −49 |

**Specification input:** `docs/development/FINTRUST_BENEISH_DECHOW_ONE_PASS_CLAUDE_PROMPT_2026-10-12.md` (untracked, unchanged). The path cited in the request, `…_PROMPT.md`, does not exist; this dated file is the one that was read.

**Test log:** `fintrust_backend/data/literature_models/handoff/LITERATURE_MODEL_TEST_RESULTS.txt` (UTF-8, 22 sections, every section exit 0).

## 1. What was built

| Area | Deliverable |
|---|---|
| Method lock | `literature_method_registry.py` and `docs/research/BENEISH_1999_DECHOW_2011_METHOD_LOCK.md`, with paper page, table and verification level for every term |
| Inputs | `literature_extraction.py`: read-only extraction of lines from the archived TIFRS XBRL (FY2013–2025) and the original TW-GAAP consolidated reports (FY2011–2012), with SHA-256 re-verified. `literature_inputs.py`: the DRAFT COMPUSTAT→Taiwan mapping and the t / t−1 / t−2 panel. `literature_store.py`: a separate append-only SQLite sidecar. `scripts/ingest_literature_inputs.py`: bounded and idempotent, 0 network requests |
| Engines | `beneish_1999.py` (eight variables, unweighted probit); `dechow_2011.py` (Table 7 Model 1 with RSST, t−2 and issuance evidence, stable logistic, 0.0037 scaling); `literature_common.py` (50-digit Decimal arithmetic) |
| Comparison | `literature_comparison.py`: version series with no hidden fallback, mode gates, same-observation pairing, coverage matrix |
| F05 | `version_selection.py`: order-independent selection with fail-closed ambiguity. Applied to reconciliation, features and literature lines; the snapshot sorts facts canonically |
| F06 | `ResearchService.verify_run` reports `method_version_changed` / `legacy_method_not_reproducible` / `source_inputs_unchanged` separately from `inputs_changed_since_run` |
| API | `GET /literature/models`, `GET /cases/{t}/literature/coverage`, `POST /literature/compute`, `POST /literature/compare`. Runs are digest-identified and persistence requires the token. OpenAPI: `docs/data/openapi_research_v2.json` |
| Flask / UI | Proxy routes (browser `persist` is always false); a seventh research view with side-by-side scores, heatmaps, a trend chart (comparable years only), the year provenance drill-down, the model and source section, and a deep link `#literature&policy=…&mode=…` |
| Results | New result kinds `literature_models` / `literature_comparison`; additive projection table `research_literature_scores` (Firestore: `<prefix>_literature_scores`) |

## 2. Test and evidence matrix (from the log)

| Tier / check | Result |
|---|---|
| Backend full suite (unit, fixture, mock, real) | **665 passed, 5 skipped** (632 → 665: 33 new) |
| Root suite (Flask, harnesses, proxy registration with literature routes) | **148 passed** |
| Literature and Phase 3–5 research subset (verbose) | 101 passed, 2 skipped (emulator-only tests, run separately below) |
| Isolated venv with pyarrow 23.0.1 | root 148 passed; backend 665 passed, 5 skipped |
| Historical audit subset | 167 passed, 2 skipped |
| Conference / JSD (Ethan's contract) | 151 passed, 1 skipped; no JSD or conference algorithm file changed |
| 2330 / 2454 | 7 passed |
| Fresh worktree, no local data | 603 passed, 67 skipped (the real-data tiers skip as designed) |
| **Firestore emulator** (firebase-tools 13, `demo-fintrust`) | 7 passed; port 8085 released |
| Literature re-extraction | dry-run digest `1dc6ef8c…748d93` equals the stored digest; append created 0 new records |
| F06 over the 6 persisted runs | 5 `reproducible`; legacy v1 run `rrun1_9caed…` → `method_version_changed` with `source_inputs_unchanged=true` |
| Pre-existing result-store rows | all 8 tables byte-identical to the copy taken before this pass; only `research_literature_scores` was added |
| **E2E** (real FastAPI and Flask processes, localhost HTTP, headless Chrome) | `ok=true`: 16 HTTP checks and 9 browser views (6 existing, plus literature in the current series, the original series and the strict cutoff) |
| Read-only staging preflight | `ok=true`, `writes_performed=none` |
| **Approved data non-mutation** | `research_baseline --compare` = **IDENTICAL**: 16 tables, 12 ZIP / sidecar files, raw archive (274 files), conference archive (4,735 files) |
| pip-audit, both requirements files | no known vulnerabilities |
| Secret scan (diff and generated evidence) | 0 / 0 |
| `node --check` | ok (the repository has no npm build or lint toolchain) |

## 3. Paper mathematics and golden fixtures (`tests/test_literature_models.py`)

- **Dechow, published Enron 2000 example** (CAR p. 61):
  - predicted value −4.575458 → paper −4.575;
  - probability 0.010197 → paper 0.01020;
  - **F-Score 2.755822 → paper 2.76**.
- **Beneish, hand-derived example from the Table 2 definitions:** the arithmetic is written in the test and re-derived with `fractions.Fraction`, independently of the engine. All eight components match exactly and M = −2.243743.
- **Dechow, synthetic fully populated fixture:** RSST WC / NCO / FIN, ch_cs with t−2, ch_roa with t−2, and issue evidence, each re-derived with `Fraction`.
- **Fail-closed checks:**
  - a `secondary_only` or `unverified` coefficient or scaling disables the score (`model_formula_unverified`);
  - a non-numeric intercept, the Beneish coefficient table reused for Dechow, or a truncated coefficient set are all refused;
  - logistic and probit stay stable at ±1000, and Φ(−50) is reported as `<1e-300` with an underflow flag.
- **Edge cases:**
  - zero and negative denominators → `invalid_denominator_*`;
  - a reported 0 is a value, while a missing line is `missing_input`;
  - a parsed statement without its anchor total → `anchor_missing`;
  - expenses printed as deductions are sign-normalised and checked against the gross-profit identity;
  - thousand-TWD values are converted exactly.
- **PDF parsers:** two-column account-code rows (including glued tokens and note references such as 四.4及26), label rows with the longest exact label winning, totals without a code, and Chinese-numeral ROC years.

## 4. PIT, case integrity, versions, F05 and F06

| Check | Result |
|---|---|
| STRICT_AS_OF at 2016-05-13 00:00, 2016-11-13 21:26:22 and 21:26:23 (+08:00) | 0 literature observations admitted; both scores `null` (`insufficient_point_in_time_evidence`) |
| Canonical facts / strict-PIT facts / comparison rows | 234 / 67 / 158, unchanged |
| FY2011–2012 TW-GAAP vs FY2013 TIFRS | Never mixed inside one model-year. A FY t−1 filing in a different framework gives `accounting_regime_break`; FY2013 t−2 uses the flagged IFRS transition opening balance |
| No hidden fallback | An unreadable latest version gives `source_unavailable`; the system does not fall back to the original |
| Ambiguity | Several machine-readable artifacts for one version give `ambiguous_version`; conflicting duplicate line values give `ambiguous_version` |
| F05 | Different values, equal amounts with different identity, and the same version with conflicting hashes are all ambiguous in either order. Reconciliation reports `ambiguous_filed_fact_versions` and returns identical output for both orders. Permuted literature inputs give the same digest and results |
| Existing runs | 5 of 6 persisted runs remain reproducible, so the earlier 1785 baseline results are preserved |
| F06 | A literature run gives `reproducible`. A changed method version gives `method_version_changed`, `legacy_method_not_reproducible=true` and `source_inputs_unchanged=true`. A changed input digest gives `inputs_changed_since_run` |
| Dependency digests | Any changed extra line observation changes the input digest and the `literature_observations` dependency digest. The earlier TPEx / PDF freeze is unchanged (debug-pass tests pass) |
| Issuance | No positive issuance line gives `issuance_absence_not_evidenced`, never 0 (real case: FY2018) |
| Incomplete t−2 | `missing_t_minus_2` (real case: FY2011 original series) |

## 5. Negative cases

| Case | Behaviour |
|---|---|
| Primary paper inaccessible | Beneish's published FAJ text: verification level stays `source_verified_author_manuscript` and is disclosed. A registry downgrade disables the score (tested) |
| Upstream regulator blocked or changed | No network is used. Extraction re-verifies SHA-256; a mismatch gives `raw_sha256_mismatch` |
| FY2011–2012 missing | MOPS XBRL `filing_not_found` (already in the archive log); the originals are taken from the PDF text |
| Ambiguous original / revised versions | `ambiguous_version` (tested) |
| Valuation convention changed | IFRS 16 is flagged (`ifrs16_*`); different frameworks are never bridged |
| Wrong scope or context | XBRL scope or entity mismatch → extraction error; the PDF requires the 合併 (consolidated) title, unit and ROC year |
| Artifact not PIT-dated | `pit_admitted=false` → strict mode returns null |
| Two versions, equal amounts, different identity | ambiguous (tested) |
| Inconsistent numerator sign | Deduction-printed costs are normalised and checked by identity |
| Coefficients reused for another model variant | refused (tested) |
| CURRENT_EVIDENCE_RECONCILIATION | 409. `earliest_available` → 422. Missing `model_ids` → 422. Unregistered ticker (2330) → 404. Unknown Flask action or ticker pattern → 400 |

## 6. Blocked scope (stated, not hidden)

| Blocker | Kind | Effect |
|---|---|---|
| Restated FY2011–2015 PDFs and original FY2013–2015 PDFs have image-only statement pages; OCR was not used | blocked by financial data | No year has both an original and a restated score, so no pre/post score delta is reported |
| No FY2010 filing archived | blocked by financial data | Dechow FY2011 (original series) not computable |
| FY2018 issuance evidence | blocked by financial data | Dechow FY2018 not computable |
| Beneish published version not accessed | blocked by paper (partially) | Manuscript-verified; reviewer decision |
| Strict-contract extension to artifact-level timing | method decision | STRICT stays null by design |
| Labelled multi-company Taiwan cohort | out of scope | No performance metrics (design only, in the case study §5) |
| GCS emulator; live or staging cloud | not available / not authorised | Not run |

## 7. Lint and static analysis (reviewed, not zero)

**ruff 0.17.0** (`--select E,F,W,B,S --line-length 130`, documented ignores S101, S603, S607, S310, E731) on every changed Python file finds **33 findings**:

| Rule | Count | Reason accepted |
|---|---:|---|
| B008 | 15 | FastAPI `Depends` / `Query` idiom in the router |
| E501 | 13 | Mostly pre-existing lines in modified files |
| S608 | 3 | Column and table names come from constant tuples; values are bound parameters |
| S105 | 1 | Comparison with the dash placeholder `"-"`, not a password |
| S311 | 1 | Deterministic shuffle in a permutation test |

**bandit** reports:
- pre-existing B201: `debug=True` in the `app.py` `__main__` local entry;
- B105 and B608: the same false positives as above.

## 8. Approved data and isolation

- The historical SQLite is opened `mode=ro`. The literature store is a different file, and the approved database path is refused.
- No ZIP, sidecar or raw archive changed.
- 1785 stays outside the production universe (2330 → 404 on literature routes).
- The FY2025 1,721-thousand-TWD gaps are never classified by a literature score; RECON mode refuses literature (409).
- The methodology remains DRAFT; Ethan's JSD code is unchanged.
