# Phase 1C Final Hardening — Validation

Date: 2026-10-11 (Asia/Taipei) · Branch `feature/historical-research-portability-cloud` · starting commit `5f7d87a`
(clean tree; no upstream; nothing pushed, merged or deployed).

> **Current release (after the independent-review fixes F1/F2, see the last section):**
> strict ZIP `304934a4a2e05dc16439155b267554a99a731ff6c07fa95e1cd05f25504f2bcf`,
> audit sidecar `c3ce8507c63c842971d2c6cf025babec329b07aec344d5d02d4f3cb274b774e6`,
> full ZIP unchanged `693e867155de00ebded16ffece99f6b32179d306e369028eee4045f6dfbaa826`.
> The sections below, up to the F1/F2 section, record the hardening pass at commit `52e2a44`.

**Outcome (hardening pass, commit `52e2a44`)**

- **Strict package rebuilt** (schema 1.2). `fintrust_1785_asof_2016-11-14.zip` was replaced through the safe procedure.
  - New SHA-256: `e665e3f5e97faf317f063e141f281f0a8bddad6689078e3708f69acbd8ec5954` (superseded by `304934a4…`).
  - Previous SHA-256: `84be7e2439b9e9dabdf2b28cfc470e73bb243841b576a35de094deea26749f49`.
  - The build is reproducible byte for byte.
- **Retrospective package unchanged.** `fintrust_1785_2011_2016_full.zip` keeps SHA-256
  `693e867155de00ebded16ffece99f6b32179d306e369028eee4045f6dfbaa826`. No verified correctness defect requires
  changing it: its known issues are wording only (see below).
- **Researcher handoff:** `docs/data/HISTORICAL_1785_RESEARCH_HANDOFF.md`.

## Gate A — source review findings

| # | Severity | Finding | Resolution |
|---|---|---|---|
| A1 | HIGH | The strict ZIP contained a summary row printed in the **2016FY** TPEx report (the FY2015 comparative, 61,376,037). That report period had not ended at the cutoff, so the row could not exist on 2016-11-14. | Strict summaries now require the report's fiscal year to have ended before the cutoff. Row excluded and the verifier re-checks this. |
| A2 | HIGH | Strict summary rows kept the later TPEx workbook reference (`O_20xxQ4.xls` URL, content hash) as if public before the cutoff. | Rows are reclassified `official_disclosed_observation` and dated by the MOPS notice that states the value; workbook URL, hash and retrieval time are withheld (`source_reference_status`). |
| A3 | MEDIUM | `statement_scope_basis` on operating-income rows read as a *revenue* match. | Export text now states that the scope belongs to the whole report row and was inferred from that row's revenue. `scope_inference_basis = report_row_revenue_match`. Summary evidence is metric-specific (`pit_evidence_label`, e.g. 營業淨利). |
| A4 | MEDIUM | Summary point-in-time evidence ignored the restatement side. | `admissible_summary_evidence` matches metric, fiscal year, scope, framework **and** the expected side (pre if the report's fiscal year ended by the disclosure, else post). |
| A5 | MEDIUM | Modern metadata in the model-facing strict ZIP:<br>• `manifest.generated_at` (2026);<br>• `manifest.excluded_by_cutoff`;<br>• quality-report exclusion counts;<br>• `missing_evidence.csv` withheld counts;<br>• `validation/provenance.csv` with 2026 retrieval times. | All moved to the reviewer-only sidecar `<zip>.audit.json`, bound by `package_sha256`. |
| A6 | MEDIUM | Model-facing timestamps were mixed (UTC and +08:00). | Every strict model-facing timestamp is now Asia/Taipei; `manifest.cutoff_taipei` added; the verifier rejects other offsets. |
| A7 | MEDIUM | The strict verifier checked only `data/` dates, the raw set and conference absence. | Ten semantic checks, fail-closed (Gate D). The builder runs the full verifier before writing. |
| A8 | LOW | The Firestore research backend computed summary availability without side/metric evidence. | Both backends now call the same `summary_evidence_map` and `finalize_summaries`; the mock-cloud parity test passes on the real archive. |
| A9 | LOW | Conference packaging reaches `company_registry.get_company`, which falls back to the production company master when `DATASTORE_BACKEND=firestore` (1785 is not in the seed list). | Fail-closed guard: conference packaging requires `DATASTORE_BACKEND=sqlite`. Test added. |
| A10 | LOW | `SUMMARY_CONTRACT_VERSION` was not emitted. | Emitted in the evidence-export envelope and in `manifest.contracts.historical_summaries`. |
| A11 | LOW | The rebuild script always rebuilt both ZIPs, overwrote `REPLACEMENT_REPORT.json`, and reused backup names. | `--rebuild strict\|full\|both`, `--expect-full-sha256`, hash-qualified backups that are never overwritten, timestamped reports, sidecar handling. |
| A12 | LOW | A coverage-gap text containing `; ` was split into two `missing_evidence` rows. | Text fixed at source. The preserved full ZIP still shows the split (cosmetic). |
| A13 | INFO | Contract docs described schema 1.1 (`provenance.csv`, `excluded_by_cutoff`). | Contracts updated to schema 1.2 and summary contract 1.1. The earlier validation report is marked as superseded in part. |

The review confirmed the following as consistent with the documentation:

- `reader` / `repository`: version-aware identities `hfv1_`/`hff1_`; facts and versions unchanged.
- `export`: facts contract v1.3.
- `conference_package`: retrospective only; conference documents never relabelled as transcripts.
- `cloud_*`: disabled unless `HISTORICAL_CLOUD_SYNC_ENABLED=true` and an explicit environment is set; production is refused.
- `research_access`.

## Gate B — summary provenance (row-level)

There were 12 summary rows in the previous strict ZIP. Values are in TWD thousand, and every disclosure is a MOPS
2016-11-13 restatement notice:

- `212531:2` is the individual table, published 21:25:31 Taipei;
- `212622:3` is the consolidated table, published 21:26:22 Taipei.

The *original status* of every row was `official_historical_summary` / `verified_by_corroboration`, with the TPEx
workbook URL present.

| # | Report | FY | Role | Metric | Value | Scope | Evidence (side · label) | Revised decision |
|---|---|---|---|---|---|---|---|---|
| 1 | 2011FY | 2011 | current | operating_income | 1,336,550 | individual | `mops:20161113:212531:2` (pre · 營業淨利) | retained as `official_disclosed_observation` |
| 2 | 2011FY | 2011 | current | revenue | 62,420,375 | individual | `212531:2` (pre+post · 營業收入淨額) | retained |
| 3 | 2012FY | 2011 | prior-year comp. | operating_income | 1,336,550 | individual | `212531:2` (pre · 營業淨利) | retained |
| 4 | 2012FY | 2011 | prior-year comp. | revenue | 62,420,375 | individual | `212531:2` (pre+post · 營業收入淨額) | retained |
| 5 | 2012FY | 2012 | current | operating_income | 354,151 | individual | `212531:2` (pre · 營業淨利) | retained |
| 6 | 2012FY | 2012 | current | revenue | 65,758,524 | individual | `212531:2` (pre+post · 營業收入淨額) | retained |
| 7 | 2013FY | 2013 | current | revenue | 34,241,550 | consolidated | `mops:20161113:212622:3` (pre+post · 營業收入) | retained |
| 8 | 2014FY | 2013 | prior-year comp. | revenue | 34,241,550 | consolidated | `212622:3` (pre+post · 營業收入) | retained |
| 9 | 2014FY | 2014 | current | revenue | 53,305,891 | consolidated | `212622:3` (pre+post · 營業收入) | retained |
| 10 | 2015FY | 2014 | prior-year comp. | revenue | 53,305,891 | consolidated | `212622:3` (pre+post · 營業收入) | retained |
| 11 | 2015FY | 2015 | current | revenue | 61,372,337 | consolidated | `212622:3` (pre · 營業收入) | retained (as previously reported) |
| 12 | 2016FY | 2015 | prior-year comp. | revenue | 61,376,037 | consolidated | `212622:3` (post · 營業收入) | **excluded**: the 2016FY report period had not ended at the cutoff |

What the 12 rows show:

- All 12 are side-consistent. For example, the FY2015 value as printed in the FY2015 report equals the 重編前
  (pre) figure, and the same year printed in the FY2016 report equals the 重編後 (post) figure.
- No value was changed.
- The remaining 67 summary rows have no contemporaneous disclosure of their exact value and stay excluded from the
  strict package.
- The per-row decisions are in the sidecar (`summary_observation_review`).

## Gate C — model-facing vs reviewer-only metadata

Strict ZIP contents (model-facing):

- `README.md`, `manifest.json`;
- `contracts/` (two generic contracts);
- `data/` (8 CSVs + facts JSON);
- `raw_evidence/`: 7 original PDFs and 4 notices;
- `validation/`: `quality_report.json`, `checksums.sha256`, `verify_package.py`.

What the build checks confirm:

- `manifest.generated_at = null`, and the manifest contains only allow-listed keys;
- no `excluded_by_cutoff`, no provenance file, no 2024–2027 date and no post-cutoff marker in any model-facing file;
- every timestamp is `+08:00`;
- filing, observation, disclosure, effective and event times are separate fields.

The sidecar `fintrust_1785_asof_2016-11-14.audit.json` holds:

- `package_sha256` and `generated_at`;
- `excluded_by_cutoff`: versions 10, source documents 24, summaries 68, events 110, conference documents 6;
- `summary_observation_review` (79 decisions);
- `raw_evidence_provenance`.

## Gate D — semantic verifier and cutoff matrix

`package_verify._verify_strict` runs 10 fail-closed checks:

1. manifest allow-list and null generation time;
2. no post-cutoff or non-Taipei timestamp in model-facing files;
3. filing versions and inventory are public before the cutoff;
4. raw evidence is admissible only; no conference content;
5. every SHA-256 reference resolves to included evidence;
6. fact eligibility and withheld-identity rules, with disclosure resolution;
7. summary reclassification and side consistency;
8. comparisons;
9. timeline links;
10. CSV / JSON / manifest consistency.

Tamper tests (fixture tier) each fail for the intended reason:

- modern manifest key;
- `generated_at`;
- reference to excluded evidence;
- unresolved disclosure;
- non-Taipei timestamp;
- conference material;
- count mismatch.

Cutoff matrix on the real archive (`RealStrictCutoffMatrix`). The assertions are derived from database
relationships; the counts below are measurements, not hardcoded expectations.

| Cutoff (Asia/Taipei) | Facts | Versions | Summaries | Comparisons | Events | Raw | Notes |
|---|---|---|---|---|---|---|---|
| 2016-05-12 (end of day) | 0 | 0 | 0 | 0 | 139 | 0 | no financial inputs before the revelation |
| 2016-05-13 00:00:00 | 0 | 0 | 0 | 0 | 139 | 0 | identical: date-only 2016-05-13 notices count from the next midnight |
| 2016-11-13 21:26:21 | 0 | 7 | 6 | 79 | 231 | 10 | only the individual table (21:25:31) |
| 2016-11-13 21:26:22 | 27 | 7 | 11 | 158 | 233 | 11 | consolidated table; facts dated 21:26:22 |
| 2016-11-14 (end of day) | 27 | 7 | 11 | 158 | 249 | 11 | the shipped strict package |
| 2017-12-31 (end of day) | 27 | 8 | 12 | 158 | 359 | 18 | FY2016 PDF (verified 2017-03-22) included; XBRL identity still withheld |

Every package verified, and the counts grow monotonically across cutoffs.

## Gates E/F — packages

Safe procedure, implemented in `scripts/rebuild_historical_packages.py --rebuild strict --expect-full-sha256 …`:

1. Back up to `previous/` under a hash-qualified name. The pre-hardening strict ZIP is
   `previous/fintrust_1785_asof_2016-11-14.84be7e2439b9.zip`.
2. Build to `*.new.zip`.
3. Run the full semantic verification and check the SHA-256.
4. Run the shipped verifier with `python -I` from a temporary directory outside the repository, on both the ZIP and
   the safely extracted folder. It also ran under the system Python 3.14 without the virtualenv.
5. Run the strict and modern-metadata checks.
6. Confirm the sidecar's SHA-256 binding.
7. Confirm the full ZIP is unchanged.
8. Replace atomically.

Two intermediate strict builds from this phase are kept in `previous/intermediate_phase1c_hardening/`:

- `ba759b3d…`: before the scope-wording fix;
- `8662db77…`: before the contract-document update.

Final result:

- Strict: 25 files, `content_digest` `9d47392c…`, `status: verified`.
- Facts 27, versions 7, summaries 11, comparisons 158, events 249, inventory 4, raw 11.

Known wording issues in the preserved full ZIP (not value defects, so not rebuilt):

- the A3 scope-basis text;
- the A12 split row.

## Gate H — regression

| Tier | Result |
|---|---|
| Historical suites (fixture + real local + mock cloud) | 115 passed, 2 skipped |
| — facts/audit case, e2e, evidence, review fixes, research package, cloud (mock), conference/strict (fixture) | 37 / 2 / 15 / 10 / 10 / 10 / 14 passed |
| — real local archive (`test_historical_evidence_real.py`, incl. cutoff matrix and real mock-cloud parity) | 17 passed |
| Conference / JSD / 2330 / 2454 selection (`-k "jsd or conference or 2330 or 2454"`) | 177 passed |
| Full backend regression | 512 passed, 3 skipped |
| Skipped | live MOPS (opt-in), Firestore emulator (not configured), one PDF fixture (reportlab absent) |
| Emulator | not run (not configured) |

Integrity checks:

- **Database.** No writes in this phase (file time predates `5f7d87a`). Compared with the pre-Phase-1C backup,
  these tables have identical content hashes: facts (72), filing versions (17), comparisons (158), summaries (84),
  events (359) and source documents (41). `observation_availability` differs only by the earlier review fix: side
  wording and ID version, with the same observations, times and corroborations.
- **Conference PDFs.** All six (2010, 2011, 2017) re-hash to their manifests.
- **Full ZIP.** Unchanged.
- **Cloud and secrets.**
  - Cloud sync is disabled (no `HISTORICAL_CLOUD_SYNC_ENABLED`, no `DATASTORE_BACKEND` override).
  - No production access, no deployment.
  - No secrets in the diff.
  - Changes are confined to `historical_audit`, its scripts, tests and docs; no other team's module was modified.

## Independent review fixes (F1, F2) — after `52e2a44`

### F1 — summary verification was not independent

**Confirmed.** An independent reviewer reproduced the gap:

1. In a copy of the strict ZIP, change a retained summary's `pit_evidence_side` from `pre` to `post`.
2. Recompute every checksum and the manifest.
3. Run the shipped verifier, which still returned `verified`.

We confirmed it on `e665e3f5…`. Mutating the value or the scope also verified. This was a gap in the verifier, not
a data error: no financial value was wrong.

**Fix.** `package_verify.py` is standard-library only and is shipped as `validation/verify_package.py`. It now has
its own MOPS-notice parser, `parse_restatement_notice`, and does not import the producer. The parser reads:

- the notice's own 序號, 發言日期 and 發言時間, which give the event key and publication time;
- the 主旨 (subject), which gives the scope: 個體 or 合併;
- the 重編前/重編後 tables, which must be in 仟元 and have ROC-year columns.

Every summary row is then re-derived from the included raw notice. The verifier checks:

- the metric, against a fixed independent label table: revenue = 營業收入淨額/營業收入, operating income = 營業淨利/營業利益;
- that period, fiscal year and observation role are mutually consistent;
- the accounting framework: TW-GAAP up to FY2012, TIFRS from FY2013;
- the unit (TWD thousand, with `normalized_value` = value × 1000 in TWD);
- the scope stated by the notice;
- that the notice states the amount;
- the exact side(s) carrying that amount, compared with `pit_evidence_side`;
- the notice line, compared with `pit_evidence_label`;
- the event key and URL;
- that the effective time equals the notice's own publication time;
- the side a report of that period must carry (pre if the report's fiscal year ended by the disclosure, else post);
- that a matching `restatement_comparisons` row exists.

`side_consistency` is still required to read `consistent`, but it is no longer sufficient on its own.

All 158 comparison rows are also re-read from their notices:

- identity and time;
- scope and unit;
- both the pre and the post amount.

A notice that cannot be parsed, or that is not in 仟元, fails closed.

Results on the real archive, reproduced with a scratch script that touches no tracked file:

- 158 comparisons give 316 pre/post cells, all equal to the raw notices.
- All 11 retained summaries match. Their raw sides are pre for the three operating-income rows and for FY2015
  current, and pre+post for the seven revenue rows; each equals `pit_evidence_side`.
- No financial value changed. The data files of the rebuilt ZIP are byte-identical to `e665e3f5…`: only
  `verify_package.py`, the embedded package contract, the checksums and the manifest differ.

Negative tests recompute every checksum and the manifest, so only semantic checks can catch them. Each fails for a
named reason.

Real tier (`RealStrictCutoffMatrix`):
- side;
- value (with a consistent `normalized_value`);
- scope;
- period;
- metric;
- metric mapping;
- unit;
- framework;
- label;
- evidence reference;
- evidence identity (the other notice's hash and time);
- a restated value placed in an earlier report;
- the producer's `side_consistency` flag;
- comparison pre value, post value, scope and announcement.

Fixture tier (`test_historical_conference_strict`):
- side, value, scope, year, unit and reference;
- parser fail-closed cases: not a notice, missing time, a unit other than 仟元, unknown scope.

All of these run under plain `unittest`. A scratch-only meta-test also confirmed that a deliberately wrong expected
reason is reported as a failure.

### F2 — the ZIP and the sidecar could be published inconsistently

**Confirmed impact.** In `52e2a44`, the ZIP was replaced first and the sidecar was written afterwards. A crash
between the two steps would leave the new, verified ZIP next to the old sidecar. That sidecar's `package_sha256`
binds the previous ZIP, and nothing detected the mismatch. The research data stays correct in that case, but the
reviewer-audit binding is silently broken.

**Fix** (`scripts/rebuild_historical_packages.py`):

1. **Staging.** Both artifacts are fully staged before anything is published. The staged sidecar already names the
   final file, and publication checks that it binds the staged ZIP.
2. **Journal.** `publish_release` writes `<zip>.release.json` atomically before the first rename. The journal
   records the old and new hashes, the staged names and the hash-qualified backups.
3. **Publication.** The script renames the ZIP, renames the sidecar, removes the journal, and validates the pair.
4. **Pair check.** `verify_release_pair` fails closed on any of:
   - a missing file;
   - a journal that is still present;
   - an unreadable sidecar;
   - a sidecar whose `package_sha256`, `package_file` or `content_digest` does not bind the ZIP;
   - a ZIP that fails package verification.
5. **Recovery.** `recover_release` uses the journal to do one of three things:
   - **roll forward**: the new ZIP is in place and the staged sidecar is present;
   - **roll back**: nothing was published yet;
   - **restore**: copy back the verified hash-qualified backups.

   If none applies, it raises (fails closed).
6. **Every run.** The script first recovers or validates the existing pair and refuses to continue on an invalid
   one. `--check-release` validates only.
7. **Backups.** Hash-qualified backups are unchanged and never overwritten.

**Failure-injection tests** (`tests/test_historical_release_pair.py`, fixture tier, 7 tests). Failures are injected
with `mock` into the renames, inside temporary directories:

- a crash between the ZIP and sidecar renames is detected, then rolled forward;
- a crash before the ZIP rename is rolled back;
- a lost staged sidecar is restored from the hash-qualified backups;
- an unrecoverable state with no backups fails closed;
- a mismatched pair without a journal is never accepted, and `--check-release` exits 1;
- an incomplete pair is rejected;
- an unbound staged sidecar is refused before anything is published.

### Results (actual)

| Tier | Result |
|---|---|
| Historical, all modules (pytest) | 126 passed, 2 skipped |
| — fixture | 97 passed: case 37, e2e 2, evidence 15, review fixes 10, research package 10, conference/strict 16, release pair 7 |
| — real local archive (`test_historical_evidence_real.py`) | 19 passed (incl. the F1 real-tier mutations and the real-archive mock-cloud parity) |
| — mock cloud (`test_historical_cloud.py`) | 10 passed |
| — emulator | skipped (Firestore emulator not configured) |
| — live MOPS | skipped (opt-in) |
| Historical, all modules (plain `unittest`) | 128 tests run, OK, 2 skipped |
| Conference / JSD / 2330 / 2454 (`-k "jsd or conference or 2330 or 2454"`) | 179 passed |
| Full backend regression | 523 passed, 3 skipped (live MOPS, emulator, reportlab PDF fixture) |

### Deliverables

| Artifact | Path (`fintrust_backend/data/historical_audit/`) | SHA-256 |
|---|---|---|
| Strict ZIP | `packages/fintrust_1785_asof_2016-11-14.zip` | `304934a4a2e05dc16439155b267554a99a731ff6c07fa95e1cd05f25504f2bcf` |
| Audit sidecar | `packages/fintrust_1785_asof_2016-11-14.audit.json` | `c3ce8507c63c842971d2c6cf025babec329b07aec344d5d02d4f3cb274b774e6` |
| Full ZIP (unchanged) | `packages/fintrust_1785_2011_2016_full.zip` | `693e867155de00ebded16ffece99f6b32179d306e369028eee4045f6dfbaa826` |
| Backup of the previous strict release | `packages/previous/fintrust_1785_asof_2016-11-14.e665e3f5e97f.zip` (+ `.ba3b334e7ceb.audit.json`) | `e665e3f5…` |

Checks on the deliverables:

- **Sidecar binding.** `package_sha256` equals the ZIP hash, `content_digest` equals the manifest
  (`92087263…`), and `package_file` names the ZIP.
- **Release pair.** `--check-release` reports `release_pair_valid`, and no journal remains.
- **Verification.** The shipped verifier was run with system Python 3.14 (`python -I`) from a directory outside the
  repository. It passed on the ZIP and, after `safe_extract`, on the extracted folder.
- **Reviewer's reproduction.** Run against the new ZIP's own verifier, it now fails with
  "pit_evidence_side 'post' but the notice states the value on pre".
- **Reproducibility.** An independent rebuild from a copy of the database is byte-identical.
- **Leakage.** The rebuild script's checks passed: no post-cutoff or modern markers, every timestamp is Taipei, and
  no conference material or workbook reference.
- **Data integrity.** Facts 27, versions 7, summaries 11, comparisons 158, events 249, raw 11 — unchanged.

Reproduce:

```bash
cd fintrust_backend
python -m scripts.rebuild_historical_packages --check-release
python -m unittest tests.test_historical_release_pair tests.test_historical_conference_strict tests.test_historical_evidence_real
python -I <outside-dir>/verify_package.py <outside-dir>/fintrust_1785_asof_2016-11-14.zip
```

### Remaining limitations

- **Format-specific parser.** The independent parser supports the MOPS material-information layout used by the
  2016-11-13 notices. Any other layout fails closed, so it must be extended before new notice formats are accepted.
- **Fixed label table.** It covers the two summary metrics present (revenue, operating income). New summary metrics
  need an explicit table entry; until then, a row with such a metric fails verification.
- **Local recovery only.** Release recovery protects local publication on one machine. It is not a multi-writer
  lock, so concurrent rebuilds are not supported.
- **Earlier limitations unchanged.** There are still no verified inputs before 2016-05-13, and the wording issues in
  the preserved full ZIP remain. The emulator tier is still not run.
