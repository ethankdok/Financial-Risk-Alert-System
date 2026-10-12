# Literature-model input evidence policy (data-integrity correction of f83aa98)

**Status:** `DRAFT_PENDING_METHOD_OWNER_REVIEW`. Every rule below is a method decision for Yu-Jing; the code applies
the conservative choice until she approves or withdraws it.

**Scope:** the inputs that the Beneish (1999) and Dechow et al. (2011) engines receive. The engines, coefficients and
transformations are unchanged (see `BENEISH_1999_DECHOW_2011_METHOD_LOCK.md`).

**Findings addressed:**
- the independent review of `f83aa98` (`FinTrust_Beneish_Dechow_Independent_Code_Audit_f83aa98_2026-10-12.md`), findings LIT-F01 to LIT-F04;
- the independent review of `df0fc44` (`FinTrust_df0fc44_Final_Independent_Code_Review_2026-10-12.md`), findings R01 (statement-anchor candidates) and R02 (zero proof verified at its point of use); see §2 and §4.

## 1. Versions (all part of the run identity and the frozen input digest)

| Component | Version | Change |
|---|---|---|
| Input mapping | `literature_input_mapping_v2` (was v1) | `sum` without any presented line is `not_presented`; `one_of` / `difference` aliases must agree; preferred stock (TW-GAAP) anchored on equity with a zero-evidence rule |
| Period panel | `literature_panel_v2` (was v1) | cross-filing t−2 overlap check; transition-year-only opening balance |
| Zero-evidence policy | `literature_zero_evidence_policy_v2` (v1 at df0fc44) | one rule, `twgaap_equity_section_exhaustive_enumeration`; v2 (R02): the frozen proof is re-derived and compared field for field where it is used |
| Source gate | `literature_source_gate_v2` (v1 at df0fc44) | TW-GAAP statement identities and XBRL balance identity gate every input line; v2 (R01): every present statement-anchor candidate is gate- and value-checked |
| TW-GAAP PDF extractor | `literature_twgaap_pdf_extractor_v2` (new) | every balance-sheet account-code row; 10 identities per column, each `verified` / `mismatch` / `incomplete` (`twgaap_statement_identities_v1`) |
| XBRL extractor | `literature_line_extractor_v1` (unchanged) | the 4,247 XBRL observations are byte-identical to f83aa98 |

The old method versions remain readable in the append-only sidecar: the 4,393 f83aa98 observations were not changed
or deleted. The current method reads only the current extractor versions (`is_current_observation`). New method
versions give new run ids; the corrected runs record `supersedes_run_id` (f83aa98 literature runs were evidence-only
and were never persisted in the result store).

## 2. Typed input evidence (LIT-F01)

A computed input always carries one `evidence_type`:

| Evidence type | Meaning |
|---|---|
| `explicit_line` | one printed / tagged line (all agreeing aliases recorded) |
| `explicit_zero` | the printed / tagged value is 0, or a TW-GAAP dash in the amount column |
| `presented_lines_sum` | the sum of the listed lines that the statement presents (absent listed lines are in `lines_not_presented`) |
| `derived_difference` | the difference of two printed lines (TIFRS preferred stock = share capital − ordinary share) |
| `verified_zero` | no listed line is printed, and a zero-evidence rule proves the value is 0 |

A non-computed input has a typed status: `missing_input`, `not_presented`, `anchor_missing`, `ambiguous_version`,
`mapping_conflict`, `source_identity_mismatch`, `source_identity_incomplete`, `missing_t_minus_2`,
`cross_filing_overlap_mismatch` or `cross_filing_overlap_unverifiable`.

**No listed line presented:** `not_presented`, never `computed/0`, unless a zero-evidence rule is verified.

**Zero-evidence rule `twgaap_equity_section_exhaustive_enumeration`** (TW-GAAP preferred share capital, code 3120).
For one balance-sheet column of one filing it is `verified` only when all of the following hold:

1. The extraction identity `3XXX = Σ every printed equity code 3000–3999` is `verified` for that column.
2. The same equation re-computes exactly from the frozen observations at assembly time (a tampered operand gives `mismatch`).
3. Every operand passes the source gate.
4. No printed equity line has code 3120 or a label containing 特別股.

Because every printed equity line is summed and the sum equals the printed total, a preferred-share balance would have
to be a printed line. Otherwise the equation would fail.

**Evidence record:** each verified proof is a frozen record containing:
- the rule and `rule_version`;
- every operand's observation id, line and printed value;
- the section total and the enumerated sum;
- the findings;
- an `evidence_fingerprint` (SHA-256 of the record).

The records are stored in `snapshot.literature_zero_evidence`, which is part of the input digest. Each model-year
result lists the fingerprints it used (`zero_evidence_used`).

**Verification at the point of use (R02, `literature_zero_evidence_policy_v2`).** A frozen record is never trusted on
its own word. Where `assemble()` would use it, `check_zero_proof()` accepts it only when all of the following hold:
1. it is the only record for that (metric, balance date) of the filing (duplicates: `duplicate_proof_records:<n>`);
2. its `status` is `verified`; otherwise `zero_evidence_not_verified:<rule>:<status>`, as before;
3. `rule`, `rule_version`, `accounting_framework`, `filing_version_id`, `metric` and `period` equal the mapping's rule,
   the current policy version and the filing/date being assembled (`<field>_differs`);
4. `evidence_fingerprint` is the SHA-256 of the record's own content (`evidence_fingerprint_mismatch`; a record that
   cannot be serialised is `malformed_record`);
5. `prove_zero()` re-derived from the current observations is `verified` (`recomputed_status:<status>`, e.g. after an
   operand changed, an operand observation disappeared, or a preferred line was added), and equals the stored record
   field for field, including every operand's observation id, line, value, printed value and locator
   (`stale_or_altered:<fields>`).

A failed check gives `not_presented`, value null, and the reason `zero_evidence_invalid:<reason>`; it never raises and
never yields `computed/0`. The operands of an accepted proof come from the re-derived record, so a missing observation
can no longer raise `KeyError`. A record without a text metric/period is ignored (it can certify nothing). A v1 record
fails check 3, so a snapshot built by v1 code is never silently re-scored by v2 code.

**Residual risk for the method owner:** a mandatorily redeemable preferred share classified as a *liability* (TW-GAAP
SFAS 36) would not be in the equity section; the mapping does not cover preferred shares presented as liabilities.

**Issuance (`long_term_debt_issued`, `stock_issued`):** there is no zero-evidence rule, by design. An absent line is
`not_presented`, which means UNKNOWN. The Dechow `issue` indicator is 1 only with a positive issuance line, and is
otherwise UNKNOWN (the score is then not computable).

**Partial sums:** when at least one listed line is presented, the presented lines are summed and the absent ones are
listed in `lines_not_presented`. This is the *component-level presentation rule*; it is the approval item in §6.

## 3. Source-identity gate (LIT-F02)

**TW-GAAP PDF lines.** A line is usable only if both of the following hold:
- **Page identity:** the unit (新台幣仟元/千元), the printed ROC year and the consolidated title are all `verified`.
- **Covering identities:** every statement identity that covers the line for its own fiscal-year column is `verified`.

| Identity | Rule | Covers |
|---|---|---|
| `balance` | 1XXX (or 資產總計) = 2XXX + 3XXX | the three totals |
| `asset_sections` | 1XXX = Σ printed 11XX, 14XX, 15XX, 17XX, 18XX | the totals and section totals |
| `current_assets_enumeration` | 11XX = Σ every printed code 1100–1399 and 120X | cash, receivables, inventory, short-term investments |
| `investments_enumeration` | 14XX = Σ every printed code 1400–1499 | non-current financial assets |
| `current_liabilities_enumeration` | 21XX = Σ every printed code 2100–2399 | short-term debt, tax payable, current maturities |
| `long_term_liabilities_enumeration` | 24XX = Σ every printed code 2400–2499 | long-term debt |
| `equity_enumeration` | 3XXX = Σ every printed code 3000–3999 | equity lines (and the zero proof) |
| `gross_profit` | 4100 − 5000 = 5910 | sales, cost of sales |
| `operating_expenses` | 6100 + 6200 + 6300 = 6000 | selling and administrative expenses |
| `net_income` | 7900 − 8110 = 9600 | consolidated net income |

**Gate outcomes for a covering identity:**
- `mismatch`: every operand is printed but the equation fails. The line is blocked as `source_identity_mismatch`.
- `incomplete`: an operand is not printed or not parsed. The line is blocked as `source_identity_incomplete`.
- In both cases the line never "assumes" the identity holds.

**Scope of a block:** an identity blocks only the lines it covers, and only in its own column. A broken income
identity does not block balance-sheet lines, and a broken 2012 column does not block the 2011 column.

**Cash-flow labels** (depreciation, amortization, issuance, operating cash flow) have no identity in the catalogue.
They are admitted on the page identity alone and flagged `arithmetic_identity_not_available_for_line:<label>`.

**Diagnostics:** the extraction diagnostics report, per identity:
- page, period, unit and statement scope;
- the rule and its version;
- the source SHA-256;
- the printed operands;
- the expected and computed values and their difference;
- any missing operands.

They also list `failed_identities`.

**Real 1785 data:** all 20 identities (10 per column) of the FY2011 and FY2012 original reports are `verified`.

**TIFRS XBRL instants** are usable only when `Assets = Liabilities + Equity` is `verified` for that instant in the same
filing. All instants used in the 1785 series are verified, including the FY2013 IFRS-transition opening balance.

**Pre-v2 observations** carry no per-line identity coverage. They are never read, and if forced they are blocked as
`identity_coverage_not_recorded`.

## 4. Alias agreement (LIT-F03)

`one_of` candidates, and each side of a `difference`, are aliases.

- **Order of evaluation:** every present candidate must first pass the source gate. Then all candidates must carry
  the same value.
- **Disagreement** gives `mapping_conflict`. The reason lists every candidate and its value, for example
  `OperatingRevenue=1000;Revenue=2000`. List order never decides, and no taxonomy precedence is applied.
- **Agreement** records every agreeing observation as a source, so all of them are in the provenance and in the
  `alias_candidates` diagnostics.

**Digest:** all observations of the selected filings are frozen, so a changed alternate value changes the input digest.

**Order independence:** results and digests do not depend on the order of the observations (tested with permutations).
Every present candidate is inspected (none is skipped after the first problem), and reasons are sorted, so the order of
the candidate list does not change the status or the reasons either.

**Statement anchors (R01, `literature_source_gate_v2`).** A `sum` is assembled only when its statement anchor is
present. Where the anchor has several candidate lines (TIFRS operating cash flow:
`CashFlowsFromUsedInOperatingActivities` / `NetCashFlowsFromUsedInOperatingActivities`; TW-GAAP total assets:
`code:1XXX` / `label:資產總計`; TW-GAAP operating cash flow: three labels), every present candidate follows the alias
rule above:
- none present: `anchor_missing` (unchanged);
- a conflicting duplicate of any candidate: `ambiguous_version`;
- any candidate blocked by the source gate: its gate status, reason `anchor:<line>:<gate reason>`;
- candidates with different values: `mapping_conflict`, reason `anchor_conflict:<anchor>:<line>=<value>;...`,
  and the candidates are listed in `alias_candidates`;
- one candidate, or several with equal values, passing the gate: the anchor is usable.

At df0fc44 only the first present candidate was checked, so a conflicting second candidate was ignored.

**Real 1785 data (R01/R02 audit):** 2 TW-GAAP balance dates present two total-assets candidates, and both agree. Every
other anchor has one candidate. No anchor decision differs from the df0fc44 rule. All 4 frozen preferred-stock proofs
are accepted at their point of use.

**Real 1785 data (alias rule):** 28 inputs have two agreeing candidates (26 current-filing, 2 original), and there are 0 conflicts.

## 5. Cross-filing t−2 coherence (LIT-F04)

**Rule:** a t−2 balance comes from the comparative column of the year-(t−1) filing. It is used only after the
overlapping year t−1 agrees for the same metric. The metric's t−1 value in the year-t filing (comparative column) must
equal its value in the year-(t−1) filing (current column).

The frameworks must also be equal and the statement scopes must be equal.

| Outcome | Status | Recorded |
|---|---|---|
| equal | computed | `cross_filing_overlap_verified:<metric>:<period>`, `t-2_from_FY<t−1>_filing`, and `cross_filing_version_types:<a>/<b>` when the version types differ |
| different | `cross_filing_overlap_mismatch` | metric, overlap period, both filing ids and version types, both values, difference |
| either side not assemblable, or scope differs | `cross_filing_overlap_unverifiable` | both statuses |

**No differences are explained automatically.** An explanation register (for example the 2023 IAS 12 amendment)
would need the method owner's approval and a documented source.

**IFRS-transition exception:** this applies only to the first fiscal year of a framework, where the prior fiscal year
is in another known framework (1785: FY2013, prior FY2012 is TW-GAAP).
- t−2 is the opening balance at `I:<t−1>-01-01` of the year-t filing.
- It is flagged `ifrs_transition_opening_balance_used_as_prior_year_end` and `framework_transition:FY2012=TW_GAAP->FY2013=TIFRS`.
- It must pass the XBRL balance identity at the opening date.
- A later year never falls back to an opening balance.

**Strict mode:** unchanged. No literature observation is admitted (`pit_admitted=false`), so post-event data never
backfills a pre-event period.

**Real 1785 data:**

| Series | Overlap checks | Verified | Mismatch |
|---|---:|---:|---:|
| `latest_available` | 24 | 22 | 2 |
| `original_only` | 2 | 2 | 0 |

The two mismatches:
- FY2015 receivables at 2014-12-31: the FY2015 filing shows 1,969,784 thousand and the FY2014 filing 1,961,884 thousand (difference +7,900 thousand).
- FY2023 total assets at 2022-12-31: the FY2023 filing shows 26,569,543 thousand and the FY2022 filing 26,600,628 thousand (difference −31,085 thousand).

## 6. Decisions for the method owner (Yu-Jing)

1. Approve or withdraw `twgaap_equity_section_exhaustive_enumeration`. If it is withdrawn, the FY2011–2012 preferred stock becomes `not_presented` and the FY2012 original-series Dechow score becomes not computable.
2. Approve or replace the component-level presentation rule for partial sums.
3. Decide whether an explanation register for cross-filing overlap differences is acceptable, and which evidence it requires (for example, a restatement note in the year-t filing).
4. Decide whether preferred shares presented as liabilities need a mapping.
5. Confirm that cash-flow labels may be admitted on page identity alone.
6. The earlier items still stand: the Beneish manuscript-only verification, the DRAFT COMPUSTAT→Taiwan mapping and the IFRS-transition opening balance.
