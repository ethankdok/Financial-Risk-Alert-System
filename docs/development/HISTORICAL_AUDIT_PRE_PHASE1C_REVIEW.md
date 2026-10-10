# Historical Audit — Independent Pre-Phase 1C Review (Phase 1A/1B)

Date: 2026-10-10. Reviewed: `5b9acf7` (Phase 1A) and `f8b32c3` (Phase 1B) on
`feature/audit-case-historical-ingestion`, which descends from `5db17c1` with no
upstream and no other worktree. `5db17c1..f8b32c3` touches 35 files, all under
historical-audit paths, docs or tests.

Earlier Claude Code reports were treated as claims to verify, not as evidence.

## Verdict

**No CRITICAL defects.** Four HIGH and two MEDIUM issues were verified and
fixed in the review commit on `feature/audit-case-historical-ingestion`.
Phase 1C proceeds on top of that commit.

## Actual validation performed

| Check | Result |
|---|---|
| Full suite, this machine, before fixes | 457 passed, 2 skipped |
| Full suite, **fresh worktree** of `f8b32c3` (no local archive) | **451 passed, 8 skipped**. The 6 real-data scenario tests skip; Phase 1B's "457 passed" was local-only |
| Archive integrity (read-only) | 58 artifact references / 45 distinct files re-hashed: 0 mismatches; every file name starts with its SHA-256 |
| SQLite `integrity_check` / `foreign_key_check` | ok / none |
| Orphans (facts → versions, comparisons → events, availability → facts) | 0 / 0 / 0 |
| DB backup before fixes | `fintrust_backend/data/historical_audit/backups/historical_audit.pre-phase1c-review.sqlite3` (gitignored; SHA-256 prefix `0d651ce1f9225d02`) |

## Findings

| ID | Severity | Area | Finding (code reference) | Fix |
|---|---|---|---|---|
| H1 | HIGH | Financial semantics / PIT | `evidence_import._corroborate` let any side of a 重編前/重編後 row date any filing fact. A *restated* fact matching only the *pre-restatement* column would have been dated by a "previously reported" value. Real impact: 2 restated revenue facts stored with `match_detail = "pre side"` because `UNIQUE(kind, observation, corroborating_id)` dropped the post-side row (pre == post there, so no wrong dates, but wrong provenance) | Side is now fixed by revision: restated → post only, original → pre only, unknown → none. Summary values record every matching side (`pre+post`). Corroboration is a deterministic rebuild of derived rows (real archive: 39 removed / 39 re-added, then 0/0 on rerun) |
| H2 | HIGH | Evidence verification | `_import_mops_material_detail` attached comparison rows to the first claim even if its quote was **not** found, still writing `verified_official_disclosure`; with no claim it crashed (`StopIteration`) | Comparison rows require a `verified_official_quote` event from the same document, otherwise import reports an error and writes nothing |
| H3 | HIGH | Export consistency / PIT | Fact rows that were eligible via a disclosure still showed only the XBRL's `content_hash`/`source_url`. That invites reading "the XBRL was public then". `quality_report.point_in_time_eligible_versions` counted only artifact-level availability (8), while the reader/exports used observation level (27 facts) | Reader and facts export (contract **v1.2**) add `availability_evidence_kind/ref/url/hash`; the artifact's own `available_at` stays null. Quality report adds `point_in_time_eligible_facts` (reader definition) and `artifact_level_verified_versions`. A test asserts reader = CSV = JSON = quality report |
| H4 | HIGH | Research cutoff integrity | No test or document established what each cutoff supports. Verified: before the 2016-05-13 revelation **nothing** is verifiably public (earliest verified evidence is the 2016-08-25 archive re-upload), so a strict pre-event detection backtest has no inputs. November-2016 PIT success says nothing about predictive performance | Fixture and real tests for pre-event (2016-05-12, 2016-05-13 00:00), restatement (2016-11-14) and retrospective (2017-12-31) cutoffs; contract section "Research cutoffs" |
| M1 | MEDIUM | Reproducibility | Real-data tests silently skip on a fresh clone | Documented executed vs skipped counts. Phase 1C's portable package gives teammates the data without the SQLite file (see Phase 1C validation) |
| M2 | MEDIUM | Security | `RawEvidenceArchive.store` built paths from plan `source_key` without containment (`read` had it) | `store` rejects `..`, `\`, `:`, empty segments and resolves inside the root; plan keys must match `[A-Za-z0-9][A-Za-z0-9._-]{0,127}` |
| L1 | LOW | DoS | lxml `huge_tree=True` on official XBRL | Accepted (official sources only, bounded) |
| L2 | LOW | Coverage matrix | "before/after disclosure from" shows the earliest of both scopes (individual 21:25:31) | Documented |

Confirmed correct (no change):
- **Artifact dates are never backdated.** `available_at` is never set from a period-level notice or from a value match (`upsert_filing_version` only fills it from verified records).
- **Classification is conservative.** `restated` needs in-filing wording plus a late audit date, or archive labels; `original` needs archive/manifest evidence.
- **Scope, unit and framework are part of every match key.** EPS is not rescaled. Comparisons are kept in NT$ thousand with an explicit `sign_factor`.
- **Fetching is safe.** Allowlisting covers redirects, SSL verification is always on, and there is no `verify=False`.

## Test delta from this review

`tests/test_historical_review_fixes.py` (10 fixture tests) and 3 new real-data
tests in `tests/test_historical_evidence_real.py`. One assertion in
`test_historical_evidence.py` was extended (not weakened) for the v1.2 fields.

After fixes: **470 passed, 2 skipped** on this machine. On a fresh clone the 9
real-data tests skip: see the Phase 1C validation report for the measured
fresh-worktree count.
