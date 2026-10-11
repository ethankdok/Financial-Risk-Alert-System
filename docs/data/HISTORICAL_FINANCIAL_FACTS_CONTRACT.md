# Historical Financial Facts → Downstream Research (contract v1.4)

Producer: `app/services/historical_audit/export.py`
(`python -m scripts.historical_audit_case export …`).
Consumers: case research (Yu-Jing), JSD / Data Shift research (Ethan), future
`feature/financial-misstatement-signals`.

This contract is a compatibility boundary. It performs no JSD, shift, ratio or
risk computation, and it is independent of the conference-PDF → JSD contract in
[`JSD_INPUT_CONTRACT.md`](JSD_INPUT_CONTRACT.md), whose meaning is unchanged.
Consumers need only the CSV/JSON files, not SQLite.

## Record fields (fixed order; CSV header and JSON `fields`)

| Field | Type | Meaning |
|---|---|---|
| `ticker` | string | e.g. `1785` |
| `company` | string | case company short name (`光洋科`) |
| `market` | `TWSE` \| `TPEX` | case market |
| `fiscal_year` | int | Gregorian fiscal year |
| `period` | string | `YYYYFY` (annual). Quarterly periods are a future extension. |
| `metric_code` | string | canonical field code (list below) |
| `value` | decimal string | exact value as filed, after iXBRL `scale`/`sign`; fixed-point text, never exponent notation (Phase 2A fix: scaled iXBRL values are stored as `1525265000`, not `1.525265E+9`); never zero-filled |
| `unit` | `TWD` \| `TWD/share` | normalized unit (full TWD, not thousands) |
| `statement_type` | `income_statement` \| `balance_sheet` \| `cash_flow` | |
| `statement_scope` | `consolidated` \| `individual` \| `unknown` | from the taxonomy entry point (`…-cr-…` / `…-ir-…`) or a manifest declaration; never assumed |
| `taxonomy_concept` | string | e.g. `ifrs:Inventories` |
| `filing_version_id` | string | `hfv1_…`; stable across reruns; one per distinct source artifact |
| `filing_version_type` | `original` \| `restated` \| `unknown_revision` | see Version semantics |
| `source_kind` | `mops_xbrl_instance` \| `mops_inline_xbrl` \| `mops_xbrl_zip` \| `official_pdf` | evidence format (`test_fixture` is excluded by default) |
| `source_url` | string | official URL the bytes came from |
| `source_published_at` | ISO-8601 UTC \| empty | verified publication time, else empty |
| `available_at` | ISO-8601 UTC \| empty | verified public-availability time, else empty |
| `availability_status` | `verified` \| `unverified` | |
| `document_dated_at` | date \| empty | audit-report date inside the filing; a lower bound only |
| `retrieved_at` | ISO-8601 UTC | when FinTrust downloaded the bytes |
| `content_hash` | hex | SHA-256 of the archived source bytes |
| `quality_status` | `accepted` \| `warning` | fact-level QA (e.g. `eps_unit_declared_as_currency`) |
| `validation_status` | `validated` \| `validated_with_warnings` | filing-level QA; quarantined versions are never exported |
| `point_in_time_eligible` | `true` \| `false` | v1.1: a verified `effective_available_at` exists (version-level **or** observation-level) |
| `evidence_type` | `official_filing_fact` | v1.1, appended |
| `accounting_framework` | `TIFRS` \| `unknown` | v1.1, from the filing's taxonomy entry point |
| `completeness` | `full_statement_filing` | v1.1 |
| `availability_scope` | `filing_version` \| `observation` \| empty | v1.1: which evidence makes the fact eligible |
| `effective_available_at` | ISO-8601 UTC \| empty | v1.1: earliest verified time, i.e. the version's own `available_at` or the publication time of an official disclosure that states this exact value |

Canonical `metric_code`s: `revenue, cost_of_goods_sold, gross_profit,
operating_income, net_income, eps, cash_and_cash_equivalents,
accounts_receivable, inventory, current_assets, total_assets,
current_liabilities, total_liabilities, equity, operating_cash_flow,
investing_cash_flow, capital_expenditure` (core 17) and
`research_and_development_expense`. Cash-flow values keep the filed sign
(outflows negative, e.g. `capital_expenditure`).

Missing / unknown: CSV uses an empty cell for null; JSON uses `null`. A core
field absent from a filing has **no row**; the JSON `coverage` section lists
`core_fields_present` / `core_fields_missing` per filing version.

## JSON envelope

```json
{
  "contract": "fintrust.historical_financial_facts",
  "contract_version": "1.3",
  "generated_at": "…",
  "filters": {"ticker": "1785", "start_year": 2011, "end_year": 2016,
              "as_of": null, "version_policy": "all", "include_test_fixtures": false},
  "fields": ["ticker", "…"],
  "record_count": 72,
  "records": [{…}],
  "coverage": [{"period": "2013FY", "filing_version_id": "…", "core_fields_missing": []}]
}
```

## Version semantics

- Every distinct source artifact for a period is its own `filing_version_id`;
  versions never overwrite each other. A different hash alone means
  "different artifact", not "official restatement".
- `restated`: the filing itself states it is restated (auditor's restated-statement
  wording plus an audit date after 30 June of FY+1), or a manifest declares it with
  evidence. `original`: only with manifest verification evidence.
  `unknown_revision`: anything else — including the current MOPS document when
  nothing proves its status.

## v1.3 changes (Phase 1C follow-up, additive)

Three fields are appended after `availability_evidence_hash`:

| Field | Meaning |
|---|---|
| `observation_available_at` | earliest verified disclosure of this exact value (null if none) |
| `filing_available_at` | the filing artifact's own verified availability (null if unverified) |
| `artifact_reference_status` | `retrospective_reference` (retrospective exports), `verified_public_artifact` or `withheld_not_public_at_cutoff` (strict packages) |

`effective_available_at` remains the earlier of the two. In strict packages a
withheld artifact's identity fields (`filing_version_id`, `content_hash`,
`source_url`, `taxonomy_concept`, `document_dated_at`, …) are empty, and
`evidence_type = official_disclosed_observation`.

## v1.2 changes (pre-Phase 1C review, additive)

Four fields are appended after `effective_available_at`:

| Field | Meaning |
|---|---|
| `availability_evidence_kind` | `filing_artifact` (the filing's own verified time) \| `restatement_disclosure` (an official restatement notice stating this exact value) \| `financial_report_disclosure` (v1.4: an official MOPS financial-report board-approval notice stating this exact value) \| empty |
| `availability_evidence_ref` | `filing_version_id`, or the notice key (e.g. `mops:20161113:212622:3`) |
| `availability_evidence_url` | URL of the evidence document |
| `availability_evidence_hash` | SHA-256 of the evidence document |

When `availability_evidence_kind = restatement_disclosure`, the filing artifact
(`content_hash`, `source_url`, `available_at`) is **not** dated by that notice:
only the value is. Restated filing facts are dated only by 重編後 (post) values
and original filing facts only by 重編前 (pre) values.

## v1.4 changes (Phase 2B, additive)

`availability_evidence_kind` has one new value, `financial_report_disclosure`. It applies to a fact whose value
is stated by an official MOPS 「…年度合併財務報告業經董事會決議通過」 notice, which is published with a
second-precision 發言日期/發言時間.

**Match rules.** A fact is dated by such a notice only when every one of these matches exactly:

- fiscal year, with the notice's reporting period covering the full year (`起訖日期` 01/01–12/31);
- canonical metric, through a fixed label table:

  | Notice line | Canonical metric |
  |---|---|
  | 營業收入 | `revenue` |
  | 營業毛利(毛損) | `gross_profit` |
  | 營業利益(損失) | `operating_income` |
  | 本期淨利(淨損) | `net_income` |
  | 基本每股盈餘(損失) | `eps` |
  | 期末總資產 | `total_assets` |
  | 期末總負債 | `total_liabilities` |

- statement scope stated in the subject (合併 / 個體);
- accounting framework;
- normalized unit and value (仟元 × 1000 = TWD; EPS in TWD/share, unscaled).

**Exclusions:**

- The version must not be `restated`, and no restatement evidence may exist for the period.
- The lines 稅前淨利, 歸屬於母公司業主淨利 and 期末歸屬於母公司業主之權益 have **no** canonical metric. In particular,
  equity attributable to owners of the parent is never matched to total `equity`.
- Interim-period notices never date an annual fact.

**Artifact availability unchanged.** As with restatement disclosures, the filing artifact (`content_hash`,
`source_url`, `available_at`) is **not** dated by the notice. The XBRL artifact keeps
`availability_status = unverified`.

**Strict verification.** The strict verifier re-derives every such fact from the included raw notice itself and
fails closed on any mismatch or unsupported notice format.

**Restatement-dated facts (Phase 2C).** Facts dated by `restatement_disclosure` are also re-derived independently.
The verifier uses its own (framework, metric) → (notice line, statement section, sign) table. The sign converts the
notice's parenthesised expenses to canonical positive amounts (e.g. 營業成本 × −1). It then requires:

- the side implied by the version type: restated → 重編後, original → 重編前;
- the notice cell × 1000 × sign to equal the fact value in TWD;
- exactly one matching comparison row, with the same unit, sign factor and side value;
- the notice's own identity, publication time, subject scope, period and framework.

**Evidence dataset.** The notice values are also exported as the evidence dataset `disclosed_financial_values`
(below).

## Research cutoffs (what the archive can support)

| Analysis | Cutoff | Strict result (1785, current evidence) |
|---|---|---|
| Pre-event detection | before the 2016-05-13 public revelation | **no verified inputs**: 0 facts, 0 comparisons, 0 summaries, 0 artifacts |
| Restatement analysis | from 2016-11-13 21:26:22 | 27 restated facts (observation level) + 158 before/after rows |
| Restatement analysis, one second earlier | 2016-11-13 21:26:21 | 0 facts; 79 individual before/after rows (21:25:31 notice); 6 individual summary rows |
| Restatement analysis | from 2016-11-13 21:26:22 | 27 restated facts (observation level) + 158 before/after rows + 11 summary rows |
| Retrospective | e.g. 2017-12-31 | same 27 facts (XBRL identity still withheld) + 8 artifact-verified PDFs (incl. the FY2016 PDF) + 12 summary rows |
| FY2011–FY2025 strict (Phase 2C) | 2026-10-10 | **67 facts** = 27 restated FY2013–2015 + 21 FY2020–2022 + **19 FY2023–2025** (7 + 7 + 5; FY2025 total assets/liabilities not matched, see inventory) |
| FY2011–FY2022 strict (Phase 2B) | 2023-12-31 | 27 FY2013–2015 restated facts + **21 FY2020–FY2022 facts** dated by board-approval notices (7 per year: revenue, gross profit, operating income, net income, EPS, total assets, total liabilities; public from 2021-03-05 17:38:20, 2022-03-16 17:59:38 and 2023-03-02 22:38:39); 0 FY2016–FY2019 facts |
| FY2011–FY2019 strict (Phase 2A) | 2020-12-31 | same 27 facts; **0** FY2017–FY2019 facts (no verified XBRL publication time and no disclosure stating the values); 10 artifact-verified PDFs (adds FY2019 consolidated/individual, public from 2020-02-14 14:58:52 / 14:59:25); 12 summary rows |

Pre-event detection requires verified first-publication evidence for the
original 2012–2016 reports, which is not yet available. TPEx summary values
exist but their workbook availability is unverified; a summary value enters a
strict package only when a contemporaneous official disclosure states the same
value (summary contract 1.1, below). The counts above were measured on the real
archive by `tests/test_historical_evidence_real.py::RealStrictCutoffMatrix`, whose
assertions are derived from database relationships, not from these numbers.

## Summary observation contract 1.1 (additive)

Ten fields are appended to `historical_summaries` / `summary_observations`; the 1.0 columns keep their order.

| Field | Meaning |
|---|---|
| `observation_origin` | `tpex_quarterly_summary_value` (the value comes from a TPEx 上櫃公司季報 summary row) |
| `scope_inference_basis` | `report_row_revenue_match`: the statement scope of the *whole report row* was inferred from that row's revenue; `not_inferred` otherwise |
| `pit_evidence_kind` | `restatement_disclosure` when a contemporaneous official disclosure states this exact value; empty otherwise |
| `pit_evidence_ref` / `_url` / `_hash` | event key, URL and SHA-256 of that disclosure |
| `pit_evidence_side` | `pre`, `post` or `pre+post`: which side(s) of the disclosure's 重編前/重編後 table carry the value |
| `pit_evidence_label` | the disclosure's own line label (e.g. 營業淨利 for operating income) |
| `side_consistency` | `consistent` (matches the expected side), `inconsistent_side`, or `no_disclosure_match` |
| `source_reference_status` | `retrospective_workbook_reference` (retrospective) or `workbook_withheld_not_public_at_cutoff` (strict) |

Matching is metric-specific: canonical metric, fiscal year, statement scope, accounting framework and the expected
restatement side. A report whose fiscal year ended (Asia/Taipei, 1 January of the next year) no later than the
disclosure must match the *as previously reported* (pre) side; a report for a later fiscal year must match the
restated (post) side. `effective_available_at` is the earliest admissible disclosure time.

`statement_scope_basis` now says explicitly that the scope belongs to the whole report row and was inferred from that
row's revenue (not from the row's own metric). Earlier exports, including the preserved retrospective ZIP, repeat the
revenue wording on operating-income rows; the scope itself and every value are unchanged.

In strict packages a summary row is retained only if the disclosure is side-consistent, published before the cutoff,
and the report's fiscal year ended before the cutoff; it becomes `evidence_type = official_disclosed_observation`,
`completeness = disclosed_value_only`, and the workbook's `source_url`, `content_hash` and `retrieved_at` are withheld.

## v1.1 changes (Phase 1B, additive)

- Five fields are appended after `point_in_time_eligible`; v1.0 columns keep their order and names.
- **Observation-level availability.** A fact is eligible when an official
  disclosure with a verified timestamp states the same period, scope,
  framework, metric and exact value (e.g. the MOPS 2016-11-13 21:26:22
  restatement notice). `available_at` and `availability_status` still describe
  the filing version only and remain unverified/null for restated XBRL.
- `as_of` filters on `effective_available_at`.

## Separate evidence datasets (Phase 1B)

Produced by `python -m scripts.historical_audit_case evidence-export --dataset <name>`
(CSV or JSON envelope `fintrust.historical_<name>`, contract 1.0). They are
never merged into the facts file.

| Dataset | Content | `as_of` | Key semantics |
|---|---|---|---|
| `summary_observations` | TPEx 上櫃公司季報 values (current-period, prior-year comparative and period-end) | yes | `evidence_type = official_historical_summary`, `completeness = summary_values_only`; `accounting_framework` TW_GAAP/TIFRS by file; `mapping_status` `mapped` / `requires_review` / `unmapped`; `value` as published (NT$ thousand) and `normalized_value` (TWD); availability unverified unless corroborated |
| `restatement_comparisons` | 重編前/重編後 rows from MOPS restatement notices | yes | `pre_restatement_value` = *as previously reported per the notice* (not necessarily first-published); NT$ thousand as disclosed (deductions negative, `sign_factor` gives the canonical sign); eligible from `disclosed_at` |
| `publication_timeline` | TPEx announcements, MOPS material information, TWSE e-book uploads, quoted claims | no | `available_from` = second-precision time, or next Taipei midnight for date-only notices; `linked_filing_versions` lists link statuses |
| `source_inventory` | every archived source artifact with category, hash, parser status, missing evidence | no | categories in `HISTORICAL_SOURCE_EVIDENCE_INVENTORY.md` |
| `coverage_matrix` | FY-by-FY original/restated/summary/comparison evidence, verified availability, PIT readiness, remaining gaps | no | for case research triage; pass `--start-year/--end-year` (default case range 2011–2016) |
| `disclosed_financial_values` (Phase 2B) | key figures stated by MOPS financial-report board-approval notices | yes | `value` as published (仟元, or 元 for EPS), `normalized_value` (TWD, TWD/share); `canonical_metric` empty where no exact canonical metric exists; `dated_facts` = filing facts dated by this value; eligible from `disclosed_at` |

## Point-in-time semantics

- `--as-of YYYY-MM-DD` means "public by the end of that day, Asia/Taipei";
  an ISO timestamp with timezone is inclusive. A naive timestamp is rejected.
- With `as_of`, only `point_in_time_eligible` facts whose `effective_available_at`
  is before the cutoff are returned. Fiscal year and `document_dated_at` are never
  used as publication time.
- `version_policy`: `all` (every eligible version), `latest_available`
  (per period/metric/scope/unit, the version with the latest `available_at`),
  `earliest_available` (unknown availability sorts last), `original_only`.

## Ordering and determinism

Records are ordered by `fiscal_year, period, metric_code, statement_scope,
unit`, then by version availability. Identical database state yields
byte-identical CSV; JSON differs only in `generated_at`.

## Change policy

Additive fields → minor version (1.x); v1.1 appended five fields (Phase 1B). Renaming/removing fields or changing a
meaning → major version and a new document section.
