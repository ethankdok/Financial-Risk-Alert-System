# Phase 2C — 1785 FY2023–FY2025 Expansion and Integrated Hardening — Validation

Date: 2026-10-11 (Asia/Taipei).

Branch `feature/historical-1785-fy2023-2025`, created from the verified Phase 2B head `c4bb82f`. Earlier branches
are preserved.

Nothing was pushed, merged or deployed. There were no Firestore/GCS or production operations and no LLM/OCR
calls. Execution time: 2026-10-11 ~16:30 Taipei, so the strict cutoff (end of 2026-10-10) is in the past.

## Outcome

| Track | Result |
|---|---|
| Carryover A1 (restatement-fact numeric verification) | implemented; reviewer case now **rejected**; all 27 FY2013–2015 facts re-derive in all 3 released and the new strict packages; no underlying inconsistency |
| Carryover A2 (coverage persistence) | `coverage_status` separate from acquisition; a storage failure or inconsistent coverage → exit 1 |
| Carryover A3 (no unsafe success) | `no_official_record` only for the verified official 「查無資料」 response; parse errors and timeouts → `failed` |
| FY2023–2025 ingestion | 3 inline-XBRL filings, 18 facts each (54), 17/17 core, idempotent, identities exact |
| Evidence | 22 sources; 3 board-approval notices; FY2023 annual note corrections; FY2025 Q2 interim XBRL correction; no restatement |
| PIT | **19 new facts** (7 + 7 + 5); FY2025 total assets/liabilities rejected (notice ≠ filed report) |
| Conference | 2023–2025: 12/12 files hash-verified, coverage consistent; cumulative 2011–2025: 44 files / 38 distinct |
| Packages | `fintrust_1785_2011_2025_full.zip`, `fintrust_1785_2011_2025_asof_2026-10-10.zip` (+ sidecar), verified outside the repository |
| Integrity | every pre-Phase-2C DB row byte-identical; all 1,204 pre-existing archive files and all 9 earlier package files unchanged |

## A. Carryover fixes

### A1 — independent numeric verification of restatement-dated facts

**Gap.** On `c4bb82f`, mutating the FY2013 `restatement_disclosure` fact `cost_of_goods_sold` from 33223945000 to
33223946000 in both CSV and JSON, with checksums recomputed, still verified.

**Fix** (`package_verify.verify_restatement_fact`, standard library only and shipped in every ZIP). For every
`restatement_disclosure` fact, in either artifact branch, the verifier requires:

- **The notice itself:** it parses the included raw notice and checks the event key, the publication time
  (= effective time) and the subject scope.
- **Fact structure:** the period equals the fiscal year, and the accounting framework fits the fiscal year
  (TW-GAAP up to FY2012, TIFRS from FY2013).
- **An independent mapping:** (framework, metric) → (notice line, statement section, sign) through
  `RESTATEMENT_NOTICE_LINES`. COGS takes sign −1, because the notice shows expenses in parentheses. An unknown
  metric fails closed.
- **Statement type** consistent with the section.
- **The side:** a restated version takes 重編後 and an original takes 重編前; any other version type is rejected.
- **The value:** exactly one notice cell, with fact value = cell × 1000 × sign and unit TWD.
- **The comparison row:** exactly one matching `restatement_comparisons` row (announcement, hash, period, scope,
  framework, metric, statement type), with the same unit (TWD_thousand), `sign_factor` and side value.

**Rechecks.** All 27 FY2013–2015 facts re-derive in the 2016-11-14, 2020-12-31, 2023-12-31 and new 2026-10-10
strict packages. No genuine inconsistency was found, so nothing was quarantined.

**Tests.**

- Fixture: 11 mutations, with CSV and JSON changed together:
  - value, sign, unit;
  - side (original and unknown);
  - scope, period, metric, statement type, framework;
  - disclosure identity.
- Real tier: 8 mutations, including the reviewer's exact case.

### A2 — coverage persistence decides delivery

**Fix.** `run_recovery` records `coverage_status` separately from acquisition:

- `failed`: the recorder raised;
- `inconsistent`: the persisted row disagrees with the outcome. A `complete` acquisition needs `conference_found`
  with missing 0 and downloaded = expected, using the recorder's **re-hashed** archive counts. A no-record year
  needs `no_official_record_found`;
- `consistent`.

The exit code is 0 only if every year is acquisition-OK **and** its coverage is `consistent`.

**Tests:** a simulated `OSError("simulated database disk full")` gives exit 1, while acquisition stays `complete`;
a hash-verified count mismatch gives `inconsistent` and exit 1; a no-record year persisted as unavailable gives
`inconsistent`.

### A3 — listing errors are never success

**Fix.**

- `no_official_record` requires every error to be the pipeline's exact `MOPS reports no data (查無資料)`, which is
  raised only after the official 「查無資料」 page is verified.
- A verified listing with zero documents is `no_documents_listed` only when no error was recorded.

**Tests:**

- both reviewer inputs give `failed`;
- 403, timeout, an unverifiable listing, a partial "查無資料" string, no-data plus timeout, and no errors at all
  give `failed`;
- the genuine no-data response gives `no_official_record`.

### Release gate for modern-era cutoffs

`check_strict` rejected any "2024-/2025-/2026-" text. That was sound only for cutoffs before 2024. Phase 1
retrievals on 2026-10-09/10 UTC fall **before** the new cutoff, so a date check alone could not catch them. The
gate now:

- applies the year markers only to pre-2024 cutoffs;
- requires `retrieved_at` / `created_at` / `recorded_at` / `generated_at` / `listing_retrieved_at` to be empty in
  every model-facing CSV;
- scans for all 366 retrieval and creation timestamps the research DB records, in both UTC and Taipei renderings.

A fixture test covers both failure modes. All earlier strict packages pass the new gate.

### Before/after reproduction

Run from `fintrust_backend/`:

```bash
python ../docs/development/evidence/historical_audit_phase2c_carryover_repro.py --before c4bb82f
```

| Finding | `c4bb82f` | Phase 2C |
|---|---|---|
| A1: FY2013 COGS +1000 TWD (CSV+JSON) | **ACCEPTED** status=verified | **REJECTED**: "value 33223946000 TWD is not the notice's post-restatement 營業成本 (-33223945 仟元, sign -1)" |
| A2: complete + coverage storage OSError | exit **0** | exit **1** |
| A3: `[1]`, no documents, parse error | `no_documents_listed` | `failed` |
| A3: `[]`, timeout, status `no_listing` | `no_official_record` | `failed` |

## B. FY2023–FY2025 ingestion

| FY | Format / entry point | Facts | Core | Quality | 2nd run | Audit report | SHA-256 (prefix) |
|---|---|---|---|---|---|---|---|
| 2023 | inline XBRL, `tifrs-ci-cr-2020-06-30` | 18 | 17/17 | validated | 0 inserted | 2024-03-06 | `d8c75ca3` |
| 2024 | inline XBRL, same | 18 | 17/17 | validated | 0 inserted | 2025-03-07 | `42432af5` |
| 2025 | inline XBRL, same | 18 | 17/17 | validated | 0 inserted | 2026-03-26 | `34336a24` |

- **Taxonomy.** The concepts are identical to FY2020–2022. The only non-primary mapping is the documented capex
  alias, and cash is `deduplicated_2_identical_facts`.
- **Correctness.**
  - revenue − COGS = gross profit, and liabilities + equity = assets, hold exactly;
  - current assets ≤ total assets, and current liabilities ≤ total liabilities;
  - no exponent text; units are TWD, with EPS in TWD/share.
- **Revision.** Every version is `unknown_revision`.

## C. Evidence, corrections and publication

**Sources:**

- TWSE e-book listings ROC 112–114;
- MOPS material listing **ROC 115 (2026)**; ROC 106–114 were already archived, so the correction search window is
  2017 to 2026-10-11;
- TPEx `O_2023Q4`–`O_2025Q4`, whose values equal the XBRL for every mapped metric.

**Annual PDFs:**

- FY2023: unverified (更(補)正 blank; the 2024-08-12 corrections are linked);
- FY2024: **verified** 2025-03-12;
- FY2025: **verified** 2026-03-26.

**Board-approval notices.** These are the FY2023, FY2024 and FY2025 notices (2024-03-06, 2025-03-07, 2026-03-06).
They gave 30 disclosed values and 19 exact matches.

**FY2025 discrepancy, recorded and not reconciled:**

- The notice states total assets 34,436,171 and total liabilities 19,423,635 thousand.
- The XBRL and the verified, audited PDF (page 8) state 34,434,450 and 19,421,914.
- Total equity is identical at 15,012,536, and the notice's figures appear nowhere in the filed report.

Both facts are therefore rejected by the exact-match rule; they keep their filed values in the full package.

**Corrections:**

- `mops:20240812:034419:2` and `mops:20240812:034500:3`: the FY2023 (112年第四季) consolidated and individual
  related-party notes. Note-only, "對本公司損益並無影響".
- `mops:20250811:143440:2`: the 2025 Q2 interim XBRL. "損益無影響"; recorded on 2025Q2, with no annual link.
- The interim 2024-08-12 #1/#4 corrections were identified from titles only.
- **No restatement** of FY2023–FY2025 was found.

**Import.** Run 1 inserted 63 events, 30 disclosed values, 6 PDF versions, 42 summaries, 15 links and 19
corroborations. Run 2 inserted **0**. Every pre-Phase-2C row is preserved.

## D. Conference recovery (2023–2025) and cumulative 2011–2025

| Year | Acquisition | Coverage | Listing rows | Files (hash-verified) | Pages (text) |
|---|---|---|---|---|---|
| 2023 | complete | consistent | 6 | 6/6 | 242 (224) |
| 2024 | complete | consistent | 2 | 4/4 | 176 (166) |
| 2025 | complete | consistent | 1 | 2/2 | 60 (56) |

The run took 15 requests, none failed, with exit 0. All three years have review status `visual_review_pending`,
which is expected with LLM/OCR disabled.

**Cumulative 2011–2025:**

- 26 listing rows (meetings);
- 44 files, 38 distinct by content, 22 language-pair keys, about 19 distinct presentations;
- 1,190 pages, 1,139 with a text layer;
- **0 JSD-ready quarterly observations**: all documents are `period_unconfirmed`, and re-listings are also
  `duplicate_document`.

The JSD contract and algorithms are unchanged. Full table: `docs/data/HISTORICAL_1785_CONFERENCE_COVERAGE.md`.

## E. Database and compatibility

| Table | Before Phase 2C | After |
|---|---|---|
| financial_filing_versions | 35 | 44 |
| versioned_financial_facts | 180 | 234 |
| historical_source_documents | 83 | 102 |
| historical_publication_events | 856 | 919 |
| publication_evidence_links | 90 | 105 |
| official_summary_observations | 168 | 210 |
| disclosed_financial_values | 30 | 60 |
| observation_availability | 60 | 79 |
| historical_conference_coverage | 15 | 18 |
| historical_acquisition_attempts / ingestion_runs | 30 / 11 | 36 / 17 |
| restatement_comparisons, cases, annotations, schema meta | unchanged | unchanged |

**Read-only smoke.** All `evidence-export` datasets ran, plus `coverage_matrix` FY2011–2025 (15 rows), the facts
export (234), the PIT export as of 2026-10-10 (67), `quality` (integrity checks 0), and `research_access`. The
database digest was identical before and after.

**Mock-cloud parity.** On the real archive, mock-cloud parity now covers FY2011–2025 at 5 cutoffs, including
2026-10-10. This is not live Firestore compatibility: the emulator is not configured.

## F. Packages

| File (`fintrust_backend/data/historical_audit/packages/`) | Bytes | SHA-256 |
|---|---|---|
| `fintrust_1785_2011_2025_full.zip` | 220,363,454 | `171e3da165a081e7b6acb4183d7c43f8663b3f3c87810fdc89f2ecdc8b4f82eb` |
| `fintrust_1785_2011_2025_asof_2026-10-10.zip` | 41,511,396 | `9f281d50b47a489ebbc1bdae12802384ebbc2b8d33258c51c0cecd40ed0c9e8c` |
| `fintrust_1785_2011_2025_asof_2026-10-10.audit.json` | — | `bf6ba1dee48c083304b60e598337c3163e0acf30bda97327922c17323874255d` |

**Strict package:**

- 58 verified files; cutoff `2026-10-11T00:00:00+08:00` exclusive; `generated_at` null;
- 67 facts, all with a withheld XBRL identity: 27 restatement-dated and 40 board-dated, all re-derived;
- 18 versions, 12 summaries, 158 comparisons, 919 events (all public before the cutoff);
- inventory 26, raw 44.

The sidecar excludes conference documents (46), versions (26), source documents (45) and summaries (193).

**Full package:**

- 269 verified files;
- 234 facts, 44 versions, 205 summaries, 60 disclosed values, 919 events, 115 inventory rows;
- 44 conference files;
- 168 raw files.

**Verification:**

- ZIP CRC passes, and the shipped verifier passes under system Python 3.14 (`python -I`) outside the repository,
  on the ZIP and after `safe_extract`.
- The sidecar binds the ZIP through `package_sha256`, `content_digest` and `package_file`.
- The release-gate leakage scan passed.

All 9 earlier package files were verified by `sha256sum -c`; they are listed in the final report.

## G. Tests (actual)

| Tier | Result |
|---|---|
| Historical (pytest), all modules | 167 passed, 2 skipped |
| — fixture | 122 passed |
| — real local archive | 35 passed (incl. A1 real mutations, Phase 2C class, FY2011–2025 mock-cloud parity) |
| — mock cloud | 10 passed |
| — emulator | skipped: Firestore emulator not configured |
| — live MOPS | skipped: opt-in (`FINTRUST_LIVE_MOPS=1`) |
| Historical (plain `unittest`) | 169 run, OK, 2 skipped |
| Conference / JSD / 2330 / 2454 | 199 passed |
| Full backend regression | 564 passed, 3 skipped (+ reportlab PDF fixture) |
| Live acquisitions | 6 XBRL downloads (3 years × 2 runs), 7 discovery, 6 PDFs, 6 notices, 15 conference requests: all successful |

Complete output: `fintrust_backend/data/historical_audit/review_bundles/phase2c_test_results.txt`.

## Remaining limitations

- **No XBRL file has a verified publication time.** PIT eligibility is value-level only: 67 of 234 facts.
- **FY2025 total assets and liabilities.** The board notice differs from the filed report, and the cause is not
  stated.
- **FY2023 PDFs** are unverified (blank 更(補)正; corrected 2024-08-12).
- **FY2017–2019 still have 0 PIT facts.** The PDF-statement corroboration route remains a proposal.
- **Conference:** 0 JSD-ready documents; all publication times unverified.
- **Unresolved FY2016 comparative EPS** (−1.23 against −1.39).
- **Released ZIPs carry their original embedded text.** The 2011–2022 full ZIP embeds the earlier inventory with
  "30 sources"; it is preserved byte for byte. The new full ZIP embeds the corrected inventory (27; cumulative
  115).
- **Emulator and live-MOPS test tiers** not run.
