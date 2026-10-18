# Phase 5B — Cross-industry FinMind raw-data pilot (2026-10-18)

## Objective
Use the now-corrected **2,086 TWSE/TPEx current nonfinancial company candidates** to
audit the availability and reported-period meaning of multi-year financial
statement line items **before** launching thousands of downloads or retraining
machine learning models. The original FinMind snapshot SHA-256 was preserved.
The issuer master is not a historical universe, and none of its members is
verified normal. Ticker `1785` remains completely out of this stage.

### Why a pilot is necessary
FinMind provides `TaiwanStockFinancialStatements`,
`TaiwanStockBalanceSheet`, and `TaiwanStockCashFlowsStatement`, each with
`date`, `stock_id`, `type`, `value`, and `origin_name` fields.
Accounting concepts can differ by company/period. A 12/31 reported number
must **not** automatically be interpreted as a complete full-year fiscal flow.
A balance-sheet point-in-time amount is not added across quarters. FinMind
values are not automatically MOPS canonical annual original-vintage values.

Reference: https://finmind.github.io/tutor/TaiwanMarket/Fundamental/

## New module
`research/financial_ml/finmind_cross_industry_pilot.py`:

- `plan`: deterministic industry-aware current-issuer sample; prioritize
  semiconductor comparisons and keep the 2330 anchor where available.
  Small bounded selection 6–30 companies, nonfinancial, no 1785. Default 24
  (72 endpoint requests). Does **not** perform HTTP.
- Existing `finmind_bulk_stage.py`: retains raw three-statement provider
  records in immutable-per-contract local archives; explicit `--execute`,
  quota fail-close, 15 s pacing by default, resumable cached requests.
- `audit`: read cached JSON, compute SHA-256, inspect statement dates, field
  types, provider origin names, missing/invalid lines, (date/type) conflicts
  and whether existing `literature_inputs.MAPPINGS` TIFRS aliases happen to
  appear in FinMind. Alias coincidence does not prove field equivalence.
  No annual transformation or training occurs.

## One-pilot recipe, in a clean dedicated Git Worktree `fintrust_backend`

```powershell
$root = (git rev-parse --show-toplevel).Trim()
$main = Join-Path (Split-Path $root -Parent) "Financial-Risk-Alert-System"
$data = Join-Path $main "fintrust_backend\data\financial_ml"
$universe = Join-Path $data "finmind_universe\taiwan_nonfinancial_current_candidates.csv"
$pilot = Join-Path $data "finmind_cross_industry_pilot"
$raw = Join-Path $data "finmind_cross_industry_raw"
$audit = Join-Path $data "finmind_cross_industry_audit"

python -m unittest discover -s tests -p "test_financial_ml_finmind_cross_industry_pilot.py" -v

python -m research.financial_ml.finmind_cross_industry_pilot plan --candidate-csv $universe --output $pilot --size 12 --semiconductor 3
# Inspect finmind_pilot_plan.json: 12 companies, at most 36 finance requests.

python -m research.financial_ml.finmind_bulk_stage --candidate-csv (Join-Path $pilot "finmind_pilot_candidates.csv") --output $raw --max-tickers 12
# Confirm endpoint budget, then explicitly fetch only this bounded sample:
python -m research.financial_ml.finmind_bulk_stage --candidate-csv (Join-Path $pilot "finmind_pilot_candidates.csv") --output $raw --max-tickers 12 --execute

python -m research.financial_ml.finmind_cross_industry_pilot audit --pilot-csv (Join-Path $pilot "finmind_pilot_candidates.csv") --raw-root $raw --output $audit
```

No credentials or API tokens should be printed or attached. If a quota/access
failure occurs, stop, keep the raw archives, and inspect the report; do not
increase concurrency to evade limits.

## Outputs to examine
- `finmind_pilot_plan.json`: candidate group representation, market mix, request budget
- `finmind_raw_acquisition_report.json`: actual successful/failed/reused downloads
- `finmind_pilot_schema_report.json`: raw coverage and alias counts
- `finmind_field_catalog.csv`: provider `type`, `origin_name`, date and issuer coverage
- `finmind_literature_input_alias_audit.csv`: exact alias overlap with 24
  literature underlying accounts, **not yet verified equivalence**
- `finmind_raw_schema_audit.csv`: per-company statement availability, dates,
  collisions and invalid line counts

## Next implementation after pilot
1. With actual FinMind provider rows, select 3–5 issuer-year examples and
   reconcile a complete year against the already archived MOPS XBRL source
   (prefer 2330 where 2013–2015 MOPS evidence exists).
2. Freeze explicit source-specific account mappings and the meaning of
   balance and flow reporting intervals; test `t`, `t-1`, `t-2` integrity.
3. Produce actual `Beneish 8 + Dechow Model 1 7` literature features via
   the **existing** source-verified engines, audit per-variable missingness
   (notably TATA / RSST / Issue / LVGI).
4. Expand across non-financial TWSE/TPEx companies with bounded requests,
   and fit diverse baselines on the genuinely enlarged feature panel.
   Reserve `1785` until all model choices are frozen.

Not in scope now: a production event pipeline, continuous online learning,
frontend or cloud deployment. No model accuracy/F1 without independent labels.
