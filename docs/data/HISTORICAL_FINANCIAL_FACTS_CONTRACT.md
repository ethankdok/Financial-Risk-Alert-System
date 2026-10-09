# Historical Financial Facts → Downstream Research (contract v1.0)

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
| `value` | decimal string | exact value as filed, after iXBRL `scale`/`sign`; never zero-filled |
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
| `point_in_time_eligible` | `true` \| `false` | `availability_status = verified` and `available_at` present |

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
  "contract_version": "1.0",
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

## Point-in-time semantics

- `--as-of YYYY-MM-DD` means "public by the end of that day, Asia/Taipei";
  an ISO timestamp with timezone is inclusive. A naive timestamp is rejected.
- With `as_of`, only `point_in_time_eligible` versions with `available_at`
  before the cutoff are returned. Fiscal year and `document_dated_at` are never
  used as publication time.
- `version_policy`: `all` (every eligible version), `latest_available`
  (per period/metric/scope/unit, the version with the latest `available_at`),
  `earliest_available` (unknown availability sorts last), `original_only`.

## Ordering and determinism

Records are ordered by `fiscal_year, period, metric_code, statement_scope,
unit`, then by version availability. Identical database state yields
byte-identical CSV; JSON differs only in `generated_at`.

## Change policy

Additive fields → minor version (1.x). Renaming/removing fields or changing a
meaning → major version and a new document section.
